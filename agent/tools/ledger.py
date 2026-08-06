"""Ledger loading and account_id → scenario_id mapping.

Per Master Plan §7 step 1 and CASE description:
  txn_id always starts with scenario_id of the borrower whose account holds it.
  Example: TXN-P1-0007 → scenario_id = P1, account_id = ACC-7801
  Example: TXN-P10-0062 → scenario_id = P10 (second hyphen segment)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from agent.config import LEDGER_PATH


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

    for txn_id, account in zip(ledger["txn_id"], ledger["account_id"], strict=False):
        account = str(account)
        scenario = scenario_from_txn_id(str(txn_id))
        if account in mapping and mapping[account] != scenario:
            conflicts.append((account, mapping[account], scenario))
            continue
        mapping[account] = scenario

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

    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["txn_id"] = df["txn_id"].astype(str)
    df["account_id"] = df["account_id"].astype(str)
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
                "amount": float(row["amount"]) if pd.notna(row["amount"]) else 0.0,
                "currency": str(row["currency"]) if pd.notna(row["currency"]) else "USD",
            }
        )
    return records


def scenario_to_account(account_to_scenario: dict[str, str]) -> dict[str, str]:
    """Invert mapping: scenario_id → account_id (one-to-one for borrowers)."""
    inverted: dict[str, str] = {}
    for acc, sc in account_to_scenario.items():
        if sc in inverted and inverted[sc] != acc:
            # Prefer ACC-7xxx borrower accounts over noise ACC-9xxx
            existing = inverted[sc]
            if acc.startswith("ACC-7") and not existing.startswith("ACC-7"):
                inverted[sc] = acc
            continue
        inverted[sc] = acc
    return inverted
