"""Node [3]: Extract Article 6 clauses from loan agreements (per scenario)."""

from __future__ import annotations

from typing import Any

from agent.models import DocType
from agent.state import AgentState
from agent.tools.covenants import covenants_to_dict, extract_covenants
from agent.tools.ledger import scenario_to_account, transactions_for_account
from agent.tools.pdf_cache import read_pdf_with_cache


def extract_covenants_for_all(state: AgentState) -> dict[str, Any]:
    """Extract covenants for every scenario; store in docs_by_scenario side channel.

    Phase 1 stores a global map scenario → covenants in state under a temporary
    key by merging into documents inventory. Per-borrower fan-out (Phase 2/3)
    will pick covenants when processing each scenario.
    """
    docs_by_scenario = state.get("docs_by_scenario") or {}
    doc_index = state.get("doc_index") or []
    account_to_scenario = state.get("account_to_scenario") or {}
    sc_to_acc = scenario_to_account(account_to_scenario)

    covenants_by_scenario: dict[str, dict[str, str]] = {}
    path_to_text = _index_texts(doc_index)

    for scenario_id, by_type in docs_by_scenario.items():
        loan_paths = by_type.get(DocType.LOAN_AGREEMENT.value, [])
        best: dict[str, str] = {}
        for path in loan_paths:
            text = path_to_text.get(path)
            if text is None:
                try:
                    text = read_pdf_with_cache(path).text
                except Exception as exc:  # noqa: BLE001
                    print(f"[covenants] read fail {path}: {exc}")
                    continue
            extracted = extract_covenants(text, source_path=path)
            as_dict = covenants_to_dict(extracted)
            # Prefer the loan that yields all 3 clauses
            if len(as_dict) > len(best):
                best = as_dict
            if len(best) >= 3:
                break
        covenants_by_scenario[scenario_id] = best
        print(
            f"[covenants] {scenario_id} "
            f"account={sc_to_acc.get(scenario_id)} "
            f"clauses={list(best.keys())}"
        )

    # Also try scenarios that have no classified loan yet: scan all loans
    scenario_ids = state.get("scenario_ids") or list(sc_to_acc.keys())
    missing = [s for s in scenario_ids if not covenants_by_scenario.get(s)]
    if missing:
        print(f"[covenants] missing loan for {missing}; scanning all loan_agreements")
        all_loans = [
            d for d in doc_index if d.get("doc_type") == DocType.LOAN_AGREEMENT.value
        ]
        for d in all_loans:
            path = d["path"]
            text = path_to_text.get(path)
            if text is None:
                try:
                    text = read_pdf_with_cache(path).text
                except Exception:  # noqa: BLE001
                    continue
            extracted = extract_covenants(text, source_path=path)
            as_dict = covenants_to_dict(extracted)
            if not as_dict:
                continue
            sc = d.get("scenario_id")
            if sc and not covenants_by_scenario.get(sc):
                covenants_by_scenario[sc] = as_dict
                print(f"[covenants] recovered {sc} from {path}")

    # Attach into state via a documents global bag
    documents = {
        "covenants_by_scenario": covenants_by_scenario,
        "path_to_text_keys": list(path_to_text.keys()),
    }

    n_full = sum(1 for c in covenants_by_scenario.values() if len(c) >= 3)
    print(
        f"[covenants] scenarios_with_full_article6={n_full}/"
        f"{len(scenario_ids)}"
    )

    return {
        "documents": documents,
        "stage": "covenants_extracted",
        "error": None,
    }


def prepare_borrower(state: AgentState) -> dict[str, Any]:
    """Hydrate per-borrower fields when scenario_id is already set (fan-out)."""
    scenario_id = state.get("scenario_id")
    if not scenario_id:
        return {"stage": "borrower_ready", "error": "scenario_id not set"}

    account_to_scenario = state.get("account_to_scenario") or {}
    sc_to_acc = scenario_to_account(account_to_scenario)
    account_id = state.get("account_id") or sc_to_acc.get(scenario_id, "")

    docs_bag = state.get("documents") or {}
    covenants = (docs_bag.get("covenants_by_scenario") or {}).get(scenario_id, {})

    ledger = state.get("ledger")
    txns = transactions_for_account(ledger, account_id) if ledger is not None else []

    return {
        "account_id": account_id,
        "covenants": covenants,
        "transactions": txns,
        "metrics": state.get("metrics") or {},
        "stage": "borrower_ready",
        "error": None,
    }


def _index_texts(doc_index: list[dict]) -> dict[str, str]:
    """Load text for non-junk docs from cache (already populated by classify)."""
    out: dict[str, str] = {}
    for d in doc_index:
        if d.get("doc_type") == DocType.JUNK.value:
            continue
        path = d.get("path")
        if not path:
            continue
        try:
            out[path] = read_pdf_with_cache(path).text
        except Exception:  # noqa: BLE001
            continue
    return out
