# Документация — Halyk Covenant Monitoring Agent

| Файл | Содержание |
|------|------------|
| [../README.md](../README.md) | Обзор, быстрый старт, score 100% |
| [architecture.md](architecture.md) | Пайплайн, hybrid policy, modules |
| [usage.md](usage.md) | CLI, env, validate, private day |
| [data-and-scoring.md](data-and-scoring.md) | Датасет, taxonomy, scoring |

Исторические LLM-smoke отчёты (без ключей): [../archive/gemini-llm-probe-20260806/](../archive/gemini-llm-probe-20260806/).

## Карта для новых участников

1. `uv sync` → `uv run python scripts/smoke_phase1.py`  
2. [usage.md](usage.md) — env, CLI  
3. `uv run python scripts/eval_phase2.py` → ожидание **36/36**  
4. `uv run python main.py phase3` → BATTLE DIAGNOSTICS → `validate`  
5. Ядро: `formula_engine.py`, `metrics.py`, `formula_reader.py` (optional LLM)  
6. Private: `DATA_DIR=...`, `rm -rf doc_cache`, `phase3` + `validate`

## Текущий статус (open set + battle readiness)

| Метрика / блок | Статус |
|----------------|--------|
| Hackathon score | **100%** (36/36) |
| Status / evidence | 100% / 100% (9/9 non-null) |
| Hardening 1–6 | ✅ never-null, extract quality, template ids, taxonomy, diagnostics |
| Provider-agnostic LLM | ✅ только `LLM_*` env |
| Formula Reader | ✅ LLM интерпретирует, code считает |
| Det backup | ✅ primary без ключа; mismatch → det если known |
| Battle policy | LLM **только** unknown/low-conf (`LLM_FORMULA_READER_ONLY_UNKNOWN=true`) |
| Taxonomy `other_*` | ~0.6% (было ~28%) |

## Hardening (кратко)

| # | Что |
|---|-----|
| 1 | Never-null `status`/`actual` + validate hard-fail |
| 2 | Extract quality (не `len≥40`), backend fallback |
| 3 | `COVENANT_IDS` из template; account/юр. формы |
| 4 | Unknown formula best-effort + optional LLM |
| 5 | Taxonomy expansion |
| 6 | Battle diagnostics в `phase3` |
