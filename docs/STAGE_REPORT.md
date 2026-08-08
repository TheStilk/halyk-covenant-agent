# Open-set case: отчёт по этапам

**Датасет:** agentic-bank-public
**Режим:** det-only (LLM off)
**Ячейки:** 12 сценариев × 3 ковенанта = 36
**CASE-скоринг на клетку:** status 0.50 + actual 0.30 + evidence 0.20 = 1.00

---

## Сводка воронки (coef / %)

| Этап | Метрика | Значение | coef | % |
|------|---------|----------|------|---|
| 0 | Ledger + borrowers | 1473 rows → 12 сценариев | 1.000 | 100% |
| 1 | PDF classify (non-junk useful) | 42 / 202 | 0.208 | 20.8% |
| 1 | Loan на сценарий | 12 / 12 | 1.000 | 100% |
| 1 | Notes на сценарий | 12 / 12 | 1.000 | 100% |
| 1 | KYC на сценарий | 11 / 12 | 0.917 | 91.7% |
| 2 | Текст всех пунктов 6.1–6.3 | 36 / 36 | 1.000 | 100% |
| 3 | Metrics + revenue > 0 | 12 / 12 | 1.000 | 100% |
| 3 | Ownership threshold из KYC | 11 / 12 | 0.917 | 91.7% |
| 4 | Threshold извлечён | 36 / 36 | 1.000 | 100% |
| 4 | Known formula_id | 36 / 36 | 1.000 | 100% |
| 4 | Strong det (known ∧ conf≥0.85) | 35 / 36 | 0.972 | 97.2% |
| 4 | Кандидаты в LLM (low conf) | 1 / 36 | 0.028 | 2.8% |
| 5 | Status vs GT | 36 / 36 | 1.000 | 100% |
| 5 | Evidence vs GT (где не null) | 9 / 9 | 1.000 | 100% |
| 5 | Actual rel err ≤1% | 36 / 36 | 1.000 | 100% |
| 5 | Hackathon score | 36.000 / 36 | 1.000 | 100% |

---

## Stage 0 — Load / preflight

| Метрика | Значение |
|---|---|
| Ledger | 1473 txns |
| Accounts → scenario | 561 map → 12 borrowers |
| PDF scanned | 200 (+2 non-pdf?) → 202 classify |
| OCR pages needed | 7 |
| Unreadable | 1 (f3fa6d20c8a1.pdf) |

---

## Stage 1 — Classify (rules only, без LLM)

| doc_type | count | % от 202 |
|---|---|---|
| junk | 160 | 79.2% |
| financial_notes | 19 | 9.4% |
| loan_agreement | 12 | 5.9% |
| kyc | 11 | 5.4% |

*Привязка к 12 сценариям: loan 100% · notes 100% · kyc 91.7% (1 без KYC-файла, parties всё равно нашлись fallback’ом).*
*CLASSIFY_USE_LLM=false → 0% документов в LLM.*

---

## Stage 2 — Covenants

| Метрика | coef | % |
|---|---|---|
| Сценарии с полным набором 6.1–6.3 | 1.000 | 100% |
| Ячейки с текстом | 1.000 | 100% |

---

## Stage 3 — Metrics

| Метрика | coef | % |
|---|---|---|
| Metrics built | 1.000 | 100% |
| revenue > 0 | 1.000 | 100% |
| KYC parties | 1.000 | 100% |
| ownership thr | 0.917 | 91.7% (P6 thr=None) |
| reclass events | 3 total | — |
| cutoffs | 3 total | — |
| missing ledger fills | P7, P8 | notes → filled |

---

## Stage 4 — Det formula engine

| Метрика | n | coef | % |
|---|---|---|---|
| thr extracted | 36/36 | 1.000 | 100% |
| known formula | 36/36 | 1.000 | 100% |
| strong det (LLM skip) | 35/36 | 0.972 | 97.2% |
| low conf → LLM if keys | 1/36 (B4/6.1 conf=0.70) | 0.028 | 2.8% |

**Топ formula_id:**

| formula | n | % |
|---|---|---|
| max_related_party | 7 | 19.4% |
| max_capex | 5 | 13.9% |
| min_revenue | 5 | 13.9% |
| rp_to_revenue | 4 | 11.1% |
| остальные (15 типов) | 1 each | 2.8% each |

---

## Stage 5 — Score vs ground truth

**CASE decomposition (потолок 36.0)**

| Компонент | вес | реализовано | % пула |
|---|---|---|---|
| status | 0.50 | 18.00 / 18.0 | 100% |
| actual | 0.30 | 10.80 / 10.8 | 100% (rel err = 0) |
| evidence | 0.20 | 7.20 / 7.2* | 100% (9/9 non-null + null-null) |
| **TOTAL** | **1.00** | **36.000 / 36** | **100%** |

*\* evidence: 9 клеток с GT txn — все угаданы; остальные null/null.*

**Гистограмма клеток:**
1.00 score — 36 (100%)
Mean coefficient на клетку: 1.0000

---

## LLM в этом прогоне

| Путь | Сработало? |
|---|---|
| Classify LLM | нет (CLASSIFY_USE_LLM=false) |
| Formula reader | нет (нет LLM_API_KEY) |
| Клеток, куда пошёл бы reader при ключах | 1/36 (2.8%) — B4/6.1 low conf |
| Остальные 35 | det strong → LLM skip |

После подключения боевой модели на open-set почти ничего не изменится (уже 36/36). LLM полезен на private, где появятся unknown формулы.

---

## Картина одной строкой

**202 PDF → 21% полезных → 12/12 loan+notes → 36/36 clauses → 36/36 thr+formula → 97% strong det → 36/36 status+actual+evidence → SCORE 36.000 (coef 1.000 = 100%)**
