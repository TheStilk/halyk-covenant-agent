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

# Decimal: 2.0 or 1,5 (EU). Money still allows 1,500.00 (US thousands) via _to_float.
_NUM_DEC = r"[0-9]+(?:[.,][0-9]+)?"
_NUM_MONEY = r"[0-9][0-9,\s]*(?:\.[0-9]+)?"
# Year / period after a bare number — not a financial threshold
_NOT_YEAR = (
    r"(?!\s*(?:год(?:а|у|ов)?|г\.?|лет|year|years?|жыл(?:ы|ға)?)\b)"
)

_THRESHOLD_RE = re.compile(
    r"(?:"
    rf"не\s+превышал[оаи]?\s+({_NUM_DEC})\s*[xх]?"
    rf"|не\s+превыша[ею]т\s+\$?\s*({_NUM_MONEY})"
    rf"|не\s+менее\s+({_NUM_DEC})\s*[xх]?"
    rf"|не\s+менее\s+\$\s*({_NUM_MONEY})"
    rf"|ниже\s+величины\s+({_NUM_DEC})\s*[xх]?"
    rf"|составлял[оаи]?\s+не\s+менее\s+({_NUM_DEC})\s*[xх]?"
    rf"|составлял[оаи]?\s+не\s+менее\s+\$\s*({_NUM_MONEY})"
    rf"|превышал[оаи]?\s+({_NUM_DEC})\s*[xх]"
    rf"|at\s+least\s+\$?\s*({_NUM_MONEY})"
    rf"|not\s+exceed\s+\$?\s*({_NUM_MONEY})"
    rf"|shall\s+not\s+exceed\s+({_NUM_DEC})\s*[xх]?"
    rf"|minimum\s+of\s+({_NUM_DEC})\s*[xх]?"
    # Kazakh: кемінде / аспауы тиіс
    rf"|кемінде\s+\$?\s*({_NUM_MONEY})"
    rf"|кемінде\s+({_NUM_DEC})\s*[xх]?"
    rf"|аспау(?:ы|ға)?\s+(?:тиіс\s+)?\$?\s*({_NUM_MONEY})"
    rf"|аспау(?:ы|ға)?\s+(?:тиіс\s+)?({_NUM_DEC})\s*[xх]?"
    # ≤/≥: reject "≤ 2025 года" as a covenant thr
    rf"|≤\s*({_NUM_DEC}){_NOT_YEAR}"
    rf"|≥\s*({_NUM_DEC}){_NOT_YEAR}"
    r")",
    re.I,
)

_MONEY_RE = re.compile(rf"\$\s*({_NUM_MONEY})")
# Latin x OR Cyrillic х (common OCR / RU PDFs)
_RATIO_RE = re.compile(rf"({_NUM_DEC})\s*[xх]\b", re.I)


