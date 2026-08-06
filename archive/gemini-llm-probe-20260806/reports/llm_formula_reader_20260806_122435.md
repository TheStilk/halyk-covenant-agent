# LLM Formula Reader probe — `llm_formula_reader_20260806_122435`

- started: `2026-08-06T12:24:35.674721+00:00`
- finished: `2026-08-06T12:25:00.792132+00:00`
- model: `gemini-2.5-flash`
- base_url: `https://generativelanguage.googleapis.com/v1beta/openai/`
- MODEL_LABEL: `gemini-2.5-flash`
- scenarios: P1, P4

## Smoke
```json
{
  "available": true,
  "status_message": "LLM available: model=gemini-2.5-flash base=https://generativelanguage.googleapis.com/v1beta/openai/",
  "model": "gemini-2.5-flash",
  "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
  "model_label": "gemini-2.5-flash",
  "structured_ok": false,
  "structured_spec": null,
  "error": "NameError: name 'LLM_MAX_RETRIES' is not defined",
  "key_used": "primary",
  "elapsed_sec": 0.063,
  "traceback": "Traceback (most recent call last):\n  File \"/home/mad/Desktop/Access/code/hakaton/scripts/test_llm_formula_reader.py\", line 157, in run_smoke\n    spec = self._with_key_fallback(\n           ^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/home/mad/Desktop/Access/code/hakaton/scripts/test_llm_formula_reader.py\", line 183, in _with_key_fallback\n    return fn()\n           ^^^^\n  File \"/home/mad/Desktop/Access/code/hakaton/scripts/test_llm_formula_reader.py\", line 158, in <lambda>\n    lambda: structured_invoke(\n            ^^^^^^^^^^^^^^^^^^\n  File \"/home/mad/Desktop/Access/code/hakaton/agent/tools/llm.py\", line 155, in structured_invoke\n    retries = LLM_MAX_RETRIES if max_retries is None else max_retries\n              ^^^^^^^^^^^^^^^\nNameError: name 'LLM_MAX_RETRIES' is not defined\n"
}
```

## Summary
- cells: **6**
- det↔llm AGREE: **0**
- det↔llm MISMATCH: **0**
- errors: **6**
- det matches truth (status+actual≤5%): **6/6**
- llm matches truth (status+actual≤5%): **0/6**
- api key used (final): `primary`

## Cells

| sc | cov | flag | det | llm | truth | err det↔llm | err llm↔truth | t(s) |
|----|-----|------|-----|-----|-------|-------------|---------------|------|
| P1 | 6.1 | ERR | BREACH/0.46 | None/None | BREACH/0.46 | — | — | 0.0 |
| P1 | 6.2 | ERR | BREACH/6842117.53 | None/None | BREACH/6842117.53 | — | — | 0.0 |
| P1 | 6.3 | ERR | COMPLIANT/283664.18 | None/None | COMPLIANT/283664.18 | — | — | 0.0 |
| P4 | 6.1 | ERR | COMPLIANT/0.33 | None/None | COMPLIANT/0.33 | — | — | 0.0 |
| P4 | 6.2 | ERR | COMPLIANT/1652704.31 | None/None | COMPLIANT/1652704.31 | — | — | 0.0 |
| P4 | 6.3 | ERR | COMPLIANT/0.04 | None/None | COMPLIANT/0.04 | — | — | 0.0 |

## Formula specs (detail)
### P1/6.1
- text: `Пункт 6.1 Maximum Capital Intensity Ratio. Заёмщик, Aktau Port Services JSC, обязуется не допускать, чтобы коэффициент капиталоёмкости за период с 2025-01-01 по 2025-12-31 превышал 0.42x. Коэффициент капиталоёмкости означает отношение совокупных капитальных затрат за период к сум`
- det reasoning: `[capital_intensity] Capital intensity = Capex / (OpEx + Lease) = 1842006.44 / (3104882.61 + 918443.27) = 0.46; threshold max 0.42`
- **error:** `formula_reader: name 'LLM_MAX_RETRIES' is not defined`

### P1/6.2
- text: `Пункт 6.2 Минимальная выручка по категории. Для целей настоящей статьи под поступлениями по статье «Выручка» понимаются суммы, отнесённые к данной статье в аудированной финансовой отчётности Заёмщика с учётом переквалификаций, произведённых аудиторами Заёмщика для целей соблюдени`
- det reasoning: `[min_revenue] Revenue (sales settlement) = 6842117.53; threshold min 7100000.00; txns=['TXN-P1-0030']`
- **error:** `formula_reader: name 'LLM_MAX_RETRIES' is not defined`

### P1/6.3
- text: `Пункт 6.3 Максимальные платежи связанным сторонам. Заёмщик, Aktau Port Services JSC, обязуется не допускать, чтобы совокупный объём платежей в пользу связанных сторон за период с 2025-01-01 по 2025-12-31 превышал $450,000.00. Связанные стороны определяются в соответствии с МСФО (`
- det reasoning: `[max_related_party] Related-party payments = 283664.18 from ['TXN-P1-0031']; threshold max 450000.00; parties=['Aktau Holdings LLP']`
- **error:** `formula_reader: name 'LLM_MAX_RETRIES' is not defined`

### P4/6.1
- text: `Пункт 6.1 Минимальная скорректированная рентабельность по EBITDA. На протяжении периода с 2025-01-01 по 2025-12-31 Aktobe Grain Terminal JSC обеспечивает, чтобы отношение Скорректированной EBITDA к Выручке составляло не менее 0.28x. Скорректированная EBITDA рассчитывается как Выр`
- det reasoning: `[adj_ebitda_margin] AdjEBITDA/Revenue = 2321317.34/7004318.47 = 0.3314→0.33; opex=4431662.19 add_backs=824152.91 non_qual_one_time=251338.94; thr min 0.28`
- **error:** `formula_reader: name 'LLM_MAX_RETRIES' is not defined`

### P4/6.2
- text: `Пункт 6.2 Максимальные расходы по категории. Ограничение расходов по статье «Капитальные затраты». Aktobe Grain Terminal JSC обязуется обеспечить, чтобы совокупные расходы по указанной статье, понесённые в период с 2025-01-01 по 2025-12-31, не превышали $1,800,000.00. Любая сумма`
- det reasoning: `[max_capex] Capex = 1652704.31 txns=['TXN-P4-0053']; threshold max 1800000.00`
- **error:** `formula_reader: name 'LLM_MAX_RETRIES' is not defined`

### P4/6.3
- text: `Пункт 6.3 Maximum Related-Party Payments as a Proportion of Revenue. Заёмщик, Aktobe Grain Terminal JSC, обязуется не допускать, чтобы совокупные Ограниченные платежи в пользу аффилированных лиц за период с 2025-01-01 по 2025-12-31 превышали 0.04x от выручки за тот же  период. От`
- det reasoning: `[rp_to_revenue] RP/Revenue = 288417.52/7004318.47 = 0.041177→0.04; threshold max 0.04`
- **error:** `formula_reader: name 'LLM_MAX_RETRIES' is not defined`

## Notes
- smoke failed — still running scenarios if possible
- foundation_sec=0.7

