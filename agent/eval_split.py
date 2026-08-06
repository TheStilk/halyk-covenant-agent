"""Frozen train / holdout split. See EVAL_SPLIT.md for the reasoning.

Do not edit these lists. The whole point of a holdout is that its composition
was decided before the results were known; re-drawing it after seeing a score
turns it back into training data.
"""

from __future__ import annotations

# Chosen from scenarios never named in a commit message or in ZHENIS.md as a
# tuning target, stratified so both account families (B*, P*) appear on each side.
HOLDOUT: tuple[str, ...] = ("B4", "P10", "P2", "P6")

TRAIN: tuple[str, ...] = ("B1", "P1", "P3", "P4", "P5", "P7", "P8", "P9")


def scenarios_for(split: str) -> list[str] | None:
    """Scenario ids for "train" / "holdout" / "all" (None means all)."""
    key = (split or "all").lower()
    if key == "train":
        return list(TRAIN)
    if key == "holdout":
        return list(HOLDOUT)
    if key == "all":
        return None
    raise ValueError(f"unknown split {split!r}; expected train, holdout or all")


def split_of(scenario_id: str) -> str:
    """Which side of the split a scenario belongs to."""
    if scenario_id in HOLDOUT:
        return "holdout"
    if scenario_id in TRAIN:
        return "train"
    return "unknown"
