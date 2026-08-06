# LLM Formula Reader probe — `llm_formula_reader_20260806_123940`

- started: `2026-08-06T12:39:40.331947+00:00`
- finished: `2026-08-06T12:46:39.889486+00:00`
- model: `gemma-4-26b-a4b-it`
- base_url: `https://generativelanguage.googleapis.com/v1beta/openai/`
- MODEL_LABEL: `gemma-4-26b-a4b-it`
- scenarios: P3, P5, P7, B1

## Smoke
```json
{
  "available": true,
  "status_message": "LLM available: model=gemma-4-26b-a4b-it base=https://generativelanguage.googleapis.com/v1beta/openai/",
  "model": "gemma-4-26b-a4b-it",
  "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
  "model_label": "gemma-4-26b-a4b-it",
  "structured_ok": true,
  "structured_spec": {
    "formula_kind": "absolute_min",
    "comparison": "min",
    "threshold": 5000000.0,
    "numerator_metrics": [
      "revenue"
    ],
    "denominator_metrics": [],
    "needs_group": false,
    "needs_addbacks": false,
    "needs_fx": false,
    "confidence": 1.0,
    "raw_interpretation": "The borrower's revenue must be at least $5,000,000."
  },
  "error": null,
  "key_used": "primary",
  "elapsed_sec": 8.789
}
```

## Summary
- cells: **12**
- det↔llm AGREE: **9**
- det↔llm MISMATCH: **1**
- errors: **2**
- det matches truth (status+actual≤5%): **12/12**
- llm matches truth (status+actual≤5%): **9/12**
- api key used (final): `primary`

## Cells

| sc | cov | flag | det | llm | truth | err det↔llm | err llm↔truth | t(s) |
|----|-----|------|-----|-----|-------|-------------|---------------|------|
| P3 | 6.1 | ERR | BREACH/1.71 | None/None | BREACH/1.71 | — | — | 201.319 |
| P3 | 6.2 | AGREE | COMPLIANT/8104772.36 | COMPLIANT/8104772.36 | COMPLIANT/8104772.36 | 0.00% | 0.00% | 20.68 |
| P3 | 6.3 | ERR | COMPLIANT/264117.82 | None/None | COMPLIANT/264117.82 | — | — | 29.808 |
| P5 | 6.1 | AGREE | BREACH/9.45 | BREACH/9.45 | BREACH/9.45 | 0.00% | 0.00% | 11.165 |
| P5 | 6.2 | AGREE | COMPLIANT/8214663.28 | COMPLIANT/8214663.28 | COMPLIANT/8214663.28 | 0.00% | 0.00% | 13.343 |
| P5 | 6.3 | AGREE | BREACH/273418.66 | BREACH/273418.66 | BREACH/273418.66 | 0.00% | 0.00% | 18.336 |
| P7 | 6.1 | AGREE | BREACH/0.36 | BREACH/0.36 | BREACH/0.36 | 0.00% | 0.00% | 12.039 |
| P7 | 6.2 | AGREE | COMPLIANT/9146882.53 | COMPLIANT/9146882.53 | COMPLIANT/9146882.53 | 0.00% | 0.00% | 11.098 |
| P7 | 6.3 | AGREE | BREACH/291663.82 | BREACH/291663.82 | BREACH/291663.82 | 0.00% | 0.00% | 12.04 |
| B1 | 6.1 | AGREE | BREACH/1.68 | BREACH/1.68 | BREACH/1.68 | 0.00% | 0.00% | 17.373 |
| B1 | 6.2 | MISMATCH | COMPLIANT/1284663.42 | BREACH/2221879.3 | COMPLIANT/1284663.42 | 42.18% | 42.18% | 17.496 |
| B1 | 6.3 | AGREE | COMPLIANT/307018.08 | COMPLIANT/307018.08 | COMPLIANT/307018.08 | 0.00% | 0.00% | 15.346 |

## Formula specs (detail)
### P3/6.1
- text: `Пункт 6.1 Springing Drawdown Leverage Test. Ограничение отношения поступлений по финансированию к EBITDA величиной 1.70x за период с 2025-01-01 по 2025-12-31 применяется к Заёмщику (Shymkent Refinery Services JSC) только при условии, что совокупные поступления по финансированию п`
- det reasoning: `[financing_to_ebitda] Financing/EBITDA = 5442118.93/3175820.12 = 1.7136→1.71; fin_txns=['TXN-P3-0002'] opex=4928952.24; thr max 1.7`
- **error:** `formula_reader: Could not parse response content as the length limit was reached - CompletionUsage(completion_tokens=4096, prompt_tokens=715, total_tokens=4811, completion_tokens_details=None, prompt_tokens_details=None)`

