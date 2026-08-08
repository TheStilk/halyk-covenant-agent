"""Deterministic compute: FormulaSpec + ScenarioMetrics → CovenantVerdict.

LLM never does arithmetic — only this module evaluates numbers.
"""

from __future__ import annotations

import math

from agent.models import CovenantVerdict
from agent.models_formula import FormulaSpec
from agent.tools.formula_engine import _r2, _safe_ratio, _status
from agent.tools.metrics import ScenarioMetrics

# Metric names the reader is allowed to reference
_METRIC_ALIASES: dict[str, str] = {
    "rev": "revenue",
    "sales": "revenue",
    "ebitda_adj": "adjusted_ebitda",
    "adj_ebitda": "adjusted_ebitda",
    "adjusted ebitda": "adjusted_ebitda",
    "rp": "related_party_payments",
    "related_party": "related_party_payments",
    "related parties": "related_party_payments",
    "financing": "financing_inflows",
    "group capex": "group_capex",
    "unrestricted": "unrestricted_transfers",
    "unrestricted_transfer": "unrestricted_transfers",
}


def _metric_map(m: ScenarioMetrics) -> dict[str, float]:
    from agent.tools.formula_engine import get_q4_revenue, get_payroll_total
    unrestr = float(m.raw_aggregates.get("unrestricted_transfer", 0.0) or 0.0)
    return {
        "revenue": m.revenue,
        "opex": m.opex,
        "ebitda": m.ebitda,
        "adjusted_ebitda": m.adjusted_ebitda,
        "capex": m.capex,
        "lease": m.lease,
        "interest": m.interest,
        "tax": m.tax,
        "utilities": m.utilities,
        "insurance": m.insurance,
        "payroll": m.payroll,
        "marketing": m.marketing,
        "related_party_payments": m.related_party_payments,
        "financing_inflows": m.financing_inflows,
        "group_capex": m.group_capex if m.group_capex > 0 else m.capex,
        "unrestricted_transfers": unrestr,
        "other_expense": m.other_expense,
        "max_payroll_tax": max(m.payroll, m.tax),
        "max_payroll_utilities": max(m.payroll, m.utilities),
        "opex_plus_lease": m.opex + m.lease,
        "lease_plus_utilities": m.lease + m.utilities,
        "tax_plus_utilities": m.tax + m.utilities,
        "revenue_plus_financing": m.revenue + m.financing_inflows,
        "opex_plus_capex": m.opex + m.capex,
        "q4_revenue": get_q4_revenue(m),
        "payroll_total": get_payroll_total(m),
    }


def resolve_metric_value(name: str, m: ScenarioMetrics, *, needs_addbacks: bool) -> float:
    """Resolve one metric token to a float from ScenarioMetrics."""
    key = _METRIC_ALIASES.get(name.strip().lower(), name.strip().lower())
    key = key.replace(" ", "_")
    values = _metric_map(m)
    if needs_addbacks and key == "ebitda":
        key = "adjusted_ebitda"
    if key not in values:
        # fuzzy: substring match with warning (cutoff raised to reduce false matches)
        candidates = [(k, v) for k, v in values.items() if key in k or k in key]
        if len(candidates) == 1:
            hit_key = candidates[0][0]
            print(
                f"[formula_compute] WARNING fuzzy metric match: '{name}' → '{hit_key}' "
                f"(not exact)"
            )
            return float(candidates[0][1])
        if len(candidates) > 1:
            # Ambiguous match — prefer exact substring over partial
            exact_sub = [(k, v) for k, v in candidates if key == k.replace("_", "")]
            if len(exact_sub) == 1:
                print(
                    f"[formula_compute] WARNING fuzzy metric match: '{name}' → '{exact_sub[0][0]}' "
                    f"(ambiguous, picked closest)"
                )
                return float(exact_sub[0][1])
            print(
                f"[formula_compute] WARNING ambiguous fuzzy match for '{name}': "
                f"{[k for k, _ in candidates]} → returning 0.0"
            )
        return 0.0
    return float(values[key])


def sum_metrics(
    names: list[str],
    m: ScenarioMetrics,
    *,
    needs_addbacks: bool,
) -> float:
    if not names:
        return 0.0
    return sum(resolve_metric_value(n, m, needs_addbacks=needs_addbacks) for n in names)


def _coerce_thr(thr: object) -> float | None:
    """Parse threshold safely; reject non-finite / unparsable values.

    Pydantic usually delivers float|None, but 'inf'/'nan' strings can pass
    as float('inf')/nan; bare float() also used for defense-in-depth.
    """
    if thr is None:
        return None
    if isinstance(thr, bool):
        return None
    try:
        v = float(thr)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


