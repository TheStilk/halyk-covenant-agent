"""Ledger loading and account_id → scenario_id mapping.

txn_id always starts with scenario_id of the borrower whose account holds it.
  Example: TXN-P1-0007 → scenario_id = P1, account_id = ACC-7801
  Example: TXN-P10-0062 → scenario_id = P10 (second hyphen segment)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from agent.config import LEDGER_PATH

# Ghost ids from NaN→str, empty cells, Excel junk
_BAD_ID_TOKENS = frozenset({"", "nan", "none", "null", "<na>", "nat", "n/a", "#n/a"})


def _is_bad_id(value: object) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    s = str(value).strip().lower()
    return s in _BAD_ID_TOKENS


def coerce_amount(value: object) -> Optional[float]:
    """Parse ledger amount: blank→None; US 1,234.56; EU 1.234,56; plain float."""
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        f = float(value)
        return None if f != f else f  # NaN
    s = str(value).strip()
    if not s or s.lower() in _BAD_ID_TOKENS:
        return None
    # strip currency / grouping spaces (incl. NBSP)
    for ch in ("\u00a0", "\u202f", " ", "$", "€", "£", "₸"):
        s = s.replace(ch, "")
    s = re.sub(r"(?i)\b(usd|kzt|eur|gbp)\b", "", s).strip()
    if not s or s in {"-", "—", "–"}:
        return None
    # sign may be paren accounting: (1234.5)
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1].strip()
    if s.startswith("+"):
        s = s[1:]
    if s.startswith("-"):
        neg = True
        s = s[1:]
    if "," in s and "." in s:
        # Last separator is decimal: EU 1.234,56 vs US 1,234.56
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        # single comma + 1–2 fractional digits → EU decimal; else thousands
        if len(parts) == 2 and parts[1].isdigit() and 1 <= len(parts[1]) <= 2:
            s = parts[0].replace(".", "") + "." + parts[1]
        else:
            s = s.replace(",", "")
    try:
        out = float(s)
    except ValueError:
        return None
    if out != out:  # NaN
        return None
    return -out if neg else out


def _parse_amount_series(series: pd.Series) -> pd.Series:
    return series.map(coerce_amount).astype("Float64")


def _parse_date_series(series: pd.Series) -> pd.Series:
    """ISO first (public set), then explicit EU formats, then cautious fallbacks.

    Never apply dayfirst to the whole column — pandas 3 can rewrite YYYY-MM-DD
    under dayfirst=True (2025-06-05 → 2025-05-06).
    """
    raw = series.map(lambda x: "" if _is_bad_id(x) else str(x).strip())
    out = pd.to_datetime(raw, format="%Y-%m-%d", errors="coerce")

    def _fill_from(parsed: pd.Series) -> None:
        nonlocal out
        good = parsed.notna()
        if not good.any():
            return
        out = out.copy()
        out.loc[good.index[good]] = parsed.loc[good]

    need = out.isna() & (raw != "")
    if need.any():
        try:
            _fill_from(pd.to_datetime(raw[need], format="ISO8601", errors="coerce"))
        except (TypeError, ValueError):
            _fill_from(pd.to_datetime(raw[need], errors="coerce"))

    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        need = out.isna() & (raw != "")
        if not need.any():
            break
        _fill_from(pd.to_datetime(raw[need], format=fmt, errors="coerce"))

    need = out.isna() & (raw != "")
    if need.any():
        # last resort: dayfirst only on leftovers (not the full ISO column)
        _fill_from(pd.to_datetime(raw[need], errors="coerce", dayfirst=True))
    return out


def scenario_from_txn_id(txn_id: str) -> str:
    """Extract scenario_id from txn_id (second hyphen-separated token)."""
    parts = str(txn_id).split("-")
    if len(parts) < 2:
        raise ValueError(f"Unexpected txn_id format: {txn_id!r}")
    return parts[1]


def build_account_to_scenario(ledger: pd.DataFrame) -> dict[str, str]:
    """Build account_id → scenario_id mapping from ledger txn_id prefixes.

    If the same account appears with multiple scenario prefixes (should not
    happen for real borrowers), the first observed mapping is kept and a
    warning is printed for conflicts.
    """
    if "txn_id" not in ledger.columns or "account_id" not in ledger.columns:
        raise ValueError("Ledger must contain columns: txn_id, account_id")

    mapping: dict[str, str] = {}
    conflicts: list[tuple[str, str, str]] = []
    skipped = 0

    for txn_id, account in zip(ledger["txn_id"], ledger["account_id"], strict=False):
        if _is_bad_id(txn_id) or _is_bad_id(account):
            skipped += 1
            continue
        account_s = str(account).strip()
        try:
            scenario = scenario_from_txn_id(str(txn_id).strip())
        except ValueError:
            skipped += 1
            continue
        if account_s in mapping and mapping[account_s] != scenario:
            conflicts.append((account_s, mapping[account_s], scenario))
            continue
        mapping[account_s] = scenario

    if skipped:
        print(f"[ledger] WARNING: skipped {skipped} rows with bad txn_id/account_id")
    if conflicts:
        sample = conflicts[:5]
        print(
            f"[ledger] WARNING: {len(conflicts)} account→scenario conflicts "
            f"(sample: {sample})"
        )
    return mapping


def load_ledger(path: str | Path | None = None) -> pd.DataFrame:
    """Load master_ledger_2025.csv as a DataFrame with typed columns."""
    path = Path(path) if path else LEDGER_PATH
    if not path.exists():
        raise FileNotFoundError(f"Ledger not found: {path}")

    df = pd.read_csv(path)
    required = {"txn_id", "date", "account_id", "counterparty", "description", "amount", "currency"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Ledger missing columns: {sorted(missing)}")

    n0 = len(df)
    # Drop empty / NaN txn_id before str coercion turns them into "nan" ghosts
    bad_txn = df["txn_id"].map(_is_bad_id)
    if bad_txn.any():
        n_bad = int(bad_txn.sum())
        print(f"[ledger] WARNING: dropping {n_bad} rows with empty/NaN txn_id")
        df = df.loc[~bad_txn].copy()

    df["amount"] = _parse_amount_series(df["amount"])
    df["date"] = _parse_date_series(df["date"])
    # String ids; avoid pandas NaN → literal "nan"
    df["txn_id"] = df["txn_id"].map(lambda x: str(x).strip())
    df["account_id"] = df["account_id"].map(
        lambda x: "" if _is_bad_id(x) else str(x).strip()
    )
    if len(df) != n0:
        print(f"[ledger] rows after clean: {len(df)} (was {n0})")
    return df


def filter_scenario_accounts(
    account_to_scenario: dict[str, str],
    scenario_ids: list[str] | set[str] | None = None,
) -> dict[str, str]:
    """Keep only accounts whose scenario_id is in the submission set.

    Useful to ignore noise accounts (ACC-9xxx) whose txn prefix is numeric.
    """
    if scenario_ids is None:
        return dict(account_to_scenario)

    wanted = set(scenario_ids)
    return {acc: sc for acc, sc in account_to_scenario.items() if sc in wanted}


def transactions_for_account(ledger: pd.DataFrame, account_id: str) -> list[dict[str, Any]]:
    """Return ledger rows for one account as a list of dicts (JSON-serializable)."""
    subset = ledger[ledger["account_id"] == account_id].copy()
    if subset.empty:
        return []

    records: list[dict[str, Any]] = []
    for _, row in subset.iterrows():
        records.append(
            {
                "txn_id": str(row["txn_id"]),
                "date": row["date"].strftime("%Y-%m-%d") if pd.notna(row["date"]) else None,
                "account_id": str(row["account_id"]),
                "counterparty": str(row["counterparty"]) if pd.notna(row["counterparty"]) else "",
                "description": str(row["description"]) if pd.notna(row["description"]) else "",
                # None when CSV amount is blank/NaN — metrics may fill from notes/treasury
                "amount": float(row["amount"]) if pd.notna(row["amount"]) else None,
                "currency": str(row["currency"]) if pd.notna(row["currency"]) else "USD",
            }
        )
    return records


def _is_noise_account(account_id: str) -> bool:
    """Open-set noise convention ACC-9xxx; do not require ACC-7* borrowers."""
    m = re.match(r"ACC-(\d+)$", str(account_id).upper())
    if not m:
        return False
    return m.group(1).startswith("9")


def scenario_to_account(account_to_scenario: dict[str, str]) -> dict[str, str]:
    """Invert mapping: scenario_id → account_id (one-to-one for borrowers).

    Preference when multiple accounts map to one scenario:
      non-noise (not ACC-9xxx) over noise — not hard-coded to ACC-7*.
    """
    inverted: dict[str, str] = {}
    for acc, sc in account_to_scenario.items():
        if sc in inverted and inverted[sc] != acc:
            existing = inverted[sc]
            if not _is_noise_account(acc) and _is_noise_account(existing):
                inverted[sc] = acc
            continue
        inverted[sc] = acc
    return inverted
