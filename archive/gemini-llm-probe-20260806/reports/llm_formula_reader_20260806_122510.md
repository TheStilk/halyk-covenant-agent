# LLM Formula Reader probe — `llm_formula_reader_20260806_122510`

- started: `2026-08-06T12:25:10.437831+00:00`
- finished: `2026-08-06T12:26:13.103220+00:00`
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
  "error": "NotFoundError: Error code: 404 - [{'error': {'code': 404, 'message': 'This model models/gemini-2.5-flash is no longer available to new users. Please update your code to use a newer model for the latest features and improvements.', 'status': 'NOT_FOUND'}}]",
  "key_used": "primary",
  "elapsed_sec": 4.316,
  "traceback": "Traceback (most recent call last):\n  File \"/home/mad/Desktop/Access/code/hakaton/scripts/test_llm_formula_reader.py\", line 157, in run_smoke\n    spec = self._with_key_fallback(\n           ^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/home/mad/Desktop/Access/code/hakaton/scripts/test_llm_formula_reader.py\", line 183, in _with_key_fallback\n    return fn()\n           ^^^^\n  File \"/home/mad/Desktop/Access/code/hakaton/scripts/test_llm_formula_reader.py\", line 158, in <lambda>\n    lambda: structured_invoke(\n            ^^^^^^^^^^^^^^^^^^\n  File \"/home/mad/Desktop/Access/code/hakaton/agent/tools/llm.py\", line 172, in structured_invoke\n    raise last_exc\n  File \"/home/mad/Desktop/Access/code/hakaton/agent/tools/llm.py\", line 159, in structured_invoke\n    result = structured.invoke(\n             ^^^^^^^^^^^^^^^^^^\n  File \"/home/mad/Desktop/Access/code/hakaton/.venv/lib/python3.12/site-packages/langchain_core/runnables/base.py\", line 3442, in invoke\n    input_ = context.run(step.invoke, input_, config, **kwargs)\n             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/home/mad/Desktop/Access/code/hakaton/.venv/lib/python3.12/site-packages/langchain_core/runnables/base.py\", line 6002, in invoke\n    return self.bound.invoke(\n           ^^^^^^^^^^^^^^^^^^\n  File \"/home/mad/Desktop/Access/code/hakaton/.venv/lib/python3.12/site-packages/langchain_core/language_models/chat_models.py\", line 476, in invoke\n    self.generate_prompt(\n  File \"/home/mad/Desktop/Access/code/hakaton/.venv/lib/python3.12/site-packages/langchain_core/language_models/chat_models.py\", line 1849, in generate_prompt\n    return self.generate(prompt_messages, stop=stop, callbacks=callbacks, **kwargs)\n           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/home/mad/Desktop/Access/code/hakaton/.venv/lib/python3.12/site-packages/langchain_core/language_models/chat_models.py\", line 1656, in generate\n    self._generate_with_cache(\n  File \"/home/mad/Desktop/Access/code/hakaton/.venv/lib/python3.12/site-packages/langchain_core/language_models/chat_models.py\", line 1994, in _generate_with_cache\n    result = self._generate(\n             ^^^^^^^^^^^^^^^\n  File \"/home/mad/Desktop/Access/code/hakaton/.venv/lib/python3.12/site-packages/langchain_openai/chat_models/base.py\", line 1747, in _generate\n    _handle_openai_api_error(e)\n  File \"/home/mad/Desktop/Access/code/hakaton/.venv/lib/python3.12/site-packages/langchain_openai/chat_models/base.py\", line 1719, in _generate\n    self.root_client.chat.completions.with_raw_response.parse(**payload)\n  File \"/home/mad/Desktop/Access/code/hakaton/.venv/lib/python3.12/site-packages/openai/_legacy_response.py\", line 369, in wrapped\n    return cast(LegacyAPIResponse[R], func(*args, **kwargs))\n                                      ^^^^^^^^^^^^^^^^^^^^^\n  File \"/home/mad/Desktop/Access/code/hakaton/.venv/lib/python3.12/site-packages/openai/resources/chat/completions/completions.py\", line 193, in parse\n    return self._post(\n           ^^^^^^^^^^^\n  File \"/home/mad/Desktop/Access/code/hakaton/.venv/lib/python3.12/site-packages/openai/_base_client.py\", line 1375, in post\n    return cast(ResponseT, self.request(cast_to, opts, stream=stream, stream_cls=stream_cls))\n                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/home/mad/Desktop/Access/code/hakaton/.venv/lib/python3.12/site-packages/openai/_base_client.py\", line 1148, in request\n    raise self._make_status_error_from_response(err.response) from None\nopenai.NotFoundError: Error code: 404 - [{'error': {'code': 404, 'message': 'This model models/gemini-2.5-flash is no longer available to new users. Please update your code to use a newer model for the latest features and improvements.', 'status': 'NOT_FOUND'}}]\n"
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
| P1 | 6.1 | ERR | BREACH/0.46 | None/None | BREACH/0.46 | — | — | 2.49 |
| P1 | 6.2 | ERR | BREACH/6842117.53 | None/None | BREACH/6842117.53 | — | — | 6.941 |
| P1 | 6.3 | ERR | COMPLIANT/283664.18 | None/None | COMPLIANT/283664.18 | — | — | 5.859 |
| P4 | 6.1 | ERR | COMPLIANT/0.33 | None/None | COMPLIANT/0.33 | — | — | 5.5 |
| P4 | 6.2 | ERR | COMPLIANT/1652704.31 | None/None | COMPLIANT/1652704.31 | — | — | 6.862 |
| P4 | 6.3 | ERR | COMPLIANT/0.04 | None/None | COMPLIANT/0.04 | — | — | 5.35 |

