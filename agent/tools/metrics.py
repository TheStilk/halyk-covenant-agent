"""Extract financial metrics for covenant analysis.

Sources:
- financial_notes + AUP reports (reclassifications, cut-offs, add-backs)
- KYC (related parties + ownership threshold)
- ledger (transaction classification + aggregates)

IMPORTANT: Intermediate AUP drafts ("ПРОЕКТ — ПРОМЕЖУТОЧНАЯ") are superseded by
final "Отчёт о выполнении согласованных процедур" and must be ignored.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from agent.models import DocType
from agent.tools.pdf_cache import read_pdf_with_cache
from agent.tools.pdf_extract import find_account_ids, normalize_whitespace

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RelatedParty:
    name: str
    ownership_pct: Optional[float] = None
    is_related: bool = True


@dataclass
class SubsidiaryPledge:
    """Subsidiary collateral coverage from KYC (unrestricted if pledge < threshold)."""

    name: str
    pledge_pct: float
    is_unrestricted: bool = False


@dataclass
class Reclassification:
    """Auditor reclassification of a transaction or amount for covenant purposes."""

    amount: float
    from_category: str
    to_category: str
    txn_id: Optional[str] = None
    counterparty: Optional[str] = None
    source_path: str = ""
    is_final: bool = True
    raw: str = ""


@dataclass
class CutoffAdjustment:
    """Transaction excluded/included due to period cut-off."""

    txn_id: str
    action: str  # exclude | include
    reason: str = ""
    source_path: str = ""


@dataclass
class ClassifiedTxn:
    txn_id: str
    date: Optional[str]
    counterparty: str
    description: str
    amount: float  # signed
    currency: str
    category: str
    abs_amount: float = 0.0
    is_related_party: bool = False
    excluded: bool = False  # cut-off excluded from covenant period

    def __post_init__(self) -> None:
        self.abs_amount = abs(float(self.amount))


@dataclass
class ScenarioMetrics:
    scenario_id: str
    account_id: str
    company_name: Optional[str] = None
    related_parties: list[RelatedParty] = field(default_factory=list)
    ownership_threshold_pct: Optional[float] = None
    reclassifications: list[Reclassification] = field(default_factory=list)
    cutoffs: list[CutoffAdjustment] = field(default_factory=list)
    transactions: list[ClassifiedTxn] = field(default_factory=list)
    # Aggregates (absolute positive numbers, post-reclass / post-cutoff)
    revenue: float = 0.0
    opex: float = 0.0
    ebitda: float = 0.0
    adjusted_ebitda: float = 0.0
    capex: float = 0.0
    lease: float = 0.0
    interest: float = 0.0
    tax: float = 0.0
    utilities: float = 0.0
    insurance: float = 0.0
    payroll: float = 0.0
    marketing: float = 0.0
    related_party_payments: float = 0.0
    other_expense: float = 0.0
    other_inflow: float = 0.0
    financing_inflows: float = 0.0
    group_capex: float = 0.0  # consolidated parent PPE additions
    # Supporting detail
    revenue_txns: list[str] = field(default_factory=list)
    capex_txns: list[str] = field(default_factory=list)
    opex_txns: list[str] = field(default_factory=list)
    interest_txns: list[str] = field(default_factory=list)
    related_party_txns: list[str] = field(default_factory=list)
    financing_txns: list[str] = field(default_factory=list)
    transfer_txns: list[str] = field(default_factory=list)  # capital asset transfers
    unrestricted_transfer_txns: list[str] = field(default_factory=list)
    unrestricted_subsidiaries: list[SubsidiaryPledge] = field(default_factory=list)
    add_backs: float = 0.0
    # One-time items from "Корректировки EBITDA" (all disclosed; add-backs = those ≥ threshold)
    one_time_items: list[dict[str, Any]] = field(default_factory=list)
    add_back_threshold: float = 300_000.0
    non_qualifying_one_time: float = 0.0  # disclosed one-time below materiality (stay in expense)
    notes_text: str = ""
    kyc_text: str = ""
    raw_aggregates: dict[str, float] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # compact for LLM prompt
        return d

    def summary_for_llm(self) -> str:
        """Compact metrics block for LLM prompts."""
        lines = [
            f"scenario_id: {self.scenario_id}",
            f"account_id: {self.account_id}",
            f"company_name: {self.company_name}",
            f"ownership_threshold_pct: {self.ownership_threshold_pct}",
            f"related_parties: {[rp.name + (f' ({rp.ownership_pct}%)' if rp.ownership_pct is not None else '') for rp in self.related_parties if rp.is_related]}",
            "",
            "=== AGGREGATES (post reclass & cutoff, absolute USD) ===",
            f"revenue: {self.revenue:.2f}  txns={self.revenue_txns}",
            f"opex: {self.opex:.2f}  txns={self.opex_txns}",
            f"ebitda (revenue - opex): {self.ebitda:.2f}",
            f"adjusted_ebitda: {self.adjusted_ebitda:.2f}  (add_backs={self.add_backs:.2f})",
            f"capex: {self.capex:.2f}  txns={self.capex_txns}",
            f"lease: {self.lease:.2f}",
            f"interest: {self.interest:.2f}  txns={self.interest_txns}",
            f"tax: {self.tax:.2f}",
            f"utilities: {self.utilities:.2f}",
            f"insurance: {self.insurance:.2f}",
            f"payroll: {self.payroll:.2f}",
            f"marketing: {self.marketing:.2f}",
            f"related_party_payments: {self.related_party_payments:.2f}  txns={self.related_party_txns}",
            f"financing_inflows: {self.financing_inflows:.2f}  txns={self.financing_txns}",
            f"group_capex: {self.group_capex:.2f}",
            f"unrestricted_transfers: {self.raw_aggregates.get('unrestricted_transfer', 0):.2f} "
            f"txns={self.unrestricted_transfer_txns}",
            f"other_expense: {self.other_expense:.2f}",
            f"other_inflow: {self.other_inflow:.2f}",
            "",
            "=== RECLASSIFICATIONS (final AUP only) ===",
        ]
        for r in self.reclassifications:
            lines.append(
                f"  {r.txn_id or r.counterparty}: {r.amount:.2f}  "
                f"{r.from_category} → {r.to_category}  [{r.source_path.split('/')[-1]}]"
            )
        if not self.reclassifications:
            lines.append("  (none)")
        lines.append("")
        lines.append("=== CUT-OFF ADJUSTMENTS ===")
        for c in self.cutoffs:
            lines.append(f"  {c.txn_id}: {c.action} — {c.reason[:80]}")
        if not self.cutoffs:
            lines.append("  (none)")
        lines.append("")
        lines.append("=== CLASSIFIED TRANSACTIONS (non-excluded) ===")
        for t in self.transactions:
            if t.excluded:
                continue
            rp = " [RELATED]" if t.is_related_party else ""
            lines.append(
                f"  {t.txn_id} {t.amount:14.2f} {t.currency} cat={t.category:12s} "
                f"| {t.counterparty[:35]:35s} | {t.description[:55]}{rp}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Category taxonomy
# ---------------------------------------------------------------------------

CATEGORY_ALIASES = {
    # Russian / English labels found in AUP reclass text
    "операционные расходы": "opex",
    "операционн": "opex",
    "operating": "opex",
    "выручка": "revenue",
    "revenue": "revenue",
    "капитальные затраты": "capex",
    "капитальн": "capex",
    "capex": "capex",
    "процентные расходы": "interest",
    "процентн": "interest",
    "interest": "interest",
    "налог": "tax",
    "tax": "tax",
    "коммунальн": "utilities",
    "utilities": "utilities",
    "utility": "utilities",
    "страховые": "insurance",
    "страхов": "insurance",
    "insurance": "insurance",
    "аренд": "lease",
    "lease": "lease",
    "rent": "lease",
    "расходы на оплату труда": "payroll",
    "оплату труда": "payroll",
    "payroll": "payroll",
    "персонал": "payroll",
    "консультационн": "consulting",
    "consulting": "consulting",
    "advisory": "consulting",
    "маркетинг": "marketing",
    "marketing": "marketing",
}


def normalize_category(label: str) -> str:
    low = label.lower().strip()
    for key, cat in CATEGORY_ALIASES.items():
        if key in low:
            return cat
    return re.sub(r"\s+", "_", low)[:40] or "other"


def classify_txn_category(description: str, amount: float) -> str:
    """Heuristic category from ledger description (no category column in CSV).

    Positive amounts: revenue / financing / refunds mapped to their expense family
    (interest, insurance, tax, …) so other_inflow shrinks. Aggregates still only
    sum outflows for expense buckets — open-set math unchanged for known formulas.
    """
    d = description.lower()

    # --- shared keyword families (both directions) ---
    def _is_interest(s: str) -> bool:
        return any(
            k in s
            for k in (
                "loan interest",
                "interest payment",
                "interest coupon",
                "interest on",
                "accrued interest",
                "default interest",
                "finance sublease",
                "revolver interest",
                "term loan interest",
                "credit facility interest",
                "overdraft interest",
                "capitalised interest",
                "capitalized interest",
                "interest true-up",
                "interest true up",
                "interest credited",
                "interest income",
                "interest recovery",
                "interest on escrow",
                "interest rebate",
                "процент",
            )
        )

    def _is_tax(s: str) -> bool:
        return any(
            k in s
            for k in (
                "tax",
                "excise",
                "duty",
                "withholding",
                "franchise tax",
                "mineral extraction",
                "emissions tax",
                "use tax",
                "vat instalment",
                "vat refund",
                "vat reclaim",
                "vat credit",
                "tax credit",
                "tax reclaim",
                "tax refund",
            )
        )

    def _is_insurance(s: str) -> bool:
        return any(
            k in s
            for k in (
                "insurance",
                "workers comp",
                "premium refund",
                "premium rebate",
                "broker rebate",
                "experience refund",
                "deductible recovery",
                "claim reimbursement",
            )
        ) or (
            # standalone insurance premium (avoid matching unrelated "premium" words)
            "premium" in s and ("insurance" in s or "insurer" in s or "policy" in s)
        ) or (s.strip().startswith("premium ") and "share" not in s)

    def _is_lease_rent(s: str) -> bool:
        if "interest" in s or "leased line" in s:
            return False
        return any(
            k in s
            for k in (
                "land lease",
                "yard lease",
                "warehouse lease",
                "depot yard rent",
                "terminal land lease",
                "equipment yard lease",
                "antenna mast lease",
                "rent for ",
                "retail unit rent",
                "office rent",
                "warehouse rent",
                "storage unit rent",
                "storage rent",
                "warehouse storage",
                "rent free period",
                "rent-free",
                "lease payments",
                "lease deposit",
                "lease incentive",
            )
        ) or s.startswith("rent ") or " lease" in s or s.endswith(" lease")

    def _is_utilities(s: str) -> bool:
        return any(
            k in s
            for k in (
                "electric",
                "utility",
                "utilities",
                "water charge",
                "water supply",
                "water and sewer",
                "waste water",
                "wastewater",
                "sewer discharge",
                "sewer charge",
                "telecom",
                "compressed air",
                "leased line",
                "mobile fleet",
                "overbilling refund",
                "metering correction",
            )
        )

    def _is_payroll(s: str) -> bool:
        return any(
            k in s
            for k in (
                "payroll",
                "salary",
                "wage",
                "night shift",
                "staff",
                "overfunding returned",
            )
        )

    def _is_marketing(s: str) -> bool:
        return any(
            k in s
            for k in (
                "marketing",
                "media buy",
                "advert",
                "sponsorship",
                "newsletter",
                "exhibition",
                "campaign",
                "trade press",
                "vehicle livery",
                "volume rebate",
                "co-operative funding",
                "cooperative funding",
                "rate adjustment credit",
                "unused ad ",
            )
        )

    if amount > 0:
        if any(
            k in d
            for k in (
                "sales settlement",
                "выручк",
                "capacity availability",
                "stevedoring",
                "port handling",
                "generation capacity",
                "generating capacity",
                "refinery turnaround services sales",
            )
        ):
            return "revenue"
        if any(
            k in d
            for k in (
                "facility drawdown",
                "loan drawdown",
                "term loan facility",
                "credit facility draw",
                "drawdown for",
                "заёмн",
                "выборка",
            )
        ):
            return "financing"
        # Refunds / credits — map to family (do not call them revenue)
        if _is_interest(d):
            return "interest"
        if _is_tax(d):
            return "tax"
        if _is_insurance(d):
            return "insurance"
        if _is_lease_rent(d):
            return "lease"
        if _is_utilities(d):
            return "utilities"
        if _is_payroll(d):
            return "payroll"
        if _is_marketing(d):
            return "marketing"
        return "other_inflow"

    # expenses (amount < 0)
    if "transfer of" in d and ("equipment" in d or "asset" in d or "subsidiary" in d or "дочерн" in d):
        return "transfer"
    if "purchase of" in d:
        return "capex"
    if re.search(r"\bequipment\b", d) and "lease" not in d and "interest" not in d and "transfer" not in d:
        return "capex"
    if any(
        k in d
        for k in (
            "operating cost",
            "operating and maintenance",
            "servicing and operating",
            "plant operating",
            "servicing contract",
            "catalyst regeneration",
            "regeneration servicing",
        )
    ):
        return "opex"
    if "maintenance expense" in d or "operating expenses" in d:
        return "opex"
    if _is_interest(d):
        return "interest"
    if _is_tax(d):
        return "tax"
    if _is_insurance(d):
        return "insurance"
    if _is_payroll(d):
        return "payroll"
    # Telecom "leased line" is utility, not facility lease
    if "leased line" in d or "mobile fleet" in d:
        return "utilities"
    if _is_lease_rent(d):
        return "lease"
    if _is_utilities(d):
        return "utilities"
    if _is_marketing(d):
        return "marketing"
    if any(k in d for k in ("management advisory", "retainer", "advisory engagement")):
        return "related_fee"
    if "consult" in d or "advisory" in d or "arbitration and legal" in d:
        return "consulting"
    # fire safety servicing → opex (not one-time repair works — leave those other)
    if "fire safety" in d and "servicing" in d:
        return "opex"
    return "other_expense"


# ---------------------------------------------------------------------------
# KYC parsing
# ---------------------------------------------------------------------------

# Matches: Turan Capital LLP 28.8% | "Turan Capital" LLP 28.8% | Atyrau Holding Group L.L.P. 37.9%
_OWNERSHIP_ROW = re.compile(
    r"[\"'«]?([A-Z][A-Za-z0-9\-\s\.'&,]+?)[\"'»]?\s*"
    r"(L\.?\s*L\.?\s*P\.?|LLP|JSC|LLC|Inc|Ltd|Bureau|Group|Company|"
    r"Works|Services|Capital|Holdings|Holding|Partners|Plant|Terminal|Personnel)"
    r"\.?\s*[.,]?\s*([0-9]+(?:\.[0-9]+)?)\s*%",
    re.I,
)

_SUBSIDIARY_PLEDGE_ROW = re.compile(
    r"([A-Z][A-Za-z0-9\-\s\.'&,]+?(?:LLP|JSC|LLC|Holdings|Assets|Processing|Conveyor|Services))"
    r"\.?\s+([0-9]+(?:\.[0-9]+)?)\s*%",
    re.I,
)

_PPE_BEGIN = re.compile(
    r"Net book value at the beginning of the year\s+\$([0-9,]+(?:\.[0-9]+)?)",
    re.I,
)
_PPE_DEP = re.compile(
    r"Depreciation charge for the year\s+\$([0-9,]+(?:\.[0-9]+)?)",
    re.I,
)
_PPE_END = re.compile(
    r"Net book value at the end of the year\s+\$([0-9,]+(?:\.[0-9]+)?)",
    re.I,
)
_PPE_DISPOSALS = re.compile(
    r"(?:Disposals|выбыти\w*)[^\n$]{0,40}\$?([0-9,]+(?:\.[0-9]+)?)",
    re.I,
)
_THRESHOLD_RE = re.compile(
    r"владеет\s+([0-9]+(?:\.[0-9]+)?)\s*%\s*и\s*более|"
    r"([0-9]+(?:\.[0-9]+)?)\s*%\s*и\s*более\s+голосующих|"
    r"([0-9]+(?:\.[0-9]+)?)\s*%\s*or\s*more",
    re.I,
)
_COMPANY_HEADER = re.compile(
    r"Проверка\s+связанных\s+сторон\s*[·•]\s*([^\n]+)|"
    r"Организация\s+([A-Z][^\n]+?JSC)",
    re.I,
)


def parse_kyc(text: str) -> tuple[list[RelatedParty], Optional[float], Optional[str]]:
    """Parse related parties and ownership threshold from KYC dossier."""
    # Limit ownership scan to the ownership section (avoid subsidiary pledge table)
    own_section = text
    start = re.search(r"Бенефициарное\s+владение|голосующих\s+прав|beneficial\s+ownership", text, re.I)
    end = re.search(
        r"Обеспечительное\s+покрытие|Идентификация\s+и\s+проверка|Проверка\s+по\s+санкцион|"
        r"Дочерние\s+организации,\s+у\s+которых|Identification\s+and\s+verification",
        text,
        re.I,
    )
    if start:
        s = start.start()
        e = end.start() if end and end.start() > s else s + 1200
        own_section = text[s:e]

    threshold: Optional[float] = None
    m = _THRESHOLD_RE.search(own_section) or _THRESHOLD_RE.search(text)
    if m:
        for g in m.groups():
            if g:
                threshold = float(g)
                break

    parties: list[RelatedParty] = []
    seen: set[str] = set()
    for m in _OWNERSHIP_ROW.finditer(own_section):
        base = re.sub(r"\s+", " ", m.group(1)).strip(" .,\"'«»")
        legal = re.sub(r"\s+", "", m.group(2).upper().replace(".", ""))
        if legal.startswith("LLP") or legal == "LLP":
            legal = "LLP"
        name = f"{base} {legal}".strip()
        # filter noise rows
        if base.lower() in {"организация", "organization", "доля голосующих прав", "дочерняя организация"}:
            continue
        if len(base) < 3 or len(name) > 90:
            continue
        pct = float(m.group(3))
        key = _normalize_cp_name(name)
        if key in seen:
            continue
        seen.add(key)
        is_related = True if threshold is None else pct >= threshold
        parties.append(RelatedParty(name=name, ownership_pct=pct, is_related=is_related))

    company = None
    cm = _COMPANY_HEADER.search(text)
    if cm:
        company = next(g for g in cm.groups() if g)
        company = re.sub(r"\s+", " ", company).strip()

    return parties, threshold, company


def parse_unrestricted_subsidiaries(text: str) -> list[SubsidiaryPledge]:
    """Parse subsidiary pledge table: pledge < 50% → unrestricted."""
    out: list[SubsidiaryPledge] = []
    # Prefer section after "Обеспечительное покрытие" / collateral coverage
    section = text
    for marker in (
        "Обеспечительное покрытие",
        "доля активов каждой дочерней",
        "Дочерняя организация",
        "unrestricted",
        "неограниченн",
    ):
        idx = text.lower().find(marker.lower()) if marker else -1
        if idx >= 0:
            section = text[idx : idx + 1500]
            break

    thr = 50.0
    mthr = re.search(r"ниже\s+([0-9]+(?:\.[0-9]+)?)\s*%", section, re.I)
    if mthr:
        thr = float(mthr.group(1))

    seen: set[str] = set()
    for m in _SUBSIDIARY_PLEDGE_ROW.finditer(section):
        name = re.sub(r"\s+", " ", m.group(1)).strip(" .,")
        if name.lower() in {"дочерняя организация", "организация", "доля активов в залоге"}:
            continue
        if len(name) < 5:
            continue
        pct = float(m.group(2))
        # Skip ownership-style rows that aren't subsidiaries (no Assets/Holdings/Processing/Conveyor)
        if not re.search(r"Assets|Holdings|Processing|Conveyor|Subsidiary|дочерн", name, re.I):
            # still accept if we're clearly in pledge section
            if "залог" not in section.lower() and "pledge" not in section.lower():
                continue
        key = _normalize_cp_name(name)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            SubsidiaryPledge(
                name=name,
                pledge_pct=pct,
                is_unrestricted=pct < thr,
            )
        )
    return out


def parse_group_capex_from_text(text: str) -> Optional[float]:
    """PPE rollforward: additions = end - begin + depreciation (+ disposals if outflow).

    Used for consolidated parent statements (Group Capex).
    """
    b = _PPE_BEGIN.search(text)
    d = _PPE_DEP.search(text)
    e = _PPE_END.search(text)
    if not (b and d and e):
        return None
    begin = _parse_money(b.group(1))
    dep = _parse_money(d.group(1))
    end = _parse_money(e.group(1))
    disposals = 0.0
    dm = _PPE_DISPOSALS.search(text)
    # Only if document says there were disposals with amounts; "no disposals" → 0
    if dm and not re.search(r"no disposals|не было выбыт|There were no disposals", text, re.I):
        disposals = _parse_money(dm.group(1))
    # Capex additions = end - begin + depreciation + disposals (NBV removed)
    capex = end - begin + dep + disposals
    return round(abs(capex), 2) if capex > 0 else None


def ocr_pdf_images(path: str) -> str:
    """OCR embedded page images via pdftoppm + tesseract (for KYC ownership tables).

    Languages: eng+rus+kaz (battle default; override via TESSERACT_LANGS env).
    """
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path as _P

    from agent.config import TESSERACT_LANG_ARG

    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        return ""
    texts: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        prefix = str(_P(td) / "page")
        try:
            subprocess.run(
                ["pdftoppm", "-png", "-r", "200", path, prefix],
                check=False,
                capture_output=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            print(f"[ocr] pdftoppm timeout (120s) on {path}")
            return ""
        except Exception as exc:  # noqa: BLE001
            print(f"[ocr] pdftoppm failed on {path}: {exc}")
            return ""
        for img in sorted(_P(td).glob("page*.png")):
            try:
                proc = subprocess.run(
                    [
                        "tesseract",
                        str(img),
                        "stdout",
                        "-l",
                        TESSERACT_LANG_ARG,
                        "--psm",
                        "6",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                if proc.stdout:
                    texts.append(proc.stdout)
            except subprocess.TimeoutExpired:
                print(f"[ocr] tesseract timeout (60s) on {img.name}")
                continue
            except Exception as exc:  # noqa: BLE001
                print(f"[ocr] tesseract failed on {img.name}: {exc}")
                continue
    return "\n".join(texts)


def _normalize_cp_name(name: str) -> str:
    n = name.lower()
    n = re.sub(r"\s*\([^)]*\)\s*", " ", n)  # strip location suffixes
    n = n.replace("l.l.p.", "llp").replace("l.l.p", "llp")
    n = n.replace(",", " ")
    n = re.sub(r"[\"'«»]", "", n)
    n = re.sub(r"[^\w\s]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def is_counterparty_related(counterparty: str, parties: list[RelatedParty]) -> bool:
    cp = _normalize_cp_name(counterparty)
    for p in parties:
        if not p.is_related:
            continue
        pn = _normalize_cp_name(p.name)
        if pn and (pn in cp or cp in pn):
            return True
        # token overlap for short distinctive names
        p_tokens = set(pn.split()) - {"llp", "jsc", "llc", "ltd", "inc", "group", "company", "the"}
        c_tokens = set(cp.split())
        if p_tokens and p_tokens <= c_tokens:
            return True
        # first two significant tokens
        p_core = [t for t in pn.split() if t not in {"llp", "jsc", "llc", "ltd", "inc"}][:2]
        if len(p_core) >= 2 and all(t in cp for t in p_core):
            return True
    return False


# ---------------------------------------------------------------------------
# Notes / AUP parsing
# ---------------------------------------------------------------------------

_DRAFT_MARKERS = re.compile(
    r"ПРОЕКТ\s*[—\-–]\s*ПРОМЕЖУТОЧНАЯ|"
    r"НЕ\s+ЯВЛЯЕТСЯ\s+ОКОНЧАТЕЛЬНОЙ\s+ПОЗИЦИЕЙ|"
    r"РАБОЧИЙ\s+ДОКУМЕНТ\s*[—\-–]\s*ЗАМЕНЕНА|"
    r"РАБОЧИЙ\s+ДОКУМЕНТ\s+ПО\s+ИТОГАМ\s+ПРОМЕЖУТОЧНОГО|"
    r"Предварительные\s+вопросы\s+по\s+классификации",
    re.I,
)
_FINAL_AUP = re.compile(
    r"Отчёт\s+о\s+выполнении\s+согласованных\s+процедур|"
    r"окончательной\s+позицией\s+аудитора\s+для\s+целей|"
    r"Настоящий\s+отчёт\s+заменяет\s+любые\s+промежуточные",
    re.I,
)

_RECLASS_PATTERNS = [
    # TXN-xx initially X reclassified as Y
    re.compile(
        r"Операция\s+(TXN-[A-Z0-9]+-\d+)[,\s]+первоначально\s+учт[ёе]нная\s+как\s+([^,(]+?)"
        r"(?:\s*\(\$([0-9,]+(?:\.[0-9]+)?)\))?"
        r"[,\s]+переклассифицирована\s+для\s+целей\s+соблюдения\s+ковенантов\s+как\s+([^\.\n]+)",
        re.I,
    ),
    # Amount paid to counterparty, initially X, reclassified as Y
    re.compile(
        r"Сумма\s+в\s+размере\s+\$([0-9,]+(?:\.[0-9]+)?),?\s+выплаченная\s+контрагенту\s+([^,\n]+?),"
        r"\s*первоначально\s+учт[ёе]нная\s+как\s+([^,\n]+?),"
        r"\s*переклассифицирована\s+для\s+целей\s+соблюдения\s+ковенантов\s+как\s+([^\.\n]+)",
        re.I,
    ),
    # Amount ... reclassified as Y (counterparty form without "первоначально" on same clause)
    re.compile(
        r"\$([0-9,]+(?:\.[0-9]+)?),?\s+выплаченная\s+контрагенту\s+([^,\n]+?)[,\n]"
        r".{0,120}?переклассифицирована.{0,40}?как\s+([^\.\n]+)",
        re.I | re.S,
    ),
]

_CUTOFF_PATTERNS = [
    re.compile(
        r"Операция\s+(TXN-[A-Z0-9]+-\d+)\s*\([^)]*\)?\s*относится\s+к\s+услугам,?\s*оказанным\s+в\s+период\s+с\s+20\d{2}",
        re.I,
    ),
    re.compile(
        r"Операция\s+(TXN-[A-Z0-9]+-\d+),?\s*датированная\s+[^,\n]+,?\s*исключена\s+из\s+ковенантного\s+периода",
        re.I,
    ),
    re.compile(
        r"(TXN-[A-Z0-9]+-\d+).{0,80}исключен[аоы]\s+из\s+ковенантного\s+периода",
        re.I,
    ),
]

_ADD_BACK_RE = re.compile(
    r"добавлен[ияе].{0,40}\$([0-9,]+(?:\.[0-9]+)?)|"
    r"add[-\s]?back.{0,20}\$?([0-9,]+(?:\.[0-9]+)?)|"
    r"разовых\s+статей.{0,60}\$([0-9,]+(?:\.[0-9]+)?)",
    re.I,
)

# Missing ledger amounts: "TXN-… сумма не отражена … фактическая сумма … $X"
_MISSING_AMOUNT_RE = re.compile(
    r"Операция\s+(TXN-[A-Z0-9]+-\d+)\s*\([^)]*\)\s*:\s*сумма\s+не\s+отражена"
    r".{0,80}?фактическая\s+сумма\s+операции\s+составляет\s+\$([0-9,]+(?:\.[0-9]+)?)",
    re.I | re.S,
)
_MISSING_AMOUNT_RE2 = re.compile(
    r"(TXN-[A-Z0-9]+-\d+).{0,120}?не\s+отражена\s+в\s+выгрузке"
    r".{0,80}?\$([0-9,]+(?:\.[0-9]+)?)",
    re.I | re.S,
)

# FX: "72,146.75 EUR … $83,690.23"
_FX_PAIR_RE = re.compile(
    r"([0-9][0-9\s,]*(?:\.[0-9]+)?)\s*(EUR|USD|KZT|GBP)\s*"
    r".{0,80}?"
    r"\$\s*([0-9,]+(?:\.[0-9]+)?)",
    re.I | re.S,
)
_FX_PAIR_RE2 = re.compile(
    r"([0-9][0-9\s,]*(?:\.[0-9]+)?)\s*(EUR|USD|KZT|GBP)"
    r".{0,40}?урегулирован\s+платежом\s+в\s+долларах\s+США\s+в\s+размере\s+\$([0-9,]+(?:\.[0-9]+)?)",
    re.I | re.S,
)

# EBITDA one-time add-back table rows: ... $251,338.94
_ONE_TIME_AMOUNT_RE = re.compile(r"\$([0-9,]+(?:\.[0-9]+)?)")
_ADD_BACK_THRESHOLD_RE = re.compile(
    r"(?:не\s+менее|at\s+least|порог\w*|существенност\w*)\s+\$?\s*([0-9,]+(?:\.[0-9]+)?)",
    re.I,
)


def _parse_money(s: str) -> float:
    return float(s.replace(",", "").replace(" ", ""))


def parse_ebitda_adjustments(text: str) -> tuple[list[dict[str, Any]], float]:
    """Parse one-time items and materiality threshold from EBITDA adjustment notes.

    Returns (items, threshold). Items are dicts with amount (positive) and raw line.
    """
    threshold = 300_000.0
    # Prefer the covenant-adjustment section
    section = text
    for marker in (
        "Корректировки EBITDA",
        "разовые статьи",
        "Adjusted EBITDA",
        "add-back",
        "обратному добавлению",
    ):
        idx = text.lower().find(marker.lower())
        if idx >= 0:
            section = text[idx : idx + 2500]
            break

    thr_m = _ADD_BACK_THRESHOLD_RE.search(section)
    if thr_m:
        threshold = _parse_money(thr_m.group(1))

    items: list[dict[str, Any]] = []
    seen_amt: set[float] = set()
    # Lines that look like adjustment rows (have a $ amount and are not the threshold sentence)
    for ln in section.splitlines():
        if "не менее" in ln.lower() or "меньшей суммы" in ln.lower() or "at least" in ln.lower():
            continue
        if "порог" in ln.lower() and "$" in ln:
            continue
        amounts = _ONE_TIME_AMOUNT_RE.findall(ln)
        if not amounts:
            continue
        # Skip pure headers
        if re.search(r"Характер|Контрагент|Сумма\s*$", ln, re.I):
            continue
        for a in amounts:
            amt = _parse_money(a)
            if amt < 1000:  # noise
                continue
            key = round(amt, 2)
            if key in seen_amt:
                continue
            seen_amt.add(key)
            items.append({"amount": key, "raw": ln.strip()[:200]})
    return items, threshold


def parse_missing_ledger_amounts(text: str) -> dict[str, float]:
    """TXN amounts missing from CSV export but disclosed in notes/treasury memos."""
    out: dict[str, float] = {}
    for pat in (_MISSING_AMOUNT_RE, _MISSING_AMOUNT_RE2):
        for m in pat.finditer(text):
            txn_id = m.group(1)
            amt = abs(_parse_money(m.group(2)))
            out[txn_id] = amt
    return out


def parse_fx_rates(text: str) -> dict[str, float]:
    """Map currency → USD per 1 unit from auditor FX disclosures."""
    rates: dict[str, float] = {}
    for pat in (_FX_PAIR_RE2, _FX_PAIR_RE):
        for m in pat.finditer(text):
            foreign_amt = _parse_money(m.group(1))
            ccy = m.group(2).upper()
            usd_amt = _parse_money(m.group(3))
            if foreign_amt > 0 and ccy != "USD":
                rates[ccy] = usd_amt / foreign_amt
    return rates


def parse_notes_and_aup(text: str, source_path: str = "") -> tuple[list[Reclassification], list[CutoffAdjustment], float]:
    """Parse reclassifications, cut-offs, add-backs. Skip draft intermediate AUP."""
    head = text[:2500]
    is_draft = bool(_DRAFT_MARKERS.search(head))
    is_final_aup = bool(_FINAL_AUP.search(head)) and not is_draft

    reclasses: list[Reclassification] = []
    cutoffs: list[CutoffAdjustment] = []
    add_backs = 0.0

    # Draft intermediate AUP → ignore reclassifications (superseded by final AUP)
    # Exception: pure notes (Примечания) are never drafts even if they mention intermediate work
    is_notes_doc = "Примечания к финансовой" in head or "ДОПОЛНЕНИЕ О СОБЛЮДЕНИИ" in text
    if is_draft and not is_notes_doc:
        return [], [], 0.0

    for pat in _RECLASS_PATTERNS:
        for m in pat.finditer(text):
            groups = m.groups()
            txn_id = None
            counterparty = None
            amount = 0.0
            from_cat = "unknown"
            to_cat = "unknown"

            if groups[0] and str(groups[0]).startswith("TXN-"):
                txn_id = groups[0]
                from_cat = normalize_category(groups[1] or "")
                if groups[2]:
                    amount = _parse_money(groups[2])
                to_cat = normalize_category(groups[3] or "")
            elif len(groups) >= 4 and groups[0] and re.match(r"[0-9]", groups[0]):
                amount = _parse_money(groups[0])
                counterparty = groups[1].strip()
                from_cat = normalize_category(groups[2] or "")
                to_cat = normalize_category(groups[3] or "")
            elif len(groups) >= 3:
                amount = _parse_money(groups[0])
                counterparty = groups[1].strip()
                to_cat = normalize_category(groups[2] or "")
                from_cat = "consulting"

            reclasses.append(
                Reclassification(
                    amount=amount,
                    from_category=from_cat,
                    to_category=to_cat,
                    txn_id=txn_id,
                    counterparty=counterparty,
                    source_path=source_path,
                    is_final=True,
                    raw=m.group(0)[:200],
                )
            )

    for pat in _CUTOFF_PATTERNS:
        for m in pat.finditer(text):
            txn_id = m.group(1)
            cutoffs.append(
                CutoffAdjustment(
                    txn_id=txn_id,
                    action="exclude",
                    reason=m.group(0)[:200],
                    source_path=source_path,
                )
            )

    for m in _ADD_BACK_RE.finditer(text):
        for g in m.groups():
            if g:
                add_backs += _parse_money(g)

    # Deduplicate reclasses by (txn_id, counterparty, to_category)
    seen: set[tuple] = set()
    uniq: list[Reclassification] = []
    for r in reclasses:
        key = (r.txn_id, (r.counterparty or "").lower()[:40], r.to_category, round(r.amount, 2))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    return uniq, cutoffs, add_backs


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------


def extract_scenario_metrics(
    *,
    scenario_id: str,
    account_id: str,
    transactions: list[dict[str, Any]],
    notes_paths: list[str] | None = None,
    kyc_paths: list[str] | None = None,
    aup_paths: list[str] | None = None,
    company_name: Optional[str] = None,
) -> ScenarioMetrics:
    """Build full ScenarioMetrics for one borrower."""
    notes_paths = notes_paths or []
    kyc_paths = kyc_paths or []
    aup_paths = aup_paths or []

    metrics = ScenarioMetrics(
        scenario_id=scenario_id,
        account_id=account_id,
        company_name=company_name,
    )

    # --- KYC ---
    kyc_parts: list[str] = []
    for path in kyc_paths:
        try:
            text = read_pdf_with_cache(path).text
        except Exception as exc:  # noqa: BLE001
            print(f"[metrics] KYC read fail {path}: {exc}")
            continue
        parties, thr, company = parse_kyc(text)
        # Always OCR KYC pages — ownership/subsidiary tables are often images
        ocr_text = ocr_pdf_images(path)
        if ocr_text:
            text = text + "\n" + ocr_text
            parties2, thr2, company2 = parse_kyc(ocr_text)
            if parties2:
                # merge, prefer OCR when denser
                if len(parties2) >= len(parties):
                    parties = parties2
                else:
                    for p in parties2:
                        if not any(_normalize_cp_name(p.name) == _normalize_cp_name(x.name) for x in parties):
                            parties.append(p)
            if thr2 is not None:
                thr = thr2
            if company2 and not company:
                company = company2
            print(f"[metrics] KYC OCR {path.split('/')[-1]}: parties={len(parties)} thr={thr}")
            # subsidiary pledge table often only in OCR page
            for sub in parse_unrestricted_subsidiaries(ocr_text):
                if not any(_normalize_cp_name(sub.name) == _normalize_cp_name(s.name) for s in metrics.unrestricted_subsidiaries):
                    metrics.unrestricted_subsidiaries.append(sub)
        # also try text-only pledge table
        for sub in parse_unrestricted_subsidiaries(text):
            if not any(_normalize_cp_name(sub.name) == _normalize_cp_name(s.name) for s in metrics.unrestricted_subsidiaries):
                metrics.unrestricted_subsidiaries.append(sub)

        kyc_parts.append(text)
        if thr is not None:
            metrics.ownership_threshold_pct = thr
        if company and not metrics.company_name:
            metrics.company_name = company
        existing = {_normalize_cp_name(p.name): p for p in metrics.related_parties}
        for p in parties:
            key = _normalize_cp_name(p.name)
            if key not in existing:
                metrics.related_parties.append(p)
                existing[key] = p
            else:
                if p.is_related:
                    existing[key].is_related = True
                    existing[key].ownership_pct = p.ownership_pct
    metrics.kyc_text = "\n\n".join(kyc_parts)

    # --- Notes + AUP + Group Capex from consolidated parent FS ---
    notes_parts: list[str] = []
    missing_amounts: dict[str, float] = {}
    fx_rates: dict[str, float] = {}
    all_doc_paths = list(dict.fromkeys([*notes_paths, *aup_paths]))
    for path in all_doc_paths:
        try:
            text = read_pdf_with_cache(path).text
        except Exception as exc:  # noqa: BLE001
            print(f"[metrics] notes read fail {path}: {exc}")
            continue
        notes_parts.append(text)
        reclasses, cutoffs, add_backs = parse_notes_and_aup(text, source_path=path)
        metrics.reclassifications.extend(reclasses)
        metrics.cutoffs.extend(cutoffs)
        metrics.add_backs += add_backs
        missing_amounts.update(parse_missing_ledger_amounts(text))
        for ccy, rate in parse_fx_rates(text).items():
            fx_rates[ccy] = rate
        gc = parse_group_capex_from_text(text)
        if gc and gc > metrics.group_capex:
            metrics.group_capex = gc
    # OCR financial notes — EBITDA add-back tables are often image-only
    for path in all_doc_paths:
        try:
            base = read_pdf_with_cache(path).text
        except Exception:  # noqa: BLE001
            base = ""
        if "EBITDA" in base or "Корректировк" in base or "разовы" in base.lower():
            try:
                ocr = ocr_pdf_images(path)
            except Exception:  # noqa: BLE001
                ocr = ""
            if ocr:
                notes_parts.append(ocr)
                items, thr = parse_ebitda_adjustments(ocr)
                if items:
                    metrics.one_time_items = items
                    metrics.add_back_threshold = thr
                    metrics.add_backs = round(
                        sum(i["amount"] for i in items if i["amount"] >= thr), 2
                    )
                    metrics.non_qualifying_one_time = round(
                        sum(i["amount"] for i in items if i["amount"] < thr), 2
                    )
                    print(
                        f"[metrics] {scenario_id} EBITDA one-time items={len(items)} "
                        f"thr={thr:.0f} add_backs={metrics.add_backs:.2f} "
                        f"non_qual={metrics.non_qualifying_one_time:.2f}"
                    )
        # also try plain text
        if not metrics.one_time_items:
            items, thr = parse_ebitda_adjustments(base)
            if items:
                metrics.one_time_items = items
                metrics.add_back_threshold = thr
                metrics.add_backs = round(
                    sum(i["amount"] for i in items if i["amount"] >= thr), 2
                )
                metrics.non_qualifying_one_time = round(
                    sum(i["amount"] for i in items if i["amount"] < thr), 2
                )

    metrics.notes_text = "\n\n".join(notes_parts)

    # Treasury / internal memos often hold NaN ledger amounts (scan by account_id)
    for path, text in _iter_docs_mentioning_account(account_id):
        missing_amounts.update(parse_missing_ledger_amounts(text))
        for ccy, rate in parse_fx_rates(text).items():
            fx_rates.setdefault(ccy, rate)
        if path not in all_doc_paths:
            notes_parts.append(text)
    if missing_amounts:
        print(f"[metrics] {scenario_id} missing ledger fills: {missing_amounts}")
    if fx_rates:
        print(f"[metrics] {scenario_id} FX rates USD-per-unit: {fx_rates}")

    # Scan corpus for consolidated FS mentioning this borrower (Group Capex)
    if metrics.group_capex <= 0 and metrics.company_name:
        metrics.group_capex = _find_group_capex_for_company(metrics.company_name, scenario_id) or 0.0

    # Build lookup for reclass by txn_id / counterparty / amount
    reclass_by_txn: dict[str, Reclassification] = {}
    reclass_by_cp: list[Reclassification] = []
    for r in metrics.reclassifications:
        if r.txn_id:
            reclass_by_txn[r.txn_id] = r
        else:
            reclass_by_cp.append(r)

    excluded_txns = {c.txn_id for c in metrics.cutoffs if c.action == "exclude"}

    # --- Classify ledger ---
    classified: list[ClassifiedTxn] = []
    for raw in transactions:
        txn_id = str(raw["txn_id"])
        desc = str(raw.get("description") or "")
        amount_raw = raw.get("amount")
        # Fill NaN / missing from notes/treasury disclosures
        if amount_raw is None or (isinstance(amount_raw, float) and amount_raw != amount_raw):
            if txn_id in missing_amounts:
                # Expenses not in export are outflows
                amount = -abs(missing_amounts[txn_id])
            else:
                amount = 0.0
        else:
            amount = float(amount_raw)
        # Convert non-USD using auditor-disclosed rate.
        # Without a rate: do NOT sum foreign amounts as USD (would break EBITDA).
        ccy = str(raw.get("currency") or "USD").upper()
        fx_unconverted = False
        if ccy != "USD" and amount != 0.0:
            if ccy in fx_rates:
                amount = amount * fx_rates[ccy]
                ccy = "USD"
            else:
                fx_unconverted = True
                print(
                    f"[metrics] {scenario_id} FX missing rate for {ccy} "
                    f"txn={txn_id} amt={amount:.2f} → exclude from aggregates"
                )
        cp = str(raw.get("counterparty") or "")
        cat = classify_txn_category(desc, amount)

        # Apply reclassification
        rec = reclass_by_txn.get(txn_id)
        if rec is None:
            for r in reclass_by_cp:
                if r.counterparty and _normalize_cp_name(r.counterparty) in _normalize_cp_name(cp):
                    rec = r
                    break
                if r.amount and abs(abs(amount) - r.amount) < 0.02:
                    rec = r
                    break
        if rec is not None:
            cat = rec.to_category
            if rec.txn_id is None:
                rec.txn_id = txn_id  # bind for later evidence

        excluded = txn_id in excluded_txns or fx_unconverted
        related = is_counterparty_related(cp, metrics.related_parties)
        # Fallback: management advisory to *Holding*/*Capital* when KYC missing party list
        if not related and not metrics.related_parties:
            if "management advisory" in desc.lower() or "retainer" in desc.lower():
                if re.search(r"holding|capital\s+(partners|group|llp)|group\s+llp", cp, re.I):
                    related = True
                    metrics.related_parties.append(
                        RelatedParty(name=cp.split("(")[0].strip(), ownership_pct=None, is_related=True)
                    )

        classified.append(
            ClassifiedTxn(
                txn_id=txn_id,
                date=raw.get("date"),
                counterparty=cp,
                description=desc,
                amount=amount,
                currency=ccy,
                category=cat,
                is_related_party=related,
                excluded=excluded,
            )
        )
    metrics.transactions = classified

    # --- Aggregates ---
    buckets: dict[str, float] = defaultdict(float)
    bucket_txns: dict[str, list[str]] = defaultdict(list)
    unrestricted_names = [
        _normalize_cp_name(s.name)
        for s in metrics.unrestricted_subsidiaries
        if s.is_unrestricted
    ]

    for t in classified:
        if t.excluded:
            continue
        if t.category == "revenue":
            # Signed: sales (+), revenue returns/refunds (-) reduce revenue
            if t.amount != 0:
                buckets["revenue"] += t.amount
                bucket_txns["revenue"].append(t.txn_id)
        elif t.category == "financing":
            if t.amount > 0:
                buckets["financing"] += t.abs_amount
                bucket_txns["financing"].append(t.txn_id)
        elif t.category == "other_inflow":
            if t.amount > 0:
                buckets["other_inflow"] += t.abs_amount
        elif t.category == "transfer":
            if t.amount < 0:
                buckets["transfer"] += t.abs_amount
                bucket_txns["transfer"].append(t.txn_id)
                # also counts toward total capital expenditures base
                buckets["capex"] += t.abs_amount
                bucket_txns["capex"].append(t.txn_id)
                # unrestricted matches recomputed cleanly below (avoid "" in name trap)
        else:
            # Expense-like buckets: outflows increase, credits/refunds decrease
            # (ledger: expense amount < 0; credit/refund amount > 0)
            if t.amount != 0:
                buckets[t.category] -= t.amount  # -(-500)=+500 expense; -(+50)=-50 credit
                bucket_txns[t.category].append(t.txn_id)

        if t.is_related_party and t.amount < 0 and not t.excluded:
            buckets["related_party_payments"] += t.abs_amount
            bucket_txns["related_party_payments"].append(t.txn_id)

    # Unrestricted transfers: require non-empty counterparty.
    # Note: "" in name is always True in Python — empty CP must not match.
    buckets["unrestricted_transfer"] = 0.0
    bucket_txns["unrestricted_transfer"] = []
    for t in classified:
        if t.excluded or t.category != "transfer" or t.amount >= 0:
            continue
        cp_n = _normalize_cp_name(t.counterparty)
        if not cp_n or not unrestricted_names:
            continue
        if any(u in cp_n or cp_n in u for u in unrestricted_names if u):
            buckets["unrestricted_transfer"] += t.abs_amount
            bucket_txns["unrestricted_transfer"].append(t.txn_id)

    metrics.revenue = round(buckets.get("revenue", 0.0), 2)
    metrics.opex = round(buckets.get("opex", 0.0), 2)
    metrics.capex = round(buckets.get("capex", 0.0), 2)
    metrics.lease = round(buckets.get("lease", 0.0), 2)
    metrics.interest = round(buckets.get("interest", 0.0), 2)
    metrics.tax = round(buckets.get("tax", 0.0), 2)
    metrics.utilities = round(buckets.get("utilities", 0.0), 2)
    metrics.insurance = round(buckets.get("insurance", 0.0), 2)
    metrics.payroll = round(buckets.get("payroll", 0.0), 2)
    metrics.marketing = round(buckets.get("marketing", 0.0), 2)
    metrics.related_party_payments = round(buckets.get("related_party_payments", 0.0), 2)
    metrics.other_expense = round(
        buckets.get("other_expense", 0.0)
        + buckets.get("consulting", 0.0)
        + buckets.get("related_fee", 0.0),
        2,
    )
    metrics.other_inflow = round(buckets.get("other_inflow", 0.0), 2)
    metrics.financing_inflows = round(buckets.get("financing", 0.0), 2)

    metrics.ebitda = round(metrics.revenue - metrics.opex, 2)
    # Adjusted EBITDA (covenant): Rev − OpEx − all disclosed one-time + qualifying add-backs
    # (= Rev − OpEx − non-qualifying one-time). One-time items sit outside the opex
    # category in the ledger (other_expense) but are operating expenses for this covenant.
    if metrics.one_time_items:
        all_one_time = sum(i["amount"] for i in metrics.one_time_items)
        metrics.adjusted_ebitda = round(
            metrics.ebitda - all_one_time + metrics.add_backs, 2
        )
    else:
        metrics.adjusted_ebitda = round(metrics.ebitda + metrics.add_backs, 2)

    metrics.revenue_txns = bucket_txns.get("revenue", [])
    metrics.capex_txns = bucket_txns.get("capex", [])
    metrics.opex_txns = bucket_txns.get("opex", [])
    metrics.interest_txns = bucket_txns.get("interest", [])
    metrics.related_party_txns = bucket_txns.get("related_party_payments", [])
    metrics.financing_txns = bucket_txns.get("financing", [])
    metrics.transfer_txns = bucket_txns.get("transfer", [])
    metrics.unrestricted_transfer_txns = bucket_txns.get("unrestricted_transfer", [])
    metrics.raw_aggregates = {k: round(v, 2) for k, v in buckets.items()}
    metrics.meta = {
        "n_txns": len(classified),
        "n_excluded": sum(1 for t in classified if t.excluded),
        "n_reclass": len(metrics.reclassifications),
        "n_related_parties": sum(1 for p in metrics.related_parties if p.is_related),
        "group_capex": metrics.group_capex,
        "unrestricted_subs": [
            s.name for s in metrics.unrestricted_subsidiaries if s.is_unrestricted
        ],
        "missing_amounts": dict(missing_amounts),
        "missing_amount_count": len(missing_amounts),
    }
    return metrics


def _iter_docs_mentioning_account(account_id: str):
    """Yield (path, text) for PDFs that mention this account (treasury memos etc.)."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "agentic-bank-public" / "documents"
    if not root.exists() or not account_id:
        return
    needle = account_id.replace("ACC-", "")
    for pdf in root.glob("*.pdf"):
        try:
            text = read_pdf_with_cache(pdf).text
        except Exception:  # noqa: BLE001
            continue
        if account_id in text or f"ACC-{needle}" in text or f"АСС-{needle}" in text:
            yield str(pdf), text