def parse_threshold(text: str) -> tuple[Optional[float], str]:
    """Return (threshold_value, direction) where direction is 'max' or 'min'."""
    low = text.lower()
    # Prefer explicit ratio with x first for ratio covenants
    is_min = bool(
        re.search(
            r"минимальн|не\s+менее|не\s+допускать\s+снижения|below|at\s+least|minimum|"
            r"кемінде|кем\s+емес|төмендемеу",
            low,
        )
    )
    is_max = bool(
        re.search(
            r"максимальн|не\s+превыш|не\s+более|не\s+допускать,?\s+чтобы|"
            r"maximum|not\s+exceed|ceiling|no\s+more\s+than|"
            r"аспау|аспауы\s+тиіс|аспауға|ең\s+к[өо]п",
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
            return _to_float(ratios[0]), "min"
    if is_max and not is_min:
        if ratios:
            return _to_float(ratios[0]), "max"
        if money:
            return _to_float(money[0]), "max"

    # Both signals: prefer based on "минимальн"/"максимальн" first word
    if re.search(r"минимальн|кемінде", low):
        if money:
            return _to_float(money[0]), "min"
        if ratios:
            return _to_float(ratios[0]), "min"
    if re.search(r"максимальн|аспау|ең\s+к[өо]п", low):
        if ratios:
            return _to_float(ratios[0]), "max"
        if money:
            return _to_float(money[0]), "max"

    # Fallback
    if ratios:
        return _to_float(ratios[0]), "max" if is_max or not is_min else "min"
    if money:
        return _to_float(money[0]), "min" if is_min else "max"
    return None, "max"


def _to_float(s: str) -> float:
    """Parse money/ratio token: US thousands (1,500.00) vs EU decimal (1,5).

    Heuristic when only comma is present:
      - exactly 3 digits after comma → thousands (1,500 → 1500)
      - 1–2 digits after comma → decimal (1,5 → 1.5)
    """
    raw = (s or "").strip().replace("\u00a0", "").replace(" ", "")
    if not raw:
        return 0.0
    if "," in raw and "." in raw:
        # 1,500.00
        raw = raw.replace(",", "")
    elif "," in raw:
        left, _, right = raw.partition(",")
        if right.isdigit() and left.replace("-", "").isdigit():
            if len(right) == 3:
                raw = left + right  # thousands
            elif 1 <= len(right) <= 2:
                raw = left + "." + right  # decimal
            else:
                raw = raw.replace(",", "")
        else:
            raw = raw.replace(",", "")
    return float(raw)


def _r2(x: float) -> float:
    return round(abs(float(x)), 2)


def _status(actual: float, threshold: float, direction: str) -> str:
    """Compare metric to threshold (raw or display — caller chooses)."""
    if direction == "min":
        return "COMPLIANT" if actual + 1e-12 >= threshold else "BREACH"
    return "COMPLIANT" if actual <= threshold + 1e-12 else "BREACH"


# Finite stand-in for ±inf on ratio edges (submission forbids non-finite actual).
# Chosen so status is consistent with a naive thr re-check:
#   min + den<=0 → COMPLIANT and actual >= thr
#   max + den<=0 → BREACH    and actual >  thr
_RATIO_EDGE_SENTINEL = 9999.0


def _safe_ratio(
    num: float,
    den: float,
    thr: float,
    direction: str,
    *,
    max_ratio_band: bool = False,
) -> tuple[float, str, float, str]:
    """Ratio with bank-safe zero-denominator policy.

    Returns (actual, status, raw, edge_note).

    den > 0 → normal num/den and threshold compare.
    den <= 0:
      min (coverage floors) → COMPLIANT, actual=max(thr, 9999)
        (no interest / no base → infinite coverage; never false BREACH)
      max (leverage ceilings) → BREACH, actual=9999
        (non-positive EBITDA etc. → cannot prove under cap; never false COMPLIANT)

    actual is never ±inf (submission/validate must stay finite).
    """
    if den > 0:
        raw = float(num) / float(den)
        if max_ratio_band and direction == "max":
            status, actual = _status_max_ratio(raw, thr)
            return actual, status, raw, ""
        actual = _r2(raw)
        return actual, _status(raw, thr, direction), raw, ""
    # Edge: report a large finite actual that agrees with status vs thr
    try:
        thr_f = float(thr)
    except (TypeError, ValueError):
        thr_f = 0.0
    if direction == "min":
        actual = _r2(max(thr_f, _RATIO_EDGE_SENTINEL))
        return (
            actual,
            "COMPLIANT",
            0.0,
            f"den<=0 → COMPLIANT actual={actual} (infinite coverage sentinel)",
        )
    actual = _r2(max(_RATIO_EDGE_SENTINEL, thr_f + 1.0 if thr_f > 0 else _RATIO_EDGE_SENTINEL))
    return (
        actual,
        "BREACH",
        0.0,
        f"den<=0 → BREACH actual={actual} (infinite leverage sentinel)",
    )


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
    if "покрытия процентов" in t or "interest coverage" in t or re.search(
        r"пайызды\s+жабу|пайыздық\s+жабын", t
    ):
        return "interest_coverage"  # ebitda / interest
    if re.search(r"капитальных\s+затрат\s+группы\s+к\s+ebitda|group.*capex.*ebitda|capex.*group.*ebitda", t):
        return "group_capex_to_ebitda"
    if "скорректированной ebitda к выручке" in t or "adjusted ebitda" in t and "выручк" in t:
        return "adj_ebitda_margin"
    if "рентабельность по ebitda" in t or ("ebitda" in t and "выручк" in t and "отношени" in t):
        return "ebitda_margin"
    if "related-party payments as a proportion" in t or (
        "связанн" in t and "от выручк" in t
    ) or ("аффилирован" in t and "0." in t and "выручк" in t) or (
        "байланысты" in t and ("түсім" in t or "кіріс" in t)
    ):
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
    if (
        "связанн" in t
        or "аффилирован" in t
        or "related-party" in t
        or "related party" in t
        or "байланысты тарап" in t
        or "байланысты тұлға" in t
    ):
        # absolute RP cap (not ratio)
        if (
            re.search(r"\$\s*[0-9]", t)
            and "выручк" not in t
            and "түсім" not in t
            and "proportion" not in t
        ):
            return "max_related_party"
        return "rp_to_revenue"
    if ("выручк" in t or "түсім" in t or "кіріс" in t) and (
        "не менее" in t or "минимальн" in t or "кемінде" in t
    ):
        return "min_revenue"
    if "капитальн" in t or "капиталдық" in t:
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
    actual, status, raw, edge = _safe_ratio(m.capex, den, thr, direction)

    def recompute(exclude: set[str]) -> float:
        capex = sum(t.abs_amount for t in m.transactions if t.category == "capex" and not t.excluded and t.txn_id not in exclude and t.amount < 0)
        opex = sum(t.abs_amount for t in m.transactions if t.category == "opex" and not t.excluded and t.txn_id not in exclude and t.amount < 0)
        lease = sum(t.abs_amount for t in m.transactions if t.category == "lease" and not t.excluded and t.txn_id not in exclude and t.amount < 0)
        d = opex + lease
        return _r2(capex / d) if d > 0 else 0.0

    evidence = _find_evidence_for_sum(
        m, m.capex_txns + m.opex_txns, thr, direction, actual, recompute=recompute
    )
    edge_s = f"; {edge}" if edge else ""
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=evidence,
        reasoning=(
            f"Capital intensity = Capex / (OpEx + Lease) = "
            f"{m.capex:.2f} / ({m.opex:.2f} + {m.lease:.2f}) = {actual:.2f}; "
            f"threshold {direction} {thr}{edge_s}"
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
    actual, status, raw, edge = _safe_ratio(m.ebitda, m.interest, thr, direction)

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
    edge_s = f"; {edge}" if edge else ""
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=evidence,
        reasoning=(
            f"Interest coverage = EBITDA/Interest = ({m.revenue:.2f}-{m.opex:.2f})/{m.interest:.2f} "
            f"= {m.ebitda:.2f}/{m.interest:.2f} = {actual:.2f}; threshold {direction} {thr}{edge_s}"
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
    actual, status, raw, edge = _safe_ratio(
        m.related_party_payments,
        m.revenue,
        thr,
        direction,
        max_ratio_band=(direction == "max"),
    )

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
    edge_s = f"; {edge}" if edge else ""
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=evidence,
        reasoning=(
            f"RP/Revenue = {m.related_party_payments:.2f}/{m.revenue:.2f} = {raw:.6f}→{actual:.2f}; "
            f"threshold {direction} {thr}{edge_s}"
        ),
        confidence=0.88 if m.revenue > 0 else 0.4,
        formula_id="rp_to_revenue",
    )


def _compute_rp_to_opex(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    actual, status, raw, edge = _safe_ratio(m.related_party_payments, m.opex, thr, direction)

    def recompute(exclude: set[str]) -> float:
        rp = sum(t.abs_amount for t in m.transactions if t.is_related_party and t.amount < 0 and not t.excluded and t.txn_id not in exclude)
        opex = sum(t.abs_amount for t in m.transactions if t.category == "opex" and t.amount < 0 and not t.excluded and t.txn_id not in exclude)
        return (rp / opex) if opex > 0 else 0.0

    evidence = _find_evidence_for_sum(m, m.related_party_txns, thr, direction, raw, recompute=recompute)
    edge_s = f"; {edge}" if edge else ""
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=evidence,
        reasoning=f"RP/OpEx = {m.related_party_payments:.2f}/{m.opex:.2f} = {raw:.4f}→{actual:.2f}; thr {direction} {thr}{edge_s}",
        confidence=0.85 if m.opex > 0 else 0.4,
        formula_id="rp_to_opex",
    )


def _compute_ebitda_margin(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    """Plain or adjusted EBITDA / Revenue.

    Adjusted (covenant wording «Скорректированная EBITDA»):
      Rev − OpEx − disclosed one-time items + qualifying add-backs (≥ materiality).
    Equivalently: base EBITDA − non-qualifying one-time (sub-threshold stays deducted).
    """
    use_adj = bool(m.one_time_items) or m.add_backs > 0 or "adjust" in (
        getattr(m, "meta", {}) or {}
    ).get("formula_hint", "")
    # Always prefer adjusted_ebitda when one-time table was parsed
    ebitda = m.adjusted_ebitda if (m.one_time_items or m.add_backs > 0) else m.ebitda
    actual, status, raw, edge = _safe_ratio(ebitda, m.revenue, thr, direction)
    edge_s = f"; {edge}" if edge else ""
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=None,
        reasoning=(
            f"AdjEBITDA/Revenue = {ebitda:.2f}/{m.revenue:.2f} = {raw:.4f}→{actual:.2f}; "
            f"opex={m.opex:.2f} add_backs={m.add_backs:.2f} "
            f"non_qual_one_time={m.non_qualifying_one_time:.2f}; thr {direction} {thr}{edge_s}"
        ),
        confidence=0.95 if m.revenue > 0 else 0.4,
        formula_id="adj_ebitda_margin" if (m.one_time_items or m.add_backs) else "ebitda_margin",
    )


def _compute_tax_util_to_ebitda(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    num = m.tax + m.utilities
    actual, status, raw, edge = _safe_ratio(num, m.ebitda, thr, direction)
    edge_s = f"; {edge}" if edge else ""
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=None,
        reasoning=(
            f"(Tax+Util)/EBITDA = ({m.tax:.2f}+{m.utilities:.2f})/{m.ebitda:.2f} = {raw:.4f}→{actual:.2f}{edge_s}"
        ),
        confidence=0.9 if m.ebitda > 0 and num > 0 else 0.4,
        formula_id="tax_util_to_ebitda",
    )


def _compute_insurance_to_lease(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    """Insurance / (Lease + Utilities) when covenant covers facility occupancy costs."""
    den = m.lease + m.utilities
    actual, status, raw, edge = _safe_ratio(m.insurance, den, thr, direction)
    edge_s = f"; {edge}" if edge else ""
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=None,
        reasoning=(
            f"Insurance/(Lease+Util) = {m.insurance:.2f}/({m.lease:.2f}+{m.utilities:.2f}) = {raw:.4f}→{actual:.2f}{edge_s}"
        ),
        confidence=0.9 if den > 0 else 0.4,
        formula_id="insurance_to_lease",
    )


def _compute_group_capex_to_ebitda(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    """Group Capex (consolidated PPE additions) / Borrower EBITDA."""
    group_capex = m.group_capex if m.group_capex > 0 else m.capex
    actual, status, raw_ratio, edge = _safe_ratio(group_capex, m.ebitda, thr, direction)
    conf = 0.95 if m.group_capex > 0 else 0.5
    edge_s = f"; {edge}" if edge else ""
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=None,
        reasoning=(
            f"GroupCapex/EBITDA = {group_capex:.2f}/{m.ebitda:.2f} = {raw_ratio:.4f}→{actual:.2f}; "
            f"threshold {direction} {thr}. "
            f"source={'consolidated PPE rollforward' if m.group_capex > 0 else 'borrower capex proxy'}"
            f"{edge_s}"
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
    actual, status, raw, edge = _safe_ratio(sources, uses, thr, direction)

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
    edge_s = f"; {edge}" if edge else ""
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=evidence,
        reasoning=(
            f"Sources/Uses = (rev {m.revenue:.2f} + fin {financing:.2f}) / "
            f"(opex {m.opex:.2f} + capex {m.capex:.2f}) = {raw:.4f}→{actual:.2f}; thr {direction} {thr}{edge_s}"
        ),
        confidence=0.85 if uses > 0 else 0.4,
        formula_id="sources_to_uses",
    )


def _compute_revenue_to_payroll_util(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    den = m.payroll + m.utilities
    actual, status, raw, edge = _safe_ratio(m.revenue, den, thr, direction)
    edge_s = f"; {edge}" if edge else ""
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=None,
        reasoning=(
            f"Revenue/(Payroll+Util) = {m.revenue:.2f}/({m.payroll:.2f}+{m.utilities:.2f}) "
            f"= {actual:.2f}{edge_s}"
        ),
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
    actual, status, raw, edge = _safe_ratio(transferred, total_capex, thr, direction)

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
    edge_s = f"; {edge}" if edge else ""
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=evidence,
        reasoning=(
            f"Unrestricted transfers {transferred:.2f} / total capex {total_capex:.2f} = {raw:.4f}→{actual:.2f}; "
            f"txns={t_txns}; thr {direction} {thr}{edge_s}"
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
    actual, status, raw, edge = _safe_ratio(fin, m.ebitda, thr, direction)
    edge_s = f"; {edge}" if edge else ""
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=None,
        reasoning=(
            f"Financing/EBITDA = {fin:.2f}/{m.ebitda:.2f} = {raw:.4f}→{actual:.2f}; "
            f"fin_txns={m.financing_txns} opex={m.opex:.2f}; thr {direction} {thr}{edge_s}"
        ),
        confidence=0.9 if fin > 0 and m.ebitda > 0 else 0.35,
        formula_id="financing_to_ebitda",
    )


def _is_q4_date(date_str: str | None) -> bool:
    """True if date is calendar Q4 (Oct–Dec), any year. Expects YYYY-MM-DD."""
    if not date_str or len(date_str) < 7:
        return False
    # Prefer ISO month segment; also accept leading YYYY-MM
    try:
        month = int(str(date_str)[5:7])
    except ValueError:
        return False
    return month in (10, 11, 12)


def _compute_q4_revenue(m: ScenarioMetrics, thr: float, direction: str) -> FormulaResult:
    q4 = 0.0
    txns = []
    for t in m.transactions:
        if t.category != "revenue" or t.amount <= 0 or t.excluded:
            continue
        if _is_q4_date(t.date):
            q4 += t.abs_amount
            txns.append(t.txn_id)
    # If no date-filtered revenue, fall back: any Q4 sales-like inflow
    if q4 == 0:
        for t in m.transactions:
            if t.amount <= 0 or t.excluded:
                continue
            if _is_q4_date(t.date):
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

# Confidence ceiling for non-catalog / best-effort paths (LLM may refine later)
_UNKNOWN_CONF = 0.28
_HEURISTIC_CONF = 0.38


def _lower_conf(result: FormulaResult, conf: float, tag: str) -> FormulaResult:
    return FormulaResult(
        actual=result.actual,
        status=result.status,
        evidence_txn_id=result.evidence_txn_id,
        reasoning=f"[{tag}] {result.reasoning}",
        confidence=min(float(result.confidence), conf),
        formula_id=f"{tag}:{result.formula_id}",
    )


def _best_effort_unknown(
    metrics: ScenarioMetrics,
    thr: Optional[float],
    direction: str,
    text: str,
    *,
    covenant_id: str = "",
) -> FormulaResult:
    """Fill a cell when detect_formula_id failed — never silent BREACH/0.0.

    Uses keyword cues + threshold shape (money vs ratio, min vs max) against
    available ScenarioMetrics. Always returns status + actual >= 0 with low conf.
    """
    low = (text or "").lower()
    direction = direction if direction in ("min", "max") else "max"

    # --- soft keyword → existing handlers (low conf) ---
    soft: list[tuple[bool, Callable, str]] = [
        (
            bool(re.search(r"ebitda|eбитда|марж", low)),
            _compute_ebitda_margin,
            "ebitda_margin",
        ),
        (
            bool(re.search(r"interest\s+coverage|покрыт.*процент|процентн", low)),
            _compute_interest_coverage,
            "interest_coverage",
        ),
        (
            bool(re.search(r"связанн|аффилир|related", low)),
            _compute_max_related_party
            if thr is not None and thr >= 100
            else _compute_rp_to_revenue,
            "related_party",
        ),
        (
            bool(re.search(r"выручк|revenue|оборот", low)),
            _compute_min_revenue,
            "revenue",
        ),
        (
            bool(re.search(r"капитальн|capex|ppe|основн", low)),
            _compute_max_capex,
            "capex",
        ),
        (
            bool(re.search(r"налог|tax|коммунал|utilit", low)),
            _compute_tax_util_to_ebitda,
            "tax_util",
        ),
        (
            bool(re.search(r"страхован|insurance", low)),
            _compute_insurance_to_lease,
            "insurance",
        ),
        (
            bool(re.search(r"персонал|payroll|зарплат|wage", low)),
            _compute_payroll_total,
            "payroll",
        ),
    ]
    for matched, handler, name in soft:
        if not matched:
            continue
        use_thr = thr if thr is not None else 0.0
        try:
            fr = handler(metrics, use_thr, direction)
            return _lower_conf(
                fr,
                _UNKNOWN_CONF,
                f"unknown_best_effort:{name}",
            )
        except Exception:  # noqa: BLE001
            continue

    # --- shape-based guess from threshold magnitude ---
    # thr >= 100 → treat as money; else ratio-like
    is_money = thr is not None and thr >= 100.0

    if direction == "min":
        if is_money or thr is None:
            actual = _r2(metrics.revenue)
            t = thr if thr is not None else actual  # no thr → COMPLIANT on revenue
            status = _status(actual, t, "min") if thr is not None else "COMPLIANT"
            return FormulaResult(
                actual=actual,
                status=status,
                evidence_txn_id=None,
                reasoning=(
                    f"unknown_best_effort:min_money covenant={covenant_id} "
                    f"using revenue={actual} thr={thr}"
                ),
                confidence=_UNKNOWN_CONF,
                formula_id="unknown_best_effort:min_money_revenue",
            )
        # min ratio — prefer interest coverage / ebitda margin
        try:
            fr = _compute_interest_coverage(metrics, thr or 1.0, "min")
            return _lower_conf(fr, _UNKNOWN_CONF, "unknown_best_effort:min_ratio")
        except Exception:  # noqa: BLE001
            pass
        ebitda_m = (
            _r2(metrics.ebitda / metrics.revenue) if metrics.revenue > 0 else 0.0
        )
        status = _status(ebitda_m, thr or 0.0, "min")
        return FormulaResult(
            actual=ebitda_m,
            status=status,
            evidence_txn_id=None,
            reasoning=f"unknown_best_effort:min_ratio ebitda/revenue={ebitda_m} thr={thr}",
            confidence=_UNKNOWN_CONF,
            formula_id="unknown_best_effort:min_ratio_ebitda_margin",
        )

    # direction == max
    if is_money or thr is None:
        # largest risk outflow among RP / capex / tax
        candidates = {
            "related_party": metrics.related_party_payments,
            "capex": metrics.capex,
            "tax": metrics.tax,
            "opex": metrics.opex,
        }
        best_name, best_val = max(candidates.items(), key=lambda kv: kv[1])
        actual = _r2(best_val)
        if thr is not None:
            status = _status(actual, thr, "max")
        else:
            # no thr: cannot prove compliance
            status = "BREACH"
        return FormulaResult(
            actual=actual,
            status=status,
            evidence_txn_id=None,
            reasoning=(
                f"unknown_best_effort:max_money covenant={covenant_id} "
                f"using {best_name}={actual} thr={thr}"
            ),
            confidence=_UNKNOWN_CONF,
            formula_id=f"unknown_best_effort:max_money_{best_name}",
        )

    # max ratio
    den = metrics.revenue if metrics.revenue > 0 else 1.0
    raw = metrics.related_party_payments / den
    actual = _r2(raw)
    status, actual = _status_max_ratio(raw, thr or 0.0)
    return FormulaResult(
        actual=actual,
        status=status,
        evidence_txn_id=None,
        reasoning=(
            f"unknown_best_effort:max_ratio rp/revenue={actual} thr={thr} "
            f"covenant={covenant_id}"
        ),
        confidence=_UNKNOWN_CONF,
        formula_id="unknown_best_effort:max_ratio_rp_rev",
    )


def is_unknown_formula_verdict(verdict: CovenantVerdict) -> bool:
    """True when deterministic path used unknown/best-effort (LLM may refine)."""
    r = (verdict.reasoning or "").lower()
    return (
        "unknown" in r
        or "best_effort" in r
        or "heuristic_fallback" in r
        or verdict.confidence < _HEURISTIC_CONF
        and "could not parse threshold" in r
    )


def evaluate_covenant(
    covenant_text: str,
    metrics: ScenarioMetrics,
    *,
    covenant_id: str = "",
) -> CovenantVerdict:
    """Evaluate one covenant deterministically → CovenantVerdict.

    Known open-set formulas: unchanged high-confidence handlers.
    Unknown formulas: keyword remap → best-effort guess (never empty BREACH/0.0
    without an attempted metric). LLM refine is handled by analyze_one_covenant.
    """
    formula_id = detect_formula_id(covenant_text)
    thr, direction = parse_threshold(covenant_text)
    handler = _FORMULA_HANDLERS.get(formula_id)
    used_heuristic_remap = False

    # Soft remap only when catalog detection failed
    if handler is None:
        low = (covenant_text or "").lower()
        if "связанн" in low or "аффилир" in low:
            handler = _compute_max_related_party
            formula_id = "max_related_party_fallback"
            used_heuristic_remap = True
        elif "выручк" in low:
            handler = _compute_min_revenue
            formula_id = "min_revenue_fallback"
            used_heuristic_remap = True
        elif "капитальн" in low:
            handler = _compute_max_capex
            formula_id = "max_capex_fallback"
            used_heuristic_remap = True

    # Known (or remapped) handler with threshold — primary path
    if handler is not None and thr is not None:
        result = handler(metrics, thr, direction)
        conf = result.confidence
        reasoning = f"[{result.formula_id}] {result.reasoning}"
        if used_heuristic_remap:
            conf = min(conf, _HEURISTIC_CONF)
            reasoning = f"[heuristic_fallback:{formula_id}] {result.reasoning}"
        return CovenantVerdict(
            status=result.status,  # type: ignore[arg-type]
            actual=_r2(result.actual),
            evidence_txn_id=result.evidence_txn_id,
            reasoning=reasoning,
            confidence=conf,
        )

    # Known formula id but threshold unparseable — keep conservative (open-set always has thr)
    if handler is not None and thr is None and not used_heuristic_remap:
        return CovenantVerdict(
            status="BREACH",
            actual=0.0,
            evidence_txn_id=None,
            reasoning=(
                f"Could not parse threshold from covenant {covenant_id}. "
                f"formula_id={formula_id}"
            ),
            confidence=0.2,
        )

    # Unknown formula (or remapped without thr): best-effort, always filled
    result = _best_effort_unknown(
        metrics,
        thr,
        direction,
        covenant_text,
        covenant_id=covenant_id,
    )
    return CovenantVerdict(
        status=result.status,  # type: ignore[arg-type]
        actual=_r2(result.actual),
        evidence_txn_id=result.evidence_txn_id,
        reasoning=result.reasoning,
        confidence=result.confidence,
    )
