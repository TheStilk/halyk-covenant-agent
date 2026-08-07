#!/usr/bin/env bash
# Battle day one-shot: OCR check → clear doc_cache → phase3 → validate.
#
# Usage:
#   ./scripts/battle_run.sh /path/to/private-dataset
#   DATA_DIR=/path/to/private ./scripts/battle_run.sh
#   ./scripts/battle_run.sh                 # default DATA_DIR from env or agentic-bank-public
#
# Options (env):
#   KEEP_CACHE=1     do not rm -rf doc_cache
#   SKIP_UV_SYNC=1   skip `uv sync`
#   NO_LLM=1         unset LLM_API_KEY for det-only run (default: leave env as-is)
#
# Exit: non-zero if preflight/OCR, phase3, or validate fails.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# --- resolve DATA_DIR ---
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '2,16p' "$0" | sed 's/^# \?//'
  exit 0
fi

if [[ -n "${1:-}" ]]; then
  export DATA_DIR="$(cd "$1" && pwd)"
elif [[ -n "${DATA_DIR:-}" ]]; then
  export DATA_DIR="$(cd "$DATA_DIR" && pwd)"
else
  export DATA_DIR="$ROOT/agentic-bank-public"
fi

echo "=== BATTLE RUN ==="
echo "ROOT     = $ROOT"
echo "DATA_DIR = $DATA_DIR"
echo "DATE     = $(date -Iseconds 2>/dev/null || date)"

if [[ ! -d "$DATA_DIR" ]]; then
  echo "ERROR: DATA_DIR does not exist: $DATA_DIR" >&2
  exit 1
fi

# --- optional det-only ---
if [[ "${NO_LLM:-0}" == "1" ]]; then
  unset LLM_API_KEY || true
  echo "NO_LLM=1 → LLM_API_KEY unset (det-only)"
fi

# --- uv ---
if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv not found on PATH" >&2
  exit 1
fi
if [[ "${SKIP_UV_SYNC:-0}" != "1" ]]; then
  echo "--- uv sync ---"
  uv sync
fi

# --- OCR toolchain (eng+rus+kaz) ---
echo "--- OCR check ---"
OCR_OK=1
if ! command -v pdftoppm >/dev/null 2>&1; then
  echo "✗ pdftoppm missing (install poppler-utils)"
  OCR_OK=0
else
  echo "✓ pdftoppm: $(command -v pdftoppm)"
fi
if ! command -v tesseract >/dev/null 2>&1; then
  echo "✗ tesseract missing (install tesseract-ocr)"
  OCR_OK=0
else
  echo "✓ tesseract: $(command -v tesseract)"
  LANGS="$(tesseract --list-langs 2>&1 || true)"
  for lang in eng rus kaz; do
    if echo "$LANGS" | grep -qx "$lang"; then
      echo "✓ tesseract lang: $lang"
    else
      echo "✗ tesseract lang missing: $lang  (e.g. tesseract-ocr-$lang)"
      OCR_OK=0
    fi
  done
fi
if [[ "$OCR_OK" != "1" ]]; then
  echo "ERROR: OCR preflight failed — fix before battle run." >&2
  exit 1
fi
echo "OCR check OK"

# --- cache ---
CACHE_DIR="${DOC_CACHE_DIR:-$ROOT/doc_cache}"
if [[ "${KEEP_CACHE:-0}" == "1" ]]; then
  echo "KEEP_CACHE=1 → leaving $CACHE_DIR"
else
  echo "--- clearing cache: $CACHE_DIR ---"
  rm -rf "$CACHE_DIR"
fi

# --- pipeline ---
echo "--- phase3 (full pipeline → submission.json) ---"
uv run python main.py phase3

echo "--- validate ---"
uv run python main.py validate

echo ""
echo "=== BATTLE RUN OK ==="
echo "submission: $ROOT/submission.json"
echo "Next: check BATTLE DIAGNOSTICS above, team/email/model fields, then submit."
exit 0