def _find_group_capex_for_company(company_name: str, scenario_id: str) -> Optional[float]:
    """Scan documents/ for consolidated PPE rollforward mentioning this borrower."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "agentic-bank-public" / "documents"
    if not root.exists():
        return None
    # Normalize whitespace so line-broken names still match
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip().lower()

    company_key = _norm(company_name.split("JSC")[0])
    # First 3 significant tokens (handles line breaks; avoids Ekibastuz Energy≠Power)
    tokens = [t for t in company_key.split() if t not in {"jsc", "the", "of", "and"}][:3]
    best = None
    for pdf in root.glob("*.pdf"):
        try:
            text = read_pdf_with_cache(pdf).text
        except Exception:  # noqa: BLE001
            continue
        if "Consolidated" not in text and "консолидир" not in text.lower():
            if "Net book value at the beginning" not in text:
                continue
        text_n = _norm(text)
        matched = company_key in text_n
        if not matched and len(tokens) >= 2:
            # require ALL of first 3 tokens (Power vs Energy distinction)
            matched = all(tok in text_n for tok in tokens)
        if not matched:
            continue
        # Segment note should mention the borrower subsidiary
        gc = parse_group_capex_from_text(text)
        if gc and (best is None or gc > best):
            best = gc
            print(f"[metrics] group_capex for {company_name} from {pdf.name}: {gc:.2f}")
    return best


def extract_metrics_for_state(
    *,
    scenario_id: str,
    account_id: str,
    transactions: list[dict],
    docs_by_scenario: dict[str, dict[str, list[str]]],
    doc_index: list[dict] | None = None,
) -> ScenarioMetrics:
    """Convenience: pull notes/kyc/aup paths from classify output."""
    by_type = docs_by_scenario.get(scenario_id) or {}
    notes = list(by_type.get(DocType.FINANCIAL_NOTES.value, []))
    kyc = list(by_type.get(DocType.KYC.value, []))

    # AUP final reports may be classified as financial_notes already; also scan doc_index
    aup: list[str] = []
    if doc_index:
        for d in doc_index:
            if d.get("scenario_id") != scenario_id:
                continue
            path = d.get("path") or ""
            # peek text marker cheaply via cache
            try:
                text = read_pdf_with_cache(path).text[:800]
            except Exception:  # noqa: BLE001
                continue
            if _FINAL_AUP.search(text) or "согласованных процедур" in text.lower():
                if path not in notes:
                    aup.append(path)

    company = None
    for d in doc_index or []:
        if d.get("scenario_id") == scenario_id and d.get("company_name"):
            company = d["company_name"]
            break

    return extract_scenario_metrics(
        scenario_id=scenario_id,
        account_id=account_id,
        transactions=transactions,
        notes_paths=notes,
        kyc_paths=kyc,
        aup_paths=aup,
        company_name=company,
    )
