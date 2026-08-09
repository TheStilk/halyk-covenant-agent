"""Covenant analysis node: formula engine + optional LLM formula reader / reflection."""

from __future__ import annotations

import json
from typing import Any, Optional

from agent.config import (
    CONFIDENCE_THRESHOLD,
    COVENANT_IDS,
    FORMULA_READER_PREFER_DET_ON_MISMATCH,
    LLM_FORMULA_READER_ONLY_UNKNOWN,
    USE_LLM_FORMULA_READER,
    covenant_ids_for_scenario,
)
from agent.models import (
    CovenantVerdict,
    FinalCovenantResult,
    ensure_filled_answers,
    ensure_filled_cell,
)
from agent.prompts.system import COVENANT_USER_PROMPT, REFLECTION_PROMPT, SYSTEM_PROMPT
from agent.state import AgentState
from agent.tools.formula_compute import compute_from_formula_spec, specs_agree
from agent.tools.formula_engine import evaluate_covenant, is_unknown_formula_verdict
from agent.tools.formula_reader import try_read_formula_spec
from agent.tools.llm import is_llm_available
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
        try:
            m = extract_metrics_for_state(
                scenario_id=sc,
                account_id=acc,
                transactions=txns,
                docs_by_scenario=docs_by_scenario,
                doc_index=doc_index,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[metrics] ERROR extracting metrics for scenario {sc}: {exc}")
            m = ScenarioMetrics(scenario_id=sc, account_id=acc, meta={"error": str(exc)})
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
    """Analyze every covenant cell for every scenario (never leave cells empty)."""
    documents = state.get("documents") or {}
    covenants_by_sc = documents.get("covenants_by_scenario") or {}
    metrics_by_sc = documents.get("metrics_by_scenario") or {}
    scenario_ids = state.get("scenario_ids") or list(
        dict.fromkeys(list(covenants_by_sc.keys()) + list(metrics_by_sc.keys()))
    )
    use_llm = is_llm_available() and state.get("stage") != "force_deterministic"

    results: list[FinalCovenantResult] = []
    unknown_formula_cells: list[str] = []
    llm_fallback_cells: list[str] = []
    low_confidence_cells: list[str] = []
    formula_reader_cells: list[str] = []
    formula_mismatch_cells: list[str] = []

    for sc in scenario_ids:
        cov_map: dict[str, str] = covenants_by_sc.get(sc) or {}
        m_wrap = metrics_by_sc.get(sc) or {}
        metrics_obj: Optional[ScenarioMetrics] = m_wrap.get("_object")
        account_id = metrics_obj.account_id if metrics_obj is not None else ""
        cov_ids = covenant_ids_for_scenario(sc)

        for cid in cov_ids:
            text = (cov_map.get(cid) or "").strip()
            if metrics_obj is None:
                # Best-effort placeholder: cannot prove compliance without metrics
                print(f"[analyze] no metrics for {sc}/{cid} → best-effort BREACH/0.0")
                results.append(
                    FinalCovenantResult(
                        scenario_id=sc,
                        covenant_id=cid,
                        status="BREACH",
                        actual=0.0,
                        evidence_txn_id=None,
                        confidence=0.0,
                        reasoning="best-effort: missing scenario metrics",
                    )
                )
                continue
            if not text:
                print(f"[analyze] missing covenant text {sc}/{cid} → evaluate empty")
            cell_key = f"{sc}/{cid}"
            # Isolate per-cell failures so one bad PDF/bug cannot kill phase3
            try:
                verdict = analyze_one_covenant(
                    scenario_id=sc,
                    account_id=account_id,
                    covenant_id=cid,
                    covenant_text=text,
                    metrics=metrics_obj,
                    use_llm=use_llm and bool(text),
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[analyze] CELL FAIL {cell_key}: {exc} → BREACH/0.0")
                results.append(
                    FinalCovenantResult(
                        scenario_id=sc,
                        covenant_id=cid,
                        status="BREACH",
                        actual=0.0,
                        evidence_txn_id=None,
                        confidence=0.0,
                        reasoning=f"best-effort: analyze exception: {exc}",
                    )
                )
                continue

            reason_l = (verdict.reasoning or "").lower()
            if is_unknown_formula_verdict(verdict) or "unknown" in reason_l:
                unknown_formula_cells.append(cell_key)
            if "[llm" in reason_l or "llm_fallback" in reason_l or "llm_reflect" in reason_l:
                llm_fallback_cells.append(cell_key)
            if "formula_spec" in reason_l or "formula_reader" in reason_l:
                formula_reader_cells.append(cell_key)
            if "mismatch" in reason_l or "cross-check" in reason_l:
                formula_mismatch_cells.append(cell_key)
            if verdict.confidence < CONFIDENCE_THRESHOLD:
                low_confidence_cells.append(
                    f"{cell_key} conf={verdict.confidence:.2f}"
                )

            cell = ensure_filled_cell(
                {
                    "status": verdict.status,
                    "actual": verdict.actual,
                    "evidence_txn_id": verdict.evidence_txn_id,
                }
            )
            results.append(
                FinalCovenantResult(
                    scenario_id=sc,
                    covenant_id=cid,
                    status=cell["status"],
                    actual=cell["actual"],
                    evidence_txn_id=cell["evidence_txn_id"],
                    confidence=verdict.confidence,
                    reasoning=verdict.reasoning
                    or ("best-effort: empty covenant text" if not text else ""),
                )
            )
            print(
                f"[analyze] {sc}/{cid}: {cell['status']} actual={cell['actual']:.2f} "
                f"ev={cell['evidence_txn_id']} conf={verdict.confidence:.2f}"
            )

    diagnostics = dict(state.get("diagnostics") or {})
    diagnostics["unknown_formula_cells"] = unknown_formula_cells
    diagnostics["unknown_formula_count"] = len(unknown_formula_cells)
    diagnostics["llm_fallback_cells"] = llm_fallback_cells
    diagnostics["low_confidence_cells"] = low_confidence_cells
    diagnostics["low_confidence_count"] = len(low_confidence_cells)
    diagnostics["formula_reader_cells"] = formula_reader_cells
    diagnostics["formula_reader_count"] = len(formula_reader_cells)
    diagnostics["formula_mismatch_cells"] = formula_mismatch_cells
    diagnostics["formula_mismatch_count"] = len(formula_mismatch_cells)
    if unknown_formula_cells:
        print(
            f"[analyze] unknown/best-effort formulas: {len(unknown_formula_cells)} "
            f"{unknown_formula_cells[:8]}"
        )

    return {
        "results": results,
        "diagnostics": diagnostics,
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
    """Battle hybrid policy (confirmed by P1/P4/P3/P5/P7/B1 probes):

    1. Always run det formula_engine
    2. LLM unavailable / ERR → det
    3. det high-confidence known formula → det (no LLM call)
    4. det unknown/low-confidence → LLM FormulaSpec + code compute
    5. mismatch: known-like det → det; unknown det → LLM compute
    6. Never null status/actual
    """
    # 1) Deterministic always
    det = evaluate_covenant(covenant_text, metrics, covenant_id=covenant_id)
    unknown = is_unknown_formula_verdict(det)
    low_conf = det.confidence < CONFIDENCE_THRESHOLD
    det_strong = (not unknown) and (not low_conf)

    llm_ok = bool(use_llm) and is_llm_available()
    if not llm_ok:
        return det

    # Guard: empty covenant text cannot benefit from LLM — skip reader + legacy
    if not (covenant_text or "").strip():
        return det

    # 3) Strong known formula — skip LLM (open-set safe, saves RPM)
    need_reader = USE_LLM_FORMULA_READER and (covenant_text or "").strip()
    if LLM_FORMULA_READER_ONLY_UNKNOWN:
        need_reader = need_reader and (unknown or low_conf)
    if det_strong and LLM_FORMULA_READER_ONLY_UNKNOWN:
        return det

    # 4) Formula Reader for unknown / low-conf (or all cells if ONLY_UNKNOWN=false)
    if need_reader:
        print(
            f"[analyze] formula_reader {scenario_id}/{covenant_id} "
            f"(unknown={unknown} conf={det.confidence:.2f})"
        )
        spec, err = try_read_formula_spec(
            covenant_text=covenant_text,
            metrics=metrics,
            covenant_id=covenant_id,
            scenario_id=scenario_id,
        )
        if err:
            print(f"[analyze] formula_reader ERR → det {scenario_id}/{covenant_id}: {err}")
            return det
        if spec is not None:
            # Compute must not kill the graph node — fall back to det on any error
            try:
                computed = compute_from_formula_spec(
                    spec, metrics, covenant_id=covenant_id
                )
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[analyze] formula_compute ERR → det {scenario_id}/{covenant_id}: {exc}"
                )
                return det
            agree = specs_agree(computed, det)
            if agree:
                chosen = det.model_copy(deep=True)
                chosen.reasoning = (
                    f"[formula_reader+det agree] {computed.reasoning} || {det.reasoning}"
                )
                chosen.confidence = max(det.confidence, min(0.95, computed.confidence))
                return chosen

            # 5) mismatch policy
            print(
                f"[analyze] formula_reader mismatch {scenario_id}/{covenant_id}: "
                f"llm={computed.status}/{computed.actual} det={det.status}/{det.actual} | "
                f"llm_reason={(computed.reasoning or '')[:160]}"
            )
            prefer_det = FORMULA_READER_PREFER_DET_ON_MISMATCH and not unknown
            if prefer_det:
                chosen = det.model_copy(deep=True)
                chosen.confidence = min(det.confidence, 0.55)
                chosen.reasoning = (
                    f"[mismatch → det] LLM={computed.status}/{computed.actual} | "
                    f"LLM: {(computed.reasoning or '')[:200]} | "
                    f"{det.reasoning} | spec={spec.model_dump()}"
                )
                return chosen
            # unknown formula → trust LLM-compute unless unresolved tokens (confidence <= 0.05)
            if computed.confidence <= 0.05:
                chosen = det.model_copy(deep=True)
                chosen.reasoning = (
                    f"[unresolved token → det] {computed.reasoning} | {det.reasoning}"
                )
                return chosen

            if computed.evidence_txn_id is None and det.evidence_txn_id:
                computed.evidence_txn_id = det.evidence_txn_id
            computed.confidence = min(float(computed.confidence), 0.65)
            computed.reasoning = (
                f"[mismatch → llm_compute (det unknown)] {computed.reasoning} | "
                f"DET={det.status}/{det.actual}"
            )
            return computed

    # Strong det already returned; if reader off, optional legacy only when weak
    if det_strong or not USE_LLM_FORMULA_READER:
        return det

    # Legacy structured CovenantVerdict (rare path)
    print(
        f"[analyze] LLM verdict fallback {scenario_id}/{covenant_id} "
        f"(unknown={unknown} conf={det.confidence:.2f})"
    )
    try:
        llm_verdict = _llm_verdict_analyze(
            scenario_id=scenario_id,
            account_id=account_id,
            covenant_id=covenant_id,
            covenant_text=covenant_text,
            metrics=metrics,
        )
        if llm_verdict.confidence >= det.confidence:
            chosen = llm_verdict
            chosen.reasoning = (
                f"[llm_fallback] {llm_verdict.reasoning} | DET: {det.reasoning}"
            )
        else:
            chosen = det
            chosen.reasoning = (
                f"DET: {det.reasoning} | LLM(lower_conf): {llm_verdict.reasoning}"
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[analyze] LLM verdict failed {scenario_id}/{covenant_id}: {exc}")
        chosen = det

    if chosen.confidence < CONFIDENCE_THRESHOLD and is_llm_available():
        try:
            reflected = _llm_reflect(
                previous=chosen,
                covenant_text=covenant_text,
                metrics=metrics,
            )
            reflected.reasoning = (
                f"[llm_reflect] {reflected.reasoning} | prev: {chosen.reasoning}"
            )
            chosen = reflected
        except Exception as exc:  # noqa: BLE001
            print(f"[analyze] reflection failed {scenario_id}/{covenant_id}: {exc}")

    return chosen


def analyze_one_covenant_deterministic(
    covenant_text: str,
    metrics: ScenarioMetrics,
    covenant_id: str = "",
) -> CovenantVerdict:
    return evaluate_covenant(covenant_text, metrics, covenant_id=covenant_id)


def _llm_verdict_analyze(
    *,
    scenario_id: str,
    account_id: str,
    covenant_id: str,
    covenant_text: str,
    metrics: ScenarioMetrics,
) -> CovenantVerdict:
    from agent.tools.llm import get_llm, invoke_with_system

    llm = get_llm(temperature=0.0)
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
    # Prefer structured; fallback to system+user parse (never double-burn 429)
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        result = structured.invoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user)]
        )
        if isinstance(result, CovenantVerdict):
            return result
        return CovenantVerdict.model_validate(result)
    except Exception as exc:
        from agent.tools.llm import _is_rate_limit_error

        if _is_rate_limit_error(exc):
            # Second call would hit the same limit and only waste timeout budget
            raise
        try:
            raw = invoke_with_system(llm, SYSTEM_PROMPT, user, use_cache_control=True)
            content = raw.content if hasattr(raw, "content") else str(raw)
            return _parse_verdict_json(content)
        except Exception as exc2:
            raise exc2 from exc


