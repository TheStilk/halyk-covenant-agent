"""PDF text extraction with multi-backend fallback chain.

Order: pdfplumber → pymupdf (fitz) → pdftotext (poppler CLI).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from agent.models import ExtractedDocument


def extract_pdf(file_path: str) -> dict[str, Any]:
    """Extract text (and simple tables) from a PDF. Returns dict for caching."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    errors: list[str] = []

    for name, fn in (
        ("pdfplumber", _extract_pdfplumber),
        ("pymupdf", _extract_pymupdf),
        ("pdftotext", _extract_pdftotext),
    ):
        try:
            result = fn(path)
            if result and result.get("text") and len(result["text"].strip()) >= 40:
                result["path"] = str(path)
                result.setdefault("method", name)
                result.setdefault("tables", [])
                result.setdefault("meta", {})
                result["meta"]["extract_errors"] = errors
                return result
            errors.append(f"{name}: empty/short text")
        except Exception as exc:  # noqa: BLE001 — we want full fallback chain
            errors.append(f"{name}: {exc}")

    # Last resort: return whatever we can (may be empty)
    return {
        "path": str(path),
        "text": "",
        "page_count": 0,
        "method": "failed",
        "tables": [],
        "meta": {"extract_errors": errors},
    }


def extract_pdf_document(file_path: str) -> ExtractedDocument:
    return ExtractedDocument(**extract_pdf(file_path))


def _extract_pdfplumber(path: Path) -> dict[str, Any]:
    import pdfplumber

    pages_text: list[str] = []
    tables: list[Any] = []
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            t = page.extract_text() or ""
            pages_text.append(t)
            try:
                page_tables = page.extract_tables() or []
                for tbl in page_tables:
                    tables.append(tbl)
            except Exception:  # noqa: BLE001
                pass
    return {
        "text": "\n\n".join(pages_text),
        "page_count": page_count,
        "method": "pdfplumber",
        "tables": tables,
        "meta": {},
    }


def _extract_pymupdf(path: Path) -> dict[str, Any]:
    import fitz  # pymupdf

    doc = fitz.open(path)
    pages_text: list[str] = []
    try:
        for page in doc:
            pages_text.append(page.get_text("text") or "")
        page_count = doc.page_count
    finally:
        doc.close()
    return {
        "text": "\n\n".join(pages_text),
        "page_count": page_count,
        "method": "pymupdf",
        "tables": [],
        "meta": {},
    }


def _extract_pdftotext(path: Path) -> dict[str, Any]:
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext not on PATH")
    proc = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0 and not proc.stdout:
        raise RuntimeError(proc.stderr.strip() or f"pdftotext exit {proc.returncode}")
    text = proc.stdout or ""
    # rough page count via form feed
    page_count = max(1, text.count("\x0c") + (1 if text.strip() else 0))
    return {
        "text": text.replace("\x0c", "\n\n"),
        "page_count": page_count,
        "method": "pdftotext",
        "tables": [],
        "meta": {},
    }


# ---------------------------------------------------------------------------
# Helpers used by classifiers / extractors
# ---------------------------------------------------------------------------

_ACCOUNT_RE = re.compile(r"\bACC[-\s]?(\d{4})\b", re.IGNORECASE)
_ACCOUNT_SPACED_RE = re.compile(
    r"A\s*C\s*C\s*[-–—]?\s*((?:\d\s*){4})",
    re.IGNORECASE,
)
_COMPANY_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9\-\s&']+?\s+JSC)\b",
)


def find_account_ids(text: str) -> list[str]:
    """Extract ACC-XXXX identifiers from free text (handles spaced OCR forms)."""
    found: list[str] = []
    seen: set[str] = set()

    for m in _ACCOUNT_RE.finditer(text):
        acc = f"ACC-{m.group(1)}"
        if acc not in seen:
            seen.add(acc)
            found.append(acc)

    for m in _ACCOUNT_SPACED_RE.finditer(text):
        digits = re.sub(r"\s+", "", m.group(1))
        if len(digits) == 4:
            acc = f"ACC-{digits}"
            if acc not in seen:
                seen.add(acc)
                found.append(acc)

    return found


def find_company_names(text: str) -> list[str]:
    """Heuristic company-name finder (… JSC)."""
    found: list[str] = []
    seen: set[str] = set()
    for m in _COMPANY_RE.finditer(text):
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        # Filter out noise phrases
        if len(name) < 8 or len(name) > 80:
            continue
        lower = name.lower()
        if any(x in lower for x in ("halyk bank", "настоящий", "договор")):
            continue
        if name not in seen:
            seen.add(name)
            found.append(name)
    return found


def normalize_whitespace(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
