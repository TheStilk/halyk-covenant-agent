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
from agent.tools.extraction_quality import assess_text, find_blind_pages


def extract_pdf(file_path: str) -> dict[str, Any]:
    """Extract text (and simple tables) from a PDF. Returns dict for caching.

    Every backend is tried and the *best* result wins, rather than the first one
    clearing a length threshold. That ordering matters: `pdftotext` returns
    Cyrillic-stripped text on this corpus which used to be accepted as soon as
    it exceeded 40 characters, silently replacing a good extraction with one
    that matches none of the domain patterns (audit finding C2).
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    errors: list[str] = []
    candidates: list[tuple[float, str, dict[str, Any]]] = []

    for name, fn in (
        ("pdfplumber", _extract_pdfplumber),
        ("pymupdf", _extract_pymupdf),
        ("pdftotext", _extract_pdftotext),
    ):
        try:
            result = fn(path)
        except Exception as exc:  # noqa: BLE001 — we want the full fallback chain
            errors.append(f"{name}: {exc}")
            continue

        if not result or not result.get("text"):
            errors.append(f"{name}: no text")
            continue

        text = result["text"]
        report = assess_text(text, result.get("page_count", 0))
        if not report.ok:
            errors.append(f"{name}: {report.describe()}")
        # Rank by usable letters, not raw length: whitespace and punctuation are
        # exactly what a mangled extraction retains.
        letters = sum(1 for ch in text if ch.isalpha())
        candidates.append((letters, name, result))

        # A clean read from the highest-fidelity backend needs no alternatives.
        if report.ok and name == "pdfplumber":
            break

    # Content that lives in page images is invisible to every text backend.
    blind = find_blind_pages(path)

    if candidates:
        candidates.sort(key=lambda c: c[0], reverse=True)
        _, name, result = candidates[0]
        result["path"] = str(path)
        result.setdefault("method", name)
        result.setdefault("tables", [])
        result.setdefault("meta", {})
        result["meta"]["extract_errors"] = errors
        result["meta"]["blind_pages"] = [b.page for b in blind]
        result["meta"]["quality"] = assess_text(
            result["text"], result.get("page_count", 0)
        ).describe()
        return result

    # Nothing worked at all. Say so loudly rather than returning "" as if the
    # document were simply blank.
    print(
        f"[extract] UNREADABLE {path.name}: no backend produced usable text; "
        f"attempts: {errors or 'none'}"
        + (f"; {len(blind)} image-only page(s)" if blind else "")
    )
    return {
        "path": str(path),
        "text": "",
        "page_count": 0,
        "method": "failed",
        "tables": [],
        "meta": {
            "extract_errors": errors,
            "blind_pages": [b.page for b in blind],
            "unreadable": True,
        },
    }


def extract_pdf_document(file_path: str) -> ExtractedDocument:
    return ExtractedDocument(**extract_pdf(file_path))


# Documents are not necessarily PDFs. The public corpus hides a .txt stating the
# dataset's own rule ("only the current edition is in force") and a .csv of
# server logs; the private corpus may put something load-bearing in either
# (audit finding V3).
SUPPORTED_SUFFIXES = (".pdf", ".txt", ".csv", ".md", ".json")


def extract_text_file(file_path: str) -> dict[str, Any]:
    """Read a plain-text-ish document, trying the encodings this corpus uses."""
    path = Path(file_path)
    errors: list[str] = []
    for encoding in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            text = path.read_text(encoding=encoding)
        except (UnicodeDecodeError, LookupError) as exc:
            errors.append(f"{encoding}: {exc}")
            continue
        return {
            "path": str(path),
            "text": text,
            "page_count": max(1, text.count("\f") + 1),
            "method": f"text:{encoding}",
            "tables": [],
            "meta": {"extract_errors": errors},
        }

    print(f"[extract] UNREADABLE {path.name}: no encoding worked; attempts: {errors}")
    return {
        "path": str(path),
        "text": "",
        "page_count": 0,
        "method": "failed",
        "tables": [],
        "meta": {"extract_errors": errors, "unreadable": True},
    }


def extract_document(file_path: str) -> dict[str, Any]:
    """Extract any supported document type, dispatching on suffix."""
    if Path(file_path).suffix.lower() == ".pdf":
        return extract_pdf(file_path)
    return extract_text_file(file_path)


def iter_documents(documents_dir: str | Path) -> list[Path]:
    """All documents we know how to read, in stable order."""
    root = Path(documents_dir)
    found: list[Path] = []
    for suffix in SUPPORTED_SUFFIXES:
        found.extend(root.glob(f"*{suffix}"))
    return sorted(found)


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

# Account ids are ACC-7801 on the public set, but the digit count is a property
# of that dataset, not of the task (audit finding C4).
_ACCOUNT_RE = re.compile(r"\bACC[-\s]?(\d{3,6})\b", re.IGNORECASE)
_ACCOUNT_SPACED_RE = re.compile(
    r"A\s*C\s*C\s*[-–—]?\s*((?:\d\s*){3,6})",
    re.IGNORECASE,
)
# Legal-form suffixes seen in the corpus plus the ones a Kazakh dataset can
# reasonably use. Matching only "JSC" would drop every LLP/TOO counterparty.
_LEGAL_FORMS = (
    "JSC", "LLP", "LLC", "Ltd", "PLC", "Inc", "GmbH", "SA", "NV", "AG",
    "АО", "ТОО", "ООО", "ЗАО", "ПАО",
)
_COMPANY_RE = re.compile(
    r"\b([A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9\-\s&'\"«»]+?\s+(?:"
    + "|".join(re.escape(f) for f in _LEGAL_FORMS)
    + r"))\b",
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
        if 3 <= len(digits) <= 6:
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
