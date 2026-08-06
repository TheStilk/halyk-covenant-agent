# Halyk Covenant Monitoring Agent

Автономный AI-агент для **Halyk AI Challenge**: читает «грязные» финансовые PDF и `master_ledger_2025.csv`, для каждого ковенанта каждого заёмщика определяет:

| Поле | Значение |
|------|----------|
| `status` | `COMPLIANT` \| `BREACH` |
| `actual` | положительное число, 2 знака после запятой |
| `evidence_txn_id` | ID транзакции-улики или `null` |

Результат — один файл `submission.json` строго по шаблону `submission_template.json`.

**Open set (финал):** hackathon score **100%** (36/36), status **100%**, evidence **100%** (9/9 non-null).

**Репозиторий:** https://github.com/TheStilk/halyk-covenant-agent

---

## Содержание документации

| Документ | О чём |
|----------|--------|
| [README.md](README.md) (этот файл) | Быстрый старт, обзор, команды |
| [docs/architecture.md](docs/architecture.md) | Пайплайн, модули, State, формулы |
| [docs/usage.md](docs/usage.md) | CLI, env, прогоны, validate, отладка |
| [docs/data-and-scoring.md](docs/data-and-scoring.md) | Датасет, маппинг, оценка хакатона |
| [PLAN.md](PLAN.md) | Master Plan (единственный source of truth по ТЗ) |

---

## Быстрый старт

Требования: **Python ≥ 3.12**, [uv](https://github.com/astral-sh/uv), `pdftotext` / `pdftoppm` / `tesseract` (рекомендуется — OCR KYC и таблиц EBITDA).

```bash
# 1. Зависимости + .venv
uv sync

# 2. Конфиг (опционально — LLM-ключи)
cp .env.example .env

# 3. Полный прогон → submission.json
uv run python main.py phase3

# 4. Валидация формата сдачи
uv run python main.py validate

# 5. Сверка с ground_truth (open set)
uv run python scripts/eval_phase2.py
```

Без API-ключей агент работает **детерминированным formula engine** (Qwen/Gemini — при ключах и низкой confidence).

---

## Что делает агент

```
PDF (opaque hashes) + master_ledger_2025.csv
        │
        ▼
  account_id → scenario_id   (из txn_id: TXN-P1-0007 → P1)
        │
        ▼
  classify PDF → loan | notes | kyc | junk
        │
        ▼
  Article 6 → тексты 6.1 / 6.2 / 6.3
        │
        ▼
  metrics: Revenue, EBITDA, Capex, RP, Group Capex,
           reclass, cut-off, FX, NaN fills, one-time add-backs…
        │
        ▼
  formula engine (+ optional Qwen) → status / actual / evidence
        │
        ▼
  submission.json  →  main.py validate
```

Ключевые технические приёмы:

- **Кэш PDF** (`diskcache`) — повторные прогоны быстрые  
- **Final AUP only** — промежуточные «ПРОЕКТ»-ведомости игнорируются  
- **Group Capex** — PPE rollforward из consolidated FS материнской группы  
- **Adjusted EBITDA** — one-time items + порог существенности (OCR notes)  
- **NaN ledger fills** — суммы «не в выгрузке» из notes/treasury  
- **FX** — EUR→USD по курсу из notes  
- **KYC OCR** — related parties / unrestricted subsidiaries  
- **evidence** — транзакция, без которой вердикт меняется  

---

## Структура репозитория

```
hakaton/
├── PLAN.md                 # Master Plan (ТЗ)
├── README.md
├── docs/                   # подробная документация
├── pyproject.toml          # зависимости (uv)
├── uv.lock
├── requirements.txt        # uv export (совместимость)
├── .env.example
├── main.py                 # CLI entrypoint
├── agent/
│   ├── config.py           # пути, модели, knobs
│   ├── models.py           # Pydantic-схемы
│   ├── state.py            # LangGraph AgentState
│   ├── graph.py            # граф: load → classify → … → collect
│   ├── prompts/system.py   # боевые промпты §6
│   ├── nodes/              # ноды графа
│   └── tools/              # ledger, pdf, metrics, formulas, llm
├── scripts/
│   ├── smoke_phase1.py
│   ├── run_one_scenario.py
│   ├── eval_phase2.py
│   └── validate_submission.py
├── agentic-bank-public/    # open dataset
│   ├── master_ledger_2025.csv
│   ├── documents/
│   ├── submission_template.json
│   └── ground_truth.json
├── doc_cache/              # кэш извлечённого текста PDF (gitignored)
└── submission.json         # выход (gitignored)
```

---

## Команды

```bash
uv run python main.py foundation      # Phase 1: ledger + classify + Article 6
uv run python main.py phase2          # полный расчёт → submission.json
uv run python main.py phase3          # alias phase2
uv run python main.py validate        # проверка submission vs template
uv run python main.py map-accounts    # account ↔ scenario
uv run python main.py classify PATH   # один PDF
uv run python main.py extract-covenants PATH

uv run python scripts/smoke_phase1.py
uv run python scripts/run_one_scenario.py P1 P5
uv run python scripts/eval_phase2.py
uv run python scripts/validate_submission.py
```

Подробнее: [docs/usage.md](docs/usage.md).

---

## Модели (по ТЗ)

| Модель | Роль |
|--------|------|
| **Qwen 3.8-Max** | Reasoning, structured `CovenantVerdict`, reflection |
| **Gemini 3.6 Flash** | Быстрая классификация / bulk (опционально) |

Переменные: `QWEN_API_KEY`, `QWEN_BASE_URL`, `QWEN_MODEL`, `GOOGLE_API_KEY`, `GEMINI_MODEL` — см. `.env.example`.

---

## Стек

- **LangGraph** — пайплайн  
- **LangChain** — LLM clients  
- **pdfplumber / PyMuPDF / pdftotext** — PDF  
- **diskcache** — кэш документов  
- **pandas / pydantic** — ledger и structured I/O  
- **uv** — env + lock  
- **tesseract / pdftoppm** — OCR KYC и таблиц notes  

---

## Оценка (кратко)

36 ячеек (12 сценариев × 3 ковенанта). Каждая 0–1:

| Компонент | Баллы | Условие |
|-----------|-------|---------|
| `status` | **0.50** | exact; неверный → вся ячейка 0 |
| `actual` | **0.30** | `0.30 × max(0, 1 − e/0.05)`, `e = \|pred−true\|/\|true\|` |
| `evidence_txn_id` | **0.20** | exact; если GT `null` — масштабируется с `actual` |

Open set: **36.0 / 36.0 (100%)**.  
Детали: [docs/data-and-scoring.md](docs/data-and-scoring.md).

---

## Боевой день (private set)

```bash
export DATA_DIR=/path/to/private-dataset
rm -rf doc_cache          # чистый кэш на новых PDF
uv run python main.py phase3
uv run python main.py validate
# сдать submission.json
```

---

## Лицензия / хакатон

Ответы для сдачи должен генерировать **ваш агент**, не ручной разбор.  
Датасет синтетический; компании и договоры вымышлены.
