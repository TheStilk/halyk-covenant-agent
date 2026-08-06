#!/usr/bin/env python3
"""Evaluate Phase-2 results against ground_truth.json using hackathon scoring."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.console import setup_console  # noqa: E402

setup_console()


def cell_score(pred: dict, truth: dict) -> dict:
    """Score one cell 0..1 (status 0.5 + actual 0.3 + evidence 0.2)."""
    if not pred or pred.get("status") is None:
        return {"total": 0.0, "status": 0.0, "actual": 0.0, "evidence": 0.0}

    p_status = pred.get("status")
    t_status = truth.get("status")
    if p_status != t_status:
        return {"total": 0.0, "status": 0.0, "actual": 0.0, "evidence": 0.0}

    status_pts = 0.50

    p_act = pred.get("actual")
    t_act = truth.get("actual")
    actual_pts = 0.0
    rel_err = None
    if p_act is not None and t_act is not None:
        try:
            p_act = float(p_act)
            t_act = float(t_act)
            if abs(t_act) < 1e-12:
                rel_err = 0.0 if abs(p_act) < 1e-12 else 1.0
            else:
                rel_err = abs(p_act - t_act) / abs(t_act)
            actual_pts = 0.30 * max(0.0, 1.0 - rel_err / 0.05)
        except (TypeError, ValueError):
            actual_pts = 0.0
            rel_err = 1.0

    t_ev = truth.get("evidence_txn_id")
    p_ev = pred.get("evidence_txn_id")
    if t_ev is None:
        # evidence points scale with actual accuracy
        evidence_pts = 0.20 * (actual_pts / 0.30) if actual_pts > 0 else 0.0
    else:
        evidence_pts = 0.20 if p_ev == t_ev else 0.0

    return {
        "total": status_pts + actual_pts + evidence_pts,
        "status": status_pts,
        "actual": actual_pts,
        "evidence": evidence_pts,
        "rel_err": rel_err,
    }


def run_eval(scenario_ids: list[str] | None = None, *, use_llm: bool = False) -> dict:
    from agent.config import (
        GROUND_TRUTH_PATH,
        TEMPLATE_PATH,
        covenant_ids_for_scenario,
    )
    from agent.eval_split import split_of
    from agent.graph import run_foundation
    from agent.nodes.analyze import analyze_one_covenant
    from agent.tools.ledger import scenario_to_account, transactions_for_account
    from agent.tools.metrics import extract_metrics_for_state

    gt_raw = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
    gt = gt_raw.get("scenarios", gt_raw)

    template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    all_sc = list(template["answers"].keys())
    if scenario_ids:
        requested = list(scenario_ids)
        all_sc = [s for s in all_sc if s in requested]
        if not all_sc:
            # The frozen train/holdout split names public scenarios (B4, P10, …).
            # Point this at a template that uses different ids — the private set
            # will — and the selection is empty, which used to divide by zero in
            # the summary below rather than say what went wrong.
            print(
                f"No scenarios to evaluate: asked for {sorted(requested)}, "
                f"but the template has {sorted(template['answers'])}.\n"
                "The train/holdout split in EVAL_SPLIT.md is defined over the "
                "public scenario ids; on a different dataset use --split all "
                "(the default) or pass --scenarios explicitly."
            )
            return {
                "rows": [],
                "total_score": 0.0,
                "max_score": 0.0,
                "status_ok": 0,
                "n_cells": 0,
            }

    print("=== Foundation ===")
    state = run_foundation()
    sc_to_acc = scenario_to_account(state["account_to_scenario"])
    covenants_by = state["documents"]["covenants_by_scenario"]
    docs_by = state["docs_by_scenario"]
    ledger = state["ledger"]
    doc_index = state["doc_index"]

    rows = []
    total_score = 0.0
    n_cells = 0
    status_ok = 0
    evidence_ok = 0
    evidence_total = 0
    rel_errors = []

    print(
        f"\n{'sc':4s} {'cov':4s} {'pred':10s} {'true':10s} "
        f"{'p_act':>12s} {'t_act':>12s} {'err%':>8s} {'score':>6s} evidence"
    )
    print("-" * 100)

    for sc in all_sc:
        acc = sc_to_acc.get(sc, "")
        txns = transactions_for_account(ledger, acc)
        metrics = extract_metrics_for_state(
            scenario_id=sc,
            account_id=acc,
            transactions=txns,
            docs_by_scenario=docs_by,
            doc_index=doc_index,
        )
        for cid in covenant_ids_for_scenario(sc):
            text = (covenants_by.get(sc) or {}).get(cid, "")
            verdict = analyze_one_covenant(
                scenario_id=sc,
                account_id=acc,
                covenant_id=cid,
                covenant_text=text,
                metrics=metrics,
                use_llm=use_llm,
            )
            from agent.models import ensure_filled_cell

            pred = ensure_filled_cell(
                {
                    "status": verdict.status,
                    "actual": verdict.actual,
                    "evidence_txn_id": verdict.evidence_txn_id,
                }
            )
            truth = (gt.get(sc) or {}).get("covenants", {}).get(cid, {})
            sc_res = cell_score(pred, truth)
            n_cells += 1
            total_score += sc_res["total"]
            if pred["status"] == truth.get("status"):
                status_ok += 1
            if truth.get("evidence_txn_id") is not None:
                evidence_total += 1
                if pred["evidence_txn_id"] == truth.get("evidence_txn_id"):
                    evidence_ok += 1
            if sc_res.get("rel_err") is not None and pred["status"] == truth.get("status"):
                rel_errors.append(sc_res["rel_err"])

            err_pct = (
                None if sc_res.get("rel_err") is None else round(sc_res["rel_err"] * 100, 2)
            )
            print(
                f"{sc:4s} {cid:4s} {pred['status']:10s} {str(truth.get('status')):10s} "
                f"{pred['actual']:12.2f} {str(truth.get('actual')):>12s} "
                f"{str(err_pct):>8s} {sc_res['total']:6.3f} "
                f"p={pred['evidence_txn_id']} t={truth.get('evidence_txn_id')}"
            )
            rows.append(
                {
                    "scenario": sc,
                    "covenant": cid,
                    "split": split_of(sc),
                    "pred": pred,
                    "truth": truth,
                    "score": sc_res,
                    "reasoning": verdict.reasoning,
                }
            )

    max_score = n_cells * 1.0
    pct = 100.0 * total_score / max_score if max_score else 0.0
    mean_err = sum(rel_errors) / len(rel_errors) if rel_errors else None
    max_err = max(rel_errors) if rel_errors else None

    print("\n=== SUMMARY ===")
    print(f"cells: {n_cells}")
    print(f"status accuracy: {status_ok}/{n_cells} = {100*status_ok/n_cells:.1f}%")
    print(
        f"evidence accuracy (where non-null): {evidence_ok}/{evidence_total}"
        + (f" = {100*evidence_ok/evidence_total:.1f}%" if evidence_total else "")
    )
    if mean_err is not None:
        print(f"mean rel error (status-correct cells): {mean_err*100:.2f}%")
        print(f"max rel error (status-correct cells): {max_err*100:.2f}%")
    print(f"hackathon score: {total_score:.3f} / {max_score:.1f}  ({pct:.1f}%)")

    # Per-split breakdown. Only the holdout number estimates anything; the train
    # number is a fit statistic and must never be quoted as performance — see
    # EVAL_SPLIT.md. It also holds for the deterministic engine: its formula
    # handlers were written looking at all 36 public cells, so even its
    # holdout number here is an upper bound, not a clean estimate.
    by_split: dict[str, list[float]] = {}
    for r in rows:
        by_split.setdefault(r["split"], []).append(r["score"]["total"])
    print("\n=== BY SPLIT (see EVAL_SPLIT.md) ===")
    for name in ("train", "holdout", "unknown"):
        scores = by_split.get(name)
        if not scores:
            continue
        label = "  <- the only number that estimates the private set" if name == "holdout" else ""
        print(
            f"  {name:8s} {sum(scores):6.3f} / {len(scores):3d} "
            f"= {100 * sum(scores) / len(scores):5.1f}%{label}"
        )

    # Worst cells (lowest score first)
    worst = sorted(rows, key=lambda r: r["score"]["total"])
    print("\n=== WORST CELLS ===")
    for r in worst[:8]:
        if r["score"]["total"] >= 0.999:
            break
        print(
            f"  {r['scenario']}/{r['covenant']}: score={r['score']['total']:.3f} "
            f"pred={r['pred']} true={r['truth']}"
        )
        print(f"    {r.get('reasoning', '')[:140]}")

    return {
        "rows": rows,
        "total_score": total_score,
        "max_score": max_score,
        "status_ok": status_ok,
        "n_cells": n_cells,
    }


def main() -> int:
    from agent.eval_split import scenarios_for

    p = argparse.ArgumentParser()
    p.add_argument("--scenarios", nargs="*", default=None)
    p.add_argument(
        "--split",
        choices=("train", "holdout", "all"),
        default="all",
        help="evaluate one side of the frozen split (see EVAL_SPLIT.md)",
    )
    p.add_argument("--llm", action="store_true")
    args = p.parse_args()
    scenarios = args.scenarios or scenarios_for(args.split)
    run_eval(scenarios, use_llm=args.llm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
