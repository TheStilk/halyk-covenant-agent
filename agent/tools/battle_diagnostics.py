"""Battle-day diagnostics summary for phase3 / phase2 runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from agent.config import CONFIDENCE_THRESHOLD, covenant_ids_for_scenario
from agent.models import DocType, FinalCovenantResult


def collect_battle_diagnostics(
    state: dict[str, Any],
    *,
    answers: Optional[dict[str, dict[str, Any]]] = None,
    elapsed_sec: Optional[float] = None,
) -> dict[str, Any]:
    """Aggregate battle metrics from agent state + optional submission answers."""
    diagnostics = dict(state.get("diagnostics") or {})
    scenario_ids: list[str] = list(
        state.get("scenario_ids")
        or (answers.keys() if answers else [])
        or []
    )
    docs_by = state.get("docs_by_scenario") or {}
    documents = state.get("documents") or {}
    metrics_by = documents.get("metrics_by_scenario") or {}
    results: list[Any] = state.get("results") or []

    if answers is None:
        answers = documents.get("submission_answers") or {}

    # --- cells filled ---
    cells_expected = 0
    cells_filled = 0
    for sc in scenario_ids:
        ids = covenant_ids_for_scenario(sc)
        cells_expected += len(ids)
        sc_map = answers.get(sc) or {}
        for cid in ids:
            cell = sc_map.get(cid) or {}
            if cell.get("status") in ("COMPLIANT", "BREACH") and cell.get("actual") is not None:
                cells_filled += 1

    # --- unknown / low conf from analyze diagnostics or results ---
    unknown_cells = list(diagnostics.get("unknown_formula_cells") or [])
    low_conf = list(diagnostics.get("low_confidence_cells") or [])
    if not low_conf and results:
        for r in results:
            conf = getattr(r, "confidence", None)
            if conf is None and isinstance(r, dict):
                conf = r.get("confidence", 1.0)
            sc = getattr(r, "scenario_id", None) or (r.get("scenario_id") if isinstance(r, dict) else "")
            cid = getattr(r, "covenant_id", None) or (r.get("covenant_id") if isinstance(r, dict) else "")
            if conf is not None and float(conf) < CONFIDENCE_THRESHOLD:
                low_conf.append(f"{sc}/{cid} conf={float(conf):.2f}")

    # --- bad extracts ---
    bad_extracts = diagnostics.get("bad_extracts") or []
    bad_count = int(diagnostics.get("bad_extract_count") or len(bad_extracts))

    # --- missing amounts (ledger NaN fills from notes/treasury) ---
    missing_by_sc: dict[str, dict[str, float]] = {}
    for sc, wrap in metrics_by.items():
        meta = {}
        if isinstance(wrap, dict):
            meta = wrap.get("meta") or {}
            obj = wrap.get("_object")
            if not meta and obj is not None:
                meta = getattr(obj, "meta", None) or {}
        ma = meta.get("missing_amounts") or {}
        if ma:
            missing_by_sc[sc] = dict(ma)
    missing_total = sum(len(v) for v in missing_by_sc.values())

    # --- scenarios without loan / notes ---
    no_loan: list[str] = []
    no_notes: list[str] = []
    loan_key = DocType.LOAN_AGREEMENT.value
    notes_key = DocType.FINANCIAL_NOTES.value
    for sc in scenario_ids:
        by_type = docs_by.get(sc) or {}
        if not by_type.get(loan_key):
            no_loan.append(sc)
        if not by_type.get(notes_key):
            no_notes.append(sc)

    report = {
        "cells_filled": cells_filled,
        "cells_expected": cells_expected,
        "unknown_formula_count": int(
            diagnostics.get("unknown_formula_count") or len(unknown_cells)
        ),
        "unknown_formula_cells": unknown_cells,
        "low_confidence_count": len(low_conf),
        "low_confidence_cells": low_conf,
        "bad_extract_count": bad_count,
        "bad_extracts": [
            Path(b.get("path", "")).name if isinstance(b, dict) else str(b)
            for b in bad_extracts[:20]
        ],
        "missing_amount_count": missing_total,
        "missing_amounts_by_scenario": missing_by_sc,
        "scenarios_without_loan": no_loan,
        "scenarios_without_notes": no_notes,
        "llm_fallback_cells": list(diagnostics.get("llm_fallback_cells") or []),
        "elapsed_sec": elapsed_sec,
        "scenario_count": len(scenario_ids),
    }
    return report


def format_battle_diagnostics(report: dict[str, Any]) -> str:
    """Human-readable battle summary block."""
    filled = report.get("cells_filled", 0)
    expected = report.get("cells_expected", 0)
    unknown_n = report.get("unknown_formula_count", 0)
    unknown_cells = report.get("unknown_formula_cells") or []
    low_n = report.get("low_confidence_count", 0)
    low_cells = report.get("low_confidence_cells") or []
    bad_n = report.get("bad_extract_count", 0)
    bad_names = report.get("bad_extracts") or []
    miss_n = report.get("missing_amount_count", 0)
    miss_by = report.get("missing_amounts_by_scenario") or {}
    no_loan = report.get("scenarios_without_loan") or []
    no_notes = report.get("scenarios_without_notes") or []
    elapsed = report.get("elapsed_sec")

    def _preview(items: list[Any], n: int = 6) -> str:
        if not items:
            return "—"
        head = [str(x) for x in items[:n]]
        more = f" (+{len(items) - n})" if len(items) > n else ""
        return ", ".join(head) + more

    miss_preview = "—"
    if miss_by:
        parts = []
        for sc, amap in sorted(miss_by.items()):
            parts.append(f"{sc}:{len(amap)}")
        miss_preview = _preview(parts, 8) + f" (txns={miss_n})"

    elapsed_s = "—"
    if elapsed is not None:
        elapsed_s = f"{float(elapsed):.1f}s"

    lines = [
        "=== BATTLE DIAGNOSTICS ===",
        f"cells filled: {filled}/{expected}",
        f"unknown formulas: {unknown_n}"
        + (f" [{_preview(unknown_cells)}]" if unknown_n else ""),
        f"low confidence: {low_n}"
        + (f" [{_preview(low_cells)}]" if low_n else ""),
        f"bad extracts: {bad_n}"
        + (f" [{_preview(bad_names)}]" if bad_n else ""),
        f"missing amounts: {miss_n}"
        + (f" [{miss_preview}]" if miss_n else ""),
        f"scenarios without loan: {no_loan if no_loan else '—'}",
        f"scenarios without notes: {no_notes if no_notes else '—'}",
        f"time total: {elapsed_s}",
        "REMINDER: ALWAYS rm -rf doc_cache/ on new machine or after extractor changes",
    ]
    return "\n".join(lines)


def print_battle_diagnostics(
    state: dict[str, Any],
    *,
    answers: Optional[dict[str, dict[str, Any]]] = None,
    elapsed_sec: Optional[float] = None,
) -> dict[str, Any]:
    """Collect, print, and return battle diagnostics report."""
    report = collect_battle_diagnostics(
        state, answers=answers, elapsed_sec=elapsed_sec
    )
    print(format_battle_diagnostics(report))
    return report
