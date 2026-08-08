# Battle runbook

**Состояние:** `main` — hybrid det-first + battle-hardening (FX, safe ratios, KZ/RU/EN classify, cell isolation, `battle_run.sh`).  
Open set + OCR eng+rus+kaz: **36/36**. Не менять known formula handlers без `eval_phase2`.

---

## 0. Не ломать

- Не пушить «улучшения» без `eval_phase2` full + validate.  
- Не трогать known formula handlers «на глаз».  
- Не гонять все ячейки через LLM на free tier.  
- Ключи API — только локальный `.env` (gitignored).  
- Первый submit: **скорость** (det-only) → потом опционально LLM.

---

## 1. Системные зависимости (Linux)

См. [README.md](../README.md) — пакеты для **Debian/Ubuntu**, **Fedora**, **Arch**.

Минимум:

```bash
which pdftoppm tesseract pdftotext
tesseract --list-langs | grep -E '^(eng|rus|kaz)$'
```

| Ожидание | Если нет |
|----------|----------|
| `pdftoppm`, `tesseract`, `pdftotext` | install poppler + tesseract (см. README) |
| langs **eng**, **rus**, **kaz** | `phase3` **preflight упадёт** |

**Норма в логе:**

```text
=== PREFLIGHT OK ===
[metrics] KYC OCR ....pdf: parties=...
```

**Плохо:** missing langs / `OCR toolchain: MISSING`.

Sanity open set:

```bash
uv sync
uv run python scripts/eval_phase2.py
# 36.000 / 36.0
```

Типичное время full open-set с OCR: **~2–4 min** (CPU-зависимо).

---

## 2. Private dataset

### One-shot (рекомендуется)

```bash
# det-only — быстрее, без API (хорош для «кто сдал первым»)
NO_LLM=1 ./scripts/battle_run.sh /path/to/private-dataset

# с LLM (OpenAI-compatible, unknown/low-conf only):
# export LLM_API_KEY=... LLM_BASE_URL=https://.../v1 LLM_MODEL=...
./scripts/battle_run.sh /path/to/private-dataset
```

Опции env:

| Env | Смысл |
|-----|--------|
| `KEEP_CACHE=1` | не чистить `doc_cache` |
| `SKIP_UV_SYNC=1` | пропустить `uv sync` |
| `NO_LLM=1` | unset `LLM_API_KEY` |
| `DATA_DIR=...` | альтернатива аргументу пути |

### Вручную

```bash
export DATA_DIR=/path/to/private-dataset
rm -rf doc_cache
uv run python main.py phase3
uv run python main.py validate
```

### После phase3

1. `cells filled` = template × scenarios  
2. `validate` → `OK — submission is valid`  
3. `team`, `contact_email`, `model` заполнены  
4. нет null `status` / `actual`  
5. `unknown formulas` / `scenarios without loan` — смотреть, не игнорировать  
6. при OCR missing — **не** сдавать silent-wrong actual  

---

## 3. Eval splits (open set only)

```bash
uv run python scripts/eval_phase2.py
uv run python scripts/eval_phase2.py --split train
uv run python scripts/eval_phase2.py --split holdout
```

Holdout open-set — **верхняя** граница для det (handlers видели public formulas).

---

## 4. Hybrid policy

```text
1. Always det
2. LLM down / ERR / 429 → det
3. det strong known → det (no LLM)
4. unknown / low-conf → FormulaSpec + code compute
5. mismatch: known det → det; unknown → LLM compute
6. never null cells; per-cell try/except
```

Knobs: `LLM_FORMULA_READER_ONLY_UNKNOWN=false` (LLM cross-checks every cell), `FORMULA_READER_PREFER_DET_ON_MISMATCH=true`, `LLM_MAX_TOKENS=4096`.

---

## 5. Если что-то пошло не так

| Симптом | Действие |
|---------|----------|
| preflight OCR fail | install langs, re-run |
| empty cells | check diagnostics, logs |
| FX missing rate logs | non-USD without rate skipped (by design) |
| slow / 429 | `NO_LLM=1`, or raise backoff / lower RPM |
| wrong DATA_DIR | `rm -rf doc_cache`, set path, re-run |
| path overrides | `LEDGER_PATH` / `TEMPLATE_PATH` / `DOCUMENTS_DIR` |

---

## 6. Что уже зашито (не «чинить» в день X)

- Safe ratio edges (9999 sentinel)  
- Signed revenue / expense nets  
- FX skip without rate  
- Covenant merge + orphan fill  
- RU ё/е + KZ classify/headers/thr  
- Cell crash isolation  
- Cache path rewrite + side-cache isolation  
- OOM guards (`MAX_TEXT_FILE_MB`, `MAX_TABLE_PAGES`)  
