# Up/Down Paper Trading Desk: User & Operations Guide

Welcome to the **dangerously-skip-permissions** paper trading desk. This system studies the 5-minute Bitcoin Up/Down binary options strategy practiced by target Polymarket trader `0xc53375ff94e96100f2b30a4b5775db35218d69a9`.

The environment runs **100% paper-only**—no live funds, private keys, or wallet connections required. The engine is **maker-first**: it rests bids on both outcomes, manages the queue ahead of each resting clip, and balances inventory instead of blindly taking the ask.

---

## 1. Quick Start (Launch Everything in 2 Steps)

### Step 1: Start the Python Desk API
The desk API is a lightweight stdlib loopback service. Its default bind is `127.0.0.1:8789` (set in `bot/api.py` and mirrored in `src/app/lib/bot.ts`); it coordinates the background loop, streams book/print data, and serves run-scoped metrics.

```bash
# Terminal 1: Launch Backend API (default 127.0.0.1:8789)
python bot/api.py

# Optional: bind a different port (must match on both sides)
# python bot/api.py --port 8789
# VITE_BOT_ORIGIN=http://127.0.0.1:8789 bun run dev
```

*Verify:* Navigate to `http://127.0.0.1:8789/api/bot/control` in your browser. You should receive a JSON status response (`"running": false`, `"mode": "paper"`).

On Windows, `bot/restart_api.ps1` does a clean restart: it finds any process holding the API port or running `bot/api.py`, stops it, waits until the port is released, spawns a fresh background instance, and verifies the control endpoint responds:

```powershell
powershell -ExecutionPolicy Bypass -File bot/restart_api.ps1
```

---

### Step 2: Start the Web Desk UI
The frontend is a React + Vite dashboard with six sections.

