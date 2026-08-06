"""Node [1]: Load ledger and build account → scenario mapping."""

from __future__ import annotations

import json
from typing import Any

from agent.config import TEMPLATE_PATH
from agent.state import AgentState
from agent.tools.ledger import (
    build_account_to_scenario,
    filter_scenario_accounts,
    load_ledger,
    scenario_to_account,
)


def load_ledger_node(state: AgentState) -> dict[str, Any]:
    """Load CSV, build mapping, retain only submission scenarios."""
    ledger = load_ledger()
    full_map = build_account_to_scenario(ledger)

    scenario_ids = _load_template_scenarios()
    borrower_map = filter_scenario_accounts(full_map, scenario_ids)

    # Ensure we have all template scenarios covered
    inv = scenario_to_account(borrower_map)
    missing = [s for s in scenario_ids if s not in inv]
    if missing:
        print(f"[load_ledger] WARNING: no account for scenarios: {missing}")

    print(
        f"[load_ledger] rows={len(ledger)} full_accounts={len(full_map)} "
        f"borrowers={len(borrower_map)} scenarios={sorted(borrower_map.values())}"
    )

    return {
        "ledger": ledger,
        "account_to_scenario": borrower_map,
        "scenario_ids": scenario_ids,
        "stage": "ledger_loaded",
        "error": None,
        "results": [],
    }


def _load_template_scenarios() -> list[str]:
    if not TEMPLATE_PATH.exists():
        # Open-set default
        return [f"P{i}" for i in range(1, 11)] + ["B1", "B4"]
    data = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    return list(data.get("answers", {}).keys())
