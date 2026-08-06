# Halyk Covenant Monitoring Agent

Автономный AI-агент для **Halyk AI Challenge**: читает «грязные» финансовые PDF и `master_ledger_2025.csv`, для каждого ковенанта каждого заёмщика определяет:

| Поле | Значение |
|------|----------|
| `status` | `COMPLIANT` \| `BREACH` |
| `actual` | положительное число, 2 знака после запятой |
| `evidence_txn_id` | ID транзакции-улики или `null` |

Результат — один файл `submission.json` строго по шаблону `submission_template.json`.

**Open set (финал):** hackathon score **100%** (36/36), status **100%**, evidence **100%** (9/9 non-null).

**Команда:** «Сычуанский Соус» · `serkebaevmadiyar09@gmail.com`, `zhenis415@gmail.com`

**Репозиторий:** https://github.com/TheStilk/halyk-covenant-agent

**Архитектура:** hybrid — **deterministic first**, LLM только как fallback (unknown formula / low confidence). Open-set score держится без API-ключей.

---

## Содержание документации

| Документ | О чём |
|----------|--------|
| [README.md](README.md) (этот файл) | Быстрый старт, обзор, команды |
| [docs/architecture.md](docs/architecture.md) | Пайплайн, hardening, formulas, diagnostics |
| [docs/usage.md](docs/usage.md) | CLI, env, battle diagnostics, validate |
| [docs/data-and-scoring.md](docs/data-and-scoring.md) | Датасет, taxonomy, scoring |
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

Без `LLM_*` агент работает **детерминированным formula engine**.  
С ключом — optional Formula Reader / reflection (модель задаётся только env).

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
  template covenant ids → clause texts (fallback Article N)
        │
        ▼
  metrics: Revenue, EBITDA, Capex, RP, Group Capex,
           reclass, cut-off, FX, NaN fills, one-time add-backs…
        │
        ▼
  formula engine (known) → unknown best-effort → optional LLM reader
        │
        ▼
  ensure no null cells → submission.json → battle diagnostics → validate
```

Ключевые технические приёмы:

- **Hybrid** — formula engine first; LLM только interpretation (не арифметика)  
- **Model swap via env** — `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` (+ optional `MODEL_LABEL`)  
- **Never-null cells** — `status`/`actual` всегда заполнены (best-effort)  
- **Extract quality guards** — кириллица, ACC/TXN/$/Статья; fallback backend  
- **Template-driven** — `COVENANT_IDS` из `submission_template.json`  
- **Taxonomy** — `other_*` ~0.6%  
- **Battle diagnostics** — в конце `phase3`  
- **Кэш PDF / Final AUP / Group Capex / Adj EBITDA / NaN / FX / KYC OCR / evidence**  

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

## LLM (смена модели без правок кода)

OpenAI-compatible клиент. Вся привязка к модели — **только env**:

```bash
LLM_API_KEY=...
LLM_BASE_URL=https://your-provider/v1
LLM_MODEL=provider/model-id
# optional: MODEL_LABEL=...   # поле model в submission; default = LLM_MODEL
```

| Переменная | Назначение |
|------------|------------|
| `LLM_*` | Formula Reader / structured / reflection |
| `CLASSIFY_*` | optional отдельная модель для classify PDF |
| `MODEL_LABEL` | строка в `submission.json` |

Без ключа пайплайн не падает — det formula engine.  
Исторические ограничения хакатона по моделям — в [PLAN.md](PLAN.md); операционный конфиг — `.env`.

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
# optional: LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
rm -rf doc_cache
uv run python main.py phase3
# === BATTLE DIAGNOSTICS ===
uv run python main.py validate
```

На private set важно:

1. **Не null** в `status`/`actual`.  
2. Covenant ids — из **template**.  
3. Account не только `ACC-7*`.  
4. Unknown formula → best-effort; с LLM — Formula Reader + code compute.  
5. Battle diagnostics.

---

## Лицензия / хакатон

Ответы для сдачи должен генерировать **ваш агент**, не ручной разбор.  
Датасет синтетический; компании и договоры вымышлены.
