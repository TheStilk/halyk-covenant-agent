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
# ---------------------------------------------------------------------------
# LLM — provider-agnostic OpenAI-compatible endpoint
# Swap model/provider ONLY via env (no code edits, no vendor roles in logic).
#
#   LLM_API_KEY=...
#   LLM_BASE_URL=https://any-compatible-host/v1
#   LLM_MODEL=provider/model-id
#   MODEL_LABEL=...   # optional; defaults to LLM_MODEL for submission.json
#
# Legacy aliases still accepted: OPENAI_API_KEY, QWEN_*, OPENAI_BASE_URL.
# ---------------------------------------------------------------------------
LLM_API_KEY = (
    os.getenv("LLM_API_KEY")
    or os.getenv("OPENAI_API_KEY")
    or os.getenv("QWEN_API_KEY")
    or ""
)
LLM_BASE_URL = (
    os.getenv("LLM_BASE_URL")
    or os.getenv("OPENAI_BASE_URL")
    or os.getenv("QWEN_BASE_URL")
    or ""
)
LLM_MODEL = (
    os.getenv("LLM_MODEL")
    or os.getenv("OPENAI_MODEL")
    or os.getenv("QWEN_MODEL")
    or ""
)
LLM_TIMEOUT_SEC = float(os.getenv("LLM_TIMEOUT_SEC", "60"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))

# Field `model` in submission.json — single source of truth
MODEL_LABEL = (os.getenv("MODEL_LABEL") or LLM_MODEL or "deterministic-formula-engine").strip()

# Optional second OpenAI-compatible endpoint for PDF classify only.
# If unset, CLASSIFY_USE_LLM reuses the primary LLM_* client.
CLASSIFY_API_KEY = (
    os.getenv("CLASSIFY_API_KEY")
    or os.getenv("GOOGLE_API_KEY")
    or os.getenv("GEMINI_API_KEY")
    or ""
)
CLASSIFY_BASE_URL = os.getenv("CLASSIFY_BASE_URL") or LLM_BASE_URL
CLASSIFY_MODEL = (
    os.getenv("CLASSIFY_MODEL")
    or os.getenv("GEMINI_MODEL")
    or LLM_MODEL
)

# Legacy aliases (same objects) so old imports do not break
QWEN_API_KEY = LLM_API_KEY
QWEN_BASE_URL = LLM_BASE_URL
QWEN_MODEL = LLM_MODEL
GOOGLE_API_KEY = CLASSIFY_API_KEY
GEMINI_MODEL = CLASSIFY_MODEL

# ---------------------------------------------------------------------------
# Runtime knobs
# ---------------------------------------------------------------------------
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.85"))
MAX_BORROWER_CONCURRENCY = int(os.getenv("MAX_BORROWER_CONCURRENCY", "6"))
CLASSIFY_USE_LLM = os.getenv("CLASSIFY_USE_LLM", "false").lower() in {"1", "true", "yes"}
# LLM Formula Reader: interpret covenant text → formula_spec; code computes numbers.
# Battle default: only run reader when det is unknown / low-confidence (not every cell).
USE_LLM_FORMULA_READER = os.getenv("USE_LLM_FORMULA_READER", "true").lower() in {
    "1",
    "true",
    "yes",
}
LLM_FORMULA_READER_ONLY_UNKNOWN = os.getenv(
    "LLM_FORMULA_READER_ONLY_UNKNOWN", "true"
).lower() in {"1", "true", "yes"}
# On mismatch: prefer det when det is strong; prefer LLM-compute when det is unknown
FORMULA_READER_PREFER_DET_ON_MISMATCH = os.getenv(
    "FORMULA_READER_PREFER_DET_ON_MISMATCH", "true"
).lower() in {"1", "true", "yes"}
# Cap covenant text sent to reader (reduces Gemma length-limit blowups)
FORMULA_READER_MAX_TEXT_CHARS = int(os.getenv("FORMULA_READER_MAX_TEXT_CHARS", "900"))
# FormulaSpec / short JSON — keep low to avoid long hallucination timeouts
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1024"))
PDF_TEXT_PREVIEW_CHARS = 3000
# Soft OOM guard for .txt/.csv/.md/.json extract (latin-1 can load whole file)
MAX_TEXT_FILE_MB = float(os.getenv("MAX_TEXT_FILE_MB", "16"))
MAX_TEXT_FILE_BYTES = int(MAX_TEXT_FILE_MB * 1024 * 1024)
# pdfplumber extract_tables: only first N pages (full-doc walk can OOM)
MAX_TABLE_PAGES = int(os.getenv("MAX_TABLE_PAGES", "32"))

# Tesseract languages required for battle OCR (KYC / notes tables; KZ + RU + EN)
TESSERACT_LANGS = tuple(
    x.strip()
    for x in os.getenv("TESSERACT_LANGS", "eng+rus+kaz").split("+")
    if x.strip()
)
TESSERACT_LANG_ARG = "+".join(TESSERACT_LANGS)  # tesseract -l eng+rus+kaz

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
