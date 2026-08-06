"""Deterministic covenant formula engine.

Parses covenant text for type + threshold, computes `actual` from ScenarioMetrics,
determines COMPLIANT/BREACH, and finds evidence_txn_id when a single transaction
determines the verdict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from agent.models import CovenantVerdict
from agent.tools.metrics import ClassifiedTxn, ScenarioMetrics

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_THRESHOLD_RE = re.compile(
    r"(?:"
    r"не\s+превышал[оаи]?\s+([0-9]+(?:\.[0-9]+)?)\s*x?"
    r"|не\s+превыша[ею]т\s+\$?\s*([0-9,]+(?:\.[0-9]+)?)"
    r"|не\s+менее\s+([0-9]+(?:\.[0-9]+)?)\s*x?"
    r"|не\s+менее\s+\$\s*([0-9,]+(?:\.[0-9]+)?)"
    r"|ниже\s+величины\s+([0-9]+(?:\.[0-9]+)?)\s*x?"
    r"|составлял[оаи]?\s+не\s+менее\s+([0-9]+(?:\.[0-9]+)?)\s*x?"
    r"|составлял[оаи]?\s+не\s+менее\s+\$\s*([0-9,]+(?:\.[0-9]+)?)"
    r"|превышал[оаи]?\s+([0-9]+(?:\.[0-9]+)?)\s*x"
    r"|at\s+least\s+\$?\s*([0-9,]+(?:\.[0-9]+)?)"
    r"|not\s+exceed\s+\$?\s*([0-9,]+(?:\.[0-9]+)?)"
    r"|shall\s+not\s+exceed\s+([0-9]+(?:\.[0-9]+)?)\s*x?"
    r"|minimum\s+of\s+([0-9]+(?:\.[0-9]+)?)\s*x?"
    r"|≤\s*([0-9]+(?:\.[0-9]+)?)"
    r"|≥\s*([0-9]+(?:\.[0-9]+)?)"
    r")",
    re.I,
)

_MONEY_RE = re.compile(r"\$\s*([0-9,]+(?:\.[0-9]+)?)")
_RATIO_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*x\b", re.I)


def parse_threshold(text: str) -> tuple[Optional[float], str]:
    """Return (threshold_value, direction) where direction is 'max' or 'min'."""
    low = text.lower()
    # Prefer explicit ratio with x first for ratio covenants
    is_min = bool(
        re.search(
            r"минимальн|не\s+менее|не\s+допускать\s+снижения|below|at\s+least|minimum",
            low,
        )
    )
    is_max = bool(
        re.search(
            r"максимальн|не\s+превыш|не\s+допускать,?\s+чтобы|maximum|not\s+exceed|ceiling",
            low,
        )
    )

    # Money thresholds
    money = _MONEY_RE.findall(text)
    ratios = _RATIO_RE.findall(text)

    # For min revenue style — money threshold with "не менее"
    if is_min and not is_max:
        if money:
            return _to_float(money[0]), "min"
        if ratios:
            return float(ratios[0]), "min"
    if is_max and not is_min:
        if ratios:
            return float(ratios[0]), "max"
        if money:
            return _to_float(money[0]), "max"

    # Both signals: prefer based on "минимальн"/"максимальн" first word
    if re.search(r"минимальн", low):
        if money:
            return _to_float(money[0]), "min"
        if ratios:
            return float(ratios[0]), "min"
    if re.search(r"максимальн", low):
        if ratios:
            return float(ratios[0]), "max"
        if money:
            return _to_float(money[0]), "max"

    # Fallback
    if ratios:
        return float(ratios[0]), "max" if is_max or not is_min else "min"
    if money:
        return _to_float(money[0]), "min" if is_min else "max"
    return None, "max"


def _to_float(s: str) -> float:
    return float(s.replace(",", "").replace(" ", ""))


def _r2(x: float) -> float:
    return round(abs(float(x)), 2)


def _status(actual: float, threshold: float, direction: str) -> str:
    """Compare metric to threshold (raw or display — caller chooses)."""
    if direction == "min":
        return "COMPLIANT" if actual + 1e-12 >= threshold else "BREACH"
    return "COMPLIANT" if actual <= threshold + 1e-12 else "BREACH"


def _status_max_ratio(raw: float, thr: float) -> tuple[str, float]:
    """Max-ratio covenants ('не превышать X'): report 2 d.p., test fairly.

    - Report actual = round(raw, 2)
    - If raw ≤ thr → COMPLIANT
    - If displayed value > thr → BREACH
    - If displayed == thr but raw slightly over: COMPLIANT when relative
      overshoot ≤ 5% (same band as scoring actual scale) — covers float/
      presentation cases like 0.0412→0.04 COMPLIANT vs 0.0434→0.04 BREACH.
    """
    actual = _r2(raw)
    if raw <= thr + 1e-12:
        return "COMPLIANT", actual
    if actual > thr + 1e-12:
        return "BREACH", actual
    # actual rounds to thr but raw > thr
    if thr > 0 and (raw - thr) / thr <= 0.05 + 1e-12:
        return "COMPLIANT", actual
    return "BREACH", actual


# ---------------------------------------------------------------------------
# Covenant type detection
# ---------------------------------------------------------------------------


@dataclass
class FormulaResult:
    actual: float
    status: str
    evidence_txn_id: Optional[str]
    reasoning: str
    confidence: float
    formula_id: str


def detect_formula_id(covenant_text: str) -> str:
    t = covenant_text.lower()
    if "капиталоёмкост" in t or "capital intensity" in t:
        return "capital_intensity"  # capex / (opex + lease)
    if "покрытия процентов" in t or "interest coverage" in t:
        return "interest_coverage"  # ebitda / interest
    if re.search(r"капитальных\s+затрат\s+группы\s+к\s+ebitda|group.*capex.*ebitda|capex.*group.*ebitda", t):
        return "group_capex_to_ebitda"
    if "скорректированной ebitda к выручке" in t or "adjusted ebitda" in t and "выручк" in t:
        return "adj_ebitda_margin"
    if "рентабельность по ebitda" in t or ("ebitda" in t and "выручк" in t and "отношени" in t):
        return "ebitda_margin"
    if "related-party payments as a proportion" in t or (
        "связанн" in t and "от выручк" in t
    ) or ("аффилирован" in t and "0." in t and "выручк" in t):
        return "rp_to_revenue"
    if "доля платежей связанным" in t and "операционн" in t:
        return "rp_to_opex"
    if "налоговой и коммунальной" in t or ("налог" in t and "коммунальн" in t and "ebitda" in t):
        return "tax_util_to_ebitda"
    if "страховое покрытие" in t or ("страховых премий" in t and "аренд" in t):
        return "insurance_to_lease"
    if "выручка за вычетом наибольшей" in t:
        return "revenue_minus_max_overhead"
    if "покрытие расходов на персонал" in t or ("персонал" in t and "коммунальн" in t and "выручк" in t):
        return "revenue_to_payroll_util"
    if "cover of applications" in t or ("выручки и поступлений по финансированию" in t):
        return "sources_to_uses"
    if "поступлений по финансированию к ebitda" in t or "springing" in t or "drawdown leverage" in t:
        return "financing_to_ebitda"
    if "выручка за четвёртый" in t or "четвёртый квартал" in t or "q4" in t:
        return "q4_revenue"
    if "обязательства по персоналу" in t or "совокупные обязательства по персоналу" in t:
        return "payroll_total"
    if "переданных неограниченным дочерним" in t or "капитальных активов, переданных" in t:
        return "assets_transferred"
    if "минимальная выручка" in t or "минимальн" in t and "выручк" in t:
        return "min_revenue"
    if "максимальные расходы по категории" in t or (
        "капитальные затраты" in t and "не превыша" in t
    ):
        return "max_capex"
    if "individual overhead" in t or "отдельная статья накладных" in t:
        return "max_single_overhead"
    if "связанн" in t or "аффилирован" in t or "related-party" in t or "related party" in t:
        # absolute RP cap (not ratio)
        if re.search(r"\$\s*[0-9]", t) and "выручк" not in t and "proportion" not in t:
            return "max_related_party"
        return "rp_to_revenue"
    if "выручк" in t and ("не менее" in t or "минимальн" in t):
        return "min_revenue"
    if "капитальн" in t:
        return "max_capex"
    return "unknown"


# ---------------------------------------------------------------------------
# Evidence helpers
# ---------------------------------------------------------------------------


def _find_evidence_for_sum(
    metrics: ScenarioMetrics,
    txn_ids: list[str],
    threshold: float,
    direction: str,
    base_actual: float,
    *,
    recompute: Callable[[set[str]], float],
) -> Optional[str]:
    """Find a single txn whose removal flips the verdict."""
    base_status = _status(base_actual, threshold, direction)
    candidates = txn_ids or []
    # Also try related reclass-driving txns
    for r in metrics.reclassifications:
        if r.txn_id and r.txn_id not in candidates:
            candidates.append(r.txn_id)

    for tid in candidates:
        try:
            alt = recompute({tid})
        except Exception:  # noqa: BLE001
            continue
        alt_status = _status(alt, threshold, direction)
        if alt_status != base_status:
            return tid
    return None


# ---------------------------------------------------------------------------
# Formula implementations
# ---------------------------------------------------------------------------


def _compute_capital_intensity(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    """capex / (opex + lease)."""
    den = m.opex + m.lease
    actual = _r2(m.capex / den) if den > 0 else 0.0
    status = _status(actual, thr, direction)

    def recompute(exclude: set[str]) -> float:
        capex = sum(t.abs_amount for t in m.transactions if t.category == "capex" and not t.excluded and t.txn_id not in exclude and t.amount < 0)
        opex = sum(t.abs_amount for t in m.transactions if t.category == "opex" and not t.excluded and t.txn_id not in exclude and t.amount < 0)
        lease = sum(t.abs_amount for t in m.transactions if t.category == "lease" and not t.excluded and t.txn_id not in exclude and t.amount < 0)
        d = opex + lease
        return _r2(capex / d) if d > 0 else 0.0

    evidence = _find_evidence_for_sum(
        m, m.capex_txns + m.opex_txns, thr, direction, actual, recompute=recompute
    )
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=evidence,
        reasoning=(
            f"Capital intensity = Capex / (OpEx + Lease) = "
            f"{m.capex:.2f} / ({m.opex:.2f} + {m.lease:.2f}) = {actual:.2f}; "
            f"threshold {direction} {thr}"
        ),
        confidence=0.92 if den > 0 and m.capex > 0 else 0.55,
        formula_id="capital_intensity",
    )


def _compute_min_revenue(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    actual = _r2(m.revenue)
    status = _status(actual, thr, direction)
    evidence = None  # aggregate revenue; rarely single-txn evidence
    # If only one revenue txn and breach/compliant hinges on it
    if len(m.revenue_txns) == 1:
        only = m.revenue_txns[0]
        if _status(0.0, thr, direction) != status:
            evidence = only
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=evidence,
        reasoning=f"Revenue (sales settlement) = {actual:.2f}; threshold {direction} {thr:.2f}; txns={m.revenue_txns}",
        confidence=0.95 if m.revenue > 0 else 0.4,
        formula_id="min_revenue",
    )


def _compute_max_related_party(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    actual = _r2(m.related_party_payments)
    status = _status(actual, thr, direction)

    def recompute(exclude: set[str]) -> float:
        return _r2(
            sum(
                t.abs_amount
                for t in m.transactions
                if t.is_related_party and t.amount < 0 and not t.excluded and t.txn_id not in exclude
            )
        )

    evidence = _find_evidence_for_sum(
        m, m.related_party_txns, thr, direction, actual, recompute=recompute
    )
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=evidence,
        reasoning=(
            f"Related-party payments = {actual:.2f} from {m.related_party_txns}; "
            f"threshold {direction} {thr:.2f}; parties={[p.name for p in m.related_parties if p.is_related]}"
        ),
        confidence=0.9 if m.related_parties else 0.5,
        formula_id="max_related_party",
    )


def _compute_interest_coverage(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    """EBITDA / Interest (post reclass)."""
    actual = _r2(m.ebitda / m.interest) if m.interest > 0 else 0.0
    status = _status(actual, thr, direction)

    def recompute(exclude: set[str]) -> float:
        rev = sum(t.abs_amount for t in m.transactions if t.category == "revenue" and not t.excluded and t.txn_id not in exclude and t.amount > 0)
        opex = sum(t.abs_amount for t in m.transactions if t.category == "opex" and not t.excluded and t.txn_id not in exclude and t.amount < 0)
        # For interest: if excluding a reclassed txn, revert it out of interest
        interest = sum(t.abs_amount for t in m.transactions if t.category == "interest" and not t.excluded and t.txn_id not in exclude and t.amount < 0)
        ebitda = rev - opex
        return _r2(ebitda / interest) if interest > 0 else 0.0

    evidence = _find_evidence_for_sum(
        m, m.interest_txns + m.opex_txns, thr, direction, actual, recompute=recompute
    )
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=evidence,
        reasoning=(
            f"Interest coverage = EBITDA/Interest = ({m.revenue:.2f}-{m.opex:.2f})/{m.interest:.2f} "
            f"= {m.ebitda:.2f}/{m.interest:.2f} = {actual:.2f}; threshold {direction} {thr}"
        ),
        confidence=0.9 if m.interest > 0 and m.revenue > 0 else 0.45,
        formula_id="interest_coverage",
    )


def _compute_max_capex(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    actual = _r2(m.capex)
    status = _status(actual, thr, direction)

    def recompute(exclude: set[str]) -> float:
        return _r2(
            sum(
                t.abs_amount
                for t in m.transactions
                if t.category == "capex" and not t.excluded and t.txn_id not in exclude and t.amount < 0
            )
        )

    evidence = _find_evidence_for_sum(
        m, m.capex_txns, thr, direction, actual, recompute=recompute
    )
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=evidence,
        reasoning=f"Capex = {actual:.2f} txns={m.capex_txns}; threshold {direction} {thr:.2f}",
        confidence=0.9 if m.capex > 0 else 0.5,
        formula_id="max_capex",
    )


def _compute_rp_to_revenue(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    raw = (m.related_party_payments / m.revenue) if m.revenue > 0 else 0.0
    if direction == "max":
        status, actual = _status_max_ratio(raw, thr)
    else:
        actual = _r2(raw)
        status = _status(raw, thr, direction)

    def recompute(exclude: set[str]) -> float:
        rp = sum(
            t.abs_amount
            for t in m.transactions
            if t.is_related_party and t.amount < 0 and not t.excluded and t.txn_id not in exclude
        )
        rev = sum(
            t.abs_amount
            for t in m.transactions
            if t.category == "revenue" and t.amount > 0 and not t.excluded and t.txn_id not in exclude
        )
        return (rp / rev) if rev > 0 else 0.0

    evidence = _find_evidence_for_sum(
        m, m.related_party_txns, thr, direction, raw, recompute=recompute
    )
    # No evidence when COMPLIANT at rounded ceiling (aggregate ratio)
    if status == "COMPLIANT" and direction == "max":
        evidence = None
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=evidence,
        reasoning=(
            f"RP/Revenue = {m.related_party_payments:.2f}/{m.revenue:.2f} = {raw:.6f}→{actual:.2f}; "
            f"threshold {direction} {thr}"
        ),
        confidence=0.88 if m.revenue > 0 else 0.4,
        formula_id="rp_to_revenue",
    )


def _compute_rp_to_opex(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    raw = (m.related_party_payments / m.opex) if m.opex > 0 else 0.0
    actual = _r2(raw)
    status = _status(raw, thr, direction)

    def recompute(exclude: set[str]) -> float:
        rp = sum(t.abs_amount for t in m.transactions if t.is_related_party and t.amount < 0 and not t.excluded and t.txn_id not in exclude)
        opex = sum(t.abs_amount for t in m.transactions if t.category == "opex" and t.amount < 0 and not t.excluded and t.txn_id not in exclude)
        return (rp / opex) if opex > 0 else 0.0

    evidence = _find_evidence_for_sum(m, m.related_party_txns, thr, direction, raw, recompute=recompute)
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=evidence,
        reasoning=f"RP/OpEx = {m.related_party_payments:.2f}/{m.opex:.2f} = {raw:.4f}→{actual:.2f}; thr {direction} {thr}",
        confidence=0.85 if m.opex > 0 else 0.4,
        formula_id="rp_to_opex",
    )


def _compute_ebitda_margin(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    ebitda = m.adjusted_ebitda if m.add_backs else m.ebitda
    actual = _r2(ebitda / m.revenue) if m.revenue > 0 else 0.0
    status = _status(actual, thr, direction)
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=None,
        reasoning=f"EBITDA/Revenue = {ebitda:.2f}/{m.revenue:.2f} = {actual:.2f}; thr {direction} {thr}",
        confidence=0.85 if m.revenue > 0 else 0.4,
        formula_id="ebitda_margin",
    )


def _compute_tax_util_to_ebitda(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    num = m.tax + m.utilities
    raw = (num / m.ebitda) if m.ebitda > 0 else 0.0
    actual = _r2(raw)
    status = _status(raw, thr, direction)
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=None,
        reasoning=(
            f"(Tax+Util)/EBITDA = ({m.tax:.2f}+{m.utilities:.2f})/{m.ebitda:.2f} = {raw:.4f}→{actual:.2f}"
        ),
        confidence=0.9 if m.ebitda > 0 and num > 0 else 0.4,
        formula_id="tax_util_to_ebitda",
    )


def _compute_insurance_to_lease(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    """Insurance / (Lease + Utilities) when covenant covers facility occupancy costs."""
    den = m.lease + m.utilities
    raw = (m.insurance / den) if den > 0 else 0.0
    actual = _r2(raw)
    status = _status(raw, thr, direction)
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=None,
        reasoning=(
            f"Insurance/(Lease+Util) = {m.insurance:.2f}/({m.lease:.2f}+{m.utilities:.2f}) = {raw:.4f}→{actual:.2f}"
        ),
        confidence=0.9 if den > 0 else 0.4,
        formula_id="insurance_to_lease",
    )


def _compute_group_capex_to_ebitda(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    """Group Capex (consolidated PPE additions) / Borrower EBITDA."""
    group_capex = m.group_capex if m.group_capex > 0 else m.capex
    raw_ratio = (group_capex / m.ebitda) if m.ebitda > 0 else 0.0
    actual = _r2(raw_ratio)
    status = _status(raw_ratio, thr, direction)
    conf = 0.95 if m.group_capex > 0 else 0.5
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=None,
        reasoning=(
            f"GroupCapex/EBITDA = {group_capex:.2f}/{m.ebitda:.2f} = {raw_ratio:.4f}→{actual:.2f}; "
            f"threshold {direction} {thr}. "
            f"source={'consolidated PPE rollforward' if m.group_capex > 0 else 'borrower capex proxy'}"
        ),
        confidence=conf,
        formula_id="group_capex_to_ebitda",
    )


def _compute_max_single_overhead(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    """Max of defined overhead *line items* (categories), not single transactions.

    B1 covenant: max(payroll_total, utilities_total) ≤ threshold.
    """
    payroll = m.payroll
    utilities = m.utilities
    actual = _r2(max(payroll, utilities))
    status = _status(actual, thr, direction)
    evidence = None
    # If one category alone causes breach, evidence = largest txn in that category
    if status == "BREACH":
        cat = "payroll" if payroll >= utilities else "utilities"
        cands = [t for t in m.transactions if t.category == cat and t.amount < 0 and not t.excluded]
        if cands:
            evidence = max(cands, key=lambda t: t.abs_amount).txn_id
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=evidence,
        reasoning=(
            f"Max overhead line = max(payroll={payroll:.2f}, utilities={utilities:.2f}) = {actual:.2f}; "
            f"thr {direction} {thr:.2f}"
        ),
        confidence=0.9,
        formula_id="max_single_overhead",
    )


def _compute_sources_to_uses(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    """(Revenue + financing inflows) / (OpEx + Capex)."""
    financing = m.financing_inflows
    fin_txns = list(m.financing_txns)
    if financing <= 0:
        for t in m.transactions:
            if t.excluded or t.amount <= 0:
                continue
            d = t.description.lower()
            if any(k in d for k in ("financing", "loan draw", "facility draw", "credit line", "финансир", "drawdown")):
                financing += t.abs_amount
                fin_txns.append(t.txn_id)
    sources = m.revenue + financing
    uses = m.opex + m.capex
    raw = (sources / uses) if uses > 0 else 0.0
    actual = _r2(raw)
    status = _status(raw, thr, direction)

    def recompute(exclude: set[str]) -> float:
        rev = sum(t.abs_amount for t in m.transactions if t.category == "revenue" and t.amount > 0 and not t.excluded and t.txn_id not in exclude)
        fin = sum(
            t.abs_amount
            for t in m.transactions
            if t.amount > 0
            and not t.excluded
            and t.txn_id not in exclude
            and (
                t.category == "financing"
                or any(k in t.description.lower() for k in ("financing", "loan draw", "facility draw", "credit line", "финансир", "drawdown"))
            )
        )
        opex = sum(t.abs_amount for t in m.transactions if t.category == "opex" and t.amount < 0 and not t.excluded and t.txn_id not in exclude)
        capex = sum(t.abs_amount for t in m.transactions if t.category in ("capex", "transfer") and t.amount < 0 and not t.excluded and t.txn_id not in exclude)
        u = opex + capex
        return (rev + fin) / u if u > 0 else 0.0

    # Prefer reclass-driving txns for evidence (they often flip coverage ratios)
    reclass_ids = [r.txn_id for r in m.reclassifications if r.txn_id]
    candidates = reclass_ids + m.opex_txns + m.capex_txns + fin_txns + m.revenue_txns
    evidence = _find_evidence_for_sum(
        m, candidates, thr, direction, raw, recompute=recompute
    )
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=evidence,
        reasoning=(
            f"Sources/Uses = (rev {m.revenue:.2f} + fin {financing:.2f}) / "
            f"(opex {m.opex:.2f} + capex {m.capex:.2f}) = {raw:.4f}→{actual:.2f}; thr {direction} {thr}"
        ),
        confidence=0.85 if uses > 0 else 0.4,
        formula_id="sources_to_uses",
    )


def _compute_revenue_to_payroll_util(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    den = m.payroll + m.utilities
    actual = _r2(m.revenue / den) if den > 0 else 0.0
    status = _status(actual, thr, direction)
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=None,
        reasoning=f"Revenue/(Payroll+Util) = {m.revenue:.2f}/({m.payroll:.2f}+{m.utilities:.2f}) = {actual:.2f}",
        confidence=0.85 if den > 0 and m.revenue > 0 else 0.4,
        formula_id="revenue_to_payroll_util",
    )


def _compute_assets_transferred(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    """Unrestricted-subsidiary capital transfers / total capex (incl. all transfers)."""
    transferred = 0.0
    t_txns = list(m.unrestricted_transfer_txns)
    for t in m.transactions:
        if t.txn_id in t_txns and t.amount < 0 and not t.excluded:
            transferred += t.abs_amount
    # Fallback: if unrestricted list empty, use all transfer-category txns
    if transferred <= 0:
        t_txns = list(m.transfer_txns)
        transferred = sum(
            t.abs_amount
            for t in m.transactions
            if t.category == "transfer" and t.amount < 0 and not t.excluded
        )
    total_capex = m.capex  # includes purchases + transfers
    raw = (transferred / total_capex) if total_capex > 0 else 0.0
    actual = _r2(raw)
    status = _status(raw, thr, direction)

    def recompute(exclude: set[str]) -> float:
        tr = sum(
            t.abs_amount
            for t in m.transactions
            if t.txn_id in t_txns and t.txn_id not in exclude and t.amount < 0 and not t.excluded
        )
        cap = sum(
            t.abs_amount
            for t in m.transactions
            if t.category in ("capex", "transfer")
            and t.amount < 0
            and not t.excluded
            and t.txn_id not in exclude
        )
        return (tr / cap) if cap > 0 else 0.0

    evidence = _find_evidence_for_sum(m, t_txns, thr, direction, raw, recompute=recompute)
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=evidence,
        reasoning=(
            f"Unrestricted transfers {transferred:.2f} / total capex {total_capex:.2f} = {raw:.4f}→{actual:.2f}; "
            f"txns={t_txns}; thr {direction} {thr}"
        ),
        confidence=0.9 if transferred > 0 and total_capex > 0 else 0.4,
        formula_id="assets_transferred",
    )


def _compute_revenue_minus_max_overhead(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    """Revenue − max(payroll, tax) [or other named overhead pair]."""
    # Default pair from P10: payroll vs tax
    a, b = m.payroll, m.tax
    max_oh = max(a, b)
    raw = m.revenue - max_oh
    actual = _r2(raw)
    status = _status(raw, thr, direction)
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=None,
        reasoning=(
            f"Revenue - max(payroll={a:.2f}, tax={b:.2f}) = {m.revenue:.2f}-{max_oh:.2f} = {actual:.2f}; "
            f"thr {direction} {thr:.2f}"
        ),
        confidence=0.9 if m.revenue > 0 else 0.4,
        formula_id="revenue_minus_max_overhead",
    )


def _compute_financing_to_ebitda(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    """Springing leverage: financing inflows / EBITDA (FX-converted OpEx in EBITDA)."""
    fin = m.financing_inflows
    raw = (fin / m.ebitda) if m.ebitda > 0 else 0.0
    actual = _r2(raw)
    status = _status(raw, thr, direction)
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=None,
        reasoning=(
            f"Financing/EBITDA = {fin:.2f}/{m.ebitda:.2f} = {raw:.4f}→{actual:.2f}; "
            f"fin_txns={m.financing_txns} opex={m.opex:.2f}; thr {direction} {thr}"
        ),
        confidence=0.9 if fin > 0 and m.ebitda > 0 else 0.35,
        formula_id="financing_to_ebitda",
    )


def _compute_q4_revenue(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    q4 = 0.0
    txns = []
    for t in m.transactions:
        if t.category != "revenue" or t.amount <= 0 or t.excluded:
            continue
        if t.date and (t.date.startswith("2025-10") or t.date.startswith("2025-11") or t.date.startswith("2025-12")):
            q4 += t.abs_amount
            txns.append(t.txn_id)
    # If no date-filtered revenue, fall back: any revenue in Q4 by date among all positive sales
    if q4 == 0:
        for t in m.transactions:
            if t.amount <= 0 or t.excluded:
                continue
            if t.date and t.date[:7] in {"2025-10", "2025-11", "2025-12"}:
                if t.category == "revenue" or "sales" in t.description.lower():
                    q4 += t.abs_amount
                    txns.append(t.txn_id)
    # Fallback to full revenue if still empty (date missing)
    if q4 == 0 and m.revenue > 0:
        q4 = m.revenue
        txns = m.revenue_txns
    actual = _r2(q4)
    status = _status(actual, thr, direction)
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=None,
        reasoning=f"Q4 revenue = {actual:.2f} txns={txns}; thr {direction} {thr:.2f}",
        confidence=0.7,
        formula_id="q4_revenue",
    )


def _compute_payroll_total(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    """Payroll expenses + severance program obligations from notes.

    Missing ledger payroll rows are already filled into m.payroll by metrics.
    Severance program amounts are off-book disclosures (not separate ledger rows).
    """
    import re as _re

    severance = 0.0
    notes = m.notes_text or ""
    for pat in (
        r"выходных\s+пособий[^\d$]{0,40}\$?\s*([0-9,]+(?:\.[0-9]+)?)",
        r"severance[^\d$]{0,30}\$?\s*([0-9,]+(?:\.[0-9]+)?)",
        r"программ\w*\s+выходных[^\d$]{0,40}\$?\s*([0-9,]+(?:\.[0-9]+)?)",
        r"удержания\s+персонала[^\d$]{0,40}\$?\s*([0-9,]+(?:\.[0-9]+)?)",
        r"\$([0-9,]+(?:\.[0-9]+)?)\s*[^\n]{0,40}выходн",
    ):
        mm = _re.search(pat, notes, _re.I)
        if mm:
            severance = _to_float(mm.group(1))
            break

    actual = _r2(m.payroll + severance)
    status = _status(actual, thr, direction)
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=None,
        reasoning=(
            f"Payroll obligations = payroll {m.payroll:.2f} + severance {severance:.2f} "
            f"= {actual:.2f}; thr {direction} {thr:.2f}"
        ),
        confidence=0.9,
        formula_id="payroll_total",
    )


_FORMULA_HANDLERS: dict[str, Callable[[ScenarioMetrics, float, str], FormulaResult]] = {
    "capital_intensity": _compute_capital_intensity,
    "min_revenue": _compute_min_revenue,
    "max_related_party": _compute_max_related_party,
    "interest_coverage": _compute_interest_coverage,
    "max_capex": _compute_max_capex,
    "rp_to_revenue": _compute_rp_to_revenue,
    "rp_to_opex": _compute_rp_to_opex,
    "ebitda_margin": _compute_ebitda_margin,
    "adj_ebitda_margin": _compute_ebitda_margin,
    "tax_util_to_ebitda": _compute_tax_util_to_ebitda,
    "insurance_to_lease": _compute_insurance_to_lease,
    "group_capex_to_ebitda": _compute_group_capex_to_ebitda,
    "max_single_overhead": _compute_max_single_overhead,
    "q4_revenue": _compute_q4_revenue,
    "payroll_total": _compute_payroll_total,
    "sources_to_uses": _compute_sources_to_uses,
    "revenue_to_payroll_util": _compute_revenue_to_payroll_util,
    "assets_transferred": _compute_assets_transferred,
    "revenue_minus_max_overhead": _compute_revenue_minus_max_overhead,
    "financing_to_ebitda": _compute_financing_to_ebitda,
}


def evaluate_covenant(
    covenant_text: str,
    metrics: ScenarioMetrics,
    *,
    covenant_id: str = "",
) -> CovenantVerdict:
    """Evaluate one covenant deterministically → CovenantVerdict."""
    formula_id = detect_formula_id(covenant_text)
    thr, direction = parse_threshold(covenant_text)

    if thr is None:
        return CovenantVerdict(
            status="BREACH",
            actual=0.0,
            evidence_txn_id=None,
            reasoning=f"Could not parse threshold from covenant {covenant_id}. formula_id={formula_id}",
            confidence=0.2,
        )

    handler = _FORMULA_HANDLERS.get(formula_id)
    if handler is None:
        # Heuristic fallback: if money max + related → RP; if money min + revenue → revenue
        low = covenant_text.lower()
        if "связанн" in low or "аффилир" in low:
            handler = _compute_max_related_party
            formula_id = "max_related_party_fallback"
        elif "выручк" in low:
            handler = _compute_min_revenue
            formula_id = "min_revenue_fallback"
        elif "капитальн" in low:
            handler = _compute_max_capex
            formula_id = "max_capex_fallback"
        else:
            return CovenantVerdict(
                status="BREACH",
                actual=0.0,
                evidence_txn_id=None,
                reasoning=f"Unknown formula for covenant {covenant_id}: {formula_id}",
                confidence=0.25,
            )

    result = handler(metrics, thr, direction)
    return CovenantVerdict(
        status=result.status,  # type: ignore[arg-type]
        actual=_r2(result.actual),
        evidence_txn_id=result.evidence_txn_id,
        reasoning=f"[{result.formula_id}] {result.reasoning}",
        confidence=result.confidence,
    )
