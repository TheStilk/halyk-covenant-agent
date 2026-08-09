# Halyk Covenant Monitoring Agent

Автономный AI-агент для **Halyk AI Challenge**: читает «грязные» финансовые PDF и ledger CSV, для каждого ковенанта каждого заёмщика определяет:

| Поле | Значение |
|------|----------|
| `status` | `COMPLIANT` \| `BREACH` |
| `actual` | число ≥ 0, 2 знака после запятой |
| `evidence_txn_id` | ID транзакции-улики или `null` |

Результат — один файл `submission.json` строго по шаблону `submission_template.json`.

**Open set:** hackathon score **100%** (36/36), status **100%**, evidence **100%** (9/9 non-null) при OCR eng+rus+kaz.

**Команда:** «Сычуанский Соус» · `serkebaevmadiyar09@gmail.com`, `zhenis415@gmail.com`

**Репозиторий:** https://github.com/TheStilk/halyk-covenant-agent

**Архитектура:** hybrid — **deterministic first**; LLM Formula Reader только для **unknown / low-conf** (интерпретация → code считает). Open set **100% без API-ключей**.

---

## Содержание документации

| Документ | О чём |
|----------|--------|
| [README.md](README.md) (этот файл) | Быстрый старт, Linux-пакеты, battle |
| [docs/architecture.md](docs/architecture.md) | Пайплайн, formulas, hardening, KZ |
| [docs/usage.md](docs/usage.md) | CLI, env, validate, diagnostics |
| [docs/BATTLE_RUNBOOK.md](docs/BATTLE_RUNBOOK.md) | День сдачи: OCR → phase3 → validate |
| [docs/data-and-scoring.md](docs/data-and-scoring.md) | Датасет, taxonomy, scoring |

---

## Системные пакеты (Linux)

