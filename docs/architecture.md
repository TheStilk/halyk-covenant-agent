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
END  → main.py пишет submission.json
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

Per-borrower поля (`scenario_id`, `covenants`, `metrics`, `transactions`) используются при fan-out (задел под Phase 3 parallelism).

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
| `ledger.py` | `build_account_to_scenario`, filter, transactions_for_account |
| `pdf_extract.py` | pdfplumber → pymupdf → pdftotext; account/company regex |
| `pdf_cache.py` | diskcache по path+size+mtime |
| `classifier.py` | rules (loan/notes/kyc/junk) + optional Gemini |
| `covenants.py` | поиск Article 6, split 6.1–6.3 |
| `metrics.py` | KYC, AUP reclass, cut-off, ledger taxonomy, Group Capex, RP |
| `formula_engine.py` | детект типа ковенанта, расчёт actual/status/evidence |
| `llm.py` | Qwen (OpenAI-compatible) + Gemini factories |

### `agent/models.py` — схемы

- `DocType`, `DocClassification`  
- `CovenantVerdict` — structured output LLM  
- `FinalCovenantResult` — ячейка submission  
- `ExtractedDocument` — payload кэша PDF  

### `agent/prompts/system.py`

Боевые промпты из Master Plan §6: system, covenant user, reflection, doc classify.

---

## Извлечение метрик (`metrics.py`)

Для каждого `scenario_id` строится `ScenarioMetrics`:

1. **KYC** — threshold ownership, related parties; OCR (`pdftoppm` + `tesseract`) для image-таблиц; unrestricted subsidiaries (pledge &lt; 50%).  
2. **Notes / AUP** — reclassifications (только final AUP; draft intermediate отбрасываются), cut-offs, add-backs.  
3. **Ledger** — классификация описаний (`revenue`, `opex`, `capex`, `lease`, `interest`, `tax`, `utilities`, `insurance`, `payroll`, `financing`, `transfer`, …).  
4. **Aggregates** — `revenue`, `ebitda = revenue − opex`, `capex` (purchase + transfers), `related_party_payments`, `financing_inflows`, …  
5. **Group Capex** — поиск consolidated FS с PPE rollforward:

   ```
   group_capex = NBV_end − NBV_begin + depreciation (+ disposals)
   ```

   Документ привязывается к заёмщику по упоминанию компании в segment note.

---

## Formula engine

`detect_formula_id(covenant_text)` → handler:

| formula_id | Смысл actual |
|------------|----------------|
| `capital_intensity` | Capex / (OpEx + Lease) |
| `min_revenue` | Revenue (sales settlement) |
| `max_related_party` | сумма платежей related parties |
| `rp_to_revenue` / `rp_to_opex` | доли RP |
| `interest_coverage` | EBITDA / Interest (с reclass) |
| `max_capex` | Capex absolute |
| `group_capex_to_ebitda` | Group Capex / borrower EBITDA |
| `ebitda_margin` / `adj_ebitda_margin` | EBITDA / Revenue |
| `tax_util_to_ebitda` | (Tax + Utilities) / EBITDA |
| `insurance_to_lease` | Insurance / (Lease + Utilities) |
| `sources_to_uses` | (Rev + Financing) / (OpEx + Capex) |
| `revenue_minus_max_overhead` | Revenue − max(Payroll, Tax) |
| `assets_transferred` | unrestricted transfers / total capex |
| `payroll_total` | payroll + severance from notes |
| `max_single_overhead` | max(payroll, utilities) line totals |
| `financing_to_ebitda` | Financing / EBITDA (springing) |
| `q4_revenue` | revenue в Q4 |

**Status:** сравнение на полной precision (raw), `actual` в ответе — `round(abs(x), 2)`.

**evidence_txn_id:** единственная транзакция, при исключении которой status меняется; для reclass-кейсов кандидаты reclass txn идут первыми.

---

## Analyze path (LLM)

`analyze_one_covenant` (`nodes/analyze.py`):

1. Детерминированный `evaluate_covenant`  
2. Если `QWEN_API_KEY` и `confidence < CONFIDENCE_THRESHOLD` → Qwen `with_structured_output(CovenantVerdict)`  
3. Если confidence всё ещё низкая → reflection-промпт  

На open set без ключей достаточно formula engine.

---

## Классификация документов

Rules-first (`classifier.py`):

| Тип | Сигналы |
|-----|---------|
| `loan_agreement` | ДОГОВОР БАНКОВСКОГО ЗАЙМА, Статья 6, Пункт 6.1 |
| `financial_notes` | Примечания к ФО, AUP, EBITDA, Consolidated FS, PPE rollforward |
| `kyc` | Досье KYC, НАДЛЕЖАЩАЯ ПРОВЕРКА |
| `junk` | пресс-релизы, АХО, IT-инциденты, **НЕДЕЙСТВУЮЩАЯ РЕДАКЦИЯ**, internal procedures |

Superseded loan agreements и draft intermediate AUP не используются как authoritative source.

---

## Кэширование

`get_file_key(path) = md5(resolve + size + mtime_ns)`  
`doc_cache/` — payload `ExtractedDocument` (text, page_count, method, tables).

---

## Расширение

1. **Новый тип ковенанта** — handler в `formula_engine.py` + ветка в `detect_formula_id`.  
2. **Новая категория ledger** — `classify_txn_category` в `metrics.py`.  
3. **Новый source метрики** — парсер в `metrics.py`, поле в `ScenarioMetrics`.  
4. **Параллелизм** — `asyncio` / LangGraph `Send` по `scenario_ids` (задел в state).  

Не ломать: маппинг account→scenario, схему `answers`, правила actual &gt; 0 с 2 знаками.
