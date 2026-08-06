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
| `pdftoppm` (poppler) | рендер страниц KYC для OCR |
| `tesseract` (+ eng/rus) | OCR таблиц ownership / subsidiaries |

```bash
# Debian/Ubuntu (пример)
sudo apt install poppler-utils tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng
```

---

## Конфигурация (`.env`)

Скопируйте `.env.example` → `.env`.

| Переменная | Default | Описание |
|------------|---------|----------|
| `TEAM_NAME` | `halyk-covenant-agent` | поле submission |
| `CONTACT_EMAIL` | `team@example.com` | поле submission |
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

`model` в submission всегда: `qwen3.8-max + gemini-3.6-flash` (`config.MODEL_LABEL`).

---

## CLI (`main.py`)

Все команды через `uv run`:

### Полный пайплайн

```bash
uv run python main.py phase3
# или
uv run python main.py phase2
```

Пишет `submission.json` в корень репозитория:

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

### Phase 1 — foundation

```bash
uv run python main.py foundation
```

Только ledger + classify + Article 6. Полезно проверить покрытие 12/12 ковенантов.

### Утилиты

```bash
# Маппинг счетов
uv run python main.py map-accounts

# Классификация одного PDF
uv run python main.py classify agentic-bank-public/documents/1d262694c308.pdf

# Извлечение Article 6
uv run python main.py extract-covenants agentic-bank-public/documents/1d262694c308.pdf
```

---

## Scripts

### Smoke Phase 1

```bash
uv run python scripts/smoke_phase1.py
```

Без LLM: mapping, cache, classifier, covenants, foundation graph.

### Один / несколько сценариев

```bash
uv run python scripts/run_one_scenario.py           # default P1 P5
uv run python scripts/run_one_scenario.py B1 P7
uv run python scripts/run_one_scenario.py P5 --llm  # с Qwen, если ключ есть
```

Печатает metrics summary + таблицу pred vs ground_truth.

### Оценка open set

```bash
uv run python scripts/eval_phase2.py
uv run python scripts/eval_phase2.py --scenarios P1 P5 B1
uv run python scripts/eval_phase2.py --llm
```

Вывод:

- таблица по всем 36 ячейкам  
- status / evidence accuracy  
- mean/max relative error  
- **hackathon score**  
- **WORST CELLS** (низкий score + reasoning)  

---

## Типичные workflow

### Open set: отладка одной ячейки

```bash
uv run python scripts/run_one_scenario.py P5
# смотрим metrics + reasoning formula_id
uv run python scripts/eval_phase2.py --scenarios P5
```

### После смены кода формул

```bash
uv run python scripts/eval_phase2.py
# смотрим WORST CELLS
```

### Боевой день (private dataset)

1. Положить датасет в `DATA_DIR` (или `export DATA_DIR=...`).  
2. `rm -rf doc_cache` при полном сбросе кэша.  
3. `uv run python main.py phase3`.  
4. Проверить, что все ключи `answers` заполнены (не `null` status).  
5. Сдать `submission.json`.

---

## Кэш документов

- Каталог: `DOC_CACHE_DIR` (default `./doc_cache`).  
- Ключ: `md5(abs_path:size:mtime_ns)`.  
- После правки extractors: удалить кэш или `force=True` в `read_pdf_with_cache`.

```bash
rm -rf doc_cache
```

---

## Отладка

| Симптом | Что проверить |
|---------|----------------|
| 0 related-party | KYC OCR, threshold, `L.L.P.` / quotes в ownership |
| Group Capex = borrower only | consolidated FS в `documents/`, segment name = company |
| Reclass не применился | final AUP vs draft intermediate |
| evidence ≠ GT | `_find_evidence_for_sum`, reclass txn order |
| Медленный eval | OCR на каждом KYC (~1–2 мин на 12 сценариев) |

Полезный ad-hoc:

```bash
uv run python -c "
from agent.tools.metrics import extract_scenario_metrics
from agent.tools.ledger import load_ledger, transactions_for_account
m = extract_scenario_metrics(
    scenario_id='P5', account_id='ACC-7805',
    transactions=transactions_for_account(load_ledger(), 'ACC-7805'),
    notes_paths=['agentic-bank-public/documents/ea8d8bac3e62.pdf'],
    kyc_paths=['agentic-bank-public/documents/89af6ae7964f.pdf'],
    company_name='Ekibastuz Power Services JSC',
)
print(m.summary_for_llm())
"
```

---

## Добавление зависимости

```bash
uv add package-name
uv lock
uv sync
# обновить frozen requirements (опционально)
uv export --no-dev --no-hashes -o requirements.txt
```