Нужны **Python ≥ 3.12**, [uv](https://github.com/astral-sh/uv) и system tools для PDF + OCR.

| Бинарь | Зачем |
|--------|--------|
| `pdftotext` | fallback извлечения текста (poppler) |
| `pdftoppm` | рендер страниц для OCR (poppler) |
| `tesseract` | OCR (KYC / таблицы notes) |
| tesseract langs **`eng`**, **`rus`**, **`kaz`** | preflight **падает**, если нет любого |

### Debian / Ubuntu / Mint

```bash
sudo apt update
sudo apt install -y \
  python3 python3-venv \
  poppler-utils \
  tesseract-ocr tesseract-ocr-eng tesseract-ocr-rus tesseract-ocr-kaz
```

### Fedora / RHEL / Rocky

```bash
sudo dnf install -y \
  python3 \
  poppler-utils \
  tesseract tesseract-langpack-eng tesseract-langpack-rus tesseract-langpack-kaz
```

### Arch Linux / Manjaro

```bash
sudo pacman -S --needed \
  python \
  poppler \
  tesseract tesseract-data-eng tesseract-data-rus tesseract-data-kaz
```

### Проверка OCR

```bash
which pdftoppm tesseract pdftotext
tesseract --list-langs | grep -E '^(eng|rus|kaz)$'
# ожидаются три строки: eng, kaz, rus
```

### uv (менеджер Python-зависимостей)

```bash
# https://github.com/astral-sh/uv
curl -LsSf https://astral.sh/uv/install.sh | sh
# затем в PATH: ~/.local/bin
```

---

## Быстрый старт

```bash
# 1. Зависимости Python + .venv
uv sync

# 2. Конфиг (опционально — LLM)
cp .env.example .env

# 3. Полный прогон → submission.json
uv run python main.py phase3

# 4. Валидация формата сдачи
uv run python main.py validate

# 5. Сверка с ground_truth (open set)
uv run python scripts/eval_phase2.py
# ждать: hackathon score 36.000 / 36.0
```

Без `LLM_*` — полный **deterministic** formula engine.  
С OpenAI-compatible API — Formula Reader только на unknown/low-conf.

**Типичное время** full open-set с OCR: ~**2–4 min** (зависит от CPU; второй прогон с `doc_cache` быстрее).

---

## Что делает агент

```
PDF (opaque hashes) + master_ledger_*.csv
        │
        ▼
  account_id → scenario_id   (из txn_id: TXN-P1-0007 → P1)
        │
        ▼
  classify PDF → loan | notes | kyc | junk   (RU / EN / KZ keywords)
        │
        ▼
  template covenant ids → clause texts (Пункт / Clause / Тармақ / Бап)
        │
        ▼
  metrics: Revenue, EBITDA, Capex, RP, FX, reclass, cut-off, OCR KYC/notes…
        │
        ▼
  formula engine → unknown best-effort → optional LLM reader
        │
        ▼
  ensure no null cells → submission.json → battle diagnostics → validate
```

Ключевые приёмы (battle-hardening):

- **Hybrid policy** — det always; LLM only unknown/low-conf; mismatch → det if known  
- **Safe ratios** — den≤0: min → COMPLIANT (9999), max → BREACH (9999)  
- **FX** — non-USD без курса **не** суммируется as-is  
- **Never-null cells** + isolate per-cell exceptions  
- **OCR eng+rus+kaz** + extract quality + content-hash cache  
- **RU/EN/KZ** classify & thr keywords; clause line-start headers  
- **battle_run.sh** — one-shot OCR check → phase3 → validate  

---

## Структура репозитория

```
hakaton/
├── README.md
├── docs/                   # usage, architecture, battle runbook
├── archive/                # historical LLM smoke (no keys)
├── pyproject.toml / uv.lock
├── .env.example
├── main.py                 # CLI + preflight
├── agent/                  # graph, nodes, tools
├── scripts/
│   ├── battle_run.sh       # ★ one-shot private/public battle
│   ├── smoke_phase1.py
│   ├── smoke_llm.py
│   ├── eval_phase2.py
│   └── validate_submission.py
├── agentic-bank-public/    # open dataset
├── doc_cache/              # gitignored
└── submission.json         # gitignored
```

---

## Команды

```bash
uv run python main.py foundation
uv run python main.py phase2|phase3
uv run python main.py validate
uv run python main.py map-accounts
uv run python main.py classify PATH
uv run python main.py extract-covenants PATH

uv run python scripts/smoke_phase1.py
uv run python scripts/smoke_llm.py
uv run python scripts/eval_phase2.py
./scripts/battle_run.sh /path/to/dataset   # OCR + phase3 + validate
```

Подробнее: [docs/usage.md](docs/usage.md).

---

## LLM (optional)

Любой **OpenAI-compatible** endpoint (OpenAI, Qwen gateway, Clodex, …):

```bash
export LLM_API_KEY=...
export LLM_BASE_URL=https://your-provider/v1
export LLM_MODEL=provider/model-id
# MODEL_LABEL=...   # submission.model
```

| Knob | Default |
|------|---------|
| `LLM_FORMULA_READER_ONLY_UNKNOWN` | `true` |
| `FORMULA_READER_PREFER_DET_ON_MISMATCH` | `true` |
| `LLM_MAX_TOKENS` | `1024` (floor 512) |
| `CLASSIFY_USE_LLM` | `false` |

Нет ключа / 429 / timeout → **det fallback**, пайплайн не обязан падать.  
Второй слот `CLASSIFY_*` — только optional LLM-classify (по умолчанию выкл).

---

## Боевой день (private set)

```bash
# 1) OCR langs уже установлены (см. выше)
# 2) det-only first submit (скорость):
NO_LLM=1 ./scripts/battle_run.sh /path/to/private-dataset

# 3) с LLM (если API готов):
# export LLM_API_KEY=... LLM_BASE_URL=... LLM_MODEL=...
./scripts/battle_run.sh /path/to/private-dataset
```

Опции: `KEEP_CACHE=1`, `SKIP_UV_SYNC=1`, `DATA_DIR=...`

Чеклист: [docs/BATTLE_RUNBOOK.md](docs/BATTLE_RUNBOOK.md).

---

## Оценка (кратко)

| Компонент | Баллы | Условие |
|-----------|-------|---------|
| `status` | **0.50** | exact; иначе вся ячейка 0 |
| `actual` | **0.30** | шкала 5% rel error |
| `evidence_txn_id` | **0.20** | exact; GT `null` → с `actual` |

Open set: **36.0 / 36.0**. Подробнее: [docs/data-and-scoring.md](docs/data-and-scoring.md).

---

## Стек

LangGraph · LangChain (optional LLM) · pdfplumber / PyMuPDF / pdftotext · diskcache · pandas · pydantic · tesseract / pdftoppm · uv

---

## Лицензия / хакатон

Ответы для сдачи генерирует **агент**, не ручной разбор.  
Датасет синтетический; компании и договоры вымышлены.
