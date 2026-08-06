"""Node [2]: Classify & route all PDFs to scenarios."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from tqdm import tqdm

from agent.config import DOCUMENTS_DIR
from agent.models import DocType
from agent.state import AgentState
from agent.tools.classifier import classify_document
from agent.tools.pdf_cache import read_pdf_with_cache


def classify_docs_node(state: AgentState) -> dict[str, Any]:
    """Read every PDF (cached), classify, bind to scenario via account_id."""
    account_to_scenario = state.get("account_to_scenario") or {}
    docs_dir = DOCUMENTS_DIR
    if not docs_dir.exists():
        return {
            "stage": "docs_classified",
            "error": f"Documents dir missing: {docs_dir}",
            "doc_index": [],
            "docs_by_scenario": {},
        }

    pdfs = sorted(docs_dir.glob("*.pdf"))
    doc_index: list[dict] = []
    docs_by_scenario: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    # Also index by company name for docs without account_id
    company_to_scenario = _build_company_to_scenario(pdfs, account_to_scenario)

    type_counts: dict[str, int] = defaultdict(int)

    for pdf_path in tqdm(pdfs, desc="classify PDFs", unit="pdf"):
        try:
            extracted = read_pdf_with_cache(pdf_path)
            text = extracted.text or ""
        except Exception as exc:  # noqa: BLE001
            print(f"[classify] extract failed {pdf_path.name}: {exc}")
            continue

        classification = classify_document(
            text,
            path=str(pdf_path),
            account_to_scenario=account_to_scenario,
        )

        # Fallback: bind via company name if no account
        if not classification.scenario_id and classification.company_name:
            classification.scenario_id = company_to_scenario.get(
                classification.company_name.lower()
            )

        entry = classification.model_dump()
        entry["page_count"] = extracted.page_count
        entry["extract_method"] = extracted.method
        entry["text_len"] = len(text)
        doc_index.append(entry)
        type_counts[classification.doc_type.value] += 1

        if classification.scenario_id and classification.doc_type != DocType.JUNK:
            docs_by_scenario[classification.scenario_id][
                classification.doc_type.value
            ].append(str(pdf_path))

    # Materialize nested defaultdicts
    docs_by_scenario_plain = {
        sc: {dt: paths for dt, paths in types.items()}
        for sc, types in docs_by_scenario.items()
    }

    print(f"[classify] total={len(doc_index)} by_type={dict(type_counts)}")
    print(f"[classify] scenarios_with_docs={sorted(docs_by_scenario_plain.keys())}")

    return {
        "doc_index": doc_index,
        "docs_by_scenario": docs_by_scenario_plain,
        "stage": "docs_classified",
        "error": None,
    }


def _build_company_to_scenario(
    pdfs: list[Path],
    account_to_scenario: dict[str, str],
) -> dict[str, str]:
    """First pass over KYC/loan docs that have both company + account."""
    mapping: dict[str, str] = {}
    # Lightweight: only scan files that look like KYC or loan by name is impossible;
    # we'll fill this during the main loop instead. Placeholder for future.
    _ = pdfs
    _ = account_to_scenario
    return mapping


def bind_companies_from_index(doc_index: list[dict]) -> dict[str, str]:
    """Derive company_name → scenario_id from classified docs that have both."""
    out: dict[str, str] = {}
    for d in doc_index:
        company = d.get("company_name")
        scenario = d.get("scenario_id")
        if company and scenario:
            out[company.lower()] = scenario
    return out
