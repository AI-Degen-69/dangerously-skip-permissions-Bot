"""Reverse-engineer a wallet's 5m BTC Up/Down strategy from a fill ledger.

Any date range works: a week, a month, a quarter.

Reads a ledger CSV (default: data/leaderboard/dangerously-skip-permissions/raw/dangerously_2026-11-01_to_2026-11-08.csv,
or pass one as argv[1] / TRADES_CSV) and prints the analysis sections (markdown) used in the reports.
The same text is saved as `<csv-stem>_strategy.md` in
`docs/leaderboard-traders/ledgers/<account>/analysis/` when the CSV sits under
`data/leaderboard/<account>/raw/`, otherwise next to the CSV.

Key recovered facts the script relies on:
  - USD_Amount = Shares * Price * (1 + fee), fee per share = 0.07 * p * (1-p) when taker.
  - Zero-fee fills are maker fills; the two never mix inside one transaction hash.
    Newer ledgers drop the hash, so row order is the sort tiebreaker for them.
  - REDEEM USD_Amount ~= Shares => winning token, 0 => losing token.
"""
import csv
import os
import pathlib
import sys
import numpy as np
import pandas as pd
from ..report_kit import REPO_ROOT

csv.field_size_limit(10**9)
DEFAULT_PATH = os.path.join(
    REPO_ROOT,
    "data",
    "leaderboard",
    "dangerously-skip-permissions",
    "raw",
    "dangerously_2026-11-01_to_2026-11-08.csv",
)
PATH = (
    next((a for a in sys.argv[1:] if a.lower().endswith(".csv")), None)
    or os.environ.get("TRADES_CSV")
    or DEFAULT_PATH
)
REQUIRED_COLUMNS = (
    "Timestamp_UTC", "Type", "Market_Slug", "Condition_ID",
    "Outcome", "Token_ID", "Price", "Shares", "USD_Amount",
)
FEE_RATE = 0.07
def load():
    df = pd.read_csv(PATH)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing column(s): {', '.join(missing)}")
    if "Transaction_Hash" not in df.columns:
        # Newer ledgers drop the hash; row order becomes the sort tiebreaker, so
        # the duplicate-tx line in section A reads 0 for them.
        df["Transaction_Hash"] = df.index.to_series().map("{:010d}".format)
    df["ts"] = pd.to_datetime(df["Timestamp_UTC"], utc=True)
    sec = (df["ts"] - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds().astype("int64")
    df["epoch"] = sec
    df["open_ts"] = pd.to_numeric(df["Market_Slug"].str.split("-").str[-1], errors="coerce").fillna(0).astype(int)
    df["close_ts"] = df["open_ts"] + 300
    df["secs_before_close"] = df["close_ts"] - df["epoch"]
    df["offset"] = df["epoch"] - df["open_ts"]
    tr = df[df["Type"] == "TRADE"].copy()
    tr["gross"] = tr["Price"] * tr["Shares"]
    tr["fee"] = tr["USD_Amount"] - tr["gross"]
    tr["is_taker"] = tr["fee"] > 1e-9
    rd = df[df["Type"] == "REDEEM"].copy()
    rb = df[df["Type"].astype(str).str.contains("REBATE")].copy()
    return df, tr, rd, rb
def run():
    if not os.path.isfile(PATH):
        sys.exit(
            f"Ledger not found: {PATH}\n"
            "Pass a ledger .csv path, set TRADES_CSV, or pull one first with "
            "python -m scripts.leaderboard_traders.puller."
        )
    if os.path.getsize(PATH) == 0:
        sys.exit(f"Ledger is empty: {PATH}")
    df, tr, rd, rb = load()
    tok, m = build_markets(tr, rd)
    if tr.empty:
        sys.exit(f"No TRADE rows in {PATH}; nothing to analyse.")
    target = analysis_target(PATH, "_strategy.md")
    tmp = target.with_name(target.name + ".tmp")
    original = sys.stdout
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            sys.stdout = Tee(original, handle)
            try:
                print("# Strategy reverse-engineering - computed sections")
                _kv("Ledger", PATH)
                section_a(df, tr, rd, rb, m)
                section_b(tr, m)
                section_c(m, rb)
                section_d(tr, m)
                section_e(tr, m)
                section_f(tr, m)
                section_g(tr, m, rb)
                section_h(tr, m, tok)
                section_i(tr, m, rb)
            finally:
                sys.stdout = original
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    print(f"\nWrote {target}")
def main():
    try:
        run()
    except Exception as exc:
        print(f"Cannot analyse {PATH}: {exc}", file=sys.stderr)
        sys.exit(1)

from ..report_kit import Tee, analysis_target

from .data import build_markets, q, split_thirds
from .report import SECTION_WIDTH, _kv, _section, md
from .sections import (
    section_a,
    section_b,
    section_c,
    section_d,
    section_e,
    section_f,
    section_g,
    section_h,
    section_i,
)

__all__ = [
    "DEFAULT_PATH", "FEE_RATE", "PATH", "REQUIRED_COLUMNS",
    "SECTION_WIDTH", "Tee", "analysis_target", "build_markets",
    "load", "main", "md", "q", "run", "_kv", "_section",
    "section_a", "section_b", "section_c", "section_d",
    "section_e", "section_f", "section_g", "section_h",
    "section_i", "split_thirds",
]
