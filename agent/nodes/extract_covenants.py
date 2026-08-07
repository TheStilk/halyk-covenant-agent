"""Node [3]: Extract financial covenant clauses from loan agreements (per scenario)."""

from __future__ import annotations

from typing import Any

from agent.config import COVENANT_IDS, covenant_ids_for_scenario
from agent.models import DocType
from agent.state import AgentState
from agent.tools.covenants import covenants_to_dict, extract_covenants
from agent.tools.ledger import scenario_to_account, transactions_for_account
from agent.tools.pdf_cache import read_pdf_with_cache


def extract_covenants_for_all(state: AgentState) -> dict[str, Any]:
    """Extract covenants for every scenario; store in documents bag.

    Clause ids come from submission_template.json (per scenario when they differ).
    """
    docs_by_scenario = state.get("docs_by_scenario") or {}
    doc_index = state.get("doc_index") or []
    account_to_scenario = state.get("account_to_scenario") or {}
    sc_to_acc = scenario_to_account(account_to_scenario)

    covenants_by_scenario: dict[str, dict[str, str]] = {}
    path_to_text = _index_texts(doc_index)

    def _merge_clauses(dst: dict[str, str], src: dict[str, str]) -> None:
        """Union by covenant id; keep longer text when both present."""
        for cid, text in src.items():
            if not text:
                continue
            if cid not in dst or len(text) > len(dst[cid]):
                dst[cid] = text

    for scenario_id, by_type in docs_by_scenario.items():
        expected_ids = covenant_ids_for_scenario(scenario_id)
        expected_n = len(expected_ids)
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
            extracted = extract_covenants(
                text, source_path=path, covenant_ids=expected_ids
            )
            as_dict = covenants_to_dict(extracted)
            # Merge across multiple loan docs (do not replace-by-count)
            _merge_clauses(best, as_dict)
            if len(best) >= expected_n:
                # Still scan remaining loans for any missing ids / longer text
                continue
        covenants_by_scenario[scenario_id] = best
        print(
            f"[covenants] {scenario_id} "
            f"account={sc_to_acc.get(scenario_id)} "
            f"clauses={list(best.keys())}"
        )

    # Scenarios with no classified loan: scan all loan agreements
    scenario_ids = state.get("scenario_ids") or list(sc_to_acc.keys())
    missing = [s for s in scenario_ids if not covenants_by_scenario.get(s)]
    orphan_global: dict[str, str] = {}
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
            sc = d.get("scenario_id")
            ids = covenant_ids_for_scenario(sc) if sc else COVENANT_IDS
            extracted = extract_covenants(text, source_path=path, covenant_ids=ids)
            as_dict = covenants_to_dict(extracted)
            if not as_dict:
                continue
            if sc:
                if not covenants_by_scenario.get(sc):
                    covenants_by_scenario[sc] = as_dict
                    print(f"[covenants] recovered {sc} from {path}")
                else:
                    _merge_clauses(covenants_by_scenario[sc], as_dict)
            else:
                # Unscoped loan: collect for global fill of still-empty scenarios
                _merge_clauses(orphan_global, as_dict)
                print(
                    f"[covenants] orphan loan (no scenario_id) from {path}: "
                    f"clauses={list(as_dict.keys())}"
                )

    # Apply orphan/global clauses only to scenarios still missing any clause
    if orphan_global:
        still_missing = [s for s in scenario_ids if not covenants_by_scenario.get(s)]
        for sc in still_missing:
            # Filter to template ids for that scenario
            want = set(covenant_ids_for_scenario(sc))
            filled = {cid: t for cid, t in orphan_global.items() if cid in want}
            if filled:
                covenants_by_scenario[sc] = filled
                print(
                    f"[covenants] applied orphan/global clauses to {sc}: "
                    f"{list(filled.keys())}"
                )

    documents = {
        "covenants_by_scenario": covenants_by_scenario,
        "path_to_text_keys": list(path_to_text.keys()),
    }

    n_full = sum(
        1
        for sc, c in covenants_by_scenario.items()
        if len(c) >= len(covenant_ids_for_scenario(sc))
    )
    print(
        f"[covenants] scenarios_with_full_template_clauses="
        f"{n_full}/{len(scenario_ids)}"
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
