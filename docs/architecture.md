# Архитектура агента

## Высокоуровневый пайплайн

Реализован как **LangGraph** StateGraph (`agent/graph.py`).

```
START
  │
  ▼
load_ledger          # CSV → DataFrame, account_id → scenario_id
  │
  ▼
classify_docs        # все PDF: extract + classify + bind to scenario
  │
  ▼
extract_covenants    # loan agreements → Article 6 → 6.1 / 6.2 / 6.3
  │
  ▼
extract_metrics      # notes + KYC + ledger → ScenarioMetrics
  │
  ▼
analyze_covenants    # formula engine (+ optional Qwen / reflection)
  │
  ▼
collect_results      # answers dict → documents["submission_answers"]
  │
  ▼
END  → main.py пишет submission.json → validate
```

Phase 1 (foundation) останавливается после `extract_covenants`.  
Phase 2/3 — полный граф до `collect_results`.

---

## AgentState

Определён в `agent/state.py` (TypedDict):

| Поле | Смысл |
|------|--------|
| `ledger` | `pd.DataFrame` всего леджера |
| `account_to_scenario` | `ACC-7801 → P1` (только submission-сценарии) |
| `scenario_ids` | ключи из `submission_template.json` |
| `doc_index` | список классификаций всех PDF |
| `docs_by_scenario` | `scenario → {loan_agreement, financial_notes, kyc} → [paths]` |
| `documents` | bag: covenants_by_scenario, metrics_by_scenario, submission_answers |
| `results` | `Annotated[list[FinalCovenantResult], operator.add]` |
| `stage` / `error` | контроль |

---

## Слои кода

### `agent/nodes/` — шаги графа

| Модуль | Нода | Ответственность |
|--------|------|-----------------|
| `load_ledger.py` | `load_ledger` | CSV, mapping, template scenarios |
| `classify_docs.py` | `classify_docs` | batch PDF, route to scenarios |
| `extract_covenants.py` | `extract_covenants` | Article 6 split |
| `analyze.py` | `extract_metrics`, `analyze_covenants`, `collect_results` | метрики + вердикты + сборка |

### `agent/tools/` — доменная логика

| Модуль | Роль |
|--------|------|
| `ledger.py` | mapping, transactions; `amount=None` при NaN в CSV |
| `pdf_extract.py` | pdfplumber → pymupdf → pdftotext |
| `pdf_cache.py` | diskcache по path+size+mtime |
| `classifier.py` | rules (loan/notes/kyc/junk) + optional Gemini |
| `covenants.py` | Article 6 → 6.1–6.3 |
| `metrics.py` | KYC, AUP, cut-off, FX, NaN fills, Group Capex, one-time EBITDA |
| `formula_engine.py` | детект формулы, actual/status/evidence |
| `llm.py` | Qwen + Gemini factories |

### `agent/models.py` — схемы

- `DocType`, `DocClassification`  
- `CovenantVerdict` — structured output LLM  
- `FinalCovenantResult` — ячейка submission  
- `ExtractedDocument` — payload кэша PDF  

### `agent/prompts/system.py`

Боевые промпты Master Plan §6.

---

## Извлечение метрик (`metrics.py`)

Для каждого `scenario_id` → `ScenarioMetrics`:

1. **KYC** — ownership threshold, related parties; OCR image-таблиц; unrestricted subsidiaries (pledge &lt; 50%).  
2. **Notes / AUP** — final reclass only; cut-offs; missing ledger amounts; FX rates.  
3. **EBITDA one-time table** (OCR «Корректировки EBITDA») — items + materiality threshold.  
4. **Ledger** — taxonomy (`revenue`, `opex`, `capex`, `lease`, `interest`, `tax`, `utilities`, `financing`, `transfer`, …); NaN fill; FX convert.  
5. **Aggregates** — revenue, ebitda, adjusted_ebitda, capex, RP, financing, group_capex, …  

### Adjusted EBITDA

```
AdjEBITDA = Revenue − OpEx − Σ(one-time) + Σ(qualifying add-backs)
          = Revenue − OpEx − non_qualifying_one_time

qualifying = one-time items with amount ≥ materiality (often $300,000)
```

Пример P4: dredge $251k (не add-back) остаётся в вычете → margin **0.33**.

### Group Capex

PPE rollforward из consolidated FS:

```
group_capex = NBV_end − NBV_begin + depreciation (+ disposals)
actual = group_capex / borrower_EBITDA
```

Привязка к заёмщику — segment note («through {Borrower} JSC»).

### NaN ledger fills

CSV может содержать `amount=NaN`. Суммы берутся из notes/treasury:

```
Операция TXN-…: сумма не отражена … фактическая сумма … $X
```

### FX

Из notes: `72,146.75 EUR … $83,690.23` → rate → конвертация non-USD для EBITDA/opex.

---

## Formula engine

`detect_formula_id(covenant_text)` → handler:

| formula_id | actual |
|------------|--------|
| `capital_intensity` | Capex / (OpEx + Lease) |
| `min_revenue` | Revenue (sales settlement) |
| `max_related_party` | сумма RP payments |
| `rp_to_revenue` / `rp_to_opex` | доли RP |
| `interest_coverage` | EBITDA / Interest |
| `max_capex` | Capex absolute |
| `group_capex_to_ebitda` | Group Capex / EBITDA |
| `ebitda_margin` / `adj_ebitda_margin` | (Adj)EBITDA / Revenue |
| `tax_util_to_ebitda` | (Tax + Utilities) / EBITDA |
| `insurance_to_lease` | Insurance / (Lease + Utilities) |
| `sources_to_uses` | (Rev + Financing) / (OpEx + Capex) |
| `revenue_minus_max_overhead` | Revenue − max(Payroll, Tax) |
| `assets_transferred` | unrestricted transfers / total capex |
| `payroll_total` | payroll + severance (notes) |
| `max_single_overhead` | max(payroll, utilities) category totals |
| `financing_to_ebitda` | Financing / EBITDA (springing) |
| `q4_revenue` | revenue in Q4 |

**Status (max ratio):** raw vs thr; если round(raw,2)==thr, но raw чуть выше — COMPLIANT при relative overshoot ≤ 5% (presentation band).  

**actual:** `round(abs(x), 2)`.  

**evidence_txn_id:** единственная txn, без которой status меняется (reclass-кандидаты первыми).

---

## Analyze path (LLM)

`analyze_one_covenant`:

1. Детерминированный `evaluate_covenant`  
2. При `QWEN_API_KEY` и low confidence → Qwen structured output  
3. Reflection при confidence &lt; threshold  

На open set достаточно formula engine (100% без ключей).

---

## Классификация документов

| Тип | Сигналы |
|-----|---------|
| `loan_agreement` | ДОГОВОР БАНКОВСКОГО ЗАЙМА, Статья 6 |
| `financial_notes` | Примечания, AUP, Consolidated FS, PPE rollforward |
| `kyc` | Досье KYC, НАДЛЕЖАЩАЯ ПРОВЕРКА |
| `junk` | пресс-релизы, АХО, superseded loan, internal procedures |

---

## Кэширование

`get_file_key = md5(resolve:size:mtime_ns)` → `doc_cache/`.

---

## Расширение

1. Новый тип ковенанта → handler + `detect_formula_id`.  
2. Новая категория ledger → `classify_txn_category`.  
3. Новый source метрики → `metrics.py` + поле `ScenarioMetrics`.  

Не ломать: mapping account→scenario, схему `answers`, actual &gt; 0 с 2 знаками.
