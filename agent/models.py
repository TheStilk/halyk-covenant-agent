"""Pydantic models for structured agent I/O."""

from __future__ import annotations

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
    """Structured output from Qwen for a single covenant analysis."""

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
        return {
            "status": self.status,
            "actual": round(abs(float(self.actual)), 2),
            "evidence_txn_id": self.evidence_txn_id,
        }


class ExtractedDocument(BaseModel):
    """Cached PDF extraction payload."""

    path: str
    text: str
    page_count: int = 0
    method: str = "pdfplumber"  # pdfplumber | pymupdf | pdftotext
    tables: list[Any] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
