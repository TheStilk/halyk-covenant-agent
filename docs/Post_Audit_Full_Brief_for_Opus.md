# Post-Audit Full Brief for Opus / Zhenis

**Команда:** Сычуанский Соус  
**Репозиторий:** `github.com/TheStilk/halyk-covenant-agent`  
**Дата брифа:** 6 августа 2026  
**Open-set score сейчас:** **100% (36.0 / 36)**  
**Полный прогон:** ~1.5–2.5 минуты  

Этот документ — полный контекст **после** аудита Opus.  
Он описывает: что было принято из аудита, что отклонено, какие шаги hardening сделаны, как изменилась архитектура, как проверен LLM, какая боевая политика зафиксирована, и что делать 9 августа.

---

## 0. Зачем этот бриф

Аудит Opus правильно вскрыл риски:

1. LLM-слой был написан, но почти не использовался  
2. Много логики заточено под public ground truth  
3. `6.1/6.2/6.3` не означают один и тот же тип формулы  
4. Regex может **обознаться**, а не только сказать “unknown”  
5. Silent PDF extraction fail опасен  
6. `unknown → BREACH + actual=0.0` — плохой default  
7. Полный rewrite в tool-use агента за 2–3 дня рискован без стабильного ключа

После аудита команда **не сносила** рабочий пайплайн.  
Вместо этого:

- усилила deterministic core  
- убрала критические failure modes  
- добавила реальный LLM Formula Reader  
- зафиксировала hybrid policy для private set  

---

## 1. Стратегическое решение после аудита

### Что приняли полностью

- Не удалять старый pipeline до конца хакатона  
- Checkpoint-логика: если LLM-путь не готов — сдаём усиленный det  
- Нужны extraction guards  
- Нужно убрать silent zeros / null cells  
- Нужен способ обобщаться на новые формулировки ковенантов  
- API/provider должен быть сменяемым  

### Что скорректировали

Аудит предлагал сильный крен в tool-use агента.  
Практическое решение команды:

```text
НЕ полный rewrite агента за 2–3 дня
А hybrid:

deterministic first
LLM only for formula interpretation on unknown/low-conf
compute always in code
old formula_engine remains backup + cross-check
```

### Почему не полный rewrite

На момент решения:

- open set уже был **100%**
- полный прогон ~2 минуты
- validate работал
- до private set оставалось мало времени
- без стабильного ключа tool-use агент = высокий риск прийти на бой с полусломанной системой

Поэтому выбран путь:

**усилить то, что работает + добавить LLM-интерпретацию формул**

---

## 2. Важное эмпирическое наблюдение по датасету

Проверка всех 12 loan agreements подтвердила:

> Номер пункта (`6.1`) **не определяет** тип ковенанта.

Примеры разных `6.1`:

- Group Capex / EBITDA  
- Adjusted EBITDA margin  
- Capital Intensity Ratio  
- Springing Drawdown Leverage Test  
- Interest coverage  
- Tax+utilities / EBITDA  
- Insurance coverage  
- Q4 revenue  
- Related-party share  
- Assets transferred to subsidiaries  

**12 заёмщиков ≈ 12 разных формул под одним номером.**

Следствие для private set:

- “unknown formula” будет частым  
- ещё опаснее false match regex по словам вроде “EBITDA”, “выручка”, “overhead”

Именно поэтому нужен LLM reader на интерпретацию формулировки, а не только “fallback когда regex честно признался, что не знает”.

---

## 3. Что было до hardening (коротко)

К моменту аудита уже существовал сильный det pipeline:

- LangGraph linear flow  
- ledger mapping `txn_id → scenario_id`  
- PDF classify: loan / notes / kyc / junk  
- Article 6 extraction  
- metrics: KYC, AUP, FX, NaN fills, Group Capex, Adj EBITDA add-backs  
- formula_engine с набором handlers  
- open set доведён до **100%**  
- evidence 100%  

Но риски аудита были реальными:

- hardcode под known wording  
- LLM path inactive  
- weak/unknown defaults  
- silent extraction edge-cases  

---

## 4. Hardening после аудита — все шаги

Ниже — фактические шаги, которые были сделаны **после** аудита.

### Шаг 0 — Baseline

```bash
uv run python scripts/eval_phase2.py
```

Результат до изменений:

- score **36/36**
- status 36/36
- evidence 9/9
- mean/max rel error 0%

Baseline зафиксирован.

---

### Шаг 1 — Никогда не оставлять пустые ячейки

