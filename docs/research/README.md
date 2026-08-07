# Research notes

Background write-ups from audits (not wired into runtime):

| File | Topic | Battle action |
|------|--------|----------------|
| [langgraph_concurrency_research.md](langgraph_concurrency_research.md) | Send / fan-out | **Defer** — phase3 is sequential |
| [pdf_extraction_research.md](pdf_extraction_research.md) | Marker / mojibake | Short-term OCR already in metrics |
| [pydantic_llm_recovery_research.md](pydantic_llm_recovery_research.md) | structured output | Soft recovery + try/except already present |

See [BATTLE_RUNBOOK.md](../BATTLE_RUNBOOK.md) for what is frozen vs optional.