### P3/6.2
- text: `Пункт 6.2 Минимальная выручка по категории. Минимальный объём по статье «Выручка». Условием предоставления заёмных средств является то, что совокупные поступления Shymkent Refinery Services JSC по указанной статье за период с 2025-01-01 по 2025-12-31 будут не ниже $6,500,000.00. `
- det reasoning: `[min_revenue] Revenue (sales settlement) = 8104772.36; threshold min 6500000.00; txns=['TXN-P3-0010']`
```json
{
  "formula_kind": "absolute_min",
  "comparison": "min",
  "threshold": 6500000.0,
  "numerator_metrics": [
    "revenue"
  ],
  "denominator_metrics": [],
  "needs_group": false,
  "needs_addbacks": false,
  "needs_fx": false,
  "confidence": 1.0,
  "raw_interpretation": "Минимальная выручка по категории должна быть не ниже $6,500,000.00."
}
```
- llm compute: `[formula_spec:absolute_min] Минимальная выручка по категории должна быть не ниже $6,500,000.00. | num=['revenue']=8104772.3600 den=[]=0.0000 → actual=8104772.36 min thr=6500000.0 → COMPLIANT`

### P3/6.3
- text: `Пункт 6.3 Максимальные платежи связанным сторонам. Для целей настоящей статьи под связанной стороной понимается любое лицо, признанное связанной стороной Заёмщика по данным досье «Знай своего клиента» (KYC), независимо от назначения платежа, указанного в бухгалтерском учёте Заёмщ`
- det reasoning: `[max_related_party] Related-party payments = 264117.82 from ['TXN-P3-0001']; threshold max 400000.00; parties=['Turan Capital LLP']`
- **error:** `formula_reader: Error code: 500 - [{'error': {'code': 500, 'message': 'Internal error encountered.', 'status': 'INTERNAL'}}]`

### P5/6.1
- text: `Пункт 6.1 Максимальное отношение капитальных затрат Группы к EBITDA Заёмщика. На протяжении периода с 2025-01-01 по 2025-12-31 Ekibastuz Power Services JSC обеспечивает, чтобы отношение совокупных капитальных затрат Группы к EBITDA Заёмщика не превышало 9.00x. Капитальные затраты`
- det reasoning: `[group_capex_to_ebitda] GroupCapex/EBITDA = 21847362.55/2312216.15 = 9.4487→9.45; threshold max 9.0. source=consolidated PPE rollforward`
```json
{
  "formula_kind": "ratio",
  "comparison": "max",
  "threshold": 9.0,
  "numerator_metrics": [
    "group_capex"
  ],
  "denominator_metrics": [
    "ebitda"
  ],
  "needs_group": true,
  "needs_addbacks": false,
  "needs_fx": false,
  "confidence": 1.0,
  "raw_interpretation": "Отношение совокупных капитальных затрат Группы к EBITDA Заёмщика не превышает 9.00x."
}
```
- llm compute: `[formula_spec:ratio] Отношение совокупных капитальных затрат Группы к EBITDA Заёмщика не превышает 9.00x. | num=['group_capex']=21847362.5500 den=['ebitda']=2312216.1500 → actual=9.45 max thr=9.0 → BREACH`

### P5/6.2
- text: `Пункт 6.2 Минимальная выручка по категории. Для целей настоящей статьи под поступлениями по статье «Выручка» понимаются суммы, отнесённые к данной статье в аудированной финансовой отчётности Заёмщика с учётом переквалификаций, произведённых аудиторами Заёмщика для целей соблюдени`
- det reasoning: `[min_revenue] Revenue (sales settlement) = 8214663.28; threshold min 7500000.00; txns=['TXN-P5-0013']`
```json
{
  "formula_kind": "absolute_min",
  "comparison": "min",
  "threshold": 7500000.0,
  "numerator_metrics": [
    "revenue"
  ],
  "denominator_metrics": [],
  "needs_group": false,
  "needs_addbacks": false,
  "needs_fx": false,
  "confidence": 1.0,
  "raw_interpretation": "Минимальная выручка должна быть не менее $7,500,000.00."
}
```
- llm compute: `[formula_spec:absolute_min] Минимальная выручка должна быть не менее $7,500,000.00. | num=['revenue']=8214663.2800 den=[]=0.0000 → actual=8214663.28 min thr=7500000.0 → COMPLIANT`

