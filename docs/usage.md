# Использование

## Установка

```bash
# Python 3.12+ подтянется через uv при необходимости
uv sync
```

Системные утилиты (рекомендуется):

| Утилита | Зачем |
|---------|--------|
| `pdftotext` (poppler) | fallback извлечения текста |
| `pdftoppm` (poppler) | рендер страниц KYC / notes для OCR |
| `tesseract` (+ eng/rus) | OCR ownership, subsidiaries, EBITDA tables |

```bash
# Debian/Ubuntu (пример)
sudo apt install poppler-utils tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng
```

---

## Конфигурация (`.env`)

Скопируйте `.env.example` → `.env`.

| Переменная | Default | Описание |
|------------|---------|----------|
| `TEAM_NAME` | `Сычуанский Соус` | поле submission |
| `CONTACT_EMAIL` | `serkebaevmadiyar09@gmail.com, zhenis415@gmail.com` | поле submission (обе почты команды) |
| `DATA_DIR` | `./agentic-bank-public` | датасет |
| `DOC_CACHE_DIR` | `./doc_cache` | кэш PDF |
| `LLM_API_KEY` | — | ключ OpenAI-compatible API |
| `LLM_BASE_URL` | — | `https://host/v1` (любой провайдер) |
| `LLM_MODEL` | — | id модели у провайдера |
| `MODEL_LABEL` | =`LLM_MODEL` | поле `model` в submission |
| `CLASSIFY_API_KEY` / `BASE_URL` / `MODEL` | optional | отдельная модель для classify |
| `USE_LLM_FORMULA_READER` | `true` | LLM → formula_spec, code → actual |
| `FORMULA_READER_PREFER_DET_ON_MISMATCH` | `true` | mismatch → det engine |
| `CLASSIFY_USE_LLM` | `false` | LLM для ambiguous PDF |
| `CONFIDENCE_THRESHOLD` | `0.85` | low-conf / reflection |

**Смена модели:** правьте только env — не код и не «роли» vendor’ов.

```bash
# пример
export LLM_API_KEY=...
export LLM_BASE_URL=https://openrouter.ai/api/v1
export LLM_MODEL=your/model-id

uv run python scripts/smoke_llm.py
```

---

## CLI (`main.py`)

Все команды через `uv run` (или активированный `.venv`).

### Полный пайплайн + валидация

```bash
uv run python main.py phase3
uv run python main.py validate
```

`phase3` / `phase2` пишут `submission.json` и печатают **battle diagnostics**:

```text
=== BATTLE DIAGNOSTICS ===
cells filled: 36/36
unknown formulas: 0
low confidence: 1 [B4/6.1 conf=0.70]
bad extracts: 1 [f3fa6d20c8a1.pdf]
missing amounts: 2 [P7:1, P8:1 (txns=2)]
scenarios without loan: —
scenarios without notes: —
time total: ~100s
```

`submission.json` в корне:

```json
{
  "team": "...",
  "contact_email": "...",
  "model": "<MODEL_LABEL or LLM_MODEL>",
  "answers": {
    "P1": {
      "6.1": { "status": "BREACH", "actual": 0.46, "evidence_txn_id": null },
      "6.2": { ... },
      "6.3": { ... }
    }
  }
}
```

### Validate

```bash
uv run python main.py validate
uv run python main.py validate --submission ./submission.json
uv run python scripts/validate_submission.py
```

Проверяет submission относительно `submission_template.json`:

1. Валидный JSON  
2. Поля `team`, `contact_email`, `model`, `answers`  
3. Точный набор `scenario_id` и `covenant_id` (нельзя добавлять/удалять/переименовывать)  
4. `status` ∈ `{COMPLIANT, BREACH}`  
5. `actual` — число ≥ 0, не больше 2 знаков после запятой  
6. `evidence_txn_id` — string или null  
7. **Hard-fail** на null/missing `status` / `actual` (и NaN)  