## Formula specs (detail)
### P1/6.1
- text: `Пункт 6.1 Maximum Capital Intensity Ratio. Заёмщик, Aktau Port Services JSC, обязуется не допускать, чтобы коэффициент капиталоёмкости за период с 2025-01-01 по 2025-12-31 превышал 0.42x. Коэффициент капиталоёмкости означает отношение совокупных капитальных затрат за период к сум`
- det reasoning: `[capital_intensity] Capital intensity = Capex / (OpEx + Lease) = 1842006.44 / (3104882.61 + 918443.27) = 0.46; threshold max 0.42`
- **error:** `formula_reader: Error code: 404 - [{'error': {'code': 404, 'message': 'This model models/gemini-2.5-flash is no longer available to new users. Please update your code to use a newer model for the latest features and improvements.', 'status': 'NOT_FOUND'}}]`

### P1/6.2
- text: `Пункт 6.2 Минимальная выручка по категории. Для целей настоящей статьи под поступлениями по статье «Выручка» понимаются суммы, отнесённые к данной статье в аудированной финансовой отчётности Заёмщика с учётом переквалификаций, произведённых аудиторами Заёмщика для целей соблюдени`
- det reasoning: `[min_revenue] Revenue (sales settlement) = 6842117.53; threshold min 7100000.00; txns=['TXN-P1-0030']`
- **error:** `formula_reader: Error code: 429 - [{'error': {'code': 429, 'message': 'You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 5, model: gemini-2.5-flash\nPlease retry in 26.964469045s.', 'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': 'type.googleapis.com/google.rpc.Help', 'links': [{'description': 'Learn more about Gemini API quotas', 'url': 'https://ai.google.dev/gemini-api/docs/rate-limits'}]}, {'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaMetric': 'generativelanguage.googleapis.com/generate_content_free_tier_requests', 'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier', 'quotaDimensions': {'location': 'global', 'model': 'gemini-2.5-flash'}, 'quotaValue': '5'}]}, {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '26s'}]}}]`

