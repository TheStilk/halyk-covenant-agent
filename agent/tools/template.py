"""Submission template as the single source of truth for task structure.

The template tells us which scenarios exist and which clause numbers each of them
is asked about. Nothing else in the codebase may assume that the answer is always
("6.1", "6.2", "6.3") or that a borrower account starts with "ACC-7" — those are
properties of the public dataset, not rules of the task (audit finding C4).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from agent.config import TEMPLATE_PATH

# Fallback used only when the template file is genuinely absent (unit tests).
_FALLBACK_COVENANT_IDS = ("6.1", "6.2", "6.3")

_CLAUSE_ID_RE = re.compile(r"^\d+(?:\.\d+)+$")


@lru_cache(maxsize=4)
def load_template(path: str | Path | None = None) -> dict[str, list[str]]:
    """Return {scenario_id: [covenant_id, ...]} exactly as the template asks.

    Order of covenant ids is preserved from the file so that generated output
    keeps template order rather than sort order.
    """
    p = Path(path) if path else TEMPLATE_PATH
    if not p.exists():
        return {}

    data = json.loads(p.read_text(encoding="utf-8"))
    answers = data.get("answers") or {}
    out: dict[str, list[str]] = {}
    for scenario_id, cells in answers.items():
        if not isinstance(cells, dict):
            continue
        out[str(scenario_id)] = [str(cid) for cid in cells]
    return out


def template_scenarios(path: str | Path | None = None) -> list[str]:
    """Scenario ids the submission must answer, in template order."""
    return list(load_template(path))


def covenant_ids_for(scenario_id: str, path: str | Path | None = None) -> list[str]:
    """Clause numbers asked for one scenario.

    Per-scenario, because nothing guarantees the private template gives every
    borrower the same three clause numbers.
    """
    tmpl = load_template(path)
    return list(tmpl.get(scenario_id) or all_covenant_ids(path))


def all_covenant_ids(path: str | Path | None = None) -> tuple[str, ...]:
    """Union of clause numbers across all scenarios, in first-seen order.

    Used where a single regex/whitelist has to cover the whole run.
    """
    seen: dict[str, None] = {}
    for ids in load_template(path).values():
        for cid in ids:
            seen.setdefault(cid, None)
    return tuple(seen) or _FALLBACK_COVENANT_IDS


def article_numbers(path: str | Path | None = None) -> tuple[str, ...]:
    """Article numbers implied by the clause ids ("6.1" → "6"), first-seen order.

    The covenants live under some article of the loan agreement; which article
    that is must be read off the template, not assumed to be Article 6.
    """
    seen: dict[str, None] = {}
    for cid in all_covenant_ids(path):
        head = cid.split(".")[0]
        if head.isdigit():
            seen.setdefault(head, None)
    return tuple(seen) or ("6",)


def is_clause_id(value: str) -> bool:
    """True for strings shaped like a clause number ("6.1", "12.3.1")."""
    return bool(_CLAUSE_ID_RE.match(value.strip()))
