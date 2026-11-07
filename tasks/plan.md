# Task Plan: Mimic dangerously-skip-permissions 5m BTC Up/Down Bot

## Goal
Build a Python live-trading bot that reproduces the measured execution behavior of `0xc533…69a9` (buy-only straddle-plus-lean, 30-share clips, every 5-min BTC window, hold-to-redeem) with a pluggable lean signal, validated by 24h paper fidelity before any live size.

## Current Phase
Phase 5 complete — hand off to Station IV (review)

## Phases

### Phase 1: Requirements & Discovery
- [x] Reverse-engineer CSV execution (timing, sizing, tilt, M4 fade)
- [x] Capture Polymarket SDK/API surface from docs/polymarket-sdks-and-api
- [x] Confirm stack choice: Python `polymarket-client` (py-sdk) as default
- [x] Confirm paper-first constraint and no live funding until M4 gate
- **Status:** complete

### Phase 2: Planning & Structure
- [x] Define module layout (discovery, signal, executor, risk, redeem, reconcile)
- [x] Freeze execution constants from CSV (clips, caps, schedule)
- [x] Define lean-signal interface (lean in [-1,+1] + confidence)
- [x] Document decisions with rationale in findings.md
- **Status:** complete

### Phase 2b: CRM hosts bot (operator request 2026-11-07)
- [x] Worker hosts control-plane: `bot_windows` + `bot_trades` tables (append-only schema), `/api/bot/status|constants|windows|windows/seed`
- [x] App hosts dashboard: `/bot` page + nav, frozen 24h moments (288 windows, 58.5/45 trades, 97.2% both-sides, 30-share clip)
- [x] Python package `bot/`: `constants.py` (frozen), `signal.py` (Dumb + BookMicroprice stub), `__init__.py`
- [x] Fix Windows `scripts/postbuild.mjs` path (fileURLToPath) — build passes
- **Status:** complete

### Phase 3: Implementation (paper executor first)
- [x] Gamma discovery: current/next `btc-updown-5m` event, token_ids, condition_id (`bot/discovery.py` — `get_window`/`current_and_next`, live verified)
- [x] Executor state machine: T+3–25s open → +15s hedge → M1–M3 work → M4 snipe → hold (`bot/executor.py` `plan_window` + `bot/live_paper.py` `trade_window`, live BUY prices, non-blocking settle)
- [x] Risk: per-window caps, clip limiter, single-window invariant, kill-switch, heartbeats (`bot/risk.py` — `check_window`/`clip_shares`/`kill` + `assert_single_window`/`heartbeat`/`is_stale`; kill file `bot/kill`; `state.json` updatedAtMs heartbeat)
- [x] Redeem + reconcile jobs (redeemable scan, CSV dump reuse) (`bot/redeem.py` `--dry-run`/mark/`--csv` REDEEM rows; `bot/reconcile.py` `fidelity()` vs frozen moments; `bot/run_paper.py` 288-window fidelity: median 44 vs 45)
- [x] Dumb signal (lean=0) so plumbing is testable without alpha (`bot/signal.py` `DumbLean`; `BookMicropriceLean` stub + live `microprice_lean` in `live_paper.py`)
- **Status:** complete 2026-11-07

### Phase 4: Testing & Verification
- [x] Unit tests — `bot/tests/test_bot.py` (18 tests, unittest + mock pattern)
- [x] 288-window paper run; diff vs CSV moments (median 44 vs 45, both 288/288 vs 280/288, mean $432 vs $447)
- [x] Backtest lean candidates — deterministic sweep (dumb even 52% Up; ±tilt 82/18 with both-sides kept); PolyTest/Codex historical replay deferred (needs external book history)
- **Status:** complete 2026-11-07

### Phase 5: Delivery
- [x] Paper fidelity report + live micro-size runbook (`docs/bot-fidelity-report.md` + `bot/RUNBOOK.md`)
- [x] Redeem verification + kill-switch drill (`redeem.py --dry-run` 10 redeemable, kill drill 2026-11-07 green)
- [x] Hand off with run/operate docs (`bot/RUNBOOK.md`)
- **Status:** complete 2026-11-07

## Key Questions
1. Python (py-sdk) vs TypeScript (ts-sdk) for live trader? Default: Python, matches repo.
2. Lean signal source: spot momentum vs book microprice vs TWAP gap — which to build first?
3. Paper duration before live: 288 windows (24h) minimum acceptable?
4. Funding/risk sign-off: who approves live keys and daily loss cap?

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Clone execution, isolate signal | CSV proves execution; lean signal is unobserved |
| Paper executor before alpha | Validates plumbing without funding risk |
| Buy-only hold-to-redeem, no sells | Matches 16,855 BUY / 0 SELL observation |
| Python `polymarket-client` 0.7.1 (PublicClient/AsyncPublicClient, Python 3.12.10 verified) | Official py-sdk; operator confirmed 2026-11-07; correct import is `from polymarket import PublicClient` |
| Paper-first 288 windows (24h) before any live keys | Operator confirmed 2026-11-07; fidelity gate: 45 trades/market median, both-sides rate, M0-M4 shape |
| Lean first: book microprice (lean in [-1,+1] + confidence) | Operator confirmed 2026-11-07; CSV shows lean forms mid-window; dumb lean=0 for plumbing first |
| Risk sign-off: operator approves, cap set next step | Operator confirmed 2026-11-07; no live funding until M4 gate |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| | | |

## Notes
- Re-read this plan before major decisions.
- Log ALL errors; never repeat a failed action.
- External/web content goes to findings.md, never task_plan.md.
