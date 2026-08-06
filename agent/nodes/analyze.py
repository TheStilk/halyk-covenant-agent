"""Covenant analysis node: formula engine + Qwen 3.8-Max structured output + reflection."""

from __future__ import annotations

import json
from typing import Any, Optional

from agent.config import CONFIDENCE_THRESHOLD, COVENANT_IDS, QWEN_API_KEY
from agent.models import CovenantVerdict, FinalCovenantResult
from agent.prompts.system import COVENANT_USER_PROMPT, REFLECTION_PROMPT, SYSTEM_PROMPT
from agent.state import AgentState
from agent.tools.formula_engine import evaluate_covenant
from agent.tools.metrics import ScenarioMetrics, extract_metrics_for_state


def extract_metrics_node(state: AgentState) -> dict[str, Any]:
    """Extract metrics for all scenarios; store under documents['metrics_by_scenario']."""
    account_to_scenario = state.get("account_to_scenario") or {}
    from agent.tools.ledger import scenario_to_account, transactions_for_account

    sc_to_acc = scenario_to_account(account_to_scenario)
    ledger = state.get("ledger")
    docs_by_scenario = state.get("docs_by_scenario") or {}
    doc_index = state.get("doc_index") or []
    scenario_ids = state.get("scenario_ids") or list(sc_to_acc.keys())

    metrics_by_scenario: dict[str, dict] = {}
    for sc in scenario_ids:
        acc = sc_to_acc.get(sc, "")
        txns = transactions_for_account(ledger, acc) if ledger is not None and acc else []
        m = extract_metrics_for_state(
            scenario_id=sc,
            account_id=acc,
            transactions=txns,
            docs_by_scenario=docs_by_scenario,
            doc_index=doc_index,
        )
        metrics_by_scenario[sc] = {
            "summary": m.summary_for_llm(),
            "aggregates": {
                "revenue": m.revenue,
                "opex": m.opex,
                "ebitda": m.ebitda,
                "adjusted_ebitda": m.adjusted_ebitda,
                "capex": m.capex,
                "lease": m.lease,
                "interest": m.interest,
                "tax": m.tax,
                "utilities": m.utilities,
                "insurance": m.insurance,
                "payroll": m.payroll,
                "related_party_payments": m.related_party_payments,
            },
            "related_parties": [
                {"name": p.name, "pct": p.ownership_pct, "is_related": p.is_related}
                for p in m.related_parties
            ],
            "reclassifications": [
                {
                    "txn_id": r.txn_id,
                    "amount": r.amount,
                    "from": r.from_category,
                    "to": r.to_category,
                    "counterparty": r.counterparty,
                }
                for r in m.reclassifications
            ],
            "cutoffs": [{"txn_id": c.txn_id, "action": c.action} for c in m.cutoffs],
            "meta": m.meta,
            "_object": m,  # kept in-memory for analyze (not JSON-serialized to disk)
        }
        print(
            f"[metrics] {sc} rev={m.revenue:.2f} opex={m.opex:.2f} ebitda={m.ebitda:.2f} "
            f"capex={m.capex:.2f} rp={m.related_party_payments:.2f} "
            f"reclass={len(m.reclassifications)} cutoffs={len(m.cutoffs)}"
        )

    documents = dict(state.get("documents") or {})
    documents["metrics_by_scenario"] = metrics_by_scenario
    return {
        "documents": documents,
        "stage": "metrics_extracted",
        "error": None,
    }


def analyze_all_covenants_node(state: AgentState) -> dict[str, Any]:
    """Analyze 6.1/6.2/6.3 for every scenario (sequential; parallel later)."""
    documents = state.get("documents") or {}
    covenants_by_sc = documents.get("covenants_by_scenario") or {}
    metrics_by_sc = documents.get("metrics_by_scenario") or {}
    scenario_ids = state.get("scenario_ids") or list(covenants_by_sc.keys())
    use_llm = bool(QWEN_API_KEY) and state.get("stage") != "force_deterministic"

    results: list[FinalCovenantResult] = []
    for sc in scenario_ids:
        cov_map: dict[str, str] = covenants_by_sc.get(sc) or {}
        m_wrap = metrics_by_sc.get(sc) or {}
        metrics_obj: Optional[ScenarioMetrics] = m_wrap.get("_object")
        if metrics_obj is None:
            print(f"[analyze] no metrics for {sc}, skip")
            continue
        account_id = metrics_obj.account_id
        for cid in COVENANT_IDS:
            text = cov_map.get(cid, "")
            if not text:
                print(f"[analyze] missing covenant text {sc}/{cid}")
                continue
            verdict = analyze_one_covenant(
                scenario_id=sc,
                account_id=account_id,
                covenant_id=cid,
                covenant_text=text,
                metrics=metrics_obj,
                use_llm=use_llm,
            )
            results.append(
                FinalCovenantResult(
                    scenario_id=sc,
                    covenant_id=cid,
                    status=verdict.status,
                    actual=round(abs(float(verdict.actual)), 2),
                    evidence_txn_id=verdict.evidence_txn_id,
                    confidence=verdict.confidence,
                    reasoning=verdict.reasoning,
                )
            )
            print(
                f"[analyze] {sc}/{cid}: {verdict.status} actual={verdict.actual:.2f} "
                f"ev={verdict.evidence_txn_id} conf={verdict.confidence:.2f}"
            )

    return {
        "results": results,
        "stage": "analyzed",
        "error": None,
    }


