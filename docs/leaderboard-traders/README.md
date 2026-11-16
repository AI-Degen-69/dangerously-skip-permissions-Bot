# Leaderboard traders

Reverse-engineering of Polymarket 5-minute BTC Up/Down wallets seen on the
leaderboard, and how the bot compares with them. The public API exposes fills
only, never quotes, so every number here is reconstructed from filled trades.

Run every command from the repo root. `scratch/` and `data/` are gitignored.

## Layout

| Path | Contents |
|---|---|
| `ledgers/<account>/raw/` | Trade-ledger CSVs written by `save-trades-to-csv.py` (the `<tag>_<date>_partial.csv` autosave also lives here during a crawl) |
| `ledgers/<account>/reports/` | Finished write-ups about that account |
| `ledgers/<account>/analysis/` | Machine output from both analysers for that account's ledgers |
| `scripts/` | Pull and analysis scripts (Python 3.12) |
| `tests/` | Unit tests for `save-trades-to-csv.py`, `analyze_mechanics.py` and `analyze_strategy.py` |

One account = one folder under `ledgers/`. Its raw exports, its reports and its
analysis output all sit inside it; nothing account-specific sits at a root.

```
ledgers/
  dangerously-skip-permissions/
    raw/        dangerously_2026-11-01_to_2026-11-08.csv
    reports/    weekly_strategy_2026-11-01_to_2026-11-08.md
    analysis/   dangerously_2026-11-01_to_2026-11-08_strategy.md
                dangerously_2026-11-01_to_2026-11-08_mechanics.md
```

The puller creates `raw/`, `reports/` and `analysis/` on first use, anchored to
`docs/leaderboard-traders/` so the output lands in the same place whatever
directory you run it from.

## Scripts

| Script | Purpose | Input |
|---|---|---|
| `save-trades-to-csv.py` | Pull Polymarket activity into the 11-column ledger CSV (`Timestamp_UTC, Type, Market, Outcome, Side, Price, Shares, USD_Amount, Condition_ID, Token_ID, Market_Slug`). `-u` username/@handle/profile URL/address, `-d` window end or `max` to crawl back until the account runs dry (also offered in the interactive date prompt, where `cancel` or Ctrl+C quits), `--days 1\|7`, `-o` override. Without `-o` the file lands in `ledgers/<account>/raw/`; `max` names it after the pull itself (`<tag>_<windows>-windows_<days>-days.csv`, counting distinct market slugs and UTC days) and blocks at a checkpoint until you answer (Enter saves, `c` keeps pulling); during the crawl it autosaves `ledgers/<account>/raw/<tag>_<date>_partial.csv` every 5 windows and prints an ETA once it knows the account's first fill (`--no-autosave` disables) | Polymarket data-api + gamma API |
| `analyze_strategy.py` | Strategy reconstruction over any span, one week to a quarter: pair cost, rebates, timing fingerprint, per-day regime table, phase thirds. Prints the markdown and saves it to `ledgers/<account>/analysis/<csv-stem>_strategy.md` (next to the CSV when it sits outside `ledgers/<account>/raw/`) | CSV argument, `TRADES_CSV`, or the default ledger |
| `analyze_mechanics.py` | Wallet mechanics in one pass: first-leg price/time vs outcome (cash P&L from buys, sells, redeems and merges), first-leg decay, second-leg pricing, ticket sizing, clip size per price level, ladder order. Rates carry their sample size and a Wilson 95% CI; unresolved markets are a reported P&L range and each table names what it excluded. Prints the markdown and saves it to `ledgers/<account>/analysis/<csv-stem>_mechanics.md` (same fallback next to the CSV) | CSV argument or `TRADES_CSV` (any account, any window) |

Both analysers name their output after the CSV, so several spans for one account
accumulate side by side instead of overwriting each other.

## Ledgers

Exports are local working files; commit only the small ones worth keeping with
the research. `raw/` holds whatever the puller produced for that account, dated
`<tag>_<range>.csv`, or `<tag>_<windows>-windows_<days>-days.csv` after a `max`
crawl. Older exports that predate the column trim still carry `Proxy_Wallet`,
`Transaction_Hash` and `Event_Slug`; the analysers ignore the extras.

## Reproduce

```powershell
# One week: lands in ledgers/dangerously-skip-permissions/raw/dangerously_2026-11-01_to_2026-11-08.csv
python docs/leaderboard-traders/scripts/save-trades-to-csv.py -u dangerously-skip-permissions -d "2026-11-08 21:35" --days 7

# Full history: crawl back until the account runs dry, then wait at the checkpoint
python docs/leaderboard-traders/scripts/save-trades-to-csv.py -u dangerously-skip-permissions -d max

# Rebuild every table in the strategy reports
#   -> ledgers/dangerously-skip-permissions/analysis/dangerously_2026-11-01_to_2026-11-08_strategy.md
python docs/leaderboard-traders/scripts/analyze_strategy.py docs/leaderboard-traders/ledgers/dangerously-skip-permissions/raw/dangerously_2026-11-01_to_2026-11-08.csv

# Wallet mechanics for any account and window
#   -> ledgers/dangerously-skip-permissions/analysis/dangerously_2026-07-17_to_2026-11-08_mechanics.md
python docs/leaderboard-traders/scripts/analyze_mechanics.py docs/leaderboard-traders/ledgers/dangerously-skip-permissions/raw/dangerously_2026-07-17_to_2026-11-08.csv

# Tests
python -m pytest docs/leaderboard-traders/tests -q
```

## Known gaps

- `analyze_mechanics.py` values shares still held in a resolved market only when
  a REDEEM row names the winning side. Without one the outcome is unknown, so
  that market is reported as a `$0..$1`-per-share P&L range and left out of the
  rate columns and of the exact net total.
- `analyze_mechanics.py` reads the market length from the slug (`-5m-`, `-15m-`,
  `-1h-<epoch>`); a slug without that clock is counted in the exclusion line, not
  analysed.
