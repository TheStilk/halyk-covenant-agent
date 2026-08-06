"""Corpus-level preflight: what cannot be read, reported before the run starts.

Text-quality scoring of a single extract lives in `pdf_extract.assess_extract_quality`
— this module deliberately does not duplicate it. What it adds is the *page-level*
question that document-level scoring cannot answer (audit finding C2):

    A mostly-textual audit note whose one numeric table is pasted in as a picture
    scores fine as a document, so nothing flags it. `2ed0b2ee4b57.pdf` p.4 holds
    P4's EBITDA one-time table; without it P4/6.1 reports 0.37 instead of 0.33 —
    with confidence 0.95 and no error anywhere.

Running this up front costs one PyMuPDF pass over the corpus (~5s for 200 files,
measured) and buys knowing at second five rather than at minute three that a
covenant is about to be answered from data nobody could read.

The page-level test itself is `pdf_extract.find_blind_pages`, imported here so
that the "what counts as a blind page" threshold has exactly one definition.
"""

from __future__ import annotations

from pathlib import Path

from agent.tools.pdf_extract import find_blind_pages, ocr_toolchain_available

# Binaries the OCR path in metrics.ocr_pdf_images() shells out to.
OCR_BINARIES = ("pdftoppm", "tesseract")


def ocr_toolchain() -> tuple[bool, list[str]]:
    """(available, missing_binaries) for the pdftoppm + tesseract OCR path."""
    import shutil

    missing = [b for b in OCR_BINARIES if not shutil.which(b)]
    return (not missing), missing


def preflight(documents_dir: str | Path) -> dict[str, object]:
    """Scan the corpus before the run and report what cannot be read.

    Returns a dict so callers can log it, print it, or fail on it. Nothing here
    raises: the decision to abort belongs to the caller, but the facts must
    never be silent again.
    """
    docs = sorted(Path(documents_dir).glob("*.pdf"))

    blind: list[dict[str, object]] = []
    for p in docs:
        for page in find_blind_pages(p):
            blind.append({**page, "path": str(p)})

    ocr_ok, missing = ocr_toolchain()
    affected = sorted({Path(str(b["path"])).name for b in blind})

    return {
        "documents_scanned": len(docs),
        "blind_pages": blind,
        "affected_documents": affected,
        "ocr_available": ocr_ok,
        "ocr_missing": missing,
        # Content exists that only OCR can reach, and OCR cannot run.
        "unreadable_content": bool(blind) and not ocr_ok,
    }


def describe_blind_page(entry: dict[str, object]) -> str:
    """One blind page as a human-readable line (pages shown 1-based)."""
    name = Path(str(entry["path"])).name
    page = int(entry["page"]) + 1
    return f"{name} p.{page} (text={entry['chars']} chars, images={entry['images']})"


def format_preflight(report: dict[str, object]) -> str:
    """Human-readable preflight summary for stdout / logs."""
    lines = [
        f"[preflight] documents scanned: {report['documents_scanned']}",
        "[preflight] OCR toolchain: "
        + ("available" if report["ocr_available"] else f"MISSING {report['ocr_missing']}"),
    ]
    blind = report["blind_pages"]
    if blind:
        lines.append(f"[preflight] pages readable only via OCR: {len(blind)}")  # type: ignore[arg-type]
        for entry in blind:  # type: ignore[union-attr]
            lines.append(f"[preflight]     {describe_blind_page(entry)}")
    if report["unreadable_content"]:
        lines.append(
            "[preflight] *** These pages will NOT be read. Any covenant that depends "
            "on them will be answered from incomplete data, confidently and wrongly. "
            "Install poppler-utils + tesseract, or route these documents to a "
            "vision-capable model. ***"
        )
    return "\n".join(lines)


__all__ = [
    "OCR_BINARIES",
    "describe_blind_page",
    "format_preflight",
    "ocr_toolchain",
    "ocr_toolchain_available",
    "preflight",
]
