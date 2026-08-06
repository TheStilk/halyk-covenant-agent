"""Quality gates for PDF text extraction (audit finding C2).

The old rule — accept a backend's output as soon as it produced 40 characters —
cannot tell "this document was read" from "this document was destroyed". Two
failure modes it lets through silently, both measured on the public corpus:

1.  A page whose content is an embedded **image**: the text layer is empty but
    the page carries the numbers the covenant depends on. `2ed0b2ee4b57.pdf`
    p.4 holds P4's EBITDA one-time table; without it P4/6.1 reports 0.37
    instead of 0.33 — with confidence 0.95 and no error anywhere.

2.  A backend that returns text with the **Cyrillic stripped out**. `pdftotext`
    does exactly this on this corpus and still clears 40 characters; every
    domain regex is Cyrillic, so metrics silently collapse to zero.

Thresholds are calibrated on the public corpus (843 pages): median 2433 chars
per page, 5th percentile 535, 1st percentile 110. `MIN_CHARS_PER_PAGE = 60`
therefore sits well below any genuinely-extracted page while still catching the
seven image-only pages that exist.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# --- calibrated on agentic-bank-public/documents (843 pages) ----------------
MIN_CHARS_PER_PAGE = 60
MIN_DOC_CHARS = 200
# Fraction of non-whitespace characters that must be letters. Mangled output
# keeps punctuation and digits but loses the alphabet, so this collapses.
MIN_LETTER_RATIO = 0.45
# A document written in Cyrillic that comes back without any is a red flag; we
# only apply it when the document is *expected* to be Cyrillic (see below).
MIN_CYRILLIC_RATIO = 0.15

_CYRILLIC = re.compile(r"[а-яёА-ЯЁ]")
# Markers that survive any encoding and prove we are looking at the real corpus
_STRUCTURAL_MARKERS = re.compile(r"ACC-\d{3,6}|TXN-[A-Z0-9]+-\d+|\d{4}-\d{2}-\d{2}|\$[\d,]+")


@dataclass
class QualityReport:
    """Verdict on one extraction attempt."""

    ok: bool
    chars: int
    page_count: int
    chars_per_page: float
    letter_ratio: float
    cyrillic_ratio: float
    reasons: list[str] = field(default_factory=list)

    def describe(self) -> str:
        head = "OK" if self.ok else "REJECTED"
        return (
            f"{head} chars={self.chars} pages={self.page_count} "
            f"cpp={self.chars_per_page:.0f} letters={self.letter_ratio:.2f} "
            f"cyr={self.cyrillic_ratio:.2f}"
            + (f" — {'; '.join(self.reasons)}" if self.reasons else "")
        )


def assess_text(text: str, page_count: int, *, expect_cyrillic: bool = False) -> QualityReport:
    """Judge whether extracted text is usable, not merely non-empty."""
    stripped = (text or "").strip()
    chars = len(stripped)
    pages = max(1, page_count or 1)
    non_space = sum(1 for ch in stripped if not ch.isspace())
    letters = sum(1 for ch in stripped if ch.isalpha())
    cyrillic = len(_CYRILLIC.findall(stripped))

    letter_ratio = letters / non_space if non_space else 0.0
    cyrillic_ratio = cyrillic / letters if letters else 0.0
    chars_per_page = chars / pages

    reasons: list[str] = []
    if chars < MIN_DOC_CHARS:
        reasons.append(f"only {chars} chars in the whole document")
    if chars_per_page < MIN_CHARS_PER_PAGE:
        reasons.append(f"{chars_per_page:.0f} chars/page < {MIN_CHARS_PER_PAGE}")
    if letter_ratio < MIN_LETTER_RATIO:
        reasons.append(
            f"letters are {letter_ratio:.0%} of non-space chars — text looks mangled"
        )
    if expect_cyrillic and cyrillic_ratio < MIN_CYRILLIC_RATIO:
        reasons.append(
            f"Cyrillic is {cyrillic_ratio:.0%} of letters — the backend dropped it"
        )

    return QualityReport(
        ok=not reasons,
        chars=chars,
        page_count=pages,
        chars_per_page=chars_per_page,
        letter_ratio=letter_ratio,
        cyrillic_ratio=cyrillic_ratio,
        reasons=reasons,
    )


@dataclass
class BlindPage:
    """A page whose content cannot be reached through the text layer."""

    path: str
    page: int  # 0-based
    chars: int
    images: int

    def __str__(self) -> str:
        return f"{Path(self.path).name} p.{self.page + 1} (text={self.chars} chars, images={self.images})"


def find_blind_pages(file_path: str | Path) -> list[BlindPage]:
    """Pages that carry an image but (almost) no text — i.e. OCR-only content.

    This is page-level on purpose. Looking at whole documents misses the case
    that actually costs points here: a mostly-textual audit note whose one
    numeric table is pasted in as a picture.
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        return []

    path = Path(file_path)
    out: list[BlindPage] = []
    try:
        doc = fitz.open(path)
    except Exception:  # noqa: BLE001 — an unopenable file is reported elsewhere
        return []
    try:
        for i, page in enumerate(doc):
            chars = len((page.get_text() or "").strip())
            if chars >= MIN_CHARS_PER_PAGE:
                continue
            images = len(page.get_images(full=True))
            if images:
                out.append(BlindPage(str(path), i, chars, images))
    finally:
        doc.close()
    return out


def ocr_toolchain() -> tuple[bool, list[str]]:
    """(available, missing_binaries) for the pdftoppm + tesseract OCR path."""
    missing = [b for b in ("pdftoppm", "tesseract") if not shutil.which(b)]
    return (not missing), missing


def preflight(documents_dir: str | Path) -> dict[str, object]:
    """Scan the corpus before the run and report what cannot be read.

    Returns a dict so callers can log it, print it, or fail on it. Nothing here
    raises: the decision to abort belongs to the caller, but the facts must
    never be silent again.
    """
    docs = sorted(Path(documents_dir).glob("*.pdf"))
    blind: list[BlindPage] = []
    for p in docs:
        blind.extend(find_blind_pages(p))

    ocr_ok, missing = ocr_toolchain()
    affected = sorted({Path(b.path).name for b in blind})

    return {
        "documents_scanned": len(docs),
        "blind_pages": blind,
        "affected_documents": affected,
        "ocr_available": ocr_ok,
        "ocr_missing": missing,
        # Content exists that only OCR can reach, and OCR cannot run.
        "unreadable_content": bool(blind) and not ocr_ok,
    }


def format_preflight(report: dict[str, object]) -> str:
    """Human-readable preflight summary for stdout / logs."""
    lines = [
        f"[preflight] documents scanned: {report['documents_scanned']}",
        f"[preflight] OCR toolchain: "
        + ("available" if report["ocr_available"] else f"MISSING {report['ocr_missing']}"),
    ]
    blind = report["blind_pages"]  # type: ignore[assignment]
    if blind:
        lines.append(f"[preflight] pages readable only via OCR: {len(blind)}")
        for b in blind:  # type: ignore[union-attr]
            lines.append(f"[preflight]     {b}")
    if report["unreadable_content"]:
        lines.append(
            "[preflight] *** These pages will NOT be read. Any covenant that depends "
            "on them will be answered from incomplete data, confidently and wrongly. "
            "Install poppler-utils + tesseract, or route these documents to a "
            "vision-capable model. ***"
        )
    return "\n".join(lines)
