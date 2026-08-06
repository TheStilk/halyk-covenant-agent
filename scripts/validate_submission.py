#!/usr/bin/env python3
"""Validate submission.json against submission_template.json.

Checks (Halyk AI Challenge format):
1. Valid JSON
2. Top-level fields: team, contact_email, model, answers
3. scenario_id / covenant_id keys exactly match the template
4. status ∈ {COMPLIANT, BREACH}
5. actual is a number >= 0 (prefer 2 decimal places)
6. evidence_txn_id is str or null
7. status and actual are not null
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ALLOWED_STATUS = frozenset({"COMPLIANT", "BREACH"})
REQUIRED_TOP = ("team", "contact_email", "model", "answers")
REQUIRED_CELL = ("status", "actual", "evidence_txn_id")


def validate_submission(
    submission_path: Path,
    template_path: Path,
) -> list[str]:
    """Return list of error strings; empty list means OK."""
    errors: list[str] = []

    if not submission_path.exists():
        return [f"submission file not found: {submission_path}"]
    if not template_path.exists():
        return [f"template file not found: {template_path}"]

    # 1. Valid JSON
    try:
        raw = submission_path.read_text(encoding="utf-8")
        sub = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"]
    except OSError as exc:
        return [f"cannot read submission: {exc}"]

    try:
        template = json.loads(template_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [f"cannot load template: {exc}"]

    if not isinstance(sub, dict):
        return ["submission root must be a JSON object"]

    # 2. Required top-level fields
    for key in REQUIRED_TOP:
        if key not in sub:
            errors.append(f"missing top-level field: {key!r}")
    if errors:
        return errors

    for key in ("team", "contact_email", "model"):
        val = sub.get(key)
        if not isinstance(val, str) or not val.strip():
            errors.append(f"{key} must be a non-empty string (got {val!r})")

    answers = sub.get("answers")
    tpl_answers = template.get("answers")
    if not isinstance(answers, dict):
        errors.append("answers must be an object")
        return errors
    if not isinstance(tpl_answers, dict):
        errors.append("template answers is not an object")
        return errors

    # 3. Exact key sets for scenarios
    sub_scenarios = set(answers.keys())
    tpl_scenarios = set(tpl_answers.keys())
    extra_sc = sub_scenarios - tpl_scenarios
    missing_sc = tpl_scenarios - sub_scenarios
    if extra_sc:
        errors.append(f"extra scenario_id keys (not in template): {sorted(extra_sc)}")
    if missing_sc:
        errors.append(f"missing scenario_id keys (required by template): {sorted(missing_sc)}")

    # Per-scenario covenants + cell checks
    for sc in sorted(tpl_scenarios & sub_scenarios):
        cell_map = answers[sc]
        tpl_cells = tpl_answers[sc]
        if not isinstance(cell_map, dict):
            errors.append(f"answers[{sc!r}] must be an object")
            continue
        if not isinstance(tpl_cells, dict):
            continue

        sub_cov = set(cell_map.keys())
        tpl_cov = set(tpl_cells.keys())
        extra_c = sub_cov - tpl_cov
        missing_c = tpl_cov - sub_cov
        if extra_c:
            errors.append(f"answers[{sc!r}]: extra covenant keys: {sorted(extra_c)}")
        if missing_c:
            errors.append(f"answers[{sc!r}]: missing covenant keys: {sorted(missing_c)}")

        for cov in sorted(tpl_cov & sub_cov):
            cell = cell_map[cov]
            path = f"answers[{sc!r}][{cov!r}]"
            if not isinstance(cell, dict):
                errors.append(f"{path} must be an object")
                continue

            for k in REQUIRED_CELL:
                if k not in cell:
                    errors.append(f"{path}: missing field {k!r}")

            # 7. No null in status/actual
            status = cell.get("status")
            actual = cell.get("actual")
            evidence = cell.get("evidence_txn_id")

            if status is None:
                errors.append(f"{path}.status is null (must be COMPLIANT or BREACH)")
            elif not isinstance(status, str) or status not in ALLOWED_STATUS:
                # 4. status enum
                errors.append(
                    f"{path}.status must be one of {sorted(ALLOWED_STATUS)} (got {status!r})"
                )

            if actual is None:
                errors.append(f"{path}.actual is null (must be a number >= 0)")
            else:
                # 5. actual number >= 0
                if isinstance(actual, bool) or not isinstance(actual, (int, float)):
                    errors.append(f"{path}.actual must be a number (got {type(actual).__name__})")
                elif actual < 0:
                    errors.append(f"{path}.actual must be >= 0 (got {actual})")
                else:
                    # prefer 2 decimal places (warning-style as soft error for exactness)
                    rounded = round(float(actual), 2)
                    if abs(float(actual) - rounded) > 1e-9:
                        errors.append(
                            f"{path}.actual should have at most 2 decimal places "
                            f"(got {actual}; expected like {rounded:.2f})"
                        )

            # 6. evidence_txn_id string or null
            if evidence is not None and not isinstance(evidence, str):
                errors.append(
                    f"{path}.evidence_txn_id must be string or null "
                    f"(got {type(evidence).__name__})"
                )
            elif isinstance(evidence, str) and not evidence.strip():
                errors.append(f"{path}.evidence_txn_id empty string; use null instead")

            # no extra cell keys beyond template
            tpl_cell_keys = set(tpl_cells[cov].keys()) if isinstance(tpl_cells.get(cov), dict) else set(REQUIRED_CELL)
            extra_keys = set(cell.keys()) - tpl_cell_keys
            if extra_keys:
                errors.append(f"{path}: extra keys not in template: {sorted(extra_keys)}")

    return errors


def format_report(errors: list[str]) -> str:
    if not errors:
        return "OK — submission is valid"
    lines = [f"INVALID — {len(errors)} error(s):"]
    for i, err in enumerate(errors, 1):
        lines.append(f"  {i}. {err}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from agent.config import SUBMISSION_PATH, TEMPLATE_PATH

    p = argparse.ArgumentParser(description="Validate submission.json vs template")
    p.add_argument(
        "--submission",
        type=Path,
        default=SUBMISSION_PATH,
        help=f"path to submission.json (default: {SUBMISSION_PATH})",
    )
    p.add_argument(
        "--template",
        type=Path,
        default=TEMPLATE_PATH,
        help=f"path to submission_template.json (default: {TEMPLATE_PATH})",
    )
    args = p.parse_args(argv)

    errors = validate_submission(args.submission, args.template)
    print(format_report(errors))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
