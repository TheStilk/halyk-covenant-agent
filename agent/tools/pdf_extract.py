"""PDF text extraction with multi-backend fallback chain.

Order: pdfplumber → pymupdf (fitz) → pdftotext (poppler CLI).
Acceptance is quality-based (not mere len(text) >= 40).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent.models import ExtractedDocument

# Bump when quality thresholds change (paired with pdf_cache key version).
EXTRACT_QUALITY_VERSION = "q2"

_CYR_RE = re.compile(r"[А-Яа-яЁё]")
_LAT_RE = re.compile(r"[A-Za-z]")
_ALNUM_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]")
# "Meaningful" tokens: letters/digits/currency punctuation, not pure whitespace/noise
_MEANINGFUL_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё$%.,;:()/\-]")

_MARKER_CHECKS: list[tuple[str, re.Pattern[str]]] = [
    ("ACC", re.compile(r"\bACC[-\s]?\d{3,}", re.I)),
    ("TXN", re.compile(r"\bTXN[-\s]?", re.I)),
    ("MONEY", re.compile(r"\$\s*\d|USD\b|доллар", re.I)),
    ("ARTICLE", re.compile(r"Статья\s+\d|Article\s+\d", re.I)),
]


@dataclass
class ExtractQuality:
    """Quality assessment for a single extract attempt."""

    ok: bool
    score: float
    reasons: list[str] = field(default_factory=list)
    meaningful_len: int = 0
    cyrillic_ratio: float = 0.0
    letter_count: int = 0
    marker_hits: int = 0
    markers: dict[str, bool] = field(default_factory=dict)
    version: str = EXTRACT_QUALITY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_extract_quality(text: str | None) -> ExtractQuality:
    """Score extracted PDF text for domain usefulness.

    Replaces the old ``len(text) >= 40`` gate with:
    - minimum meaningful character count
    - Cyrillic share among letters (RU loan docs)
    - domain markers: ACC- / TXN- / $ / Статья|Article
    """
    raw = text or ""
    stripped = raw.strip()
    reasons: list[str] = []

    meaningful_len = len(_MEANINGFUL_RE.findall(stripped))
    cyr_n = len(_CYR_RE.findall(stripped))
    lat_n = len(_LAT_RE.findall(stripped))
    letter_count = cyr_n + lat_n
    cyr_ratio = (cyr_n / letter_count) if letter_count else 0.0

    markers = {name: bool(pat.search(stripped)) for name, pat in _MARKER_CHECKS}
    marker_hits = sum(1 for v in markers.values() if v)

    # --- score (0..1) ---
    score = 0.0
    if meaningful_len >= 200:
        score += 0.35
    elif meaningful_len >= 80:
        score += 0.25
    elif meaningful_len >= 40:
        score += 0.10
    else:
        reasons.append("too_short")

    if letter_count >= 200 and cyr_ratio >= 0.15:
        score += 0.25
    elif letter_count >= 100 and cyr_ratio >= 0.10:
        score += 0.18
    elif letter_count >= 150:
        # mostly Latin but long enough to be real text
        score += 0.15
    elif letter_count < 40:
        reasons.append("few_letters")

    if marker_hits >= 3:
        score += 0.40
    elif marker_hits == 2:
        score += 0.30
    elif marker_hits == 1:
        score += 0.15
    else:
        reasons.append("no_domain_markers")

    # Density: reject binary/garbage pages full of control chars
    total = max(len(stripped), 1)
    alnum = len(_ALNUM_RE.findall(stripped))
    density = alnum / total
    if density < 0.25 and meaningful_len < 200:
        score *= 0.5
        reasons.append("low_alnum_density")

    score = max(0.0, min(1.0, score))

    # Accept if clearly useful for covenant/ledger pipeline
    ok = False
    if meaningful_len >= 80 and marker_hits >= 1:
        ok = True
    elif meaningful_len >= 150 and cyr_ratio >= 0.15 and letter_count >= 80:
        ok = True
    elif meaningful_len >= 250 and letter_count >= 200:
        # long clean extract without markers (some notes/KYC)
        ok = True
    elif meaningful_len >= 40 and marker_hits >= 2:
        ok = True

    if ok:
        reasons = [r for r in reasons if r not in {"no_domain_markers"}]
        if not reasons:
            reasons = ["ok"]

    return ExtractQuality(
        ok=ok,
        score=round(score, 3),
        reasons=reasons,
        meaningful_len=meaningful_len,
        cyrillic_ratio=round(cyr_ratio, 3),
        letter_count=letter_count,
        marker_hits=marker_hits,
        markers=markers,
    )


def find_blind_pages(path: Path) -> list[dict[str, Any]]:
    """Pages that carry an image but (almost) no text — content the quality
    score above cannot see, because it scores the *document*, not the page.

    This is the gap that let P4's EBITDA one-time table (a $251,338.94 line
    item pasted in as a picture on an otherwise text-rich, quality-OK
    document) through silently: the document-level score passes easily on the
    surrounding pages, so nothing here flags that page 4 specifically is
    unreadable without OCR. `ocr_pdf_images()` in metrics.py is the only path
    to that content, and it returns "" with no warning when pdftoppm/tesseract
    are missing.
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        return []
    try:
        doc = fitz.open(path)
    except Exception:  # noqa: BLE001 — reported via the normal error paths
        return []
    blind: list[dict[str, Any]] = []
    try:
        for i, page in enumerate(doc):
            chars = len((page.get_text() or "").strip())
            if chars >= 60:
                continue
            images = len(page.get_images(full=True))
            if images:
                blind.append({"page": i, "chars": chars, "images": images})
    finally:
        doc.close()
    return blind


