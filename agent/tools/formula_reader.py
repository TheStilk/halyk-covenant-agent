"""LLM Formula Reader: covenant text → FormulaSpec (no arithmetic)."""

from __future__ import annotations

from typing import Optional

from agent.config import FORMULA_READER_MAX_TEXT_CHARS
from agent.models_formula import FormulaSpec
from agent.tools.llm import is_llm_available, llm_status_message, structured_invoke
from agent.tools.metrics import ScenarioMetrics

# Keep system short — long prompts + thinking models hit completion length limits.
_SYSTEM = """Bank covenant formula interpreter. Output FormulaSpec only.
Rules:
- Covenant text may be Russian, English, or Kazakh (қазақ тілі) — treat all equally.
- No arithmetic, no invented numbers/txn ids.
- Extract threshold (strip $ ,). comparison: min (≥/не менее/кемінде/кем емес) or max (≤/не превышать/аспауы тиіс/аспауға).
- Use ONLY metric tokens listed in the user message.
- adjusted/скорректированн/түзетілген → adjusted_ebitda; group/Групп/топ → group_capex.
- related/аффилир/связанн/байланысты/үлестес payments → related_party_payments.
- revenue/выручк/түсім/кіріс → revenue; capex/капитальн/капиталдық → capex.
- Ratio A/B → numerator=[A], denominator=[B]. Absolute cap → numerator=[metric], denominator=[].
- Individual overhead / max single line / max(payroll, utilities): use max_payroll_utilities
  (NOT sum of payroll+utilities in numerator).
- raw_interpretation: one short sentence.
"""

_USER_TMPL = """id={covenant_id} sc={scenario_id}

TEXT:
{covenant_text}

METRICS (context only, do not recalculate):
{metrics_summary}

TOKENS: revenue,opex,ebitda,adjusted_ebitda,capex,lease,interest,tax,utilities,insurance,payroll,marketing,related_party_payments,financing_inflows,group_capex,unrestricted_transfers,other_expense,max_payroll_tax,max_payroll_utilities,opex_plus_lease,lease_plus_utilities,tax_plus_utilities,revenue_plus_financing,opex_plus_capex

Return FormulaSpec only.
"""


def metrics_snapshot_for_reader(m: ScenarioMetrics) -> str:
    """Ultra-compact metrics snapshot."""
    u = float(m.raw_aggregates.get("unrestricted_transfer", 0.0) or 0.0)
    return (
        f"rev={m.revenue:.0f} opex={m.opex:.0f} ebitda={m.ebitda:.0f} "
        f"adj_ebitda={m.adjusted_ebitda:.0f} capex={m.capex:.0f} lease={m.lease:.0f} "
        f"int={m.interest:.0f} tax={m.tax:.0f} util={m.utilities:.0f} "
        f"ins={m.insurance:.0f} pay={m.payroll:.0f} rp={m.related_party_payments:.0f} "
        f"fin={m.financing_inflows:.0f} gcapex={m.group_capex:.0f} unrestr={u:.0f}"
    )


def _clip_covenant_text(text: str, max_chars: int) -> str:
    """Clip long covenant text for the LLM prompt.

    Keep head (clause id / preamble) AND tail (often threshold/formula),
    so a long legal preamble does not drop the numeric limit at the end.
    """
    t = (text or "").strip() or "(empty)"
    if len(t) <= max_chars:
        return t
    marker = "\n…[truncated]…\n"
    budget = max_chars - len(marker)
    if budget < 40:
        return t[: max(0, max_chars - 1)] + "…"
    # Slightly more head than tail (headers matter); still keep end for thr
    head_n = max(20, int(budget * 0.55))
    tail_n = budget - head_n
    return t[:head_n] + marker + t[-tail_n:]


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
        covenant_text=_clip_covenant_text(covenant_text, FORMULA_READER_MAX_TEXT_CHARS),
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
