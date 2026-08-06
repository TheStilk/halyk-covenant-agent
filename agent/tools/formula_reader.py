"""LLM Formula Reader: covenant text → FormulaSpec (no arithmetic)."""

from __future__ import annotations

from typing import Optional

from agent.models_formula import FormulaSpec
from agent.tools.llm import is_llm_available, llm_status_message, structured_invoke
from agent.tools.metrics import ScenarioMetrics

_SYSTEM = """You are a bank covenant formula interpreter.
Your ONLY job: read the covenant clause and fill FormulaSpec.
Rules:
- temperature semantics: be precise and conservative
- Do NOT compute any arithmetic or invent amounts
- Do NOT invent transaction IDs
- Extract threshold from text when present (strip $ and commas)
- comparison: "min" if floor / at least / не менее; "max" if ceiling / not exceed / не превышать
- numerator_metrics / denominator_metrics: ONLY names from the allowed metric vocabulary
- Prefer adjusted_ebitda when text says adjusted / adjusted EBITDA / скорректированный
- Prefer group_capex when text says group / consolidated / Группы
- related_party_payments for related/аффилированн/связанн payments
- For ratio A/B: numerator=[A], denominator=[B]
- For absolute caps: numerator=[metric], denominator=[]
- confidence reflects interpretation certainty only
- raw_interpretation: one short sentence in the language of the clause
Return structured FormulaSpec only.
"""

_USER_TMPL = """Covenant id: {covenant_id}
Scenario: {scenario_id}

=== COVENANT TEXT ===
{covenant_text}

=== AVAILABLE METRIC NAMES (use only these tokens) ===
revenue, opex, ebitda, adjusted_ebitda, capex, lease, interest, tax, utilities,
insurance, payroll, marketing, related_party_payments, financing_inflows,
group_capex, unrestricted_transfers, other_expense,
max_payroll_tax, max_payroll_utilities, opex_plus_lease, lease_plus_utilities,
tax_plus_utilities, revenue_plus_financing, opex_plus_capex

=== METRICS SNAPSHOT (for context only — do NOT recalculate) ===
{metrics_summary}

Fill FormulaSpec. Do not calculate the final actual number.
"""


def metrics_snapshot_for_reader(m: ScenarioMetrics) -> str:
    """Short metrics block — no full ledger dump."""
    return (
        f"revenue={m.revenue:.2f} opex={m.opex:.2f} ebitda={m.ebitda:.2f} "
        f"adjusted_ebitda={m.adjusted_ebitda:.2f} capex={m.capex:.2f} "
        f"lease={m.lease:.2f} interest={m.interest:.2f} tax={m.tax:.2f} "
        f"utilities={m.utilities:.2f} insurance={m.insurance:.2f} "
        f"payroll={m.payroll:.2f} related_party_payments={m.related_party_payments:.2f} "
        f"financing_inflows={m.financing_inflows:.2f} group_capex={m.group_capex:.2f} "
        f"unrestricted_transfers={m.raw_aggregates.get('unrestricted_transfer', 0):.2f}"
    )


def read_formula_spec(
    *,
    covenant_text: str,
    metrics: ScenarioMetrics,
    covenant_id: str = "",
    scenario_id: str = "",
) -> FormulaSpec:
    """Call LLM for FormulaSpec. Raises if LLM unavailable or call fails."""
    if not is_llm_available():
        raise RuntimeError(llm_status_message())

    user = _USER_TMPL.format(
        covenant_id=covenant_id or "?",
        scenario_id=scenario_id or metrics.scenario_id,
        covenant_text=(covenant_text or "").strip() or "(empty)",
        metrics_summary=metrics_snapshot_for_reader(metrics),
    )
    return structured_invoke(
        FormulaSpec,
        system=_SYSTEM,
        user=user,
        temperature=0.0,
    )


def try_read_formula_spec(
    *,
    covenant_text: str,
    metrics: ScenarioMetrics,
    covenant_id: str = "",
    scenario_id: str = "",
) -> tuple[Optional[FormulaSpec], Optional[str]]:
    """Best-effort reader: (spec, error_message). Never raises."""
    if not is_llm_available():
        return None, llm_status_message()
    try:
        spec = read_formula_spec(
            covenant_text=covenant_text,
            metrics=metrics,
            covenant_id=covenant_id,
            scenario_id=scenario_id,
        )
        return spec, None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)