def _llm_reflect(
    *,
    previous: CovenantVerdict,
    covenant_text: str,
    metrics: ScenarioMetrics,
) -> CovenantVerdict:
    from agent.tools.llm import get_llm
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = get_llm(temperature=0.0)
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
    """Assemble submission payload; every cell has non-null status/actual."""
    results: list[FinalCovenantResult] = state.get("results") or []
    template_scenarios = state.get("scenario_ids") or []

    answers: dict[str, dict[str, Any]] = {
        sc: {
            cid: ensure_filled_cell(None)
            for cid in covenant_ids_for_scenario(sc)
        }
        for sc in template_scenarios
    }

    for r in results:
        if r.scenario_id not in answers:
            # Still keep unexpected scenarios filled (private-set safety)
            answers[r.scenario_id] = {
                cid: ensure_filled_cell(None)
                for cid in covenant_ids_for_scenario(r.scenario_id)
            }
        answers[r.scenario_id][r.covenant_id] = r.to_submission_cell()

    # Per-scenario sanitize using each scenario's template ids
    sanitized: dict[str, dict[str, Any]] = {}
    for sc, cmap in answers.items():
        sanitized[sc] = ensure_filled_answers(
            {sc: cmap},
            covenant_ids=covenant_ids_for_scenario(sc),
            scenario_ids=[sc],
        )[sc]
    answers = sanitized

    null_cells = [
        f"{sc}/{cid}"
        for sc, cmap in answers.items()
        for cid, cell in cmap.items()
        if cell.get("status") is None or cell.get("actual") is None
    ]
    if null_cells:
        print(f"[collect] WARNING still-null cells after sanitize: {null_cells}")

    filled = sum(
        1
        for cmap in answers.values()
        for cell in cmap.values()
        if cell.get("status") in ("COMPLIANT", "BREACH")
        and cell.get("actual") is not None
    )
    print(f"[collect] filled cells: {filled} (null status/actual forbidden)")

    documents = dict(state.get("documents") or {})
    documents["submission_answers"] = answers
    return {
        "documents": documents,
        "stage": "collected",
        "error": None,
    }
