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
| `QWEN_API_KEY` | — | reasoning (или `OPENAI_API_KEY`) |
| `QWEN_BASE_URL` | OpenRouter | OpenAI-compatible endpoint |
| `QWEN_MODEL` | `qwen/qwen3.5-max` | slug модели |
| `GOOGLE_API_KEY` | — | Gemini (или `GEMINI_API_KEY`) |
| `GEMINI_MODEL` | `gemini-3.0-flash` | slug Flash |
| `CLASSIFY_USE_LLM` | `false` | Gemini для ambiguous PDF |
| `CONFIDENCE_THRESHOLD` | `0.85` | порог reflection / Qwen |
| `MAX_BORROWER_CONCURRENCY` | `6` | задел под parallel |

`model` в submission: `qwen3.8-max + gemini-3.6-flash` (`config.MODEL_LABEL`).

---

## CLI (`main.py`)

Все команды через `uv run` (или активированный `.venv`).

### Полный пайплайн + валидация

```bash
uv run python main.py phase3
uv run python main.py validate
```

`phase3` / `phase2` пишут `submission.json` в корень:

```json
{
  "team": "...",
  "contact_email": "...",
  "model": "qwen3.8-max + gemini-3.6-flash",
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
7. Нет null в `status` / `actual`  

Вывод:

- `OK — submission is valid` (exit 0)  
- `INVALID — N error(s):` + нумерованный список (exit 1)  

### Phase 1 — foundation

```bash
uv run python main.py foundation
```

Только ledger + classify + Article 6 (12/12 сценариев с 6.1–6.3).

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
| `scripts/eval_phase2.py` | Полный score 36 ячеек + WORST CELLS |
| `scripts/validate_submission.py` | Формат submission |

```bash
uv run python scripts/smoke_phase1.py
uv run python scripts/run_one_scenario.py           # default P1 P5
uv run python scripts/run_one_scenario.py P4
uv run python scripts/eval_phase2.py
uv run python scripts/eval_phase2.py --scenarios P5 B1
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
rm -rf doc_cache
uv run python main.py phase3
uv run python main.py validate
# сдать submission.json
```

---

## Кэш документов

- Каталог: `DOC_CACHE_DIR` (default `./doc_cache`).  
- Ключ: `md5(abs_path:size:mtime_ns)`.  

```bash
rm -rf doc_cache   # после смены extractors или датасета
```

---

## Отладка

| Симптом | Что проверить |
|---------|----------------|
| 0 related-party | KYC OCR, threshold, `L.L.P.` / quotes |
| Group Capex = borrower only | consolidated FS, segment name = company |
| Adj EBITDA margin off | OCR «Корректировки EBITDA», порог $300k |
| Reclass не применился | final AUP vs draft intermediate |
| NaN amount в ledger | notes/treasury «не отражена в выгрузке» |
| EUR в EBITDA | курс в notes (EUR … $USD) |
| evidence ≠ GT | reclass txn order в `_find_evidence_for_sum` |
| Медленный eval | OCR на каждом KYC (~1–2 мин на 12 сценариев) |

---

## Добавление зависимости

```bash
uv add package-name
uv lock && uv sync
uv export --no-dev --no-hashes -o requirements.txt   # опционально
```
