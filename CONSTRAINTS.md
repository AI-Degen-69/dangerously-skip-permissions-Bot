# Project Constraints & Quality Guardrails

Branch: i6/decouple-trade-execution-loop | Issue: #6

## 1. Zero Regressions
- All 43 pre-existing unit tests in `bot/tests/` must pass cleanly without modification to unrelated test assertions.
- Test runner: `python -m unittest discover -s bot/tests` must exit with returncode 0.

## 2. Timing & Rate Limit Guardrails
- **Active REST Fallback Polling Cadence**: Must poll between 1.0s and 1.5s when WebSocket is disconnected or stale (>3.0s). Never faster than 0.5s (to protect Polymarket CLOB 10-20 req/s rate limits), never slower than 2.0s (to eliminate multi-second blind spots).
- **Execution Loop Cadence**: No blocking 5-second sleeps in `bot/live_paper.py`. Event wait / tick checks must wake up within <=250ms upon incoming ticks.
- **Execution Spacing / Anti-Runaway Gating**: Dynamic taker fills must be gated by tick changes or minimum execution spacing (>=0.5s) so the engine never burns multiple clips in a single millisecond on a static orderbook.

## 3. Preserved Trading Invariants
- Dual-sided straddle + hold-to-redeem architecture remains untouched.
- Microprice lean calculation and confidence weighting formula must remain verbatim.
- Window budget ($4,000 max cost) and daily stop loss ($500) remain strictly enforced via `check_window` and `assert_single_window`.
- M1-M3 extreme price filtering ($0.15 < px < 0.85) and M4 late-window snipe regime remain intact.

## 4. Anti-Cheat & Code Standards
- Zero test deletions, zero `@unittest.skip` additions to bypass failing tests.
- Boring, simple implementation: thread-safe condition / background worker in `bot/ws.py` and event-driven loop in `bot/live_paper.py`.
