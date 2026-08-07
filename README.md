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

**Архитектура:** hybrid — **deterministic first**; LLM Formula Reader только для **unknown / low-conf** (интерпретация → code считает). Open set **100% без ключей**.

---

## Содержание документации

| Документ | О чём |
|----------|--------|
| [README.md](README.md) (этот файл) | Быстрый старт, обзор, команды |
| [docs/architecture.md](docs/architecture.md) | Пайплайн, formulas, LLM env, diagnostics |
| [docs/usage.md](docs/usage.md) | CLI, env, battle diagnostics, validate |
| [docs/data-and-scoring.md](docs/data-and-scoring.md) | Датасет, taxonomy, scoring |

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

- **Hybrid battle policy** — det always; LLM reader only unknown/low-conf; mismatch → det if known  
- **Model via env only** — `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` / `MODEL_LABEL`  
- **Never-null cells** — sanitize + validate hard-fail  
- **Extract quality** — markers/cyrillic/density; multi-backend fallback  
- **Template-driven covenants** — ids from `submission_template.json`  
- **Taxonomy** — `other_*` ~0.6%  
- **Battle diagnostics** — end of `phase3`  
- **Group Capex / Adj EBITDA / NaN fills / FX / KYC OCR / evidence**

---

## Структура репозитория

```
hakaton/
├── README.md
├── docs/                   # usage, architecture, scoring
├── archive/                # historical LLM smoke reports (no keys)
├── pyproject.toml / uv.lock
├── .env.example
├── main.py                 # CLI
├── agent/                  # graph, nodes, tools (det + optional LLM)
├── scripts/
│   ├── smoke_phase1.py
│   ├── smoke_llm.py
│   ├── run_one_scenario.py
│   ├── eval_phase2.py
│   └── validate_submission.py
├── agentic-bank-public/    # open dataset
├── doc_cache/              # gitignored
└── submission.json         # gitignored
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
uv run python scripts/smoke_llm.py          # optional, needs LLM_*
uv run python scripts/run_one_scenario.py P1 P5
uv run python scripts/eval_phase2.py        # 36/36, no LLM by default
uv run python scripts/validate_submission.py
```

Подробнее: [docs/usage.md](docs/usage.md).

---

## LLM (optional)

Любой **OpenAI-compatible** endpoint:

```bash
LLM_API_KEY=...
LLM_BASE_URL=https://your-provider/v1
LLM_MODEL=provider/model-id
# MODEL_LABEL=...   # submission.model; default = LLM_MODEL
```

Battle default: **LLM only when det is unknown/low-conf**  
(`LLM_FORMULA_READER_ONLY_UNKNOWN=true`).  
Mismatch on known formulas → **det wins**.

Без ключа: полный det path, open set 100%.  
Исторические smoke-отчёты: [archive/gemini-llm-probe-20260806/](archive/gemini-llm-probe-20260806/).

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
rm -rf doc_cache   # ALWAYS clear on new machine / after extractor changes
uv run python main.py phase3
# === BATTLE DIAGNOSTICS ===
uv run python main.py validate
```

На private set:

1. Full **det** always (backup).  
2. Optional `LLM_*` → reader only on unknown/low-conf.  
3. Template covenant ids; never-null cells; battle diagnostics.  
4. `MODEL_LABEL` корректный в submission.

---

## Лицензия / хакатон

Ответы для сдачи должен генерировать **ваш агент**, не ручной разбор.  
Датасет синтетический; компании и договоры вымышлены.
