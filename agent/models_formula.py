"""Structured formula_spec — LLM interprets covenant text; code computes numbers."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class FormulaSpec(BaseModel):
    """LLM output: covenant interpretation only (no arithmetic)."""

    formula_kind: str = Field(
        default="unknown",
        description=(
            "Short kind id, e.g. ratio, absolute_max, absolute_min, difference, "
            "max_component, interest_coverage, capital_intensity, unknown"
        ),
    )
    comparison: Literal["min", "max"] = Field(
        default="max",
        description="min = actual must be >= threshold; max = actual must be <= threshold",
    )
    threshold: Optional[float] = Field(
        default=None,
        description="Numeric threshold from text (money or ratio). null if not stated.",
    )
    numerator_metrics: list[str] = Field(
        default_factory=list,
        description=(
            "Metric names to sum for numerator. Allowed: revenue, opex, ebitda, "
            "adjusted_ebitda, capex, lease, interest, tax, utilities, insurance, "
            "payroll, marketing, related_party_payments, financing_inflows, "
            "group_capex, unrestricted_transfers, other_expense, max_payroll_tax, "
            "max_payroll_utilities, opex_plus_lease, lease_plus_utilities, "
            "tax_plus_utilities, revenue_plus_financing, opex_plus_capex"
        ),
    )
    denominator_metrics: list[str] = Field(
        default_factory=list,
        description="Metric names to sum for denominator; empty → absolute (no division)",
    )
    needs_group: bool = Field(
        default=False,
        description="True if formula uses consolidated / group capex",
    )
    needs_addbacks: bool = Field(
        default=False,
        description="True if formula uses adjusted EBITDA / one-time add-backs",
    )
    needs_fx: bool = Field(
        default=False,
        description="True if FX conversion is material to the covenant",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Model confidence in the interpretation (not the numeric result)",
    )
    raw_interpretation: str = Field(
        default="",
        description="One-sentence human reading of the covenant formula",
    )

    @model_validator(mode="before")
    @classmethod
    def _defaults_for_missing_llm_keys(cls, data: Any) -> Any:
        """Inject defaults when LLM omits required-looking keys (Pydantic runs this first)."""
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if not out.get("formula_kind"):
            out["formula_kind"] = "unknown"
        if not out.get("comparison"):
            out["comparison"] = "max"
        return out

    @field_validator("numerator_metrics", "denominator_metrics", mode="before")
    @classmethod
    def _ensure_list(cls, v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        if isinstance(v, (list, tuple, set)):
            return [str(x) for x in v]
        # LLM sometimes emits a bare number / dict — never list(float)
        return []

    @field_validator("comparison", mode="before")
    @classmethod
    def _norm_comparison(cls, v: object) -> str:
        s = str(v or "max").strip().lower()
        if s in {"min", "minimum", "at_least", ">=", "≥"}:
            return "min"
        return "max"

    @field_validator("formula_kind", mode="before")
    @classmethod
    def _norm_kind(cls, v: object) -> str:
        s = str(v or "unknown").strip()
        return s or "unknown"