**Проблема:** missing text/metrics могли приводить к null / skip.

**Сделано:**

- `ensure_filled_cell()` / `ensure_filled_answers()`
- sanitize перед записью submission
- validate hard-fail на null/missing status/actual + NaN
- best-effort заполнение вместо пустых ячеек

**Поведение при нехватке данных:**

- нет metrics → `BREACH`, `actual=0.0`, `evidence=null`, low conf  
- нет текста → не skip, идём в evaluate empty/best-effort  
- invalid status/actual → sanitize  

**Результат:** score остался **36/36**

---

### Шаг 2 — Extraction quality guards

**Проблема аудита:** `len(text) >= 40` слишком слабый критерий; pdftotext мог вернуть латиницу/мусор и пройти порог.

**Сделано:**

- убран `len >= 40` как критерий успеха  
- `assess_extract_quality()`:
  - meaningful length
  - доля кириллицы
  - маркеры `ACC-` / `TXN-` / `$|USD` / `Статья|Article`
  - плотность alnum
- fallback backend: pdfplumber → pymupdf → pdftotext  
- если всё плохо → degraded/failed + WARNING, не тихий пустой успех  
- cache key version bump (`EXTRACT_QUALITY_VERSION=q2`)

**Результат:**

- score **36/36**
- bad extract явно пойман: `f3fa6d20c8a1.pdf` (image-only / score 0)

---

### Шаг 3 — Template-driven structure

**Проблема аудита:** hardcode `COVENANT_IDS=("6.1","6.2","6.3")`, hardcode Article 6, ACC-7*, JSC.

**Сделано:**

- covenant ids читаются из `submission_template.json`
- per-scenario ids через `covenant_ids_for_scenario()`
- поиск блока ковенантов:
  - сначала clause ids из template
  - fallback `Статья N` / `Article N` (N из ids)
- account_id: 3–6 цифр, `АСС`, loose patterns
- юр. формы шире, чем только JSC (`LLC/LLP/ТОО/АО/...`)
- borrower selection не только через ACC-7*

**Результат:** score **36/36**, open set clauses 12/12

Это критично для private set, где нумерация/обёртка статьи могут отличаться.

---

### Шаг 4 — Unknown formula больше не silent BREACH/0

**Проблема аудита:** unknown formula → `BREACH, actual=0.0`

**Сделано:**

- unknown path больше не silent zero-breach  
- soft keyword remap с low confidence  
- best-effort по shape threshold/metrics  
- всегда заполненные status/actual  
- diagnostics: `unknown_formula_*`  
- LLM branch подготовлен: если есть ключ и unknown/low-conf → structured reader

**Результат:** score **36/36**  
Known open-set handlers не сломаны.

---

### Шаг 5 — Taxonomy транзакций

**Проблема аудита:** ~26% ledger transactions уходили в `other_*` даже на public данных.

**Сделано:** расширены family-patterns:

- interest / overdraft / capitalised interest  
- lease / storage unit rent  
- insurance refunds/rebates  
- VAT refund / tax credit  
- utilities corrections  
- marketing rebates  

**Измеренный эффект на public ledger:**

| category | до | после |
|--------------|------|
| other_inflow | 23.4% | 0.4% |
| other_expense | 4.5% | 0.2% |
| total other | ~28% | ~0.6% |

**Результат:** score **36/36**  
Известные revenue/capex/rp/tax/utilities не сломаны.

---

### Шаг 6 — Battle diagnostics

В конце `phase3` теперь печатается:

```text
=== BATTLE DIAGNOSTICS ===
cells filled: 36/36
unknown formulas: ...
low confidence: ...
bad extracts: ...
missing amounts: ...
scenarios without loan: ...
scenarios without notes: ...
time total: ...
```

Пример реального вывода:

```text
cells filled: 36/36
unknown formulas: 0
low confidence: 1 [B4/6.1 conf=0.70]
bad extracts: 1 [f3fa6d20c8a1.pdf]
missing amounts: 2 [P7:1, P8:1]
scenarios without loan: —
scenarios without notes: —
time total: 104.5s
```

---

## 5. Архитектура сейчас (после всех изменений)

### High-level flow

```text
START
  load_ledger
  classify_docs
  extract_covenants
  extract_metrics
  analyze_covenants
      ├─ always: deterministic evaluate_covenant
      ├─ if unknown/low-conf and LLM available:
      │     Formula Reader → FormulaSpec
      │     deterministic compute_from_formula_spec
      │     mismatch policy
      └─ never leave null cells
  collect_results
  write submission.json
  validate
  battle diagnostics
END
```

