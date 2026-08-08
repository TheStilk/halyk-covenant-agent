"""Configuration for the Halyk Covenant Monitoring Agent."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_float(name: str, default: float) -> float:
    """Parse float env; empty / invalid → default (never crash import on LLM_TIMEOUT_SEC=\"\")."""
    raw = os.getenv(name)
    if raw is None:
        return float(default)
    s = str(raw).strip()
    if not s:
        return float(default)
    try:
        return float(s)
    except ValueError:
        print(f"[config] WARNING: invalid {name}={raw!r}, using {default}")
        return float(default)


def _env_int(name: str, default: int) -> int:
    """Parse int env; empty / invalid → default."""
    raw = os.getenv(name)
    if raw is None:
        return int(default)
    s = str(raw).strip()
    if not s:
        return int(default)
    try:
        return int(float(s))  # allow "2.0"
    except ValueError:
        print(f"[config] WARNING: invalid {name}={raw!r}, using {default}")
        return int(default)


def _env_bool(name: str, default: bool) -> bool:
    """Parse boolean env; empty / invalid → default."""
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    s = str(raw).strip().lower()
    if not s:
        return bool(default)
    if s in ("1", "true", "yes", "y", "t", "on"):
        return True
    if s in ("0", "false", "no", "n", "f", "off"):
        return False
    print(f"[config] WARNING: invalid bool {name}={raw!r}, using {default}")
    return bool(default)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT_DIR / "agentic-bank-public"))
# Optional overrides if private set renames files; default = CASE layout under DATA_DIR
DOCUMENTS_DIR = Path(os.getenv("DOCUMENTS_DIR", DATA_DIR / "documents"))
LEDGER_PATH = Path(os.getenv("LEDGER_PATH", DATA_DIR / "master_ledger_2025.csv"))
TEMPLATE_PATH = Path(os.getenv("TEMPLATE_PATH", DATA_DIR / "submission_template.json"))
GROUND_TRUTH_PATH = Path(os.getenv("GROUND_TRUTH_PATH", DATA_DIR / "ground_truth.json"))
SUBMISSION_PATH = Path(os.getenv("SUBMISSION_PATH", ROOT_DIR / "submission.json"))
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
# Also accepted: OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL (common aliases).
# ---------------------------------------------------------------------------
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or ""
LLM_MODEL = os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL") or ""
LLM_TIMEOUT_SEC = _env_float("LLM_TIMEOUT_SEC", 60.0)
LLM_MAX_RETRIES = _env_int("LLM_MAX_RETRIES", 2)

# Field `model` in submission.json — single source of truth
MODEL_LABEL = (os.getenv("MODEL_LABEL") or LLM_MODEL or "deterministic-formula-engine").strip()

# Optional second OpenAI-compatible endpoint for PDF classify only.
# If unset, CLASSIFY_USE_LLM reuses the primary LLM_* client.
CLASSIFY_API_KEY = os.getenv("CLASSIFY_API_KEY") or ""
CLASSIFY_BASE_URL = os.getenv("CLASSIFY_BASE_URL") or LLM_BASE_URL
CLASSIFY_MODEL = os.getenv("CLASSIFY_MODEL") or LLM_MODEL

# ---------------------------------------------------------------------------
# Runtime knobs
# ---------------------------------------------------------------------------
CONFIDENCE_THRESHOLD = _env_float("CONFIDENCE_THRESHOLD", 0.85)
MAX_BORROWER_CONCURRENCY = _env_int("MAX_BORROWER_CONCURRENCY", 6)
CLASSIFY_USE_LLM = _env_bool("CLASSIFY_USE_LLM", False)

# ---------------------------------------------------------------------------
# Pipeline Behavior Controls
# ---------------------------------------------------------------------------
USE_LLM_FORMULA_READER = _env_bool("USE_LLM_FORMULA_READER", True)

LLM_FORMULA_READER_ONLY_UNKNOWN = _env_bool("LLM_FORMULA_READER_ONLY_UNKNOWN", True)

FORMULA_READER_PREFER_DET_ON_MISMATCH = _env_bool("FORMULA_READER_PREFER_DET_ON_MISMATCH", True)

FORMULA_READER_MAX_TEXT_CHARS = _env_int("FORMULA_READER_MAX_TEXT_CHARS", 900)
# FormulaSpec / JSON — allow enough tokens for thinking models (Sonnet 5) + response
LLM_MAX_TOKENS = _env_int("LLM_MAX_TOKENS", 4096)
PDF_TEXT_PREVIEW_CHARS = 3000
# Soft OOM guard for .txt/.csv/.md/.json extract (latin-1 can load whole file)
MAX_TEXT_FILE_MB = _env_float("MAX_TEXT_FILE_MB", 16.0)
MAX_TEXT_FILE_BYTES = int(MAX_TEXT_FILE_MB * 1024 * 1024)
# pdfplumber extract_tables: only first N pages (full-doc walk can OOM)
MAX_TABLE_PAGES = _env_int("MAX_TABLE_PAGES", 32)
# Cap PDF text extract + OCR raster pages (huge prospectuses)
MAX_PDF_TEXT_PAGES = _env_int("MAX_PDF_TEXT_PAGES", 80)
MAX_OCR_PAGES = _env_int("MAX_OCR_PAGES", 24)

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
            data = json.loads(tpl_path.read_text(encoding="utf-8-sig"))
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
