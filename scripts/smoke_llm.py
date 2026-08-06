#!/usr/bin/env python3
"""Point 0 of the plan: prove a live LLM call works, end to end.

Two stages, because "the key is valid" and "the key is useful" are different
claims:

  1. reachability — one trivial call, reporting model, latency and token usage;
  2. task shape    — hand the model a real clause 6.1 from the public corpus and
     require a CovenantSpec-shaped JSON back.

Stage 2 is the one that matters. It is the smallest possible version of what the
agent branch has to do 12 times on competition day, and it fails for real
reasons (model refuses JSON, context too small, clause not understood) rather
than for setup reasons.

Usage:
    python scripts/smoke_llm.py                 # auto-detect provider from env
    python scripts/smoke_llm.py --provider anthropic --model claude-sonnet-5
    python scripts/smoke_llm.py --scenario P4   # try a different borrower
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.console import setup_console  # noqa: E402

setup_console()

SPEC_INSTRUCTION = """\
Ты читаешь пункт кредитного договора и превращаешь его в спецификацию расчёта.
Ты НЕ считаешь числа и НЕ выносишь вердикт — только описываешь, что надо посчитать.

Верни РОВНО один JSON-объект, без markdown-ограждения, с полями:
  direction   — "max" если пункт ограничивает показатель сверху, "min" если снизу
  metric      — краткое описание показателя словами
  threshold   — число-порог из текста (без валютных знаков и "x")
  unit        — "ratio" или "amount"
  period      — {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}
  conditional — null, либо описание условия, при котором пункт вообще применяется
  quote       — дословная цитата из текста, где указан порог
"""

REQUIRED_SPEC_FIELDS = ("direction", "metric", "threshold", "unit", "period", "quote")


def detect_provider(explicit: str | None) -> tuple[str, str, str, str]:
    """Return (provider, base_url, api_key, default_model)."""
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    openai_key = (
        os.getenv("OPENROUTER_API_KEY")
        or os.getenv("QWEN_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    )

    if explicit == "anthropic" or (explicit is None and anthropic_key and not openai_key):
        return (
            "anthropic",
            os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            anthropic_key,
            os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"),
        )

    from agent.config import QWEN_BASE_URL, QWEN_MODEL

    return ("openai-compatible", QWEN_BASE_URL, openai_key, QWEN_MODEL)


def call_llm(
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    *,
    max_tokens: int = 1200,
) -> tuple[str, dict]:
    """One chat completion. Returns (text, usage)."""
    import httpx

    if provider == "anthropic":
        url = f"{base_url.rstrip('/')}/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
    else:
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(url, headers=headers, json=payload)

    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    if provider == "anthropic":
        text = "".join(block.get("text", "") for block in data.get("content", []))
        usage = data.get("usage", {})
    else:
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
    return text, usage


def load_clause(scenario_id: str, covenant_id: str) -> tuple[str, str]:
    """Pull one real clause out of the public corpus. Returns (account, text)."""
    from agent.graph import run_foundation
    from agent.tools.ledger import scenario_to_account

    state = run_foundation()
    account = scenario_to_account(state["account_to_scenario"]).get(scenario_id, "")
    clause = (
        (state["documents"]["covenants_by_scenario"].get(scenario_id) or {})
        .get(covenant_id, "")
    )
    return account, clause


def extract_json(text: str) -> dict | None:
    """Best-effort JSON extraction from a model reply."""
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("```")[1]
        candidate = candidate.removeprefix("json").strip()
    start, end = candidate.find("{"), candidate.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--provider", choices=("anthropic", "openai-compatible"), default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--scenario", default="P1")
    p.add_argument("--covenant", default="6.1")
    p.add_argument("--skip-task", action="store_true", help="stage 1 only")
    args = p.parse_args()

    provider, base_url, api_key, default_model = detect_provider(args.provider)
    model = args.model or default_model

    print(f"provider : {provider}")
    print(f"base_url : {base_url}")
    print(f"model    : {model}")

    if not api_key:
        print(
            "\nFAIL: no API key in the environment.\n"
            "  Set one of ANTHROPIC_API_KEY / OPENROUTER_API_KEY / QWEN_API_KEY\n"
            "  in .env, then re-run. Until this passes, the agent branch does\n"
            "  not exist — it is point 0 of the plan for exactly this reason."
        )
        return 1

    print(f"key      : ...{api_key[-4:]} ({len(api_key)} chars)")

    # --- stage 1: is the endpoint reachable and the key valid? --------------
    print("\n=== [1/2] reachability ===")
    t0 = time.monotonic()
    try:
        text, usage = call_llm(
            provider, base_url, api_key, model,
            "Ответь одним словом: работает",
            max_tokens=32,
        )
    except Exception as exc:  # noqa: BLE001 — this script exists to report failures
        print(f"FAIL: {exc}")
        return 1
    print(f"OK  {time.monotonic() - t0:.1f}s  reply={text.strip()[:60]!r}  usage={usage}")

    if args.skip_task:
        return 0

    # --- stage 2: can it do the actual job? ---------------------------------
    print(f"\n=== [2/2] task shape: {args.scenario}/{args.covenant} → CovenantSpec ===")
    account, clause = load_clause(args.scenario, args.covenant)
    if not clause:
        print(f"FAIL: no clause text extracted for {args.scenario}/{args.covenant}")
        return 1
    print(f"account={account}  clause={len(clause)} chars")

    t0 = time.monotonic()
    try:
        text, usage = call_llm(
            provider, base_url, api_key, model,
            f"{SPEC_INSTRUCTION}\n\nТЕКСТ ПУНКТА {args.covenant}:\n{clause}",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}")
        return 1

    elapsed = time.monotonic() - t0
    spec = extract_json(text)
    if spec is None:
        print(f"FAIL after {elapsed:.1f}s: reply is not JSON.\n--- raw ---\n{text[:800]}")
        return 1

    missing = [f for f in REQUIRED_SPEC_FIELDS if f not in spec]
    print(f"OK  {elapsed:.1f}s  usage={usage}")
    print(json.dumps(spec, ensure_ascii=False, indent=2)[:1200])

    if missing:
        print(f"\nPARTIAL: missing fields {missing} — prompt needs work, but the path is live.")
        return 0

    print(
        "\nPASS: live key, and the model turns a real clause into a spec.\n"
        "Point 0 is closed; point 4 (CovenantSpec + compute) can start."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
