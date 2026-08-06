"""LangGraph pipeline for covenant monitoring agent.

Phase 1: load_ledger → classify_docs → extract_covenants
Phase 2: extract_metrics → analyze_covenants → collect_results
"""

from __future__ import annotations

from typing import Any, Optional

from langgraph.graph import END, START, StateGraph

from agent.nodes.analyze import (
    analyze_all_covenants_node,
    collect_results_node,
    extract_metrics_node,
)
from agent.nodes.classify_docs import classify_docs_node
from agent.nodes.extract_covenants import extract_covenants_for_all
from agent.nodes.load_ledger import load_ledger_node
from agent.state import AgentState


def build_foundation_graph() -> Any:
    """Phase-1 only: ledger + classify + covenants."""
    g: StateGraph = StateGraph(AgentState)
    g.add_node("load_ledger", load_ledger_node)
    g.add_node("classify_docs", classify_docs_node)
    g.add_node("extract_covenants", extract_covenants_for_all)
    g.add_edge(START, "load_ledger")
    g.add_edge("load_ledger", "classify_docs")
    g.add_edge("classify_docs", "extract_covenants")
    g.add_edge("extract_covenants", END)
    return g.compile()


def build_phase2_graph() -> Any:
    """Phase-1 + Phase-2 calculation pipeline."""
    g: StateGraph = StateGraph(AgentState)
    g.add_node("load_ledger", load_ledger_node)
    g.add_node("classify_docs", classify_docs_node)
    g.add_node("extract_covenants", extract_covenants_for_all)
    g.add_node("extract_metrics", extract_metrics_node)
    g.add_node("analyze_covenants", analyze_all_covenants_node)
    g.add_node("collect_results", collect_results_node)

    g.add_edge(START, "load_ledger")
    g.add_edge("load_ledger", "classify_docs")
    g.add_edge("classify_docs", "extract_covenants")
    g.add_edge("extract_covenants", "extract_metrics")
    g.add_edge("extract_metrics", "analyze_covenants")
    g.add_edge("analyze_covenants", "collect_results")
    g.add_edge("collect_results", END)
    return g.compile()


def build_full_graph() -> Any:
    return build_phase2_graph()


def run_foundation(initial: Optional[dict[str, Any]] = None) -> AgentState:
    graph = build_foundation_graph()
    return graph.invoke(initial or {})  # type: ignore[return-value]


def run_phase2(initial: Optional[dict[str, Any]] = None) -> AgentState:
    graph = build_phase2_graph()
    return graph.invoke(initial or {})  # type: ignore[return-value]