### P5/6.3
- text: `Пункт 6.3 Максимальные платежи связанным сторонам. За период с 2025-01-01 по 2025-12-31 совокупные платежи Заёмщика (Ekibastuz Power Services JSC) в адрес аффилированных и связанных  сторон не должны превышать $260,000.00. Принадлежность контрагента к связанным сторонам устанавли`
- det reasoning: `[max_related_party] Related-party payments = 273418.66 from ['TXN-P5-0004']; threshold max 260000.00; parties=['Sarybel Capital LLP']`
```json
{
  "formula_kind": "absolute_max",
  "comparison": "max",
  "threshold": 260000.0,
  "numerator_metrics": [
    "related_party_payments"
  ],
  "denominator_metrics": [],
  "needs_group": false,
  "needs_addbacks": false,
  "needs_fx": false,
  "confidence": 1.0,
  "raw_interpretation": "Совокупные платежи Заёмщика в адрес аффилированных и связанных сторон не должны превышать $260,000.00."
}
```
- llm compute: `[formula_spec:absolute_max] Совокупные платежи Заёмщика в адрес аффилированных и связанных сторон не должны превышать $260,000.00. | num=['related_party_payments']=273418.6600 den=[]=0.0000 → actual=273418.66 max thr=260000.0 → BREACH`

### P7/6.1
- text: `Пункт 6.1 Максимальное отношение налоговой и коммунальной нагрузки к EBITDA. На протяжении периода с 2025-01-01 по 2025-12-31 Atyrau Pipeline Services JSC обеспечивает, чтобы отношение суммы Налогов и Коммунальных расходов к EBITDA не превышало 0.30x. Начисленные, но не уплаченны`
- det reasoning: `[tax_util_to_ebitda] (Tax+Util)/EBITDA = (888322.83+91447.35)/2728878.76 = 0.3590→0.36`
```json
{
  "formula_kind": "ratio",
  "comparison": "max",
  "threshold": 0.3,
  "numerator_metrics": [
    "tax_plus_utilities"
  ],
  "denominator_metrics": [
    "ebitda"
  ],
  "needs_group": false,
  "needs_addbacks": false,
  "needs_fx": false,
  "confidence": 1.0,
  "raw_interpretation": "Отношение суммы Налогов и Коммунальных расходов к EBITDA не должно превышать 0.30x."
}
```
- llm compute: `[formula_spec:ratio] Отношение суммы Налогов и Коммунальных расходов к EBITDA не должно превышать 0.30x. | num=['tax_plus_utilities']=979770.1800 den=['ebitda']=2728878.7600 → actual=0.36 max thr=0.3 → BREACH`

### P7/6.2
- text: `Пункт 6.2 Минимальная выручка по категории. Atyrau Pipeline Services JSC обязуется обеспечить, чтобы совокупные поступления по статье «Выручка» за период с 2025-01-01 по 2025-12-31 составляли не менее $8,700,000.00. При расчёте учитываются только суммы, отнесённые к указанной ста`
- det reasoning: `[min_revenue] Revenue (sales settlement) = 9146882.53; threshold min 8700000.00; txns=['TXN-P7-0032']`
```json
{
  "formula_kind": "absolute_min",
  "comparison": "min",
  "threshold": 8700000.0,
  "numerator_metrics": [
    "revenue"
  ],
  "denominator_metrics": [],
  "needs_group": false,
  "needs_addbacks": false,
  "needs_fx": false,
  "confidence": 1.0,
  "raw_interpretation": "Минимальная выручка должна составлять не менее $8,700,000.00."
}
```
- llm compute: `[formula_spec:absolute_min] Минимальная выручка должна составлять не менее $8,700,000.00. | num=['revenue']=9146882.5300 den=[]=0.0000 → actual=9146882.53 min thr=8700000.0 → COMPLIANT`

### P7/6.3
- text: `Пункт 6.3 Максимальные платежи связанным сторонам. Ограничение платежей связанным сторонам. За исключением случаев, прямо согласованных Кредитором в письменной форме, Atyrau Pipeline Services JSC не вправе прямо или косвенно перечислять, передавать или иным образом предоставлять `
- det reasoning: `[max_related_party] Related-party payments = 291663.82 from ['TXN-P7-0035']; threshold max 275000.00; parties=['Atyrau Holding Group LLP']`
```json
{
  "formula_kind": "absolute_max",
  "comparison": "max",
  "threshold": 275000.0,
  "numerator_metrics": [
    "related_party_payments"
  ],
  "denominator_metrics": [],
  "needs_group": false,
  "needs_addbacks": false,
  "needs_fx": false,
  "confidence": 1.0,
  "raw_interpretation": "Total related party payments must not exceed $275,000.00 for the period 2025-01-01 to 2025-12-31."
}
```
- llm compute: `[formula_spec:absolute_max] Total related party payments must not exceed $275,000.00 for the period 2025-01-01 to 2025-12-31. | num=['related_party_payments']=291663.8200 den=[]=0.0000 → actual=291663.82 max thr=275000.0 → BREACH`

