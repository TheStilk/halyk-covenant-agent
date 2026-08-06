"""Extract Article 6 financial covenants (clauses 6.1, 6.2, 6.3) from loan agreements."""

from __future__ import annotations

import re
from typing import Optional

from agent.config import COVENANT_IDS
from agent.models import CovenantText

# Start of Article 6 body (not TOC entry)
_ARTICLE6_START = re.compile(
    r"(?:"
    r"Статья\s+6\s*[—\-–:]\s*Финансовые\s+ковенанты"
    r"|Article\s+6\s*[—\-–:]\s*(?:Financial\s+)?Covenants?"
    r"|ARTICLE\s+6\s*[—\-–:]\s*(?:FINANCIAL\s+)?COVENANTS?"
    r")",
    re.IGNORECASE,
)

# End of Article 6 — next article or major section
_ARTICLE6_END = re.compile(
    r"(?:"
    r"Статья\s+7\b"
    r"|Article\s+7\b"
    r"|ARTICLE\s+7\b"
    r"|Статья\s+8\b"
    r")",
    re.IGNORECASE,
)

# Individual clause headers: "Пункт 6.1", "6.1.", "Clause 6.1"
_CLAUSE_HEADER = re.compile(
    r"(?:"
    r"Пункт\s+(6\.[123])\b"
    r"|Clause\s+(6\.[123])\b"
    r"|(?<!\d)(6\.[123])\s*[—\-–.:)]\s+"
    r")",
    re.IGNORECASE,
)

# Page furniture to strip from extracted text
_PAGE_NOISE = re.compile(
    r"^\s*\d{1,3}\s*$"  # lone page numbers
    r"|^\s*[—\-–_]{3,}\s*$",
    re.MULTILINE,
)


def extract_article6_block(text: str) -> Optional[str]:
    """Return the Article 6 body text, or None if not found."""
    # Prefer the *last* match of Article 6 header — TOC appears earlier
    matches = list(_ARTICLE6_START.finditer(text))
    if not matches:
        # Fallback: start at first "Пункт 6.1" if present
        m61 = re.search(r"Пункт\s+6\.1\b", text, re.I)
        if not m61:
            return None
        start = m61.start()
    else:
        start = matches[-1].start()

    rest = text[start:]
    end_m = _ARTICLE6_END.search(rest)
    # Skip end match if it appears too early (within header line)
    if end_m and end_m.start() > 40:
        block = rest[: end_m.start()]
    else:
        # take a generous window
        block = rest[:6000]

    block = _PAGE_NOISE.sub("", block)
    block = re.sub(r"\n{3,}", "\n\n", block)
    return block.strip()


def split_covenant_clauses(article6_text: str) -> dict[str, str]:
    """Split Article 6 body into 6.1 / 6.2 / 6.3 full-text clauses."""
    result: dict[str, str] = {}
    if not article6_text:
        return result

    # Find all clause header positions
    headers: list[tuple[int, str]] = []
    for m in _CLAUSE_HEADER.finditer(article6_text):
        cid = next(g for g in m.groups() if g)
        # normalize to "6.1" form
        cid = cid if cid.startswith("6.") else f"6.{cid}"
        if cid not in COVENANT_IDS:
            continue
        # avoid double-hit for same id
        if any(h[1] == cid for h in headers):
            continue
        headers.append((m.start(), cid))

    if not headers:
        return result

    headers.sort(key=lambda x: x[0])
    for i, (pos, cid) in enumerate(headers):
        end = headers[i + 1][0] if i + 1 < len(headers) else len(article6_text)
        clause = article6_text[pos:end].strip()
        clause = re.sub(r"[ \t]+", " ", clause)
        clause = re.sub(r"\n{3,}", "\n\n", clause)
        # Drop trailing page numbers / whitespace
        clause = clause.strip()
        if clause:
            result[cid] = clause

    return result


def extract_covenants(
    text: str,
    *,
    source_path: Optional[str] = None,
) -> dict[str, CovenantText]:
    """Full pipeline: find Article 6 → split 6.1/6.2/6.3 → CovenantText map."""
    block = extract_article6_block(text)
    if not block:
        return {}

    clauses = split_covenant_clauses(block)
    out: dict[str, CovenantText] = {}
    for cid, clause_text in clauses.items():
        out[cid] = CovenantText(
            covenant_id=cid,
            text=clause_text,
            source_path=source_path,
        )
    return out


def covenants_to_dict(covenants: dict[str, CovenantText]) -> dict[str, str]:
    """Convert to simple id → text dict for AgentState."""
    return {cid: c.text for cid, c in covenants.items()}
