#!/usr/bin/env python3
"""Run Phase-2 analysis for one or more scenarios (default: P1, P5)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run_scenarios(scenario_ids: list[str], *, use_llm: bool = False) -> dict:
    from agent.graph import run_foundation
    from agent.nodes.analyze import analyze_one_covenant
    from agent.tools.metrics import extract_metrics_for_state
    from agent.tools.ledger import (
        scenario_to_account,
        transactions_for_account,
    )
    from agent.config import COVENANT_IDS, GROUND_TRUTH_PATH

    print("=== Running foundation (classify + covenants) ===")
    state = run_foundation()
    sc_to_acc = scenario_to_account(state["account_to_scenario"])
    covenants_by = state["documents"]["covenants_by_scenario"]
    docs_by = state["docs_by_scenario"]
    ledger = state["ledger"]
    doc_index = state["doc_index"]

    gt = {}
    if GROUND_TRUTH_PATH.exists():
        raw = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
        gt = raw.get("scenarios", raw)

    rows = []
    for sc in scenario_ids:
        acc = sc_to_acc.get(sc, "")
        txns = transactions_for_account(ledger, acc)
        metrics = extract_metrics_for_state(
            scenario_id=sc,
            account_id=acc,
            transactions=txns,
            docs_by_scenario=docs_by,
            doc_index=doc_index,
        )
        print(f"\n{'='*70}\nSCENARIO {sc}  account={acc}")
        print(metrics.summary_for_llm())
        cov_map = covenants_by.get(sc) or {}
        for cid in COVENANT_IDS:
            text = cov_map.get(cid, "")
            verdict = analyze_one_covenant(
                scenario_id=sc,
                account_id=acc,
                covenant_id=cid,
                covenant_text=text,
                metrics=metrics,
                use_llm=use_llm,
            )
            true = (gt.get(sc) or {}).get("covenants", {}).get(cid, {})
            pred_status = verdict.status
            true_status = true.get("status")
            pred_actual = round(abs(float(verdict.actual)), 2)
            true_actual = true.get("actual")
            err = None
            if true_actual not in (None, 0, 0.0):
                err = abs(pred_actual - float(true_actual)) / abs(float(true_actual))
            elif true_actual == 0 or true_actual == 0.0:
                err = 0.0 if pred_actual == 0 else 1.0
            rows.append(
                {
                    "scenario": sc,
                    "covenant": cid,
                    "pred_status": pred_status,
                    "true_status": true_status,
                    "pred_actual": pred_actual,
                    "true_actual": true_actual,
                    "error_pct": None if err is None else round(err * 100, 2),
                    "pred_evidence": verdict.evidence_txn_id,
                    "true_evidence": true.get("evidence_txn_id"),
                    "confidence": round(verdict.confidence, 2),
                    "reasoning": verdict.reasoning[:200],
                }
            )
            print(
                f"  {cid}: {pred_status} actual={pred_actual} ev={verdict.evidence_txn_id} "
                f"| GT {true_status} {true_actual} ev={true.get('evidence_txn_id')} "
                f"| err%={None if err is None else round(err*100,2)} conf={verdict.confidence:.2f}"
            )
            print(f"       {verdict.reasoning[:180]}")

    print("\n=== TABLE ===")
    hdr = f"{'sc':4s} {'cov':4s} {'pred':10s} {'true':10s} {'p_act':>14s} {'t_act':>14s} {'err%':>8s} {'p_ev':20s} {'t_ev':20s}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(
            f"{r['scenario']:4s} {r['covenant']:4s} {str(r['pred_status']):10s} {str(r['true_status']):10s} "
            f"{r['pred_actual']:14.2f} {str(r['true_actual']):>14s} "
            f"{str(r['error_pct']):>8s} {str(r['pred_evidence']):20s} {str(r['true_evidence']):20s}"
        )
    return {"rows": rows}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("scenarios", nargs="*", default=["P1", "P5"])
    p.add_argument("--llm", action="store_true", help="Enable Qwen (needs API key)")
    args = p.parse_args()
    run_scenarios(args.scenarios, use_llm=args.llm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
