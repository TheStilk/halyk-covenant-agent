#!/usr/bin/env python3
"""Entry point for the Halyk Covenant Monitoring Agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on path when run as `python main.py`
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.console import setup_console  # noqa: E402

setup_console()


def cmd_foundation(_: argparse.Namespace) -> int:
    from agent.graph import run_foundation

    print("=== Phase 1: Foundation pipeline ===")
    state = run_foundation()
    print(f"stage={state.get('stage')} error={state.get('error')}")

    docs = state.get("documents") or {}
    covenants = docs.get("covenants_by_scenario") or {}
    print("\nCovenants extracted per scenario:")
    for sc in sorted(covenants):
        clauses = covenants[sc]
        print(f"  {sc}: {list(clauses.keys())}")
        for cid, text in clauses.items():
            preview = text.replace("\n", " ")[:120]
            print(f"    {cid}: {preview}...")

    # Summary of classification
    doc_index = state.get("doc_index") or []
    by_type: dict[str, int] = {}
    for d in doc_index:
        by_type[d["doc_type"]] = by_type.get(d["doc_type"], 0) + 1
    print(f"\nClassification summary: {by_type}")
    print(f"Borrower map: {state.get('account_to_scenario')}")
    return 0


def cmd_phase2(_: argparse.Namespace) -> int:
    from agent.graph import run_phase2
    from agent.config import SUBMISSION_PATH, TEAM_NAME, CONTACT_EMAIL, MODEL_LABEL
    import json

    print("=== Phase 2: Full calculation pipeline ===")
    state = run_phase2()
    print(f"stage={state.get('stage')} error={state.get('error')}")
    answers = (state.get("documents") or {}).get("submission_answers") or {}
    submission = {
        "team": TEAM_NAME,
        "contact_email": CONTACT_EMAIL,
        "model": MODEL_LABEL,
        "answers": answers,
    }
    SUBMISSION_PATH.write_text(json.dumps(submission, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {SUBMISSION_PATH}")
    n = sum(1 for sc in answers.values() for c in sc.values() if c.get("status"))
    print(f"Filled cells: {n}")
    return 0


def cmd_map_accounts(_: argparse.Namespace) -> int:
    from agent.tools.ledger import (
        build_account_to_scenario,
        filter_scenario_accounts,
        load_ledger,
        scenario_to_account,
    )
    from agent.nodes.load_ledger import _load_template_scenarios

    ledger = load_ledger()
    full = build_account_to_scenario(ledger)
    scenarios = _load_template_scenarios()
    borrowers = filter_scenario_accounts(full, scenarios)
    inv = scenario_to_account(borrowers)
    print(json.dumps({"account_to_scenario": borrowers, "scenario_to_account": inv}, indent=2))
    return 0


def cmd_classify(args: argparse.Namespace) -> int:
    from agent.tools.classifier import classify_document
    from agent.tools.pdf_cache import read_pdf_with_cache
    from agent.tools.ledger import build_account_to_scenario, filter_scenario_accounts, load_ledger
    from agent.nodes.load_ledger import _load_template_scenarios

    ledger = load_ledger()
    mapping = filter_scenario_accounts(
        build_account_to_scenario(ledger), _load_template_scenarios()
    )
    path = Path(args.path)
    doc = read_pdf_with_cache(path)
    result = classify_document(doc.text, path=str(path), account_to_scenario=mapping)
    print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
    return 0


def cmd_extract_covenants(args: argparse.Namespace) -> int:
    from agent.tools.covenants import extract_covenants
    from agent.tools.pdf_cache import read_pdf_with_cache

    path = Path(args.path)
    doc = read_pdf_with_cache(path)
    covenants = extract_covenants(doc.text, source_path=str(path))
    out = {cid: c.model_dump() for cid, c in covenants.items()}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from agent.config import SUBMISSION_PATH, TEMPLATE_PATH

    # Load validator without requiring scripts to be a package
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "validate_submission",
        ROOT / "scripts" / "validate_submission.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    submission = Path(args.submission) if getattr(args, "submission", None) else SUBMISSION_PATH
    template = Path(args.template) if getattr(args, "template", None) else TEMPLATE_PATH
    errors = mod.validate_submission(submission, template)
    print(mod.format_report(errors))
    return 0 if not errors else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Halyk Covenant Monitoring Agent")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("foundation", help="Run Phase-1 foundation pipeline")
    s.set_defaults(func=cmd_foundation)

    s = sub.add_parser("phase2", help="Run Phase-2/3 full calculation → submission.json")
    s.set_defaults(func=cmd_phase2)

    s = sub.add_parser("phase3", help="Alias for phase2 (full pipeline → submission.json)")
    s.set_defaults(func=cmd_phase2)

    s = sub.add_parser("map-accounts", help="Print account→scenario mapping")
    s.set_defaults(func=cmd_map_accounts)

    s = sub.add_parser("classify", help="Classify a single PDF")
    s.add_argument("path", type=str)
    s.set_defaults(func=cmd_classify)

    s = sub.add_parser("extract-covenants", help="Extract Article 6 from a loan PDF")
    s.add_argument("path", type=str)
    s.set_defaults(func=cmd_extract_covenants)

    s = sub.add_parser("validate", help="Validate submission.json vs submission_template.json")
    s.add_argument(
        "--submission",
        type=str,
        default=None,
        help="path to submission.json (default: ./submission.json)",
    )
    s.add_argument(
        "--template",
        type=str,
        default=None,
        help="path to submission_template.json",
    )
    s.set_defaults(func=cmd_validate)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
