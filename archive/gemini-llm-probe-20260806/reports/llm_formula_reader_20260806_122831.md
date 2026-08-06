# LLM Formula Reader probe — `llm_formula_reader_20260806_122831`

- started: `2026-08-06T12:28:31.700508+00:00`
- finished: `2026-08-06T12:32:54.470204+00:00`
- model: `gemini-3-flash-preview`
- base_url: `https://generativelanguage.googleapis.com/v1beta/openai/`
- MODEL_LABEL: `gemini-3-flash-preview`
- scenarios: P1, P4

## Smoke
```json
{
  "available": true,
  "status_message": "LLM available: model=gemini-3-flash-preview base=https://generativelanguage.googleapis.com/v1beta/openai/",
  "model": "gemini-3-flash-preview",
  "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
  "model_label": "gemini-3-flash-preview",
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
  "elapsed_sec": 21.217
}
```

## Summary
- cells: **6**
- det↔llm AGREE: **6**
- det↔llm MISMATCH: **0**
- errors: **0**
- det matches truth (status+actual≤5%): **6/6**
- llm matches truth (status+actual≤5%): **6/6**
- api key used (final): `primary`

## Cells

| sc | cov | flag | det | llm | truth | err det↔llm | err llm↔truth | t(s) |
|----|-----|------|-----|-----|-------|-------------|---------------|------|
| P1 | 6.1 | AGREE | BREACH/0.46 | BREACH/0.46 | BREACH/0.46 | 0.00% | 0.00% | 40.156 |
| P1 | 6.2 | AGREE | BREACH/6842117.53 | BREACH/6842117.53 | BREACH/6842117.53 | 0.00% | 0.00% | 37.862 |
| P1 | 6.3 | AGREE | COMPLIANT/283664.18 | COMPLIANT/283664.18 | COMPLIANT/283664.18 | 0.00% | 0.00% | 30.688 |
| P4 | 6.1 | AGREE | COMPLIANT/0.33 | COMPLIANT/0.33 | COMPLIANT/0.33 | 0.00% | 0.00% | 30.872 |
| P4 | 6.2 | AGREE | COMPLIANT/1652704.31 | COMPLIANT/1652704.31 | COMPLIANT/1652704.31 | 0.00% | 0.00% | 42.681 |
| P4 | 6.3 | AGREE | COMPLIANT/0.04 | COMPLIANT/0.04 | COMPLIANT/0.04 | 0.00% | 0.00% | 34.575 |

## Formula specs (detail)
### P1/6.1
- text: `Пункт 6.1 Maximum Capital Intensity Ratio. Заёмщик, Aktau Port Services JSC, обязуется не допускать, чтобы коэффициент капиталоёмкости за период с 2025-01-01 по 2025-12-31 превышал 0.42x. Коэффициент капиталоёмкости означает отношение совокупных капитальных затрат за период к сум`
- det reasoning: `[capital_intensity] Capital intensity = Capex / (OpEx + Lease) = 1842006.44 / (3104882.61 + 918443.27) = 0.46; threshold max 0.42`
```json
{
  "formula_kind": "capital_intensity",
  "comparison": "max",
  "threshold": 0.42,
  "numerator_metrics": [
    "capex"
  ],
  "denominator_metrics": [
    "opex",
    "lease"
  ],
  "needs_group": false,
  "needs_addbacks": false,
  "needs_fx": false,
  "confidence": 1.0,
  "raw_interpretation": "Коэффициент капиталоемкости (CAPEX / (OPEX + Lease)) не должен превышать 0.42."
}
```
- llm compute: `[formula_spec:capital_intensity] Коэффициент капиталоемкости (CAPEX / (OPEX + Lease)) не должен превышать 0.42. | num=['capex']=1842006.4400 den=['opex', 'lease']=4023325.8800 → actual=0.46 max thr=0.42 → BREACH`

### P1/6.2
- text: `Пункт 6.2 Минимальная выручка по категории. Для целей настоящей статьи под поступлениями по статье «Выручка» понимаются суммы, отнесённые к данной статье в аудированной финансовой отчётности Заёмщика с учётом переквалификаций, произведённых аудиторами Заёмщика для целей соблюдени`
- det reasoning: `[min_revenue] Revenue (sales settlement) = 6842117.53; threshold min 7100000.00; txns=['TXN-P1-0030']`
```json
{
  "formula_kind": "absolute_min",
  "comparison": "min",
  "threshold": 7100000.0,
  "numerator_metrics": [
    "revenue"
  ],
  "denominator_metrics": [],
  "needs_group": false,
  "needs_addbacks": false,
  "needs_fx": false,
  "confidence": 1.0,
  "raw_interpretation": "Заемщик обязуется поддерживать выручку на уровне не менее 7 100 000 долларов США."
}
```
- llm compute: `[formula_spec:absolute_min] Заемщик обязуется поддерживать выручку на уровне не менее 7 100 000 долларов США. | num=['revenue']=6842117.5300 den=[]=0.0000 → actual=6842117.53 min thr=7100000.0 → BREACH`