### B1/6.1
- text: `Пункт 6.1 Минимальный коэффициент покрытия процентов. Заёмщик, Ekibastuz Energy JSC, обязуется не допускать снижения Коэффициента покрытия процентов ниже величины 2.00x за период с 2025-01-01 по 2025-12-31. Для целей настоящего ковенанта Коэффициент покрытия процентов означает от`
- det reasoning: `[interest_coverage] Interest coverage = EBITDA/Interest = (9741934.78-6166592.66)/2133129.39 = 3575342.12/2133129.39 = 1.68; threshold min 2.0`
```json
{
  "formula_kind": "interest_coverage",
  "comparison": "min",
  "threshold": 2.0,
  "numerator_metrics": [
    "ebitda"
  ],
  "denominator_metrics": [
    "interest"
  ],
  "needs_group": false,
  "needs_addbacks": false,
  "needs_fx": false,
  "confidence": 1.0,
  "raw_interpretation": "Коэффициент покрытия процентов (EBITDA / Interest) должен быть не ниже 2.00x."
}
```
- llm compute: `[formula_spec:interest_coverage] Коэффициент покрытия процентов (EBITDA / Interest) должен быть не ниже 2.00x. | num=['ebitda']=3575342.1200 den=['interest']=2133129.3900 → actual=1.68 min thr=2.0 → BREACH`

### B1/6.2
- text: `Пункт 6.2 Individual Overhead Line Ceiling. Заёмщик, Ekibastuz Energy JSC, обязуется не допускать, чтобы какая-либо отдельная статья накладных расходов превышала $1,500,000.00 за период с 2025-01-01 по 2025-12-31. Для целей настоящего ковенанта отдельными статьями накладных расхо`
- det reasoning: `[max_single_overhead] Max overhead line = max(payroll=1284663.42, utilities=937215.88) = 1284663.42; thr max 1500000.00`
```json
{
  "formula_kind": "absolute_max",
  "comparison": "max",
  "threshold": 1500000.0,
  "numerator_metrics": [
    "payroll",
    "utilities"
  ],
  "denominator_metrics": [],
  "needs_group": false,
  "needs_addbacks": false,
  "needs_fx": false,
  "confidence": 1.0,
  "raw_interpretation": "The maximum of (payroll + utilities) must not exceed $1,500,000.00 for individual overhead lines (payroll and payroll/utilities) checked separately."
}
```
- llm compute: `[formula_spec:absolute_max] The maximum of (payroll + utilities) must not exceed $1,500,000.00 for individual overhead lines (payroll and payroll/utilities) checked separately. | num=['payroll', 'utilities']=2221879.3000 den=[]=0.0000 → actual=2221879.3 max thr=1500000.0 → BREACH`

### B1/6.3
- text: `Пункт 6.3 Максимальные платежи связанным сторонам. За период с 2025-01-01 по 2025-12-31 совокупные платежи Заёмщика (Ekibastuz Energy JSC) в адрес аффилированных и связанных сторон не должны превышать $500,000.00. Принадлежность контрагента к связанным сторонам устанавливается с `
- det reasoning: `[max_related_party] Related-party payments = 307018.08 from ['TXN-B1-0030', 'TXN-B1-0020']; threshold max 500000.00; parties=['Ertis Capital LLP']`
```json
{
  "formula_kind": "absolute_max",
  "comparison": "max",
  "threshold": 500000.0,
  "numerator_metrics": [
    "related_party_payments"
  ],
  "denominator_metrics": [],
  "needs_group": false,
  "needs_addbacks": false,
  "needs_fx": false,
  "confidence": 1.0,
  "raw_interpretation": "Совокупные платежи Заёмщика в адрес аффилированных и связанных сторон не должны превышать $500,000.00."
}
```
- llm compute: `[formula_spec:absolute_max] Совокупные платежи Заёмщика в адрес аффилированных и связанных сторон не должны превышать $500,000.00. | num=['related_party_payments']=307018.0800 den=[]=0.0000 → actual=307018.08 max thr=500000.0 → COMPLIANT`

## Notes
- foundation_sec=0.7