### Принцип hybrid

```text
LLM = интерпретатор формулировки ковенанта
Code = арифметика, status, evidence
Det engine = primary на known + backup всегда
```

### Что сохранено из старого ядра

- `metrics.py`  
- `formula_engine.py`  
- Group Capex via consolidated PPE  
- Adj EBITDA add-back threshold logic  
- NaN ledger fills from notes/treasury  
- FX conversion  
- evidence logic (“remove txn → verdict changes”)  
- validate against template keys  

### Что добавлено

- quality-guarded PDF extraction  
- template-driven covenant ids  
- no-null guarantees  
- taxonomy expansion  
- diagnostics  
- provider-agnostic LLM client  
- FormulaSpec / Formula Reader / formula_compute  
- battle policy flags in env  

---

## 6. LLM Formula Reader — как устроен

### Вход

- текст ковенанта  
- компактный metrics snapshot  
- scenario/covenant id  

### Выход (`FormulaSpec`)

Примерно:

- `formula_kind`
- `comparison`: min/max
- `threshold`
- `numerator_metrics`
- `denominator_metrics`
- `needs_group` / `needs_addbacks` / `needs_fx`
- `confidence`
- `raw_interpretation`

### Важно

LLM **не считает actual**.  
После spec всегда идёт deterministic `compute_from_formula_spec()`.

### Provider-agnostic client

Только env:

```env
LLM_API_KEY=...
LLM_BASE_URL=...
LLM_MODEL=...
```

Смена OpenRouter / Google OpenAI-compat / другого proxy = смена env, без переписывания бизнес-логики.

Дополнительно:

```env
USE_LLM_FORMULA_READER=true
LLM_FORMULA_READER_ONLY_UNKNOWN=true
FORMULA_READER_PREFER_DET_ON_MISMATCH=true
FORMULA_READER_MAX_TEXT_CHARS=900
LLM_MAX_TOKENS=8192
```

---

## 7. Боевая политика (зафиксирована в коде)

```text
1. Всегда считать det
2. LLM unavailable / ERR → det
3. det high-confidence known formula → det
   (LLM на known cells по умолчанию не вызываем)
4. det unknown / low-conf → FormulaSpec + compute
5. mismatch:
   - det known-like → det
   - det unknown → LLM compute
```

Это напрямую закрывает два риска:

- не потерять 100% на известных паттернах  
- не остаться без интерпретатора на новых private формулировках  

---

## 8. Проверки, что LLM реально работает

Было сомнение: “может тесты всё ещё только det?”

### Доказательства, что LLM вызывается

1. На hard-кейсах были **API ERR**  
   - P3/6.1 length limit  
   - P3/6.3 API 500  
2. Был смысловой **MISMATCH**  
   - B1/6.2: LLM сложил payroll+utilities  
   - det правильно взял max single overhead line  
3. В probe-отчётах есть `FormulaSpec`, `raw_interpretation`, model/base_url  

Если бы шёл только det, mismatch/API errors не появились бы.

### Результаты probe

#### P1 / P4

- 6/6 AGREE  
- det↔truth 6/6  
- llm↔truth 6/6  

#### Hard: P3 / P5 / P7 / B1

- AGREE: 9  
- MISMATCH: 1 (B1/6.2, det прав)  
- ERR: 2 (API/model limits)  
- det↔truth: 12/12  
- llm↔truth там, где LLM ответил: 9/10  

Вывод:

- LLM полезен  
- LLM иногда ошибается  
- det backup обязателен и уже спасает  

---

## 9. Модельная стратегия на бой

### План команды

| Роль | Модель |
|------|--------|
| Fast / fallback | Gemini 3.6 Flash |
| Powerful formula reader | одна top-модель рынка |
| No-LLM path | полный det |

### Почему не “всё на самую мощную”

- на known cells det уже точен  
- powerful model дороже/медленнее  
- главная ценность мощной модели — интерпретация **новых** формулировок  

### Про обрезанные промпты

Для Flash/Gemma clip (~900 chars) полезен против length limits.  
Для powerful model можно поднять clip до 2500–4000 через env, не возвращая огромные dumps транзакций.

Нужно сохранять:

- strict schema  
- запрет арифметики в LLM  
- explicit min/max rules  
- hint’ы вроде `max overhead = max(line), not sum`

---

## 10. Документация и репозиторий после изменений