Pipeline **никогда** не оставляет пустые ячейки: `ensure_filled_cell` → best-effort `BREACH`/`0.0` при нехватке данных.

Вывод:

- `OK — submission is valid` (exit 0)  
- `INVALID — N error(s):` + нумерованный список (exit 1)  

### Phase 1 — foundation

```bash
uv run python main.py foundation
```

Только ledger + classify + covenants (12/12 сценариев с полным набором template clause ids).

### Утилиты

```bash
uv run python main.py map-accounts
uv run python main.py classify agentic-bank-public/documents/1d262694c308.pdf
uv run python main.py extract-covenants agentic-bank-public/documents/1d262694c308.pdf
```

---

## Scripts

| Script | Назначение |
|--------|------------|
| `scripts/smoke_phase1.py` | Регрессия Phase 1 без LLM |
| `scripts/run_one_scenario.py` | 1+ сценариев vs ground_truth |
| `scripts/eval_phase2.py` | Полный score 36 ячеек + WORST CELLS; `--scenarios` subset |
| `scripts/validate_submission.py` | Формат submission |

```bash
uv run python scripts/smoke_phase1.py
uv run python scripts/run_one_scenario.py           # default P1 P5
uv run python scripts/run_one_scenario.py P4
uv run python scripts/eval_phase2.py
uv run python scripts/eval_phase2.py --scenarios P5 B1   # holdout-style subset
uv run python scripts/validate_submission.py --submission ./submission.json
```

---

## Типичные workflow

### Open set: полный цикл

```bash
uv sync
uv run python scripts/eval_phase2.py    # ожидаем 36.0 / 36.0
uv run python main.py phase3
uv run python main.py validate
```

### Отладка одной ячейки

```bash
uv run python scripts/run_one_scenario.py P4
uv run python scripts/eval_phase2.py --scenarios P4
```

### Private dataset (боевой день)

```bash
export DATA_DIR=/path/to/private-dataset
# optional: LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
rm -rf doc_cache
uv run python main.py phase3
# прочитать === BATTLE DIAGNOSTICS ===
uv run python main.py validate
# сдать submission.json
```

Чеклист боя:

1. `cells filled` = expected (template × scenarios)  
2. `unknown formulas` / `low confidence` — кандидаты на LLM  
3. `bad extracts` / `scenarios without loan|notes` — риск  
4. `validate` exit 0  

---

## Кэш документов

- Каталог: `DOC_CACHE_DIR` (default `./doc_cache`).  
- Ключ: `md5(abs_path:size:mtime_ns:eq=<EXTRACT_QUALITY_VERSION>)`.  

```bash
rm -rf doc_cache   # после смены extractors, quality version или датасета
```

---

## Отладка

| Симптом | Что проверить |
|---------|----------------|
| null status/actual | `ensure_filled_*`, collect_results, validate |
| degraded extract | `assess_extract_quality`, backends, `diagnostics.bad_extracts` |
| 0 related-party | KYC OCR, threshold, `L.L.P.` / quotes |
| Group Capex = borrower only | consolidated FS, segment name = company |
| Adj EBITDA margin off | OCR «Корректировки EBITDA», порог $300k |
| Reclass не применился | final AUP vs draft intermediate |
| NaN amount в ledger | notes/treasury; battle `missing amounts` |
| EUR в EBITDA | курс в notes (EUR … $USD) |
| evidence ≠ GT | reclass txn order в `_find_evidence_for_sum` |
| high other_* share | `classify_txn_category` patterns |
| unknown formula BREACH/0 | should not happen silent — `_best_effort_unknown` |
| Медленный eval | OCR KYC (~1–2 мин на 12 сценариев); cold cache rebuild |

---

## Добавление зависимости

```bash
uv add package-name
uv lock && uv sync
uv export --no-dev --no-hashes -o requirements.txt   # опционально
```
