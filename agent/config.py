"""Configuration for the Halyk Covenant Monitoring Agent."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT_DIR / "agentic-bank-public"))
DOCUMENTS_DIR = DATA_DIR / "documents"
LEDGER_PATH = DATA_DIR / "master_ledger_2025.csv"
TEMPLATE_PATH = DATA_DIR / "submission_template.json"
GROUND_TRUTH_PATH = DATA_DIR / "ground_truth.json"
SUBMISSION_PATH = ROOT_DIR / "submission.json"
DOC_CACHE_DIR = Path(os.getenv("DOC_CACHE_DIR", ROOT_DIR / "doc_cache"))

# ---------------------------------------------------------------------------
# Team meta (filled into submission.json)
# ---------------------------------------------------------------------------
TEAM_NAME = os.getenv("TEAM_NAME", "Сычуанский Соус")
CONTACT_EMAIL = os.getenv(
    "CONTACT_EMAIL",
    "serkebaevmadiyar09@gmail.com, zhenis415@gmail.com",
)
MODEL_LABEL = "qwen3.8-max + gemini-3.6-flash"

# ---------------------------------------------------------------------------
# LLM endpoints
# ---------------------------------------------------------------------------
# Qwen 3.8-Max via OpenAI-compatible API (OpenRouter / Alibaba / proxy)
QWEN_API_KEY = os.getenv("QWEN_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
QWEN_BASE_URL = os.getenv(
    "QWEN_BASE_URL",
    os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
)
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen/qwen3.5-max")  # OpenRouter slug; override for native

# Gemini 3.6 Flash
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.0-flash")  # override if slug differs

# ---------------------------------------------------------------------------
# Runtime knobs
# ---------------------------------------------------------------------------
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.85"))
MAX_BORROWER_CONCURRENCY = int(os.getenv("MAX_BORROWER_CONCURRENCY", "6"))
CLASSIFY_USE_LLM = os.getenv("CLASSIFY_USE_LLM", "false").lower() in {"1", "true", "yes"}
PDF_TEXT_PREVIEW_CHARS = 3000

# Covenant section keys — loaded from submission_template.json (not hardcoded).
# Fallback only if template is missing/empty.
_DEFAULT_COVENANT_IDS = ("6.1", "6.2", "6.3")


def load_covenant_ids_from_template(
    path: Path | None = None,
) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    """Return (union_ids, per_scenario_ids) from submission_template.json."""
    tpl_path = path or TEMPLATE_PATH
    per: dict[str, tuple[str, ...]] = {}
    if tpl_path.exists():
        try:
            data = json.loads(tpl_path.read_text(encoding="utf-8"))
            answers = data.get("answers") or {}
            if isinstance(answers, dict):
                for sc, cells in answers.items():
                    if isinstance(cells, dict) and cells:
                        # preserve template key order
                        per[str(sc)] = tuple(str(k) for k in cells.keys())
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[config] WARNING cannot read template covenant ids: {exc}")

    if not per:
        return _DEFAULT_COVENANT_IDS, {}

    # Union in stable order: first scenario's order, then any extras
    seen: list[str] = []
    for ids in per.values():
        for cid in ids:
            if cid not in seen:
                seen.append(cid)
    return tuple(seen), per


def covenant_ids_for_scenario(scenario_id: str) -> tuple[str, ...]:
    """Covenant ids for one scenario (template), else global union/default."""
    if scenario_id in COVENANT_IDS_BY_SCENARIO:
        return COVENANT_IDS_BY_SCENARIO[scenario_id]
    return COVENANT_IDS


COVENANT_IDS, COVENANT_IDS_BY_SCENARIO = load_covenant_ids_from_template()
