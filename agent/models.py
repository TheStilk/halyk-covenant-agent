"""Pydantic models for structured agent I/O."""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class DocType(str, Enum):
    LOAN_AGREEMENT = "loan_agreement"
    FINANCIAL_NOTES = "financial_notes"
    KYC = "kyc"
    JUNK = "junk"


class CovenantStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    BREACH = "BREACH"


class DocClassification(BaseModel):
    """Result of classifying a single PDF."""

    path: str
    doc_type: DocType
    account_id: Optional[str] = None
    company_name: Optional[str] = None
    scenario_id: Optional[str] = None
    confidence: float = 1.0
    method: str = "rules"  # rules | llm
    preview: str = ""


class CovenantText(BaseModel):
    """Extracted text of one covenant clause (6.1 / 6.2 / 6.3)."""

    covenant_id: str
    text: str
    source_path: Optional[str] = None


class CovenantVerdict(BaseModel):
    """Structured LLM output for a single covenant analysis (legacy path)."""

    status: Literal["COMPLIANT", "BREACH"]
    actual: float
    evidence_txn_id: Optional[str] = None
    reasoning: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)

    @field_validator("actual")
    @classmethod
    def actual_must_be_positive(cls, v: float) -> float:
        return abs(float(v))

    @field_validator("evidence_txn_id", mode="before")
    @classmethod
    def empty_evidence_to_null(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str) and v.strip().lower() in {"", "null", "none", "n/a"}:
            return None
        return str(v)


class FinalCovenantResult(BaseModel):
    """One cell in submission.answers[scenario][covenant_id]."""

    scenario_id: str
    covenant_id: str
    status: Literal["COMPLIANT", "BREACH"]
    actual: float
    evidence_txn_id: Optional[str] = None
    confidence: float = 0.0
    reasoning: str = ""

    def to_submission_cell(self) -> dict[str, Any]:
        return ensure_filled_cell(
            {
                "status": self.status,
                "actual": self.actual,
                "evidence_txn_id": self.evidence_txn_id,
            }
        )


def ensure_filled_cell(cell: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Guarantee a submission cell has non-null status/actual (best-effort).

    - status: COMPLIANT|BREACH only; anything else → BREACH (cannot prove compliance)
    - actual: number >= 0, rounded to 2 decimals; missing/invalid → 0.0
    - evidence_txn_id: non-empty str or null
    """
    src = cell if isinstance(cell, dict) else {}
    status = src.get("status")
    if status not in ("COMPLIANT", "BREACH"):
        status = "BREACH"

    raw_actual = src.get("actual")
    try:
        if raw_actual is None:
            actual = 0.0
        else:
            actual = abs(float(raw_actual))
            if not math.isfinite(actual):  # NaN / ±inf
                actual = 0.0
                if status == "COMPLIANT":
                    # cannot prove compliance with non-finite actual
                    status = "BREACH"
    except (TypeError, ValueError):
        actual = 0.0
    if actual < 0:
        actual = 0.0

    evidence = src.get("evidence_txn_id")
    if evidence is not None:
        # Coerce pandas/numpy ids (np.int64) and plain int → str; empty → null
        try:
            if isinstance(evidence, bytes):
                evidence = evidence.decode("utf-8", errors="replace")
            elif not isinstance(evidence, str):
                # bool is int subclass — treat as invalid evidence
                if isinstance(evidence, bool):
                    evidence = None
                else:
                    evidence = str(evidence).strip()
            else:
                evidence = evidence.strip()
        except Exception:  # noqa: BLE001
            evidence = None
        if not evidence or evidence.lower() in {"null", "none", "n/a", "nan"}:
            evidence = None
        else:
            import re
            evidence = re.sub(r"[^\w\-]", "", evidence).strip()
            if not evidence:
                evidence = None

    return {
        "status": status,
        "actual": round(float(actual), 2),
        "evidence_txn_id": evidence,
    }


def ensure_filled_answers(
    answers: dict[str, dict[str, Any]],
    *,
    covenant_ids: tuple[str, ...] | list[str],
    scenario_ids: Optional[list[str]] = None,
) -> dict[str, dict[str, Any]]:
    """Fill every scenario×covenant cell so status/actual are never null."""
    scenarios = scenario_ids if scenario_ids is not None else list(answers.keys())
    out: dict[str, dict[str, Any]] = {}
    for sc in scenarios:
        sc_map = answers.get(sc) if isinstance(answers.get(sc), dict) else {}
        out[sc] = {}
        # Template ids only — extra keys (LLM hallucination) fail jury validate
        for cid in covenant_ids:
            out[sc][str(cid)] = ensure_filled_cell(sc_map.get(cid))
    return out


class ExtractedDocument(BaseModel):
    """Cached PDF extraction payload."""

    path: str
    text: str
    page_count: int = 0
    method: str = "pdfplumber"  # pdfplumber | pymupdf | pdftotext
    tables: list[Any] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