def analyze_one_covenant(
    *,
    scenario_id: str,
    account_id: str,
    covenant_id: str,
    covenant_text: str,
    metrics: ScenarioMetrics,
    use_llm: bool = True,
) -> CovenantVerdict:
    """Analyze a single covenant: deterministic first, optional Qwen refine/reflect."""
    # 1) Deterministic formula engine
    det = evaluate_covenant(covenant_text, metrics, covenant_id=covenant_id)

    # 2) If LLM unavailable or high-confidence deterministic → return
    if not use_llm or not QWEN_API_KEY:
        return det

    if det.confidence >= CONFIDENCE_THRESHOLD:
        return det

    # 3) Qwen structured analysis for low-confidence cases
    try:
        llm_verdict = _qwen_analyze(
            scenario_id=scenario_id,
            account_id=account_id,
            covenant_id=covenant_id,
            covenant_text=covenant_text,
            metrics=metrics,
        )
        # Prefer LLM if higher confidence; else keep deterministic if close
        if llm_verdict.confidence >= det.confidence:
            chosen = llm_verdict
        else:
            chosen = det
            chosen.reasoning = f"DET: {det.reasoning} | LLM: {llm_verdict.reasoning}"
    except Exception as exc:  # noqa: BLE001
        print(f"[analyze] Qwen failed {scenario_id}/{covenant_id}: {exc}")
        chosen = det

    # 4) Reflection if still low confidence
    if chosen.confidence < CONFIDENCE_THRESHOLD and QWEN_API_KEY:
        try:
            chosen = _qwen_reflect(
                previous=chosen,
                covenant_text=covenant_text,
                metrics=metrics,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[analyze] reflection failed {scenario_id}/{covenant_id}: {exc}")

    return chosen


def analyze_one_covenant_deterministic(
    covenant_text: str,
    metrics: ScenarioMetrics,
    covenant_id: str = "",
) -> CovenantVerdict:
    return evaluate_covenant(covenant_text, metrics, covenant_id=covenant_id)


def _qwen_analyze(
    *,
    scenario_id: str,
    account_id: str,
    covenant_id: str,
    covenant_text: str,
    metrics: ScenarioMetrics,
) -> CovenantVerdict:
    from agent.tools.llm import get_qwen, invoke_with_system

    llm = get_qwen(temperature=0.0)
    structured = llm.with_structured_output(CovenantVerdict)

    # Provide compact transaction list
    tx_lines = []
    for t in metrics.transactions:
        if t.excluded:
            continue
        tx_lines.append(
            f"{t.txn_id}|{t.amount:.2f}|{t.currency}|{t.category}|{t.counterparty[:40]}|{t.description[:60]}"
            f"{'|RELATED' if t.is_related_party else ''}"
        )
    user = COVENANT_USER_PROMPT.format(
        scenario_id=scenario_id,
        account_id=account_id,
        covenant_id=covenant_id,
        covenant_text=covenant_text,
        metrics=metrics.summary_for_llm(),
        transactions="\n".join(tx_lines[:80]),
    )
    # Prefer structured; fallback to system+user parse
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        result = structured.invoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user)]
        )
        if isinstance(result, CovenantVerdict):
            return result
        return CovenantVerdict.model_validate(result)
    except Exception:
        raw = invoke_with_system(llm, SYSTEM_PROMPT, user, use_cache_control=True)
        content = raw.content if hasattr(raw, "content") else str(raw)
        return _parse_verdict_json(content)


def _qwen_reflect(
    *,
    previous: CovenantVerdict,
    covenant_text: str,
    metrics: ScenarioMetrics,
) -> CovenantVerdict:
    from agent.tools.llm import get_qwen
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = get_qwen(temperature=0.0)
    structured = llm.with_structured_output(CovenantVerdict)
    prompt = REFLECTION_PROMPT.format(
        previous_json=previous.model_dump_json(),
        covenant_text=covenant_text,
        data=metrics.summary_for_llm(),
    )
    result = structured.invoke(
        [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
    )
    if isinstance(result, CovenantVerdict):
        return result
    return CovenantVerdict.model_validate(result)


def _parse_verdict_json(content: str) -> CovenantVerdict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    data = json.loads(text)
    return CovenantVerdict.model_validate(data)


def collect_results_node(state: AgentState) -> dict[str, Any]:
    """Assemble submission.json payload (not written yet — runner writes)."""
    results: list[FinalCovenantResult] = state.get("results") or []
    template_scenarios = state.get("scenario_ids") or []

    answers: dict[str, dict[str, Any]] = {}
    for sc in template_scenarios:
        answers[sc] = {
            cid: {"status": None, "actual": None, "evidence_txn_id": None}
            for cid in COVENANT_IDS
        }

    for r in results:
        if r.scenario_id not in answers:
            continue
        answers[r.scenario_id][r.covenant_id] = r.to_submission_cell()

    documents = dict(state.get("documents") or {})
    documents["submission_answers"] = answers
    return {
        "documents": documents,
        "stage": "collected",
        "error": None,
    }
