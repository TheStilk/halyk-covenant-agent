"""Disk-backed PDF extraction cache."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable, Optional

from diskcache import Cache

from agent.config import DOC_CACHE_DIR
from agent.models import ExtractedDocument

_doc_cache: Optional[Cache] = None

# Must change when extract quality logic / backend selection changes,
# so old len(text)>=40 cache entries are not reused silently.
try:
    from agent.tools.pdf_extract import EXTRACT_QUALITY_VERSION as _EQ_VER
except Exception:  # noqa: BLE001
    _EQ_VER = "q0"


def get_cache(directory: str | Path | None = None) -> Cache:
    global _doc_cache
    if _doc_cache is None or directory is not None:
        path = Path(directory) if directory else DOC_CACHE_DIR
        path.mkdir(parents=True, exist_ok=True)
        _doc_cache = Cache(str(path))
    return _doc_cache


def get_file_key(file_path: str | Path) -> str:
    """Content-identity key: hash of the bytes + extract quality version.

    Keyed on content rather than path+mtime so that copying the dataset to
    another machine — which is exactly what happens on competition day — reuses
    the cache instead of silently invalidating all of it (audit finding O4).
    The quality version is still folded in so that improving the extraction
    logic invalidates stale entries rather than reusing an old bad extract.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    digest.update(f":eq={_EQ_VER}".encode())
    return digest.hexdigest()


def read_pdf_with_cache(
    file_path: str | Path,
    extract_fn: Optional[Callable[[str], dict[str, Any]]] = None,
    *,
    force: bool = False,
    cache: Optional[Cache] = None,
) -> ExtractedDocument:
    """Read a PDF, using diskcache when available.

    extract_fn must return a dict compatible with ExtractedDocument fields
    (path, text, page_count, method, tables, meta). If omitted, the default
    extractor from agent.tools.pdf_extract is used.
    """
    file_path = Path(file_path)
    key = get_file_key(file_path)
    cache = cache or get_cache()

    if not force and key in cache:
        payload = cache[key]
        doc: Optional[ExtractedDocument] = None
        if isinstance(payload, ExtractedDocument):
            doc = payload
        elif isinstance(payload, dict):
            try:
                doc = ExtractedDocument(**payload)
            except Exception as exc:  # noqa: BLE001
                print(f"[pdf_cache] bad cached dict for {file_path.name}: {exc}")
                doc = None
        else:
            print(
                f"[pdf_cache] unexpected cached type for {file_path.name}: {type(payload)}"
            )
        if doc is not None:
            # Content-hash is portable; absolute path in payload is not (other machines).
            doc.path = str(file_path)
            return doc

    if extract_fn is None:
        from agent.tools.pdf_extract import extract_pdf

        extract_fn = extract_pdf

    result = extract_fn(str(file_path))
    if isinstance(result, ExtractedDocument):
        doc = result
    else:
        result.setdefault("path", str(file_path))
        doc = ExtractedDocument(**result)

    # Store as plain dict for diskcache robustness across reloads
    cache[key] = doc.model_dump()
    return doc


def clear_cache(directory: str | Path | None = None) -> int:
    """Clear the document cache. Returns number of items removed."""
    cache = get_cache(directory)
    n = len(cache)
    cache.clear()
    return n