### P1/6.3
- text: `Пункт 6.3 Максимальные платежи связанным сторонам. Заёмщик, Aktau Port Services JSC, обязуется не допускать, чтобы совокупный объём платежей в пользу связанных сторон за период с 2025-01-01 по 2025-12-31 превышал $450,000.00. Связанные стороны определяются в соответствии с МСФО (`
- det reasoning: `[max_related_party] Related-party payments = 283664.18 from ['TXN-P1-0031']; threshold max 450000.00; parties=['Aktau Holdings LLP']`
```json
{
  "formula_kind": "absolute_max",
  "comparison": "max",
  "threshold": 450000.0,
  "numerator_metrics": [
    "related_party_payments"
  ],
  "denominator_metrics": [],
  "needs_group": false,
  "needs_addbacks": false,
  "needs_fx": true,
  "confidence": 1.0,
  "raw_interpretation": "Совокупный объем платежей связанным сторонам не должен превышать 450 000 долларов США."
}
```
- llm compute: `[formula_spec:absolute_max] Совокупный объем платежей связанным сторонам не должен превышать 450 000 долларов США. | num=['related_party_payments']=283664.1800 den=[]=0.0000 → actual=283664.18 max thr=450000.0 → COMPLIANT`

### P4/6.1
- text: `Пункт 6.1 Минимальная скорректированная рентабельность по EBITDA. На протяжении периода с 2025-01-01 по 2025-12-31 Aktobe Grain Terminal JSC обеспечивает, чтобы отношение Скорректированной EBITDA к Выручке составляло не менее 0.28x. Скорректированная EBITDA рассчитывается как Выр`
- det reasoning: `[adj_ebitda_margin] AdjEBITDA/Revenue = 2321317.34/7004318.47 = 0.3314→0.33; opex=4431662.19 add_backs=824152.91 non_qual_one_time=251338.94; thr min 0.28`
```json
{
  "formula_kind": "ratio",
  "comparison": "min",
  "threshold": 0.28,
  "numerator_metrics": [
    "adjusted_ebitda"
  ],
  "denominator_metrics": [
    "revenue"
  ],
  "needs_group": false,
  "needs_addbacks": true,
  "needs_fx": false,
  "confidence": 1.0,
  "raw_interpretation": "Отношение скорректированной EBITDA к выручке должно быть не менее 0.28."
}
```
- llm compute: `[formula_spec:ratio] Отношение скорректированной EBITDA к выручке должно быть не менее 0.28. | num=['adjusted_ebitda']=2321317.3400 den=['revenue']=7004318.4700 → actual=0.33 min thr=0.28 → COMPLIANT`

### P4/6.2
- text: `Пункт 6.2 Максимальные расходы по категории. Ограничение расходов по статье «Капитальные затраты». Aktobe Grain Terminal JSC обязуется обеспечить, чтобы совокупные расходы по указанной статье, понесённые в период с 2025-01-01 по 2025-12-31, не превышали $1,800,000.00. Любая сумма`
- det reasoning: `[max_capex] Capex = 1652704.31 txns=['TXN-P4-0053']; threshold max 1800000.00`
```json
{
  "formula_kind": "absolute_max",
  "comparison": "max",
  "threshold": 1800000.0,
  "numerator_metrics": [
    "capex"
  ],
  "denominator_metrics": [],
  "needs_group": false,
  "needs_addbacks": false,
  "needs_fx": false,
  "confidence": 1.0,
  "raw_interpretation": "Капитальные затраты не должны превышать 1 800 000 долларов США."
}
```
- llm compute: `[formula_spec:absolute_max] Капитальные затраты не должны превышать 1 800 000 долларов США. | num=['capex']=1652704.3100 den=[]=0.0000 → actual=1652704.31 max thr=1800000.0 → COMPLIANT`

### P4/6.3
- text: `Пункт 6.3 Maximum Related-Party Payments as a Proportion of Revenue. Заёмщик, Aktobe Grain Terminal JSC, обязуется не допускать, чтобы совокупные Ограниченные платежи в пользу аффилированных лиц за период с 2025-01-01 по 2025-12-31 превышали 0.04x от выручки за тот же  период. От`
- det reasoning: `[rp_to_revenue] RP/Revenue = 288417.52/7004318.47 = 0.041177→0.04; threshold max 0.04`
```json
{
  "formula_kind": "ratio",
  "comparison": "max",
  "threshold": 0.04,
  "numerator_metrics": [
    "related_party_payments"
  ],
  "denominator_metrics": [
    "revenue"
  ],
  "needs_group": false,
  "needs_addbacks": false,
  "needs_fx": false,
  "confidence": 1.0,
  "raw_interpretation": "Отношение платежей аффилированным лицам к выручке не должно превышать 0.04."
}
```
- llm compute: `[formula_spec:ratio] Отношение платежей аффилированным лицам к выручке не должно превышать 0.04. | num=['related_party_payments']=288417.5200 den=['revenue']=7004318.4700 → actual=0.04 max thr=0.04 → COMPLIANT`

## Notes
- foundation_sec=0.7

