#!/usr/bin/env python3
"""ARCHIVED probe: LLM Formula Reader det vs LLM comparison (2026-08-06).

Not on production path. Reports live under archive/gemini-llm-probe-20260806/reports/.

Usage (from repo root):
  uv run python archive/gemini-llm-probe-20260806/scripts/test_llm_formula_reader.py --scenarios P1 P4
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load .env before agent.config is imported elsewhere
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

# Allow second key without putting secrets in source
_PRIMARY = os.getenv("LLM_API_KEY", "")
_FALLBACK = os.getenv("LLM_API_KEY_FALLBACK", "") or os.getenv("LLM_API_KEY_2", "")


def _apply_key(key: str) -> None:
    """Hot-swap API key and clear LLM caches."""
    os.environ["LLM_API_KEY"] = key
    import agent.config as cfg
    import agent.tools.llm as llm_mod

    cfg.LLM_API_KEY = key
    if hasattr(llm_mod.get_chat_model, "cache_clear"):
        llm_mod.get_chat_model.cache_clear()
    if hasattr(llm_mod.get_classify_model, "cache_clear"):
        llm_mod.get_classify_model.cache_clear()


def _is_quota_error(exc: BaseException) -> bool:
    s = str(exc).lower()
    return any(
        x in s
        for x in (
            "429",
            "quota",
            "rate limit",
            "resource_exhausted",
            "too many requests",
            "insufficient",
        )
    )


def _is_model_gone_error(exc: BaseException) -> bool:
    s = str(exc).lower()
    return "no longer available" in s or (
        "404" in s and "model" in s
    )


@dataclass
class CellProbe:
    scenario_id: str
    covenant_id: str
    covenant_text_preview: str
    det_status: Optional[str] = None
    det_actual: Optional[float] = None
    det_evidence: Optional[str] = None
    det_confidence: Optional[float] = None
    det_reasoning: str = ""
    formula_spec: Optional[dict[str, Any]] = None
    llm_status: Optional[str] = None
    llm_actual: Optional[float] = None
    llm_evidence: Optional[str] = None
    llm_confidence: Optional[float] = None
    llm_reasoning: str = ""
    truth_status: Optional[str] = None
    truth_actual: Optional[float] = None
    truth_evidence: Optional[str] = None
    agree_det_llm: Optional[bool] = None
    rel_err_det_llm: Optional[float] = None
    rel_err_llm_truth: Optional[float] = None
    rel_err_det_truth: Optional[float] = None
    error: Optional[str] = None
    elapsed_sec: float = 0.0
    api_key_used: str = "primary"


@dataclass
class ProbeReport:
    started_at: str
    finished_at: str = ""
    model: str = ""
    base_url: str = ""
    model_label: str = ""
    smoke: dict[str, Any] = field(default_factory=dict)
    scenarios: list[str] = field(default_factory=list)
    cells: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class LlmFormulaReaderProbe:
    """Detailed smoke + det vs LLM Formula Reader probe (temporary)."""

    def __init__(
        self,
        scenarios: list[str],
        *,
        out_dir: Path | None = None,
        rel_tol: float = 0.05,
        sleep_between_llm_sec: float = 13.0,
    ) -> None:
        self.scenarios = scenarios
        self.out_dir = out_dir or (ROOT / "archive" / "gemini-llm-probe-20260806" / "reports")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.rel_tol = rel_tol
        self.sleep_between_llm_sec = sleep_between_llm_sec
        self.cells: list[CellProbe] = []
        self.smoke_result: dict[str, Any] = {}
        self.notes: list[str] = []
        self._key_label = "primary"
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.run_id = f"llm_formula_reader_{ts}"
        self.started_at = datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------ smoke
    def run_smoke(self) -> dict[str, Any]:
        from agent.config import LLM_BASE_URL, LLM_MODEL, MODEL_LABEL
        from agent.models_formula import FormulaSpec
        from agent.tools.llm import is_llm_available, llm_status_message, structured_invoke

        result: dict[str, Any] = {
            "available": is_llm_available(),
            "status_message": llm_status_message(),
            "model": LLM_MODEL,
            "base_url": LLM_BASE_URL,
            "model_label": MODEL_LABEL,
            "structured_ok": False,
            "structured_spec": None,
            "error": None,
            "key_used": self._key_label,
            "elapsed_sec": 0.0,
        }
        if not is_llm_available():
            self.smoke_result = result
            return result

        t0 = time.perf_counter()
        try:
            spec = self._with_key_fallback(
                lambda: structured_invoke(
                    FormulaSpec,
                    system=(
                        "Return FormulaSpec only. No arithmetic. "
                        "For min revenue of $5,000,000: comparison=min, "
                        "numerator_metrics=['revenue'], denominator_metrics=[], "
                        "threshold=5000000, formula_kind=absolute_min."
                    ),
                    user="Минимальная выручка заёмщика должна составлять не менее $5,000,000.",
                    temperature=0.0,
                )
            )
            result["structured_ok"] = True
            result["structured_spec"] = spec.model_dump()
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"{type(exc).__name__}: {exc}"
            result["traceback"] = traceback.format_exc()
        result["elapsed_sec"] = round(time.perf_counter() - t0, 3)
        result["key_used"] = self._key_label
        self.smoke_result = result
        return result

    def _with_key_fallback(self, fn):
        """Call fn; on quota errors switch to fallback API key once."""
        try:
            return fn()
        except Exception as exc:
            if _is_model_gone_error(exc):
                # try flash-latest alias once
                import agent.config as cfg
                import agent.tools.llm as llm_mod

                alt = "'flash-latest-alias'"
                if cfg.LLM_MODEL != alt:
                    self.notes.append(
                        f"model {cfg.LLM_MODEL!r} unavailable → try {alt!r}"
                    )
                    print(f"[probe] model gone, switching to {alt}")
                    os.environ["LLM_MODEL"] = alt
                    cfg.LLM_MODEL = alt
                    cfg.MODEL_LABEL = alt
                    if hasattr(llm_mod.get_chat_model, "cache_clear"):
                        llm_mod.get_chat_model.cache_clear()
                    return fn()
            if _FALLBACK and _is_quota_error(exc) and self._key_label == "primary":
                self.notes.append(
                    f"quota on primary key → switching to fallback ({type(exc).__name__})"
                )
                print(f"[probe] quota/limit on primary, trying fallback key…")
                _apply_key(_FALLBACK)
                self._key_label = "fallback"
                time.sleep(2)
                return fn()
            if _is_quota_error(exc):
                # free tier RPM — wait and retry once
                self.notes.append(f"quota hit, sleep 30s and retry: {exc}")
                print("[probe] rate limit — sleeping 30s…")
                time.sleep(30)
                return fn()
            raise

    # --------------------------------------------------------------- scenarios
    def run_scenarios(self) -> list[CellProbe]:
        from agent.config import GROUND_TRUTH_PATH, covenant_ids_for_scenario
        from agent.graph import run_foundation
        from agent.tools.formula_compute import compute_from_formula_spec, specs_agree
        from agent.tools.formula_engine import evaluate_covenant
        from agent.tools.formula_reader import try_read_formula_spec
        from agent.tools.ledger import scenario_to_account, transactions_for_account
        from agent.tools.metrics import extract_metrics_for_state

        print("=== Foundation (classify + covenants) ===")
        t_f = time.perf_counter()
        state = run_foundation()
        self.notes.append(f"foundation_sec={time.perf_counter() - t_f:.1f}")

        sc_to_acc = scenario_to_account(state["account_to_scenario"])
        covenants_by = (state.get("documents") or {}).get("covenants_by_scenario") or {}
        docs_by = state.get("docs_by_scenario") or {}
        ledger = state["ledger"]
        doc_index = state.get("doc_index") or []

        gt: dict[str, Any] = {}
        if GROUND_TRUTH_PATH.exists():
            raw = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
            gt = raw.get("scenarios", raw)

        for sc in self.scenarios:
            acc = sc_to_acc.get(sc, "")
            txns = transactions_for_account(ledger, acc)
            metrics = extract_metrics_for_state(
                scenario_id=sc,
                account_id=acc,
                transactions=txns,
                docs_by_scenario=docs_by,
                doc_index=doc_index,
            )
            cov_map = covenants_by.get(sc) or {}
            print(f"\n=== Scenario {sc} account={acc} ===")
            print(metrics.summary_for_llm()[:500], "…")

            for cid in covenant_ids_for_scenario(sc):
                text = cov_map.get(cid, "") or ""
                probe = CellProbe(
                    scenario_id=sc,
                    covenant_id=cid,
                    covenant_text_preview=text.replace("\n", " ")[:280],
                    api_key_used=self._key_label,
                )
                truth = (gt.get(sc) or {}).get("covenants", {}).get(cid, {})
                probe.truth_status = truth.get("status")
                probe.truth_actual = truth.get("actual")
                probe.truth_evidence = truth.get("evidence_txn_id")

                t0 = time.perf_counter()
                try:
                    det = evaluate_covenant(text, metrics, covenant_id=cid)
                    probe.det_status = det.status
                    probe.det_actual = float(det.actual)
                    probe.det_evidence = det.evidence_txn_id
                    probe.det_confidence = float(det.confidence)
                    probe.det_reasoning = det.reasoning

                    def _read():
                        return try_read_formula_spec(
                            covenant_text=text,
                            metrics=metrics,
                            covenant_id=cid,
                            scenario_id=sc,
                        )

                    if self.sleep_between_llm_sec > 0:
                        time.sleep(self.sleep_between_llm_sec)
                    spec, err = self._with_key_fallback(_read)
                    if err:
                        probe.error = f"formula_reader: {err}"
                    elif spec is None:
                        probe.error = "formula_reader returned None"
                    else:
                        probe.formula_spec = spec.model_dump()
                        computed = compute_from_formula_spec(
                            spec, metrics, covenant_id=cid
                        )
                        probe.llm_status = computed.status
                        probe.llm_actual = float(computed.actual)
                        probe.llm_evidence = computed.evidence_txn_id
                        probe.llm_confidence = float(computed.confidence)
                        probe.llm_reasoning = computed.reasoning
                        probe.agree_det_llm = specs_agree(
                            computed, det, rel_tol=self.rel_tol
                        )
                        probe.rel_err_det_llm = self._rel_err(
                            probe.det_actual, probe.llm_actual
                        )
                        probe.api_key_used = self._key_label

                    if probe.truth_actual is not None and probe.det_actual is not None:
                        probe.rel_err_det_truth = self._rel_err(
                            float(probe.truth_actual), probe.det_actual
                        )
                    if probe.truth_actual is not None and probe.llm_actual is not None:
                        probe.rel_err_llm_truth = self._rel_err(
                            float(probe.truth_actual), probe.llm_actual
                        )
                except Exception as exc:  # noqa: BLE001
                    probe.error = f"{type(exc).__name__}: {exc}"
                    self.notes.append(
                        f"{sc}/{cid} exception: {probe.error}"
                    )
                probe.elapsed_sec = round(time.perf_counter() - t0, 3)
                self.cells.append(probe)
                self._print_cell(probe)

        return self.cells

    @staticmethod
    def _rel_err(a: Optional[float], b: Optional[float]) -> Optional[float]:
        if a is None or b is None:
            return None
        base = max(abs(float(a)), abs(float(b)), 1e-12)
        return abs(float(a) - float(b)) / base

    def _print_cell(self, p: CellProbe) -> None:
        flag = (
            "AGREE"
            if p.agree_det_llm is True
            else ("MISMATCH" if p.agree_det_llm is False else "N/A")
        )
        print(
            f"  {p.scenario_id}/{p.covenant_id}: {flag} "
            f"det={p.det_status}/{p.det_actual} "
            f"llm={p.llm_status}/{p.llm_actual} "
            f"truth={p.truth_status}/{p.truth_actual} "
            f"err_det_llm={None if p.rel_err_det_llm is None else round(p.rel_err_det_llm*100,2)}% "
            f"t={p.elapsed_sec}s"
            + (f" ERR={p.error}" if p.error else "")
        )
        if p.formula_spec:
            print(
                f"    spec: kind={p.formula_spec.get('formula_kind')} "
                f"cmp={p.formula_spec.get('comparison')} thr={p.formula_spec.get('threshold')} "
                f"num={p.formula_spec.get('numerator_metrics')} "
                f"den={p.formula_spec.get('denominator_metrics')} "
                f"conf={p.formula_spec.get('confidence')}"
            )
            print(f"    interp: {p.formula_spec.get('raw_interpretation', '')[:160]}")

    # ----------------------------------------------------------------- report
    def build_summary(self) -> dict[str, Any]:
        n = len(self.cells)
        agree = sum(1 for c in self.cells if c.agree_det_llm is True)
        mismatch = sum(1 for c in self.cells if c.agree_det_llm is False)
        errors = sum(1 for c in self.cells if c.error)
        det_truth_ok = sum(
            1
            for c in self.cells
            if c.truth_status and c.det_status == c.truth_status
            and (c.rel_err_det_truth is None or c.rel_err_det_truth <= self.rel_tol)
        )
        llm_truth_ok = sum(
            1
            for c in self.cells
            if c.truth_status
            and c.llm_status == c.truth_status
            and (c.rel_err_llm_truth is None or c.rel_err_llm_truth <= self.rel_tol)
        )
        with_truth = sum(1 for c in self.cells if c.truth_status)
        return {
            "cells": n,
            "agree_det_llm": agree,
            "mismatch_det_llm": mismatch,
            "errors": errors,
            "det_matches_truth_status_and_actual": det_truth_ok,
            "llm_matches_truth_status_and_actual": llm_truth_ok,
            "cells_with_truth": with_truth,
            "rel_tol": self.rel_tol,
            "api_key_final": self._key_label,
        }

    def write_reports(self) -> tuple[Path, Path]:
        finished = datetime.now(timezone.utc).isoformat()
        from agent.config import LLM_BASE_URL, LLM_MODEL, MODEL_LABEL

        report = ProbeReport(
            started_at=self.started_at,
            finished_at=finished,
            model=LLM_MODEL,
            base_url=LLM_BASE_URL,
            model_label=MODEL_LABEL,
            smoke=self.smoke_result,
            scenarios=self.scenarios,
            cells=[asdict(c) for c in self.cells],
            summary=self.build_summary(),
            notes=self.notes,
        )
        json_path = self.out_dir / f"{self.run_id}.json"
        md_path = self.out_dir / f"{self.run_id}.md"
        json_path.write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        md_path.write_text(self._to_markdown(report), encoding="utf-8")
        print(f"\nWrote {json_path}")
        print(f"Wrote {md_path}")
        return json_path, md_path

    def _to_markdown(self, report: ProbeReport) -> str:
        s = report.summary
        lines = [
            f"# LLM Formula Reader probe — `{self.run_id}`",
            "",
            f"- started: `{report.started_at}`",
            f"- finished: `{report.finished_at}`",
            f"- model: `{report.model}`",
            f"- base_url: `{report.base_url}`",
            f"- MODEL_LABEL: `{report.model_label}`",
            f"- scenarios: {', '.join(report.scenarios)}",
            "",
            "## Smoke",
            "```json",
            json.dumps(report.smoke, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Summary",
            f"- cells: **{s.get('cells')}**",
            f"- det↔llm AGREE: **{s.get('agree_det_llm')}**",
            f"- det↔llm MISMATCH: **{s.get('mismatch_det_llm')}**",
            f"- errors: **{s.get('errors')}**",
            f"- det matches truth (status+actual≤5%): "
            f"**{s.get('det_matches_truth_status_and_actual')}/{s.get('cells_with_truth')}**",
            f"- llm matches truth (status+actual≤5%): "
            f"**{s.get('llm_matches_truth_status_and_actual')}/{s.get('cells_with_truth')}**",
            f"- api key used (final): `{s.get('api_key_final')}`",
            "",
            "## Cells",
            "",
            "| sc | cov | flag | det | llm | truth | err det↔llm | err llm↔truth | t(s) |",
            "|----|-----|------|-----|-----|-------|-------------|---------------|------|",
        ]
        for c in self.cells:
            flag = (
                "AGREE"
                if c.agree_det_llm is True
                else ("MISMATCH" if c.agree_det_llm is False else "ERR")
            )
            lines.append(
                f"| {c.scenario_id} | {c.covenant_id} | {flag} | "
                f"{c.det_status}/{c.det_actual} | "
                f"{c.llm_status}/{c.llm_actual} | "
                f"{c.truth_status}/{c.truth_actual} | "
                f"{self._pct(c.rel_err_det_llm)} | "
                f"{self._pct(c.rel_err_llm_truth)} | "
                f"{c.elapsed_sec} |"
            )
        lines.append("")
        lines.append("## Formula specs (detail)")
        for c in self.cells:
            lines.append(f"### {c.scenario_id}/{c.covenant_id}")
            lines.append(f"- text: `{c.covenant_text_preview}`")
            lines.append(f"- det reasoning: `{c.det_reasoning[:300]}`")
            if c.formula_spec:
                lines.append("```json")
                lines.append(json.dumps(c.formula_spec, ensure_ascii=False, indent=2))
                lines.append("```")
                lines.append(f"- llm compute: `{c.llm_reasoning[:400]}`")
            if c.error:
                lines.append(f"- **error:** `{c.error}`")
            lines.append("")
        if report.notes:
            lines.append("## Notes")
            for n in report.notes:
                lines.append(f"- {n}")
            lines.append("")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _pct(x: Optional[float]) -> str:
        if x is None:
            return "—"
        return f"{x * 100:.2f}%"

    def run(self) -> int:
        print("=== LLM Formula Reader Probe ===")
        print(f"run_id={self.run_id}")
        if _PRIMARY:
            _apply_key(_PRIMARY)
            self._key_label = "primary"
        smoke = self.run_smoke()
        print("smoke:", json.dumps({k: smoke[k] for k in smoke if k != "traceback"}, indent=2)[:800])
        if not smoke.get("available") or not smoke.get("structured_ok"):
            self.notes.append("smoke failed — still running scenarios if possible")
            print("WARNING: smoke failed")
            if not smoke.get("available"):
                self.write_reports()
                return 1

        self.run_scenarios()
        summary = self.build_summary()
        print("\n=== SUMMARY ===")
        print(json.dumps(summary, indent=2))
        self.write_reports()
        # non-zero if all llm cells errored
        if summary.get("errors", 0) == summary.get("cells", 0) and summary.get("cells", 0) > 0:
            return 2
        return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Probe LLM Formula Reader vs det")
    p.add_argument(
        "--scenarios",
        nargs="*",
        default=["P1", "P4"],
        help="scenarios to probe (default: P1 P4)",
    )
    p.add_argument("--rel-tol", type=float, default=0.05)
    p.add_argument(
        "--sleep",
        type=float,
        default=13.0,
        help="seconds between LLM calls (free-tier RPM)",
    )
    args = p.parse_args(argv)
    probe = LlmFormulaReaderProbe(
        list(args.scenarios),
        rel_tol=args.rel_tol,
        sleep_between_llm_sec=args.sleep,
    )
    return probe.run()


if __name__ == "__main__":
    raise SystemExit(main())