def ocr_toolchain_available() -> bool:
    return bool(shutil.which("pdftoppm") and shutil.which("tesseract"))


def extract_pdf(file_path: str) -> dict[str, Any]:
    """Extract text (and simple tables) from a PDF. Returns dict for caching.

    Tries backends in order; accepts the first quality-OK result. If none pass,
    returns the highest-scoring attempt with an explicit degraded warning
    (never a silent empty string when some text was produced).
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    blind_pages = find_blind_pages(path)
    ocr_ok = ocr_toolchain_available() if blind_pages else True

    errors: list[str] = []
    candidates: list[tuple[float, dict[str, Any]]] = []

    for name, fn in (
        ("pdfplumber", _extract_pdfplumber),
        ("pymupdf", _extract_pymupdf),
        ("pdftotext", _extract_pdftotext),
    ):
        try:
            result = fn(path)
            if not result:
                errors.append(f"{name}: empty result")
                continue
            text = result.get("text") or ""
            quality = assess_extract_quality(text)
            result["path"] = str(path)
            result.setdefault("method", name)
            result.setdefault("tables", [])
            result.setdefault("meta", {})
            result["meta"]["quality"] = quality.to_dict()
            result["meta"]["quality_version"] = EXTRACT_QUALITY_VERSION
            result["meta"]["extract_errors"] = list(errors)
            result["meta"]["blind_pages"] = blind_pages
            result["meta"]["ocr_needed_but_unavailable"] = bool(blind_pages) and not ocr_ok

            if quality.ok:
                result["meta"]["quality_accepted"] = True
                if errors:
                    result["meta"]["fallback_used"] = True
                if blind_pages and not ocr_ok:
                    print(
                        f"[pdf_extract] WARNING {path.name} reads fine overall but "
                        f"page(s) {[b['page'] + 1 for b in blind_pages]} are image-only "
                        f"and pdftoppm/tesseract are not installed — that content is "
                        f"invisible to every downstream regex, silently."
                    )
                return result

            errors.append(
                f"{name}: low quality score={quality.score:.2f} "
                f"reasons={quality.reasons} markers={quality.marker_hits} "
                f"mlen={quality.meaningful_len}"
            )
            candidates.append((quality.score, result))
        except Exception as exc:  # noqa: BLE001 — full fallback chain
            errors.append(f"{name}: {exc}")

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        best = candidates[0][1]
        best["meta"] = dict(best.get("meta") or {})
        best["meta"]["quality_accepted"] = False
        best["meta"]["extract_errors"] = errors
        best["meta"]["degraded"] = True
        best["meta"]["blind_pages"] = blind_pages
        best["meta"]["ocr_needed_but_unavailable"] = bool(blind_pages) and not ocr_ok
        method = best.get("method") or "unknown"
        if not str(method).endswith("+degraded"):
            best["method"] = f"{method}+degraded"
        q = (best.get("meta") or {}).get("quality") or {}
        print(
            f"[pdf_extract] WARNING degraded extract {path.name}: "
            f"method={best['method']} score={q.get('score')} "
            f"reasons={q.get('reasons')} tried={errors}"
        )
        return best

    # All backends failed hard — explicit empty + diagnostics (not silent)
    print(
        f"[pdf_extract] WARNING all backends failed for {path.name}: {errors}"
    )
    return {
        "path": str(path),
        "text": "",
        "page_count": 0,
        "method": "failed",
        "tables": [],
        "meta": {
            "extract_errors": errors,
            "quality_accepted": False,
            "degraded": True,
            "quality_version": EXTRACT_QUALITY_VERSION,
            "blind_pages": blind_pages,
            "ocr_needed_but_unavailable": bool(blind_pages) and not ocr_ok,
            "quality": ExtractQuality(
                ok=False,
                score=0.0,
                reasons=["all_backends_failed"],
            ).to_dict(),
        },
    }


def extract_pdf_document(file_path: str) -> ExtractedDocument:
    return ExtractedDocument(**extract_pdf(file_path))


# Documents are not necessarily PDFs. The public corpus hides a .txt stating the
# dataset's own rule ("only the current edition is in force") and a .csv of
# server logs; the private corpus may put something load-bearing in either
# (audit finding V3).
SUPPORTED_SUFFIXES = (".pdf", ".txt", ".csv", ".md", ".json")

# Soft OOM guards (battle: huge reports / mislabeled binaries)
_MAX_TABLE_PAGES = 20
_MAX_TEXT_FILE_BYTES = 8 * 1024 * 1024  # 8 MiB


def extract_text_file(file_path: str) -> dict[str, Any]:
    """Read a plain-text-ish document, trying the encodings this corpus uses."""
    path = Path(file_path)
    errors: list[str] = []
    try:
        size = path.stat().st_size
    except OSError as exc:
        return {
            "path": str(path),
            "text": "",
            "page_count": 0,
            "method": "failed",
            "tables": [],
            "meta": {"extract_errors": [str(exc)], "unreadable": True},
        }
    if size > _MAX_TEXT_FILE_BYTES:
        msg = f"text file too large ({size} bytes > {_MAX_TEXT_FILE_BYTES}); skip"
        print(f"[extract] {path.name}: {msg}")
        return {
            "path": str(path),
            "text": "",
            "page_count": 0,
            "method": "failed",
            "tables": [],
            "meta": {
                "extract_errors": [msg],
                "unreadable": True,
                "size_bytes": size,
            },
        }

    for encoding in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            text = path.read_text(encoding=encoding)
        except (UnicodeDecodeError, LookupError) as exc:
            errors.append(f"{encoding}: {exc}")
            continue
        # latin-1 never fails on bytes — reject if almost no printable text (binary as .txt)
        if encoding == "latin-1":
            sample = text[:4000]
            printable = sum(1 for c in sample if c.isprintable() or c in "\n\r\t")
            if sample and printable / max(len(sample), 1) < 0.7:
                errors.append("latin-1: low printable ratio (likely binary)")
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
        for i, page in enumerate(pdf.pages):
            t = page.extract_text() or ""
            pages_text.append(t)
            # Tables only on first N pages — full-doc table walk OOMs on huge PDFs
            if i >= _MAX_TABLE_PAGES:
                continue
            try:
                page_tables = page.extract_tables() or []
                for tbl in page_tables:
                    tables.append(tbl)
            except Exception as exc:  # noqa: BLE001
                print(f"[pdf_extract] table extraction warning: {exc}")
    return {
        "text": "\n\n".join(pages_text),
        "page_count": page_count,
        "method": "pdfplumber",
        "tables": tables,
        "meta": {
            "table_pages_scanned": min(page_count, _MAX_TABLE_PAGES),
        },
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

# ACC- / АСС- with 3–6 digits (not hard-limited to ACC-7xxx / 4 digits only)
_ACCOUNT_RE = re.compile(
    r"\b(?:ACC|АСС)[-\s]?(\d{3,6})\b",
    re.IGNORECASE,
)
_ACCOUNT_SPACED_RE = re.compile(
    r"(?:A\s*C\s*C|А\s*С\s*С)\s*[-–—]?\s*((?:\d\s*){3,6})",
    re.IGNORECASE,
)
# Optional: "Account ID: 7801" / "счёт № 7801" near ACC context
_ACCOUNT_LOOSE_RE = re.compile(
    r"(?:account\s*(?:id|no\.?|number)?|сч[её]т(?:\s*№)?|номер\s*сч[её]та)"
    r"\s*[:#]?\s*(?:ACC[-\s]?)?(\d{3,6})\b",
    re.IGNORECASE,
)

# Legal entity suffixes (EN + KZ/RU common forms) — not only JSC
_LEGAL_SUFFIX = (
    r"(?:"
    r"JSC|LLC|LLP|L\.?\s*L\.?\s*P\.?|Inc\.?|Ltd\.?|Corp\.?|PLC|GmbH|"
    r"АО|ТОО|ИП|КТОО"
    r")"
)
_COMPANY_RE = re.compile(
    rf"\b([A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9\-\s&'.]{{2,60}}?\s+{_LEGAL_SUFFIX})\b",
)


def normalize_account_id(raw_digits_or_acc: str) -> str:
    """Normalize to ACC-XXXX form."""
    s = str(raw_digits_or_acc).strip().upper().replace("АСС", "ACC")
    s = re.sub(r"\s+", "", s)
    m = re.search(r"(?:ACC-?)?(\d{3,6})", s)
    if not m:
        return s if s.startswith("ACC-") else f"ACC-{s}"
    return f"ACC-{m.group(1)}"


def is_noise_account_id(account_id: str) -> bool:
    """Heuristic: open-set noise accounts are ACC-9xxx; not limited to ACC-7 borrowers."""
    m = re.match(r"ACC-(\d+)$", str(account_id).upper())
    if not m:
        return False
    return m.group(1).startswith("9")


def prefer_borrower_account(
    accounts: list[str],
    *,
    account_to_scenario: dict[str, str] | None = None,
) -> str | None:
    """Pick best account_id: mapped borrower > non-noise > first seen."""
    if not accounts:
        return None
    if account_to_scenario:
        mapped = [a for a in accounts if a in account_to_scenario]
        if mapped:
            return mapped[0]
    non_noise = [a for a in accounts if not is_noise_account_id(a)]
    return (non_noise or accounts)[0]


def find_account_ids(text: str) -> list[str]:
    """Extract ACC-XXXX identifiers (3–6 digits; spaced/Cyrillic АСС forms)."""
    found: list[str] = []
    seen: set[str] = set()

    def _add(digits: str) -> None:
        digits = re.sub(r"\s+", "", digits)
        if not (3 <= len(digits) <= 6 and digits.isdigit()):
            return
        acc = f"ACC-{digits}"
        if acc not in seen:
            seen.add(acc)
            found.append(acc)

    for m in _ACCOUNT_RE.finditer(text):
        _add(m.group(1))

    for m in _ACCOUNT_SPACED_RE.finditer(text):
        _add(m.group(1))

    for m in _ACCOUNT_LOOSE_RE.finditer(text):
        _add(m.group(1))

    return found


def find_company_names(text: str) -> list[str]:
    """Heuristic company-name finder (JSC/LLC/LLP/ТОО/АО/…)."""
    found: list[str] = []
    seen: set[str] = set()
    for m in _COMPANY_RE.finditer(text):
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        if len(name) < 5 or len(name) > 90:
            continue
        lower = name.lower()
        if any(
            x in lower
            for x in (
                "halyk bank",
                "настоящий",
                "договор",
                "joint stock",
                "limited liability",
            )
        ):
            continue
        # Drop pure-suffix noise
        if re.fullmatch(rf"{_LEGAL_SUFFIX}", name, flags=re.I):
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
