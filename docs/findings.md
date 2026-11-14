# Findings & Decisions

## Requirements
- Mimic `0xc533…69a9` 5-min BTC Up/Down execution from `dangerously-skip-permissions_24h_trades.csv`.
- Buy-only, hold-to-settlement, redeem; every 5-min slot; one window at a time.
- Paper-first; no live funding until the execution-health readout looks right.
- Python default (matches repo: `scripts/save-trades-to-csv.py`, `unittest` in `tests/`).

## Research Findings
- CSV: 17,416 rows = 16,855 BUY + 559 REDEEM + 2 rebates; 0 SELLs; 288 markets = full 24h coverage.
- Economics in-window: cost $128,718, payout $129,251, net +$533 (+0.4%); 280 resolved, 130 profitable (46.4%); median net -$3.71, mean +$3.15; tails -$724 / +$657. Last window `…1794068700` ($181.89) has no redeem yet (cutoff artifact).
- Entry: first touch median 13s (mean 24s); first side 152 Down / 136 Up; first price mean 0.476. Hedge leg median +15s; 25% within 5s, 69% within 30s; 8/288 single-sided.
- Lean: median |tilt| 28%; first-trade side predicts final lean only 61% — lean forms mid-window.
- Adds: same-side step mean +0.0006, ~40% flat (level-chewing), ~30% up / ~28% down. Size flat in shares (~15–18) across price bands; USD scales with price (~$3.50 / ~$8 / ~$14).
- Cadence: M0 3,081 / M1 3,821 / M2 4,289 / M3 3,914 / M4 1,750. Median gap 1s, 43.5% sub-second, bursts to 12–15/sec.
- Late behavior: M4 fades; extremes only late (19.8% <=15c, 11.4% >=85c vs ~1% in M0).
- Sizing: 30.4% are exactly 30.0 shares; cap 50; 719 dust probes <=0.05; mean $7.64/ticket; 58.5 trades/market mean, 45 median; $447 mean / $316 median per window, max $3.8K. No martingale (91 vs 85 escalation symmetry).
- Account (live profile + Data API): +$416.1K total PnL, $25.5M volume, 30,076 markets, Obsidian tier 6; past-day +$6,558 (mark-to-market, differs from CSV window net). Lazy redeeming (Sept winners still REDEEMABLE).

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| `Polymarket/py-sdk` (`polymarket-client` 0.7.1 verified 2026-11-07, Python 3.12.10) | Official Python SDK; matches repo language and test style; correct import `from polymarket import PublicClient, AsyncPublicClient` (not `polymarket.client` / `polymarket_client`); exposes `PublicClient`, `AsyncPublicClient`, `SecureClient`, `AsyncSecureClient` |
| Gamma for discovery (`GET /events?slug=btc-updown-5m-<epoch>`) | Public, no auth; gives token_ids + condition_id per window |
| CLOB via SDK (FAK taker), raw `POST /order` fallback | Taker-only flow matches Obsidian taker profile |
| Data API v2 for reconcile (`/v2/positions`, `/v2/activity`, `/v2/value`) | Public; same envelope/cursor pattern as existing fetch script |
| CLOB WS orderbook/prices + external BTC spot WS for lean | Lean signal is unobserved in CSV; needs exogenous input |
| Executor split from signal (`lean` in [-1,+1] + confidence) | Lets straddle plumbing validate before any alpha |
| Redeem batch job, weekly cadence acceptable | Target account leaves winners unclaimed for weeks |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Profile-stats endpoints 404/410 (`/v2/users/<w>/stats`, gamma `/users/<w>`) | Used profile page + `/v2/positions` + `public-profile` instead |
| CSV window net (+$533) vs profile past-day (+$6,558) mismatch | Mark-to-market + fees + cutoff window; use lifetime +$416K as edge evidence |

## Resources
- `dangerously-skip-permissions_24h_trades.csv` — 24h activity under analysis
- `scripts/save-trades-to-csv.py` — Data API v2 cursor pattern to reuse for reconcile
- `tests/test_save_trades_to_csv.py` — unittest + mock pattern to extend
- `docs/polymarket-sdks-and-api/01-Polymarket-Repositories.md` — py-sdk / ts-sdk / rs-clob-client-v2
- `docs/polymarket-sdks-and-api/02-Polymarket-API-Reference.md` — Gamma / CLOB / Data API v2 / Bridge / WS + PolyBolt, Codex, PolyTest
- `docs/polymarket-sdks-and-api/03-Polymarket-Resources-Links.md` — link index
- Live profile: https://polymarket.com/@dangerously-skip-permissions

## Visual/Browser Findings
- Profile page shows $332.62 positions value, $753.03 biggest win, 30,076 markets, +$416.1K PnL, $25.5M volume; open positions dominated by old BTC 5m winners (lazy redeem confirmed visually).
