# Battle runbook (9 августа)

**Состояние после merge:** `main` @ `b3694db` = hybrid Formula Reader + det core **и** post-audit (holdout, preflight, content-hash cache, console UTF-8).  
Open set при OCR: **36/36**. Не менять код без крайней необходимости.

---

## 0. Не ломать

- Не пушить «улучшения» без `eval_phase2` full + validate.
- Не трогать known formula handlers «на глаз».
- Не гонять все 36 ячеек через LLM на free tier.
- Ключи API — только локальный `.env` (gitignored).

---

## 1. OCR-check на боевой машине (сделать первым)

Без OCR silently ломаются ячейки с таблицами-картинками (P4/P9-тип): actual неверный, confidence высокий.

```bash
# Linux
which pdftoppm tesseract
pdftoppm -v 2>&1 | head -1
tesseract --version 2>&1 | head -2

# Нужны eng + rus (KYC / notes)
tesseract --list-langs 2>/dev/null | grep -E 'eng|rus' || true
```

| Ожидание | Если нет |
|----------|----------|
| `pdftoppm` и `tesseract` на PATH | `sudo apt install poppler-utils tesseract-ocr tesseract-ocr-eng tesseract-ocr-rus` (или аналог) |
| langs `eng`, `rus` | доустановить пакеты языков |

**Признаки в логе phase3 (норма при OCR):**

```text
[preflight] OCR toolchain: available
[metrics] KYC OCR ....pdf: parties=...
```

**Плохо:**

```text
[preflight] OCR toolchain: MISSING ['pdftoppm', 'tesseract']
[preflight] *** These pages will NOT be read...
```

→ ставить OCR **до** финального submission.

Быстрая sanity (open set, если датасет под рукой):

```bash
cd /path/to/halyk-covenant-agent
uv sync
uv run python scripts/eval_phase2.py
# ждать 36.000 / 36.0 при рабочем OCR
```

---

## 2. Private dataset — порядок

```bash
export DATA_DIR=/path/to/private-dataset
# optional LLM (unknown/low-conf only):
# export LLM_API_KEY=...
# export LLM_BASE_URL=https://.../v1
# export LLM_MODEL=...
# export MODEL_LABEL=...   # поле model в submission

rm -rf doc_cache          # чистый кэш на новом DATA_DIR
uv run python main.py phase3
uv run python main.py validate
```

### Чеклист после phase3

1. `=== BATTLE DIAGNOSTICS ===` → `cells filled` полный (template × scenarios).  
2. `unknown formulas` / `low confidence` — ок, det/LLM policy сработает.  
3. `bad extracts` / preflight blind pages — не игнорировать, если OCR missing.  
4. `scenarios without loan` / `without notes` — риск.  
5. `validate` → `OK — submission is valid`.  
6. `submission.json`: `team`, `contact_email`, `model` (`MODEL_LABEL`) заполнены.  
7. Нет null в `status` / `actual`.

---

## 3. Eval splits (open set only)

```bash
uv run python scripts/eval_phase2.py              # full 36
uv run python scripts/eval_phase2.py --split holdout   # B4 P10 P2 P6
uv run python scripts/eval_phase2.py --split train
```

На private set ids другие → используй `--split all` (или без split).  
Holdout open set — **верхняя** оценка для det (handlers видели public formulas).

---

## 4. Hybrid policy (напоминание)

```text
1. Always det
2. LLM down / ERR → det
3. det strong known → det (no LLM call)
4. det unknown/low-conf → FormulaSpec (LLM) + compute (code)
5. mismatch: known det → det; unknown det → LLM compute
```

Knobs (defaults battle-safe):  
`LLM_FORMULA_READER_ONLY_UNKNOWN=true`, `FORMULA_READER_PREFER_DET_ON_MISMATCH=true`.

---

## 5. Если что-то пошло не так

| Симптом | Действие |
|---------|----------|
| score < baseline / wrong AdjEBITDA | OCR check (п.1) |
| Unicode crash на Windows | уже `setup_console()`; не откатывать console |
| validate fail null | не сдавать; смотреть collect / ensure_filled |
| LLM 429 / length | det backup; не паниковать |
| empty scenarios / split | private: `--split all` |

Не рефакторить mid-battle. Минимальный фикс → eval → validate → только потом push.

---

## 6. Архив smoke (не production)

`archive/gemini-llm-probe-20260806/` — исторические LLM-прогоны (без ключей).  
Probe script: `archive/.../scripts/test_llm_formula_reader.py` — не в hot path.

---

**Готово к бою, если:** OCR OK + `phase3` + `validate OK` + diagnostics cells filled.
