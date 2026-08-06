"""LangGraph AgentState (Master Plan §4)."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict

import pandas as pd

from agent.models import FinalCovenantResult


class AgentState(TypedDict, total=False):
    # Global
    ledger: pd.DataFrame
    account_to_scenario: dict[str, str]
    scenario_ids: list[str]  # from submission template

    # Per-borrower
    scenario_id: str
    account_id: str
    documents: dict[str, Any]  # path → extracted content / classification
    covenants: dict[str, str]  # "6.1" → full covenant text
    metrics: dict[str, float]  # extracted financial numbers
    transactions: list[dict]  # ledger rows for this account_id
    company_name: Optional[str]

    # Document inventory (global, built once)
    doc_index: list[dict]  # list of classification dicts
    docs_by_scenario: dict[str, dict[str, list[str]]]  # scenario → type → paths

    # Battle / quality diagnostics (bad extracts, unknown formulas, …)
    diagnostics: dict[str, Any]

    # Results (reducer: append)
    results: Annotated[list[FinalCovenantResult], operator.add]

    # Control
    stage: str
    error: Optional[str]


class CovenantWorkItem(TypedDict, total=False):
    """Payload sent via LangGraph Send API for per-covenant fan-out."""

    scenario_id: str
    account_id: str
    covenant_id: str
    covenant_text: str
    metrics: dict[str, float]
    transactions: list[dict]