Обновлено:

- `.env.example` → `LLM_*`  
- README: hybrid architecture, team contacts  
- `docs/architecture.md` / `usage.md` / `data-and-scoring.md`  
- validate hardened  
- `scripts/test_llm_formula_reader.py` для probe det vs LLM  
- `test_runs/` gitignored  

`PLAN.md` (старый master plan) удалён/заменён актуальной docs-структурой.  
Source of truth теперь: код + `docs/*` + этот бриф по post-audit решениям.

---

## 11. Текущая готовность

| Компонент | Статус |
|-----------|--------|
| Open-set score | ✅ 100% |
| Validate | ✅ |
| No null cells | ✅ |
| Extraction guards | ✅ |
| Template-driven ids | ✅ |
| Taxonomy | ✅ сильно улучшена |
| Diagnostics | ✅ |
| LLM client | ✅ provider-agnostic |
| Formula Reader | ✅ verified |
| Battle policy | ✅ in code |
| Full rewrite agent | ❌ consciously not done |
| Private-set risk | остаётся, но закрыт hybrid-подходом |

---

## 12. Что осталось до 9 августа

### Обязательно

1. Выбрать powerful-модель и сделать smoke  
2. Проверить submission fields:
   - `team`
   - `contact_email`
   - `model`
3. Сухой прогон:
   ```bash
   rm -rf doc_cache
   time uv run python main.py phase3
   uv run python main.py validate
   ```
4. Договориться, кто сдаёт `submission.json`

### Желательно

- smoke на втором provider endpoint  
- Windows backup machine у Zhenis поднимает repo и проходит `eval_phase2`  
- короткий role chart на бой  

---

## 13. Runbook боевого дня

```text
11:00  получить private dataset
11:05  export DATA_DIR=...
       rm -rf doc_cache
11:10  uv run python main.py phase3
12:30  смотреть BATTLE DIAGNOSTICS
13:00  uv run python main.py validate
13:00–13:30  если много unknown/low-conf — точечный LLM path уже включится сам
13:30–13:45  финальный validate
13:45–14:00  сдача submission.json
```

### Роли

| Кто | Зона |
|-----|------|
| Madiyar | основной прогон, validate, upload |
| Zhenis | diagnostics review, backup machine, контроль unknown/low-conf |

---

## 14. Прямые ответы на тезисы аудита

| Тезис аудита | Что сделано |
|--------------|-------------|
| Это не агент, а regex engine | Частично да; после аудита добавлен реальный LLM interpretation layer, но det core сохранён осознанно |
| 98.6/100% = overfitting | Риск признан; поэтому добавлены template-driven structure, unknown path, LLM reader, taxonomy expansion |
| LLM не участвует | Уже не так: Formula Reader verified, probe quantifies agree/mismatch/errors |
| Unknown → zero breach | Исправлено |
| Silent PDF fail | Исправлено quality guards |
| Hardcode Article6/ACC-7/JSC | Смягчено / template-driven |
| Нужен tool-use rewrite | Отложен как excess risk; вместо него hybrid interpretation/compute split |
| Нужна дисциплина backup | Соблюдена: det path всегда жив и сдаваем |

---

## 15. Главный вывод для Opus

Команда не проигнорировала аудит.

Взяли:

- риск переобучения  
- риск false-match формул  
- риск silent extraction  
- риск пустых/нулевых ячеек  
- необходимость LLM на интерпретации новых формулировок  

Не взяли:

- полный снос рабочего 100% pipeline  
- ставку “успеть настоящего tool-use агента за 48–72 часа или провал”  

Текущая система:

```text
сильный deterministic financial engine
+
реальный LLM formula interpreter на unknown/low-conf
+
жёсткие guards / validate / diagnostics
```

Это pragmatic production-style agentic system under contest constraints, а не academic purity rewrite.

**Готовность к 9 августа: высокая.**  
Основной оставшийся риск — genuinely new private formulations; под него уже есть LLM Formula Reader и never-empty submission path.

---

## 16. Если Opus продолжает работу

Полезные следующие задачи (без ломки 36/36):

1. Powerful-model profile:
   - larger covenant text window  
   - same strict FormulaSpec schema  
2. Better mismatch diagnostics dump  
3. Optional second provider failover  
4. Windows setup checklist for Zhenis  
5. One-page battle card only commands + roles  

Не нужно:

- удалять formula_engine  
- переписывать metrics с нуля  
- делать LLM-арифметику  
- включать LLM на все known cells by default  
