# Paper Fidelity Report (Phase 5, 2026-11-07)

Gate specification: 288-window paper run must reproduce the frozen CSV
moments (45 median trades/market, both-sides rate, M0–M4 shape) before any live keys.

## Deterministic sim — `python bot/run_paper.py` (dumb lean, no network)

| Metric | Paper | Target (CSV) | Verdict |
|---|---|---|---|
| Windows | 288 | 288 | ✅ |
| Median trades/window | 44 | 45 | ✅ (M-weights round to 8+10+11+10+5) |
| Mean trades/window | 44 | 58.5 | ⚠️ accepted — CSV fat tails to 404 not modeled, not tuned |
| Both-sides windows | 288/288 | 280/288 | ✅ (straddle preserved) |
| Median cost/window | $432.18 | $316 | ⚠️ documented — flat 0.476 mid-price model vs live spread |
| Mean cost/window | $432.18 | $447 | ✅ |
| Up share (dumb) | 52.3% | ~50% first-side mix | ✅ |
| Up share (−1 tilt) | 20.5% | — | ✅ responds to lean |
| Up share (+1 tilt) | 81.8% | — | ✅ responds to lean |
| Tilted both-sides | 288/288 | 97.2% | ✅ (regression test locks this) |

Lean sweep: dumb 52% Up, ±tilt 82/18 with both-sides kept on every row.
Two past bugs caught by tests and fixed: inverted negative-lean flip, and
sub-0.5 prices collapsing to single-sided. Proportional tilt beyond
|lean|≈0.45 saturates — a tuning knob for later, not a gate blocker.

Unit tests: `python -m unittest bot.tests.test_bot` — **19/19 OK**.

## Live sample — `python -m bot.reconcile` (10 settled + 1 pending, 2026-11-07)

Too small to judge the gate (deterministic sim is the gate), recorded for drift:

- Median 24.5, mean 28, both-sides 10/10, M-shape [40,44,23,29,144] (M4-heavy —
  live dust-floor skips thin mid-window quotes, extremes only late per CSV rule).
- Settled nets: −38.88, +3.00, +0.30, −60.27, +0.30, +0.30, +48.20, −51.27,
  −150.18, +196.42 (winners pay $1/share on reserve prices).

## Redeem verification

`python bot/redeem.py --dry-run`: **10 redeemable** (winners Down/Up as listed
in run output, payouts $30.00–$660.36), no mutation. Real (non-dry) run
intentionally not executed — would mutate `paper_runs/`.

## Kill-switch drill (2026-11-07 21:58Z)

- `kill(state)` → `killed: True`, all further fills blocked.
- Daily-loss cap ($500) → auto-kill, verified.
- `touch bot/kill` → desk `snapshot()` reports `killSwitch: True, halted: True`
  (loop pauses between windows); `rm bot/kill` → `False`. Drill green.

## Decision

Paper fidelity **passes** on the deterministic gate (median, both-sides,
M-shape, lean response). Mean-trade and median-cost deltas are documented
model simplifications, not plumbing failures. Live 24h sample still required
before any funding — current 10-window sample is noise, not signal.
