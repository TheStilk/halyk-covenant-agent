# Документация — Halyk Covenant Monitoring Agent

| Файл | Содержание |
|------|------------|
| [../README.md](../README.md) | Обзор, быстрый старт, score 100% |
| [architecture.md](architecture.md) | Пайплайн LangGraph, модули, metrics, formulas |
| [usage.md](usage.md) | CLI, env, scripts, validate, uv |
| [data-and-scoring.md](data-and-scoring.md) | Датасет, ковенанты, scoring, ключевые кейсы |
| [../PLAN.md](../PLAN.md) | Master Plan (ТЗ хакатона) |

## Карта для новых участников

1. Прочитать **PLAN.md** (правила оценки + ограничения моделей).  
2. `uv sync` → `uv run python scripts/smoke_phase1.py`.  
3. `uv run python scripts/run_one_scenario.py P1` — эталонный кейс.  
4. `uv run python scripts/eval_phase2.py` — полный score (ожидание: **36/36**).  
5. `uv run python main.py phase3` → смотреть **BATTLE DIAGNOSTICS** → `validate`.  
6. Изучить `metrics.py` + `formula_engine.py` + `battle_diagnostics.py`.  
7. Private dataset: `DATA_DIR=...`, `rm -rf doc_cache`, `phase3` + `validate`.

## Текущий open-set результат

| Метрика | Значение |
|---------|----------|
| Hackathon score | **100%** (36.0 / 36) |
| Status accuracy | **100%** (36/36) |
| Evidence (non-null) | **100%** (9/9) |
| Mean / max rel error | **0%** |
| `other_*` taxonomy | **~0.6%** ledger rows (было ~28%) |

## Hardening (private-set readiness)

| Шаг | Что |
|-----|-----|
| 1 | Never-null `status`/`actual` + validate hard-fail |
| 2 | Extract quality guards (не `len≥40`), backend fallback |
| 3 | `COVENANT_IDS` из template; account/юр. формы шире |
| 4 | Unknown formula → best-effort; LLM только unknown/low-conf |
| 5 | Taxonomy: interest/rent/VAT/insurance/… |
| 6 | Battle diagnostics в конце `phase3` |
