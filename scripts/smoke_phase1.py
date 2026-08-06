#!/usr/bin/env python3
"""Smoke tests for Phase-1 foundation (no LLM keys required)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_ledger_mapping() -> None:
    from agent.tools.ledger import (
        build_account_to_scenario,
        filter_scenario_accounts,
        load_ledger,
        scenario_from_txn_id,
        scenario_to_account,
    )

    assert scenario_from_txn_id("TXN-P1-0007") == "P1"
    assert scenario_from_txn_id("TXN-P10-0062") == "P10"
    assert scenario_from_txn_id("TXN-B4-0039") == "B4"

    ledger = load_ledger()
    assert len(ledger) > 0
    full = build_account_to_scenario(ledger)
    scenarios = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "B1", "B4"]
    borrowers = filter_scenario_accounts(full, scenarios)
    inv = scenario_to_account(borrowers)

    expected = {
        "ACC-7801": "P1",
        "ACC-7802": "P2",
        "ACC-7803": "P3",
        "ACC-7804": "P4",
        "ACC-7805": "P5",
        "ACC-7806": "P6",
        "ACC-7807": "P7",
        "ACC-7808": "P8",
        "ACC-7809": "P9",
        "ACC-7810": "P10",
        "ACC-7201": "B1",
        "ACC-7204": "B4",
    }
    for acc, sc in expected.items():
        assert borrowers.get(acc) == sc, f"{acc}: got {borrowers.get(acc)}, want {sc}"
        assert inv.get(sc) == acc, f"{sc}: got {inv.get(sc)}, want {acc}"
    print("[OK] ledger mapping")


def test_pdf_cache_and_extract() -> None:
    from agent.tools.pdf_cache import get_file_key, read_pdf_with_cache
    from agent.config import DOCUMENTS_DIR

    pdf = next(DOCUMENTS_DIR.glob("*.pdf"))
    k1 = get_file_key(pdf)
    k2 = get_file_key(pdf)
    assert k1 == k2

    doc1 = read_pdf_with_cache(pdf)
    doc2 = read_pdf_with_cache(pdf)  # cache hit
    assert doc1.text == doc2.text
    assert len(doc1.text) > 0
    print(f"[OK] pdf cache/extract ({pdf.name}, method={doc1.method}, chars={len(doc1.text)})")


def test_classifier_and_covenants() -> None:
    from agent.config import DOCUMENTS_DIR
    from agent.models import DocType
    from agent.tools.classifier import classify_document
    from agent.tools.covenants import extract_covenants
    from agent.tools.pdf_cache import read_pdf_with_cache

    # Known loan agreement from dataset exploration
    loan_path = DOCUMENTS_DIR / "1d262694c308.pdf"
    assert loan_path.exists()
    text = read_pdf_with_cache(loan_path).text
    clf = classify_document(text, path=str(loan_path))
    assert clf.doc_type == DocType.LOAN_AGREEMENT, clf
    assert clf.account_id == "ACC-7805", clf.account_id

    cov = extract_covenants(text, source_path=str(loan_path))
    assert set(cov.keys()) == {"6.1", "6.2", "6.3"}, list(cov.keys())
    assert "EBITDA" in cov["6.1"].text or "Выручк" in cov["6.1"].text
    assert len(cov["6.1"].text) > 50
    print(f"[OK] classify+covenants loan ({loan_path.name})")
    for cid, c in cov.items():
        print(f"     {cid}: {c.text[:100].replace(chr(10), ' ')}...")


def test_notes_and_kyc() -> None:
    from agent.config import DOCUMENTS_DIR
    from agent.models import DocType
    from agent.tools.classifier import classify_document
    from agent.tools.pdf_cache import read_pdf_with_cache

    notes = DOCUMENTS_DIR / "2ed0b2ee4b57.pdf"
    text = read_pdf_with_cache(notes).text
    clf = classify_document(text, path=str(notes))
    assert clf.doc_type == DocType.FINANCIAL_NOTES, clf
    print(f"[OK] financial_notes ({notes.name}, account={clf.account_id})")

    kyc = DOCUMENTS_DIR / "07e1a2a0275d.pdf"
    text = read_pdf_with_cache(kyc).text
    clf = classify_document(text, path=str(kyc))
    assert clf.doc_type == DocType.KYC, clf
    print(f"[OK] kyc ({kyc.name}, company={clf.company_name})")

    junk = DOCUMENTS_DIR / "028324997d3c.pdf"
    text = read_pdf_with_cache(junk).text
    clf = classify_document(text, path=str(junk))
    assert clf.doc_type == DocType.JUNK, clf
    print(f"[OK] junk ({junk.name})")


def test_foundation_graph() -> None:
    from agent.graph import run_foundation

    state = run_foundation()
    assert state.get("stage") == "covenants_extracted"
    mapping = state.get("account_to_scenario") or {}
    assert mapping.get("ACC-7801") == "P1"
    covenants = (state.get("documents") or {}).get("covenants_by_scenario") or {}
    # We expect most scenarios to have Article 6
    with_full = [s for s, c in covenants.items() if len(c) >= 3]
    print(f"[OK] foundation graph: full_article6={sorted(with_full)}")
    assert len(with_full) >= 8, f"expected ≥8 scenarios with full Article 6, got {with_full}"


def main() -> int:
    test_ledger_mapping()
    test_pdf_cache_and_extract()
    test_classifier_and_covenants()
    test_notes_and_kyc()
    test_foundation_graph()
    print("\n=== ALL PHASE-1 SMOKE TESTS PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
