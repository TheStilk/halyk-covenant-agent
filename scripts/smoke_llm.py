#!/usr/bin/env python3
"""Smoke: provider-agnostic LLM available/unavailable + optional structured call."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.console import setup_console  # noqa: E402

setup_console()


def main() -> int:
    from agent.config import LLM_BASE_URL, LLM_MODEL, MODEL_LABEL
    from agent.models_formula import FormulaSpec
    from agent.tools.llm import is_llm_available, llm_status_message, structured_invoke

    print("=== LLM smoke ===")
    print(f"MODEL_LABEL={MODEL_LABEL}")
    print(f"LLM_MODEL={LLM_MODEL}")
    print(f"LLM_BASE_URL={LLM_BASE_URL}")
    print(llm_status_message())

    if not is_llm_available():
        print("OK — LLM unavailable path (pipeline must continue without LLM)")
        return 0

    print("Calling structured FormulaSpec smoke...")
    try:
        spec = structured_invoke(
            FormulaSpec,
            system=(
                "Return FormulaSpec for a min revenue covenant of $5,000,000. "
                "No arithmetic. numerator_metrics=['revenue'], denominator=[], comparison=min."
            ),
            user="Минимальная выручка не менее $5,000,000.",
            temperature=0.0,
        )
        print("structured OK:", spec.model_dump())
        assert isinstance(spec, FormulaSpec)
        print("OK — LLM available + structured invoke")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL — LLM call error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