```bash
# Terminal 2: Launch Frontend Desk
bun run dev
# or: npm run dev / pnpm run dev
```
Open **[http://localhost:5173/](http://localhost:5173/)** in your web browser.

---

### Step 3: Start the Paper Trading Loop
You can start the trading loop in one of two ways:

- **Via the UI:** Click the blue **`Start bot`** button in the header bar of the **Dashboard** or **Live Desk**, or launch a candidate run from **A/B Lab**.
- **Via the Terminal (Manual / Headless):**
  ```bash
  # Continuous loop across all 5-minute windows:
  python bot/live_paper.py --loop

  # Trade exactly one window and exit:
  python bot/live_paper.py --once

  # Target an explicit 5-minute epoch:
  python bot/live_paper.py --slot 1794086700

  # Name the run workspace explicitly:
  python bot/live_paper.py --loop --run-id run_20261117_005536_paper_hydrogen_v2_0
  ```

### Step 4: Analyze a Run Offline (no live feed needed)
Every run records a tape of book snapshots and trade prints under `bot/runs/<run_id>/tape/`. You can replay it deterministically or re-audit fills without touching the live engine:

```bash
# Counterfactual replay of one recorded run with a placement rule:
python -m bot.replay --run bot/runs/run_20261113_080232_paper_dsp_v2_6 --rule v2.6

# Replay every recorded run (canned v2.7 / hydrogen rules also available):
python -m bot.replay --runs all --rule hydrogen

# Re-stamp a whole run's verified / attainable verdicts from its tape:
python bot/verify_run.py --run-id run_20261117_005536_paper_hydrogen_v2_0 --audit
```

Replay never reads a window's own fills to drive the simulation—only its condition id, slug (start epoch), and winner for scoring. Fills are re-derived from the recorded book and prints via `bot.fill_model`.

---

## 2. Navigating the Desk UI

The web desk consists of **6 sections** accessible from the sidebar navigation: Dashboard, Live Desk, A/B Lab, Config, Strategy, and Settings.

### 1. Dashboard (`/`) — Performance & Run History
The command center for analyzing execution performance across settled windows.

- **Session Selector (Header Bar):**
  - Switch between **`Live session`** (monitoring the active trading loop) and past historical runs (`run_YYYYMMDD_...`).
  - Selecting a past run activates **`View Only (past run)`** mode. An amber warning card appears and mutating controls are disabled so you can safely audit past runs without risking live orders.
  - Click **`Return to Live`** anytime to jump back to live operations.
- **Top Metrics Strip:**
  - Shows total settled windows, overall Net PnL ($), win rate (%), and median fills per window.
- **Cumulative PnL Curve:**
  - Visual chart of your cumulative paper bankroll trajectory.
- **Rebate Toggle (`Net before rebates` card):**
  - Switches taker and maker rebates in or out of the P&L. Off, the net, win rate, expectancy, profit factor, Sharpe, the window log and the chart all fall back to price alone, and the rebate cards show what is being left out.
- **Verified Only Switch (chart card):**
  - Counts only the fills the recorded trade prints corroborate — a maker fill at limit L is confirmed when the tape printed at least the clip's size at or below L inside that window. Every window is recomputed from its confirmed fills, and a window without one drops out of the view entirely. Taker fills cannot be checked in paper mode (there is no real book) and the fills the market never traded drop out too, so read the number as a **lower bound**, not an estimate.
  - The line under the chart says how much of the tape is corroborated: confirmed maker fills vs all maker fills, the fills that never traded, the taker fills that cannot be checked, and how much payout rests on them.
  - The verifier only stamps the window the loop is trading. After a run that started before the verifier existed, re-stamp the whole run against the recorded prints with `python bot/verify_run.py` (see `bot/RUNBOOK.md`), otherwise the view covers a slice of the tape instead of the tape.
- **Attainable P&L (chart card header):**
  - The second number beside the net is what the same windows would have made if a maker fill really had to be filled: taker **SELL** prints at or below the limit, after the fill, carrying more size than the queue already resting at that price. Prints record the taker side, so a BUY print never fills a resting bid.
  - Taker fills always count (they take the ask); the gap between the two numbers is entirely maker fills that could never have filled. Hover it for the count of surviving fills and how many windows the auditor covered.
  - It is **before rebates**, so turn the rebate switch off to compare it with the net beside it. A window whose tape holds no print at all is left out of both sides — silence is not proof that nothing traded.
  - The line under the chart says the same thing in counts: how many maker fills could actually fill, and how many never could.
  - The same audit runs **while the run is going**, and the `STATUS` column of `Orders & Fills` shows its per-fill verdict: `Attainable` as soon as the selling recorded so far could have filled that order, `Phantom` once the window's tape is complete and it could not. `Verified` remains the weaker tape check — the level traded at your size — and stays on a row only until the audit has judged it.
- **Timeframe Filter (below the chart):**
  - `1H · 12H · 1D · 1W · 1M · All` scopes the KPI cards, the chart, the window bars and the window log to that trailing window. The chart is re-based on the capital held when the window opened, so the curve starts where the account actually stood.
- **Execution health (card below the chart):**
  - No frozen-tape comparison: every row is either a plain measurement or judged against the strategy's own rules. **Both sides covered** is the straddle invariant — a single-sided window is a missed hedge. **Median pair cost** is the lock-in cost of both-sided windows against your configured `maxPairCost`. **Queue fill rate** is how many audited maker fills had selling behind the queue ahead; the rest never could fill. **Zero-price fills** must stay at zero. Fills and cost per window are shown as median · mean with no target.
  - The minute matrix under the rows splits the audited maker fills per minute M0–M4 into fills a real bid could have got (accent) and phantom fills the queue never cleared (red). It answers where in the window the quoting works, not whether it resembles an old wallet.
- **Settled Windows Table:**
  - Displays each 5-minute window slug, trade count, dollar volume, settlement outcome (Up / Down), and net PnL.

---

### 2. Live Desk (`/live`) — Real-Time Window Execution
Watch the bot make trading decisions live inside the active 5-minute window.

- **Connection Health Badges:**
  - `WSS Live (<40ms)`: Live streaming orderbook connected to Polymarket CLOB (`book`, `price_change`, and `last_trade_price` trade prints).
  - `REST Fallback`: Active background polling (1.0s–1.5s cadence) if WebSocket is stale.
- **Interactive Depth & Book Panel:**
  - Displays real-time bid/ask prices and depth for both the **Up** and **Down** contracts.
- **Live Fills Feed:**
  - Streams every execution ticket: exact minute (M0–M4), outcome, role (maker/taker), price (cents), shares, and total cost.
- **Pause / Resume Entries Button:**
  - Toggles the soft kill-switch on the fly without stopping the bot process.

---

### 3. A/B Lab (`/ab-test`) — Run & Setup Comparison
Run a statistical hypothesis test between a **baseline** run and a **candidate** run/setup.

- Pick the baseline and candidate by run id or by any entry in `STRATEGY_SETUPS`; a candidate can be launched directly from the page ("Launch Candidate Run (B)") to start gathering samples live.
- **Welch's one-tailed two-sample t-test** (α = 0.05, 80% power) over *active* windows only (`fills > 0`); zero-fill windows are excluded. The page shows the t-statistic against its dynamic critical value, the rejection boundary `μcrit = μA + tcrit · SE`, means, quartiles, win rate and P&L histograms for both arms. Three gates must pass before promotion: sample size (120 active windows), paired-window coverage (60) and sub-dollar pairs (35).
- **Pair cost** is broken into buckets (`<$0.96`, `$0.96–$1.00`, `>$1.00`) alongside paired-window and sub-$1.00 progress; this is the cost of locking both sides, not a P&L figure.
- **Fee-basis toggle:** switch rebates in or out using the account-tier rebate rate (`includeRebates`), so the comparison can be read gross or net of modeled taker rebates. Archived / tainted runs are excluded by `bot/ab_test.py`.

---

### 4. Config (`/config`) — Setup & Risk Guardrails
Select the active strategy setup and adjust its parameters. `STRATEGY_SETUPS` in `bot/constants.py` is the source of truth: its `signature`, `description`, and `configHighlights` are generated from the entry numbers, so the setup cards stay in sync with the engine. All values are validated and clamped.

- **Strategy setup selector:** choose among the versioned registry entries—`hapcs-v1`, `dangerously-skip-permissions` and `v2.6`–`v2.7`, and `hydrogen-v1.0`, `hydrogen-v1.9`, and `hydrogen-v2.0` (currently `hydrogen-v2.0`). The active id is written to `bot/config.json` and served by `/api/bot/strategy-setups`.
- **Microstructure ladder & dip curve:** `levelsPerSide` and `levelSpacing` (off-touch levels, e.g. 1 level at −1¢), `clipSchedule` (e.g. 5 shares flat), `wholeLadderClips`, `dipCurve` (`hump` or `{lo, hi, sharesLo, sharesHi}` anchors), plus `minFillPrice` / `maxFillPrice`, `minSpacingMoveSec`, `minSpacingStaticSec`, and `staticRequoteSec`.
- **Pair-cost caps:** `targetPairCost` (~$0.960), `maxPairCost` (~$0.990) and `rescuePairCostMax` (~$1.02, the late-rescue ceiling). A pair leg opens only when the opposite ask completes it under the applicable cap.
- **Unhedged inventory caps:** `maxUnhedgedShares` and `maxUnhedgedUsd` bound the light-side lead between hedges.
- **`hydrogen-v1.9` three-layer imbalance defense** (documented in the setup's highlights): **Layer 1** single 5-share maker probe in 42–49¢ with T+150s / 40 sh cutoff; **Layer 2** immediate sub-par clamped maker hedging (≤$0.990) with strict resting order hygiene on lead > 0.5 sh; and **Layer 3** patient 20s delayed taker bailout (marginal pair ≥$1.07 & ask ≤72¢) with single-window freeze latch to eliminate terminal breakout tax.
- **Timing & risk:** `startAfterOpenSec`, `stopBeforeCloseSec`, `sweepBeforeCloseSec`, `bankrollUsd`, `dailyLossCapUsd`, `maxFillsPerWindow`, and `maxConcurrentPositions` (fixed at 1).
- **Emergency Kill-Switch Card:** immediate red button to freeze all new orders.

---

### 5. Strategy (`/strategy`) — Technical Breakdown
An interactive explanation of how the maker-first engine works, with the live setup's own numbers injected from `STRATEGY_SETUPS`.

- **Resting ladders, not a taker schedule:** bids are rested off the touch on both outcomes (e.g. two levels at −1¢ and −2¢ with 10→8 share scheduled clips). A clip becomes a fill only when someone sells into it; the engine never assumes the touch was first in line.
- **Queue-ahead fill mechanics:** every resting clip records how many shares were already ahead of it at that price. Only taker **SELL** prints (or a complementary BUY on the opposite outcome at `1 − price`) consume that queue first, then the clip. A fill is *verified* when the tape traded your size, *attainable* when the queue could actually have cleared, and *phantom* when the window's tape is complete and it never could.
- **Inventory balancing:** the engine pairs legs only under the target/max pair-cost caps, then equalizes any remaining deficit with lighter-side maker clips or a patient hedge on the other side. Unhedged lead is bounded by `maxUnhedgedShares` / `maxUnhedgedUsd`, and `hydrogen-v1.9` adds the 42–49¢ probe cap, clamped maker hedge (≤$0.990) and 20s patient taker bailout so a breakout cannot strand the position.
- **Fees & settlement:** passive maker fills pay 0%; taker fills pay the parabolic fee `0.07 · p · (1 − p)` (peaking at 1.75¢/share at 50¢). Inside the 7¢ price floor and the ATM mid-band, the loop only equalizes an existing imbalance; near the close it stops adding and holds winning shares to redeem at $1.00.

---

### 6. Settings (`/settings`) — Workspace & Account
The general workspace page (not bot-specific): shows the signed-in account and sign-out, lets you rename the workspace, reports connection status for D1 database, R2 file storage and sign-in, and offers destructive **Restore sample data** / **Clear workspace** actions behind confirmation dialogs. Paper-trading controls live in Config, Live Desk and A/B Lab instead.

---

## 3. Directory Layout & Workspace Data

All bot state, runs, and artifacts live under the `bot/` directory:

```
bot/
├── api.py                  # Loopback HTTP desk API (default port 8789)
├── restart_api.ps1         # Windows: clean stop/verify/restart of the desk API
├── live_paper.py           # Window lifecycle, resting-order + queue-ahead management
├── executor.py             # Microstructure ladder evaluation, pair-cost gates, rebalance logic
├── constants.py            # Versioned STRATEGY_SETUPS registry (single source of truth)
├── signal.py               # Microprice & lean signal calculation
├── risk.py                 # Loss caps, single-window guards, kill-switch, clip sizing
├── ws.py                   # CLOB WebSocket (book / price_change / last_trade_price) + tape writer
├── discovery.py            # Polymarket Gamma 5m window discovery; REST fallback reads
├── fill_model.py           # Queue-ahead maker fill matching (SELL print / binary complement)
├── fill_audit.py           # Attainability auditing of maker fills against recorded prints
├── tape_recorder.py        # Sidecar tape recorder (book + prints, size-rotated segments)
├── tape_verifier.py        # Verified-only tape check of maker fills
├── replay.py               # Deterministic offline counterfactual replay of a recorded tape
├── ab_test.py              # Welch t-test run/setup comparison + promotion gates
├── runs.py                 # Run workspace manager & tape segment reader
├── verify_run.py           # Re-stamp a whole run's tape verdicts offline
├── reconcile.py            # Fidelity comparison vs the target wallet
├── redeem.py               # Hold-to-redeem settlement helpers
├── run_paper.py            # Batch / offline paper run helper
├── config.json             # Active strategy + entry + risk parameters
├── RUNBOOK.md              # Engine runbook
├── state.json              # Live fills & heartbeat of the active window
├── events.jsonl            # Global event audit trail
├── loop.pid / loop.log     # Active loop process id / output
├── kill                    # Soft kill-switch flag (touch to pause entries)
├── tests/                  # pytest suite
└── runs/
    ├── active_run.json     # Pointer to the active run ID
    └── run_YYYYMMDD_HHMMSS_paper_<setup>/
        ├── run_meta.json   # Status, started/ended timestamps, config snapshot, summary
        ├── events.jsonl    # Decision journal for this run
        ├── decisions.jsonl # Uncensored per-evaluation engine log (quotes + guards)
        ├── summary.json    # Session KPIs
        ├── loop.pid
        ├── loop.log
        ├── windows/        # Settled window JSON results
        └── tape/           # Recorded market tape (book snapshots + trade prints)
            ├── book.jsonl
            ├── prints.jsonl
            ├── book.<epoch>.jsonl   # Size-rotated segments (128 MB book / 32 MB prints)
            ├── prints.<epoch>.jsonl
            └── .tape_stats.json     # Incremental byte counts (avoids rescanning multi-GB tapes)
```

---

## 4. Operational Runbook & Safety Drills

### The Emergency Kill-Switch
If you ever want to immediately stop all new entries without killing the process:
1. **From UI:** Go to **Config** or **Live Desk** and toggle **Pause entries** or **Kill-Switch**.
2. **From Terminal:**
   ```bash
   # Pause entries:
   touch bot/kill

   # Resume entries:
   rm bot/kill
   ```
The bot loop checks `bot/kill` before every entry and window transition, safely preventing further fills while allowing existing contracts to resolve.

### Stopping & Resetting
- **Stop:** Click **`Stop bot`** in the UI header, or press `Ctrl + C` in the terminal.
- **Reset:** Click the reset icon (`RotateCcw`) in the UI header. This resets active state, clears current paper runs, and restores the initial paper bankroll.
- **Clean API restart (Windows):** `powershell -ExecutionPolicy Bypass -File bot/restart_api.ps1`.

### Running Automated Health Tests
To verify all engine components, run the Python suite and the frontend typecheck:

```bash
# Run all Python unit & integration tests:
python -X utf8 -m pytest bot/tests -q

# Run frontend typecheck:
bun run typecheck
```