### P1/6.3
- text: `Пункт 6.3 Максимальные платежи связанным сторонам. Заёмщик, Aktau Port Services JSC, обязуется не допускать, чтобы совокупный объём платежей в пользу связанных сторон за период с 2025-01-01 по 2025-12-31 превышал $450,000.00. Связанные стороны определяются в соответствии с МСФО (`
- det reasoning: `[max_related_party] Related-party payments = 283664.18 from ['TXN-P1-0031']; threshold max 450000.00; parties=['Aktau Holdings LLP']`
- **error:** `formula_reader: Error code: 429 - [{'error': {'code': 429, 'message': 'You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 5, model: gemini-2.5-flash\nPlease retry in 21.101785196s.', 'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': 'type.googleapis.com/google.rpc.Help', 'links': [{'description': 'Learn more about Gemini API quotas', 'url': 'https://ai.google.dev/gemini-api/docs/rate-limits'}]}, {'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaMetric': 'generativelanguage.googleapis.com/generate_content_free_tier_requests', 'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier', 'quotaDimensions': {'model': 'gemini-2.5-flash', 'location': 'global'}, 'quotaValue': '5'}]}, {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '21s'}]}}]`

### P4/6.1
- text: `Пункт 6.1 Минимальная скорректированная рентабельность по EBITDA. На протяжении периода с 2025-01-01 по 2025-12-31 Aktobe Grain Terminal JSC обеспечивает, чтобы отношение Скорректированной EBITDA к Выручке составляло не менее 0.28x. Скорректированная EBITDA рассчитывается как Выр`
- det reasoning: `[adj_ebitda_margin] AdjEBITDA/Revenue = 2321317.34/7004318.47 = 0.3314→0.33; opex=4431662.19 add_backs=824152.91 non_qual_one_time=251338.94; thr min 0.28`
- **error:** `formula_reader: Error code: 429 - [{'error': {'code': 429, 'message': 'You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 5, model: gemini-2.5-flash\nPlease retry in 59.167620012s.', 'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': 'type.googleapis.com/google.rpc.Help', 'links': [{'description': 'Learn more about Gemini API quotas', 'url': 'https://ai.google.dev/gemini-api/docs/rate-limits'}]}, {'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaMetric': 'generativelanguage.googleapis.com/generate_content_free_tier_requests', 'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier', 'quotaDimensions': {'location': 'global', 'model': 'gemini-2.5-flash'}, 'quotaValue': '5'}]}, {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '59s'}]}}]`

### P4/6.2
- text: `Пункт 6.2 Максимальные расходы по категории. Ограничение расходов по статье «Капитальные затраты». Aktobe Grain Terminal JSC обязуется обеспечить, чтобы совокупные расходы по указанной статье, понесённые в период с 2025-01-01 по 2025-12-31, не превышали $1,800,000.00. Любая сумма`
- det reasoning: `[max_capex] Capex = 1652704.31 txns=['TXN-P4-0053']; threshold max 1800000.00`
- **error:** `formula_reader: Error code: 429 - [{'error': {'code': 429, 'message': 'You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 5, model: gemini-2.5-flash\nPlease retry in 52.302294929s.', 'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': 'type.googleapis.com/google.rpc.Help', 'links': [{'description': 'Learn more about Gemini API quotas', 'url': 'https://ai.google.dev/gemini-api/docs/rate-limits'}]}, {'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaMetric': 'generativelanguage.googleapis.com/generate_content_free_tier_requests', 'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier', 'quotaDimensions': {'model': 'gemini-2.5-flash', 'location': 'global'}, 'quotaValue': '5'}]}, {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '52s'}]}}]`

### P4/6.3
- text: `Пункт 6.3 Maximum Related-Party Payments as a Proportion of Revenue. Заёмщик, Aktobe Grain Terminal JSC, обязуется не допускать, чтобы совокупные Ограниченные платежи в пользу аффилированных лиц за период с 2025-01-01 по 2025-12-31 превышали 0.04x от выручки за тот же  период. От`
- det reasoning: `[rp_to_revenue] RP/Revenue = 288417.52/7004318.47 = 0.041177→0.04; threshold max 0.04`
- **error:** `formula_reader: Error code: 404 - [{'error': {'code': 404, 'message': 'This model models/gemini-2.5-flash is no longer available to new users. Please update your code to use a newer model for the latest features and improvements.', 'status': 'NOT_FOUND'}}]`

## Notes
- smoke failed — still running scenarios if possible
- foundation_sec=0.8

