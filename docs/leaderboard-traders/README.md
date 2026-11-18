# Leaderboard traders

Reverse-engineering of Polymarket 5-minute BTC Up/Down wallets seen on the
leaderboard, and how the bot compares with them. The public API exposes fills
only, never quotes, so every number here is reconstructed from filled trades.

Run every command from the repo root. `scratch/` and `data/` are gitignored.

## Layout

| Path | Contents |
|---|---|
| `data/leaderboard/<account>/raw/` | Trade-ledger CSVs written by the puller (the `<tag>_<date>_partial.csv` autosave also lives here during a crawl) |
| `ledgers/<account>/reports/` | Finished write-ups about that account |
| `ledgers/<account>/analysis/` | Machine output from both analysers for that account's ledgers |
| `scripts/leaderboard_traders/` | Pull and analysis code (Python 3.12): `puller`, `strategy`, `mechanics`, plus shared `report_kit` |
| `scripts/leaderboard_traders/tests/` | Unit tests for the three tools |

One account = one folder, split by kind: raw CSVs under `data/leaderboard/`,
reading matter under `docs/leaderboard-traders/ledgers/`. Nothing
account-specific sits anywhere else.

```
data/leaderboard/
  dangerously-skip-permissions/
    raw/        dangerously_2026-11-01_to_2026-11-08.csv
docs/leaderboard-traders/ledgers/
  dangerously-skip-permissions/
    reports/    weekly_strategy_2026-11-01_to_2026-11-08.md
    analysis/   dangerously_2026-11-01_to_2026-11-08_strategy.md
                dangerously_2026-11-01_to_2026-11-08_mechanics.md
```

The puller creates all three folders on first use, anchored to the repo root so
the output lands in the same place whatever directory you run it from.

## Scripts

You can execute the suite through the unified module CLI (`python -m scripts.leaderboard_traders <cmd>`) or the standalone runner scripts:

| Command | Direct Script | Purpose | Input / Target |
|---|---|---|---|
| `python -m scripts.leaderboard_traders fetch` | `python scripts/fetch_trader_activity.py` | Fetch Polymarket account activity into the 11-column ledger CSV (`Timestamp_UTC, Type, Market, Outcome, Side, Price, Shares, USD_Amount, Condition_ID, Token_ID, Market_Slug`). Options: `-u <wallet>`, `-d <date\|max>`, `--days <1\|7>`, `-o <path>`. Lands in `data/leaderboard/<account>/raw/`. | Polymarket Data API v2 + Gamma API |
| `python -m scripts.leaderboard_traders strategy` | `python scripts/analyze_trader_activity.py strategy` | Strategy reconstruction: pair cost, maker/taker volume, fee rebates, timing fingerprints, phase thirds. Saves report to `ledgers/<account>/analysis/<csv-stem>_strategy.md`. | Ledger CSV path |
| `python -m scripts.leaderboard_traders mechanics` | `python scripts/analyze_trader_activity.py mechanics` | Wallet mechanics: first-leg price/time vs outcome, first-leg decay, second-leg pricing, ticket sizing, ladder order. Saves report to `ledgers/<account>/analysis/<csv-stem>_mechanics.md`. | Ledger CSV path |

Both analysers name their output after the CSV, so several spans for one account
accumulate side by side instead of overwriting each other.

## Ledgers

Exports are local working files (`data/` is gitignored); commit only the small
ones worth keeping with the research. `data/leaderboard/<account>/raw/` holds
whatever the puller produced for that account, dated
`<tag>_<range>.csv`, or `<tag>_<windows>-windows_<days>-days.csv` after a `max`
crawl. Older exports that predate the column trim still carry `Proxy_Wallet`,
`Transaction_Hash` and `Event_Slug`; the analysers ignore the extras.

## Reproduce

```powershell
# One week: lands in data/leaderboard/dangerously-skip-permissions/raw/dangerously_2026-11-01_to_2026-11-08.csv
python -m scripts.leaderboard_traders fetch -u dangerously-skip-permissions -d "2026-11-08 21:35" --days 7
# (or: python scripts/fetch_trader_activity.py -u dangerously-skip-permissions -d "2026-11-08 21:35" --days 7)

# Full history: crawl back until the account runs dry, then wait at the checkpoint
python -m scripts.leaderboard_traders fetch -u dangerously-skip-permissions -d max

# Rebuild every table in the strategy reports
#   -> docs/leaderboard-traders/ledgers/dangerously-skip-permissions/analysis/dangerously_2026-11-01_to_2026-11-08_strategy.md
python -m scripts.leaderboard_traders strategy data/leaderboard/dangerously-skip-permissions/raw/dangerously_2026-11-01_to_2026-11-08.csv

# Wallet mechanics for any account and window
#   -> docs/leaderboard-traders/ledgers/dangerously-skip-permissions/analysis/dangerously_2026-07-17_to_2026-11-08_mechanics.md
python -m scripts.leaderboard_traders mechanics data/leaderboard/dangerously-skip-permissions/raw/dangerously_2026-07-17_to_2026-11-08.csv

# Tests
python -m pytest scripts/leaderboard_traders/tests -q
```

## Known gaps

- `python -m scripts.leaderboard_traders.mechanics` values shares still held in a resolved market only when
  a REDEEM row names the winning side. Without one the outcome is unknown, so
  that market is reported as a `$0..$1`-per-share P&L range and left out of the
  rate columns and of the exact net total.
- `python -m scripts.leaderboard_traders.mechanics` reads the market length from the slug (`-5m-`, `-15m-`,
  `-1h-<epoch>`); a slug without that clock is counted in the exclusion line, not
  analysed.
