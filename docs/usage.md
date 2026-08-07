# Использование

## Установка

```bash
uv sync
```

Системные утилиты (рекомендуется):

| Утилита | Зачем |
|---------|--------|
| `pdftotext` (poppler) | fallback извлечения текста |
| `pdftoppm` (poppler) | рендер страниц KYC / notes для OCR |
| `tesseract` (**eng+rus+kaz** обязательны) | OCR KYC / notes tables (KZ docs too) |

```bash
# Debian/Ubuntu (пример)
sudo apt install poppler-utils tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng
```

---

## Конфигурация (`.env`)

```bash
cp .env.example .env
```

| Переменная | Default | Описание |
|------------|---------|----------|
| `TEAM_NAME` | `Сычуанский Соус` | submission.team |
| `CONTACT_EMAIL` | обе почты команды | submission.contact_email |
| `DATA_DIR` | `./agentic-bank-public` | датасет |
| `LEDGER_PATH` | `$DATA_DIR/master_ledger_2025.csv` | ledger CSV (override if renamed) |
| `TEMPLATE_PATH` | `$DATA_DIR/submission_template.json` | submission template |
| `DOCUMENTS_DIR` | `$DATA_DIR/documents` | PDF/docs folder |
| `DOC_CACHE_DIR` | `./doc_cache` | кэш PDF |
| `LLM_API_KEY` | — | OpenAI-compatible key |
| `LLM_BASE_URL` | — | `https://host/v1` |
| `LLM_MODEL` | — | model id у провайдера |
| `MODEL_LABEL` | =`LLM_MODEL` | submission.model (или `deterministic-formula-engine`) |
| `USE_LLM_FORMULA_READER` | `true` | enable Formula Reader |
| `LLM_FORMULA_READER_ONLY_UNKNOWN` | `true` | LLM **только** unknown/low-conf det |
| `FORMULA_READER_PREFER_DET_ON_MISMATCH` | `true` | mismatch + known det → det |
| `FORMULA_READER_MAX_TEXT_CHARS` | `900` | clip текста ковенанта в reader |
| `MAX_TEXT_FILE_MB` | `16` | skip `.txt/.csv/...` larger than N MiB (OOM guard) |
| `MAX_TABLE_PAGES` | `32` | pdfplumber `extract_tables` only first N pages |
| `LLM_MAX_TOKENS` | `1024` | max completion tokens (JSON/FormulaSpec; floor 512) |
| `CLASSIFY_USE_LLM` | `false` | optional LLM classify |
| `CONFIDENCE_THRESHOLD` | `0.85` | low-conf boundary |

**Смена провайдера/модели:** только env, без правок кода.

```bash
export LLM_API_KEY=...
export LLM_BASE_URL=https://your-provider/v1
export LLM_MODEL=your/model-id

uv run python scripts/smoke_llm.py   # available / structured smoke
```

Без ключей пайплайн полностью детерминированный.

---

## CLI (`main.py`)

```bash
uv run python main.py phase3      # full pipeline → submission.json + diagnostics
uv run python main.py validate
uv run python main.py foundation  # ledger + classify + covenants only
uv run python main.py map-accounts
uv run python main.py classify PATH
uv run python main.py extract-covenants PATH
```

### Battle diagnostics (конец phase3)

```text
=== BATTLE DIAGNOSTICS ===
cells filled: 36/36
unknown formulas: …
low confidence: …
bad extracts: …
missing amounts: …
scenarios without loan: …
scenarios without notes: …
time total: …
```

### Validate

```bash
uv run python main.py validate
uv run python scripts/validate_submission.py
```

Hard-fail на null/missing `status`/`actual`, неверный enum, лишние ключи vs template.

---

## Scripts

| Script | Назначение |
|--------|------------|
| `scripts/smoke_phase1.py` | Phase 1 без LLM |
| `scripts/smoke_llm.py` | LLM available + structured FormulaSpec |
| `scripts/run_one_scenario.py` | 1+ сценариев vs ground_truth (`--llm` optional) |
| `scripts/eval_phase2.py` | полный score 36 ячеек; `--scenarios` subset |
| `scripts/validate_submission.py` | формат submission |

```bash
uv run python scripts/eval_phase2.py                 # 36/36 without LLM calls
uv run python scripts/eval_phase2.py --scenarios P5 B1
uv run python scripts/run_one_scenario.py P1
```

---

## Типичные workflow

### Open set

```bash
uv sync
uv run python scripts/eval_phase2.py    # 36.0 / 36.0
uv run python main.py phase3
uv run python main.py validate
```

### Private set (боевой день)

```bash
export DATA_DIR=/path/to/private-dataset
# optional LLM for unknown formulas:
# export LLM_API_KEY=... LLM_BASE_URL=... LLM_MODEL=...
rm -rf doc_cache
uv run python main.py phase3
# read BATTLE DIAGNOSTICS
uv run python main.py validate
```

Чеклист:

1. `cells filled` = expected  
2. `unknown formulas` / `low confidence` — зона LLM  
3. `bad extracts` / missing loan|notes  
4. validate exit 0  
5. `MODEL_LABEL` в submission корректен  

### Hybrid policy (кратко)

1. Always det  
2. Strong known formula → det only  
3. Unknown/low-conf + key → Formula Reader + code compute  
4. Mismatch: known → det; unknown → LLM compute  
5. API fail → det  

Не гонять все 36 ячеек через LLM на free tier — default policy уже режет лишние вызовы.

---

## Кэш документов

- `DOC_CACHE_DIR` (default `./doc_cache`)  
- key includes extract quality version  

```bash
rm -rf doc_cache   # new dataset / extract changes
```

---

## Отладка

| Симптом | Проверить |
|---------|-----------|
| null status/actual | `ensure_filled_*`, validate |
| degraded PDF | `diagnostics.bad_extracts` |
| Group Capex off | consolidated PPE + company name |
| Adj EBITDA margin | OCR one-time + $300k materiality |
| NaN amount | notes/treasury; battle missing amounts |
| LLM length / 500 | shorter text clip; det backup |
| mismatch LLM vs det | expected on some overhead formulas; det wins if known |

---

## Архив LLM-smoke

Исторические отчёты (без ключей):  
`archive/gemini-llm-probe-20260806/` — P1/P4 + hard P3/P5/P7/B1.
