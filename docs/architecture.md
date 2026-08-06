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
extract_covenants    # loan → template covenant ids (fallback Article N)
  │
  ▼
extract_metrics      # notes + KYC + ledger → ScenarioMetrics
  │
  ▼
analyze_covenants    # formula engine → unknown best-effort → optional LLM
  │
  ▼
collect_results      # ensure_filled cells → documents["submission_answers"]
  │
  ▼
END  → main.py: submission.json + BATTLE DIAGNOSTICS → validate
```

Phase 1 (foundation) останавливается после `extract_covenants`.  
Phase 2/3 — полный граф до `collect_results`.

**Принцип:** deterministic first, LLM only fallback. Не переписывать formula engine ради LLM.

---

## AgentState

Определён в `agent/state.py` (TypedDict):

| Поле | Смысл |
|------|--------|
| `ledger` | `pd.DataFrame` всего леджера |
| `account_to_scenario` | `ACC-… → scenario` (submission-сценарии; не только ACC-7*) |
| `scenario_ids` | ключи из `submission_template.json` |
| `doc_index` | список классификаций всех PDF (+ extract quality) |
| `docs_by_scenario` | `scenario → {loan_agreement, financial_notes, kyc} → [paths]` |
| `documents` | bag: covenants_by_scenario, metrics_by_scenario, submission_answers |
| `diagnostics` | bad extracts, unknown formulas, low confidence, … |
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
| `ledger.py` | mapping, transactions; prefer non-`ACC-9*` borrowers |
| `pdf_extract.py` | quality-gated extract; pdfplumber → pymupdf → pdftotext |
| `pdf_cache.py` | diskcache path+size+mtime+**extract quality version** |
| `classifier.py` | rules + prefer mapped / non-noise account |
| `covenants.py` | template ids → clause block; fallback Статья/Article N |
| `metrics.py` | KYC, AUP, taxonomy, FX, NaN fills, Group Capex, Adj EBITDA |
| `formula_engine.py` | known formulas + unknown best-effort |
| `battle_diagnostics.py` | сводка cells / unknown / bad extracts / time |
| `llm.py` | OpenAI-compatible client (`LLM_*` env) |

### `agent/models.py` — схемы

- `DocType`, `DocClassification`  
- `CovenantVerdict` — structured output LLM  
- `FinalCovenantResult` — ячейка submission  
- `ensure_filled_cell` / `ensure_filled_answers` — **запрет null status/actual**  
- `ExtractedDocument` — payload кэша PDF  

### `agent/config.py`

- `COVENANT_IDS` / `COVENANT_IDS_BY_SCENARIO` — из `submission_template.json`  
- `covenant_ids_for_scenario(sc)` — per-scenario ids (private set может отличаться)  

### `agent/prompts/system.py`

Боевые промпты Master Plan §6.

---

## Извлечение метрик (`metrics.py`)

Для каждого `scenario_id` → `ScenarioMetrics`:

1. **KYC** — ownership threshold, related parties; OCR image-таблиц; unrestricted subsidiaries (pledge &lt; 50%).  
2. **Notes / AUP** — final reclass only; cut-offs; missing ledger amounts; FX rates.  
3. **EBITDA one-time table** (OCR «Корректировки EBITDA») — items + materiality threshold.  
4. **Ledger** — `classify_txn_category` (interest/overdraft/capitalised, rent/storage, insurance refunds, VAT/tax credits, utilities/sewer, marketing rebates; `other_*` ~0.6%); NaN fill; FX.  
5. **Aggregates** — revenue, ebitda, adjusted_ebitda, capex, RP, financing, group_capex, …  
   Expense buckets считают только **outflows** (`amount < 0`); inflows-refunds в family не ломают open-set totals. 

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

`detect_formula_id(covenant_text)` → handler (known open-set ids **не трогать** без eval):

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

**Unknown formula** (`detect_formula_id` → `unknown`):

1. Soft keyword remap (RP / revenue / capex) с low conf  
2. Иначе `_best_effort_unknown` — shape thr (min/max × money/ratio) + metrics  
3. **Никогда** silent `BREACH + actual=0.0` без попытки метрики  
4. conf ≈ 0.28 → LLM refine при наличии ключа  

**Status (max ratio):** raw vs thr; presentation band relative overshoot ≤ 5%.  
**actual:** `round(abs(x), 2)`.  
**evidence_txn_id:** txn, без которой status меняется.

---

## Analyze path (LLM)

`analyze_one_covenant`:

1. `evaluate_covenant` (known high-conf **без** LLM)  
2. При `LLM_*` + `USE_LLM_FORMULA_READER` → FormulaSpec (LLM) + compute (code), cross-check с det  
3. Unknown / low conf → optional structured verdict / reflection  
4. Без ключа — det best-effort, ячейка всё равно заполнена  

Модель **не зашита** в логику: только `LLM_MODEL` / `MODEL_LABEL`.  
Open set: 100% на formula engine без ключей.

---

## PDF extract quality

`assess_extract_quality(text)` вместо `len(text) ≥ 40`:

- meaningful length, доля кириллицы, маркеры ACC/TXN/$/Статья|Article, alnum density  
- backend: pdfplumber → pymupdf → pdftotext; первый `ok` принимается  
- все плохие → best score + `method=…+degraded` + WARNING (в `diagnostics.bad_extracts`)  

---

## Covenant extraction (template-driven)

1. Clause headers по ids из template (`Пункт 6.1`, `Clause 7.2`, …)  
2. Fallback: `Статья N` / `Article N` (N = major number ids)  
3. Split только на ids из template (не хардкод 6.1/6.2/6.3)

---

## Классификация документов

| Тип | Сигналы |
|-----|---------|
| `loan_agreement` | ДОГОВОР БАНКОВСКОГО ЗАЙМА, Статья N |
| `financial_notes` | Примечания, AUP, Consolidated FS, PPE rollforward |
| `kyc` | Досье KYC, НАДЛЕЖАЩАЯ ПРОВЕРКА |
| `junk` | пресс-релизы, АХО, superseded loan, internal procedures |

Account: `prefer_borrower_account` — mapping ledger → non-noise (`ACC-9*`) → first.  
Company: JSC / LLC / LLP / ТОО / АО / …  

---

## Кэширование

`get_file_key = md5(resolve:size:mtime_ns:eq=<EXTRACT_QUALITY_VERSION>)` → `doc_cache/`.  
Смена quality-логики инвалидирует кэш автоматически.

---

## Battle diagnostics

В конце `main.py phase3`:

```text
=== BATTLE DIAGNOSTICS ===
cells filled: 36/36
unknown formulas: …
low confidence: …
bad extracts: …
missing amounts: …
scenarios without loan: …
scenarios without notes: …
time total: …
```

Реализация: `agent/tools/battle_diagnostics.py`.

---

## Расширение

1. Новый тип ковенанта → handler + `detect_formula_id` (не ломать open-set 36/36).  
2. Новая категория ledger → `classify_txn_category` (не ломать revenue/capex/rp/tax/utilities).  
3. Новый source метрики → `metrics.py` + `ScenarioMetrics`.  
4. LLM Formula Reader (planned) — LLM читает формулировку → code считает; det engine остаётся backup.

Не ломать: mapping account→scenario, схему `answers`, never-null cells, actual ≥ 0 с 2 знаками.