def compute_from_formula_spec(
    spec: FormulaSpec,
    metrics: ScenarioMetrics,
    *,
    covenant_id: str = "",
) -> CovenantVerdict:
    """Evaluate formula_spec against metrics → status/actual/evidence.

    evidence_txn_id is left null for generic ratios; specialized det engine
    still provides evidence via cross-check path when preferred.

    Ratio den<=0 policy (shared with formula_engine._safe_ratio):
      min → COMPLIANT actual=0; max → BREACH actual=0.
    """
    addbacks = bool(spec.needs_addbacks)
    if spec.needs_group and "group_capex" not in [
        x.lower().replace(" ", "_") for x in (spec.numerator_metrics or [])
    ]:
        pass

    num_names = list(spec.numerator_metrics or [])
    den_names = list(spec.denominator_metrics or [])
    num = sum_metrics(num_names, metrics, needs_addbacks=addbacks)
    den = sum_metrics(den_names, metrics, needs_addbacks=addbacks)

    kind = (spec.formula_kind or "").lower()
    thr = spec.threshold
    comparison = spec.comparison if spec.comparison in ("min", "max") else "max"

    is_ratio = False
    edge_note = ""
    raw = 0.0
    actual = 0.0
    status = "BREACH"

    if kind in {"difference", "revenue_minus_max_overhead"} and len(num_names) >= 1:
        if len(num_names) >= 2:
            head = resolve_metric_value(
                num_names[0], metrics, needs_addbacks=addbacks
            )
            rest = [
                resolve_metric_value(n, metrics, needs_addbacks=addbacks)
                for n in num_names[1:]
            ]
            raw = head - max(rest) if rest else head
        else:
            raw = num - den
        actual = _r2(raw)
    elif kind in {"max_component", "max_single_overhead"}:
        parts = [
            resolve_metric_value(n, metrics, needs_addbacks=addbacks)
            for n in (num_names or ["payroll", "utilities"])
        ]
        raw = max(parts) if parts else 0.0
        actual = _r2(raw)
    elif den_names:
        is_ratio = True
        thr_f = _coerce_thr(thr)
        if thr_f is None:
            raw = (num / den) if den > 0 else 0.0
            actual = _r2(raw)
            thr = None  # treat unparsable thr as missing for status branch
        else:
            use_band = comparison == "max" and thr_f < 100
            actual, status, raw, edge_note = _safe_ratio(
                num, den, thr_f, comparison, max_ratio_band=use_band
            )
    else:
        raw = num
        actual = _r2(raw)

    thr_f = _coerce_thr(thr)
    if thr_f is None:
        status = "BREACH"
        conf = min(float(spec.confidence), 0.35)
        reasoning = (
            f"[formula_spec] {spec.raw_interpretation or kind}: "
            f"actual={actual} no threshold; covenant={covenant_id}"
        )
    elif is_ratio:
        # status already set by _safe_ratio when thr present
        conf = float(spec.confidence)
        edge_s = f" | {edge_note}" if edge_note else ""
        reasoning = (
            f"[formula_spec:{spec.formula_kind}] {spec.raw_interpretation} | "
            f"num={spec.numerator_metrics}={num:.4f} den={spec.denominator_metrics}={den:.4f} "
            f"→ actual={actual} {comparison} thr={thr_f} → {status}{edge_s}"
        )
    else:
        status = _status(actual, thr_f, comparison)
        conf = float(spec.confidence)
        reasoning = (
            f"[formula_spec:{spec.formula_kind}] {spec.raw_interpretation} | "
            f"num={spec.numerator_metrics}={num:.4f} den={spec.denominator_metrics}={den:.4f} "
            f"→ actual={actual} {comparison} thr={thr_f} → {status}"
        )

    return CovenantVerdict(
        status=status,  # type: ignore[arg-type]
        actual=actual,
        evidence_txn_id=None,
        reasoning=reasoning,
        confidence=max(0.0, min(1.0, conf)),
    )


def specs_agree(
    a: CovenantVerdict,
    b: CovenantVerdict,
    *,
    rel_tol: float = 0.05,
) -> bool:
    """True if status matches and actual within rel_tol (or both ~0)."""
    if a.status != b.status:
        return False
    aa, bb = float(a.actual), float(b.actual)
    if abs(aa) < 1e-9 and abs(bb) < 1e-9:
        return True
    base = max(abs(aa), abs(bb), 1e-9)
    return abs(aa - bb) / base <= rel_tol
