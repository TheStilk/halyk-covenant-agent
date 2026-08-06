"""Extract the financial-covenant clauses named by the submission template.

Which article holds them and which clause numbers exist are read off the
template, not hardcoded: the private template may number them differently
(audit finding C4).
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional

from agent.models import CovenantText
from agent.tools.template import all_covenant_ids, article_numbers


@lru_cache(maxsize=8)
def _article_start_re(articles: tuple[str, ...]) -> re.Pattern[str]:
    """Header of the covenant article body, e.g. "Статья 6 — Финансовые ковенанты".

    The title text after the number is optional: an agreement is free to call
    the section anything, and on the private set it probably will.
    """
    alt = "|".join(re.escape(a) for a in articles)
    return re.compile(
        rf"(?:Статья|Article|ARTICLE|Раздел)\s+(?:{alt})\b"
        rf"(?:\s*[—\-–:]\s*[^\n]{{0,80}})?",
        re.IGNORECASE,
    )


@lru_cache(maxsize=8)
def _article_end_re(articles: tuple[str, ...]) -> re.Pattern[str]:
    """Header of any article numbered above the covenant article(s)."""
    highest = max((int(a) for a in articles if a.isdigit()), default=6)
    following = "|".join(str(n) for n in range(highest + 1, highest + 4))
    return re.compile(
        rf"(?:Статья|Article|ARTICLE|Раздел)\s+(?:{following})\b",
        re.IGNORECASE,
    )


@lru_cache(maxsize=8)
def _clause_header_re(clause_ids: tuple[str, ...]) -> re.Pattern[str]:
    """Clause headers for exactly the ids the template asks about.

    Matches "Пункт 6.1", "Clause 6.1", "6.1." and "6.1)" — but only for ids
    present in the template, so body cross-references to other clauses do not
    open a new section.
    """
    alt = "|".join(re.escape(cid) for cid in sorted(clause_ids, key=len, reverse=True))
    return re.compile(
        rf"(?:"
        rf"(?:Пункт|Clause|п\.)\s*({alt})(?![\d.])"
        rf"|(?<![\d.])({alt})(?![\d.])\s*[—\-–.:)]\s+"
        rf")",
        re.IGNORECASE,
    )

# Page furniture to strip from extracted text
_PAGE_NOISE = re.compile(
    r"^\s*\d{1,3}\s*$"  # lone page numbers
    r"|^\s*[—\-–_]{3,}\s*$",
    re.MULTILINE,
)


def extract_article6_block(
    text: str,
    *,
    clause_ids: tuple[str, ...] | None = None,
) -> Optional[str]:
    """Return the covenant-article body text, or None if not found."""
    ids = clause_ids or all_covenant_ids()
    articles = article_numbers()

    # Prefer the *last* match of the article header — the TOC entry comes first
    matches = list(_article_start_re(articles).finditer(text))
    if matches:
        start = matches[-1].start()
    else:
        # Fallback: start at the first clause header the template asks about.
        # This is the path that has to work when the private agreement titles
        # its sections differently from "Статья 6 — Финансовые ковенанты".
        first = _clause_header_re(ids).search(text)
        if not first:
            return None
        start = first.start()

    rest = text[start:]
    end_m = _article_end_re(articles).search(rest)
    # Skip end match if it appears too early (within header line)
    if end_m and end_m.start() > 40:
        block = rest[: end_m.start()]
    else:
        # take a generous window
        block = rest[:6000]

    block = _PAGE_NOISE.sub("", block)
    block = re.sub(r"\n{3,}", "\n\n", block)
    return block.strip()


def split_covenant_clauses(
    article6_text: str,
    *,
    clause_ids: tuple[str, ...] | None = None,
) -> dict[str, str]:
    """Split the covenant-article body into per-clause full texts."""
    result: dict[str, str] = {}
    if not article6_text:
        return result

    ids = clause_ids or all_covenant_ids()

    # Find all clause header positions
    headers: list[tuple[int, str]] = []
    for m in _clause_header_re(ids).finditer(article6_text):
        cid = next(g for g in m.groups() if g)
        if cid not in ids:
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
    clause_ids: tuple[str, ...] | None = None,
) -> dict[str, CovenantText]:
    """Full pipeline: find the covenant article → split clauses → CovenantText map."""
    ids = clause_ids or all_covenant_ids()
    block = extract_article6_block(text, clause_ids=ids)
    if not block:
        return {}

    clauses = split_covenant_clauses(block, clause_ids=ids)
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
