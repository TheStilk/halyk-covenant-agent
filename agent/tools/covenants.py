"""Extract financial covenant clauses from loan agreements (template-driven).

Covenant ids come from submission_template.json (via agent.config), not a
hardcoded 6.1/6.2/6.3 list. Block discovery:
  1) clause numbers from template (Пункт/Clause/N.M)
  2) fallback: Статья N / Article N (N = major number of template ids)
"""

from __future__ import annotations

import re
from typing import Iterable, Optional, Sequence

from agent.config import COVENANT_IDS
from agent.models import CovenantText


def _article_major(covenant_ids: Sequence[str]) -> str:
    """Infer article number from ids like 6.1 → '6'. Default '6'."""
    majors: list[str] = []
    for cid in covenant_ids:
        m = re.match(r"^(\d+)\.", str(cid).strip())
        if m and m.group(1) not in majors:
            majors.append(m.group(1))
    return majors[0] if majors else "6"


def _clause_header_re(covenant_ids: Sequence[str]) -> re.Pattern[str]:
    """Build header matcher for the given covenant ids (order-independent)."""
    ids = [str(c).strip() for c in covenant_ids if str(c).strip()]
    if not ids:
        ids = list(COVENANT_IDS)
    # Longer first so 6.10 wins over 6.1
    alts = "|".join(re.escape(c) for c in sorted(ids, key=len, reverse=True))
    return re.compile(
        rf"(?:"
        rf"Пункт\s+({alts})\b"
        rf"|Clause\s+({alts})\b"
        rf"|(?<!\d)({alts})\s*[—\-–.:)]\s+"
        rf")",
        re.IGNORECASE,
    )


def _article_start_re(major: str) -> re.Pattern[str]:
    m = re.escape(major)
    return re.compile(
        rf"(?:"
        rf"Статья\s+{m}\s*[—\-–:]\s*Финансовые\s+ковенанты"
        rf"|Article\s+{m}\s*[—\-–:]\s*(?:Financial\s+)?Covenants?"
        rf"|ARTICLE\s+{m}\s*[—\-–:]\s*(?:FINANCIAL\s+)?COVENANTS?"
        rf"|Статья\s+{m}\b"
        rf"|Article\s+{m}\b"
        rf")",
        re.IGNORECASE,
    )


def _article_end_re(major: str) -> re.Pattern[str]:
    """Next article after the covenants article (major+1 .. major+2)."""
    try:
        n = int(major)
        nxt = [str(n + 1), str(n + 2)]
    except ValueError:
        nxt = ["7", "8"]
    alts = "|".join(re.escape(x) for x in nxt)
    return re.compile(
        rf"(?:"
        rf"Статья\s+(?:{alts})\b"
        rf"|Article\s+(?:{alts})\b"
        rf"|ARTICLE\s+(?:{alts})\b"
        rf")",
        re.IGNORECASE,
    )


# Page furniture to strip from extracted text
_PAGE_NOISE = re.compile(
    r"^\s*\d{1,3}\s*$"  # lone page numbers
    r"|^\s*[—\-–_]{3,}\s*$",
    re.MULTILINE,
)


def extract_covenant_block(
    text: str,
    covenant_ids: Sequence[str] | None = None,
) -> Optional[str]:
    """Return the covenant section body, or None if not found.

    Strategy:
      1. Locate the first template clause header (Пункт/Clause/id) — preferred
      2. Else locate Статья N / Article N financial covenants header
      3. Slice until next article or a generous window
    """
    ids = tuple(covenant_ids) if covenant_ids is not None else COVENANT_IDS
    major = _article_major(ids)
    header_re = _clause_header_re(ids)
    article_re = _article_start_re(major)
    end_re = _article_end_re(major)

    start: Optional[int] = None

    # --- 1) clause numbers from template ---
    clause_hits = list(header_re.finditer(text))
    if clause_hits:
        first_clause = min(clause_hits, key=lambda m: m.start())
        # Prefer article header just before the first clause when present
        article_hits = [m for m in article_re.finditer(text) if m.start() <= first_clause.start()]
        if article_hits:
            start = article_hits[-1].start()
        else:
            start = first_clause.start()

    # --- 2) fallback: Статья N / Article N ---
    if start is None:
        matches = list(article_re.finditer(text))
        if matches:
            # Prefer last match (TOC often appears earlier)
            start = matches[-1].start()

    if start is None:
        return None

    rest = text[start:]
    end_m = end_re.search(rest)
    if end_m and end_m.start() > 40:
        block = rest[: end_m.start()]
    else:
        block = rest[:8000]

    block = _PAGE_NOISE.sub("", block)
    block = re.sub(r"\n{3,}", "\n\n", block)
    return block.strip() or None


# Back-compat alias
def extract_article6_block(text: str) -> Optional[str]:
    return extract_covenant_block(text, COVENANT_IDS)


def split_covenant_clauses(
    block_text: str,
    covenant_ids: Sequence[str] | None = None,
) -> dict[str, str]:
    """Split covenant section body into per-id full-text clauses."""
    result: dict[str, str] = {}
    if not block_text:
        return result

    ids = tuple(covenant_ids) if covenant_ids is not None else COVENANT_IDS
    id_set = set(ids)
    header_re = _clause_header_re(ids)

    headers: list[tuple[int, str]] = []
    for m in header_re.finditer(block_text):
        cid = next(g for g in m.groups() if g)
        cid = str(cid).strip()
        if cid not in id_set:
            continue
        if any(h[1] == cid for h in headers):
            continue
        headers.append((m.start(), cid))

    if not headers:
        return result

    headers.sort(key=lambda x: x[0])
    for i, (pos, cid) in enumerate(headers):
        end = headers[i + 1][0] if i + 1 < len(headers) else len(block_text)
        clause = block_text[pos:end].strip()
        clause = re.sub(r"[ \t]+", " ", clause)
        clause = re.sub(r"\n{3,}", "\n\n", clause)
        clause = clause.strip()
        if clause:
            result[cid] = clause

    return result


def extract_covenants(
    text: str,
    *,
    source_path: Optional[str] = None,
    covenant_ids: Sequence[str] | None = None,
) -> dict[str, CovenantText]:
    """Find covenant block → split by template ids → CovenantText map."""
    ids = tuple(covenant_ids) if covenant_ids is not None else COVENANT_IDS
    block = extract_covenant_block(text, ids)
    if not block:
        return {}

    clauses = split_covenant_clauses(block, ids)
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


def expected_covenant_count(covenant_ids: Iterable[str] | None = None) -> int:
    ids = list(covenant_ids) if covenant_ids is not None else list(COVENANT_IDS)
    return len(ids)
