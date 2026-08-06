"""Configuration for the Halyk Covenant Monitoring Agent."""

from __future__ import annotations

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
TEAM_NAME = os.getenv("TEAM_NAME", "halyk-covenant-agent")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "team@example.com")
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

# Covenant section keys expected in every scenario
COVENANT_IDS = ("6.1", "6.2", "6.3")
