# Archived: LLM Formula Reader smoke (2026-08-06)

Temporary Gemini / Gemma API probes after implementing the hybrid Formula Reader.
**Keys are NOT stored here.** Provider config lived only in local `.env` (gitignored) and was cleared after the smoke.

## What was tested

| Provider surface | Notes |
|------------------|--------|
| Google AI OpenAI-compatible endpoint | `…/v1beta/openai/` |
| Models tried | Flash family (quota/404 for some free-tier ids), **gemma-4-26b-a4b-it** (worked well), gemma-4-31b-it |
| Antigravity | Separate Agent/Interactions product — **not** used as chat model in this agent |

## Results (summary)

### Easy set — P1, P4 (`gemini-3-flash-preview`)

- 6/6 det ↔ LLM AGREE  
- 6/6 LLM ↔ ground truth  
- 6/6 det ↔ ground truth  

### Hard set — P3, P5, P7, B1 (`gemma-4-26b-a4b-it`)

| cells | AGREE | MISMATCH | API ERR |
|------:|------:|---------:|--------:|
| 12 | 9 | 1 (B1/6.2) | 2 (P3/6.1 length, P3/6.3 500) |

- **Group Capex, tax+util/EBITDA, interest coverage** — AGREE  
- **B1/6.2** — LLM summed payroll+utilities; det correctly used max single overhead line  
- det ↔ truth remained **12/12** (backup policy works)

## Artifacts

- `reports/*.md` / `*.json` — full cell-level dumps  
- `scripts/test_llm_formula_reader.py` — temporary probe (not on production path)

## Battle policy confirmed

1. Always det  
2. LLM fail / unavailable → det  
3. Strong known formula → det only (no LLM call)  
4. Unknown / low-conf → FormulaSpec (LLM) + compute (code)  
5. Mismatch: strong det → det; unknown det → LLM compute  

Production code lives under `agent/` + `main.py`; this archive is historical only.
