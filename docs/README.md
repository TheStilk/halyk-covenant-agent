# Документация — Halyk Covenant Monitoring Agent

| Файл | Содержание |
|------|------------|
| [../README.md](../README.md) | Обзор, быстрый старт |
| [architecture.md](architecture.md) | Пайплайн LangGraph, модули, metrics, formulas |
| [usage.md](usage.md) | CLI, env, scripts, отладка, uv |
| [data-and-scoring.md](data-and-scoring.md) | Датасет, ковенанты, scoring |
| [../PLAN.md](../PLAN.md) | Master Plan (ТЗ хакатона) |

## Карта для новых участников

1. Прочитать **PLAN.md** (правила оценки + ограничения моделей).  
2. `uv sync` → `uv run python scripts/smoke_phase1.py`.  
3. `uv run python scripts/run_one_scenario.py P1` — один идеальный кейс.  
4. `uv run python scripts/eval_phase2.py` — полный score.  
5. Изучить `agent/tools/metrics.py` + `formula_engine.py` — ядро расчётов.  
6. При private dataset: сменить `DATA_DIR`, очистить `doc_cache`, `main.py phase3`.
