# Up/Down Paper Trading Desk: User & Operations Guide

Welcome to the **dangerously-skip-permissions** paper trading desk. This system reverse-engineers the 5-minute Bitcoin Up/Down binary options strategy practiced by target Polymarket trader `0xc53375ff94e96100f2b30a4b5775db35218d69a9`.

The environment runs **100% paper-only**—no live funds, private keys, or wallet connections required.

---

## 1. Quick Start (Launch Everything in 2 Steps)

### Step 1: Start the Python Desk API
The desk API runs a lightweight loopback service on `127.0.0.1:8789`. It coordinates the background execution process, streams WebSocket/REST market data, and manages run-scoped sessions.

```bash
# Terminal 1: Launch Backend API
python bot/api.py
```
*Verify:* Navigate to `http://127.0.0.1:8789/api/bot/control` in your browser. You should receive a JSON status response (`"running": false`, `"mode": "paper"`).

---

### Step 2: Start the Web Desk UI
The frontend is a React + Vite dashboard.

```bash
# Terminal 2: Launch Frontend Desk
bun run dev
# or: npm run dev / pnpm run dev
```
Open **[http://localhost:5173/](http://localhost:5173/)** in your web browser.

---

### Step 3: Start the Paper Trading Loop
You can start the trading loop in one of two ways:

- **Via the UI:** Click the blue **`Start bot`** button in the header bar of the **Dashboard** or **Live Desk**.
- **Via the Terminal (Manual / Headless):**
  ```bash
  # Continuous loop across all 5-minute windows:
  python bot/live_paper.py --loop

  # Trade exactly one window and exit:
  python bot/live_paper.py --once

  # Target an explicit 5-minute epoch:
  python bot/live_paper.py --slot 1794086700
  ```

---

## 2. Navigating the Desk UI

The web desk consists of 4 main sections accessible from the sidebar navigation:

### 1. Dashboard (`/`) — Performance & Run History
The command center for analyzing execution performance across settled windows.

- **Session Selector (Header Bar):**
  - Switch between **`Live session`** (monitoring the active trading loop) and past historical runs (`run_YYYYMMDD_...`).
  - Selecting a past run activates **`View Only (past run)`** mode. An amber warning card appears and mutating controls are disabled so you can safely audit past runs without risking live orders.
  - Click **`Return to Live`** anytime to jump back to live operations.
- **Top Metrics Strip:**
  - Shows total settled windows, overall Net PnL ($), win rate (%), and median fills per window (target is 45 fills).
- **Cumulative PnL Curve:**
  - Visual chart of your cumulative paper bankroll trajectory.
- **Rebate Toggle (`Net before rebates` card):**
  - Switches taker and maker rebates in or out of the P&L. Off, the net, win rate, expectancy, profit factor, Sharpe, the window log and the chart all fall back to price alone, and the rebate cards show what is being left out.
- **Verified Only Switch (chart card):**
  - Counts only the fills the tape verifier confirmed against real trade prints. Every window is recomputed from its verified fills, and a window without a verified fill drops out of the view entirely. Taker fills are never verified in paper mode, so they fall away with the unconfirmed makers — the resulting P&L is a subset, not a correction.
- **Timeframe Filter (below the chart):**
  - `1H · 12H · 1D · 1W · 1M · All` scopes the KPI cards, the chart, the window bars and the window log to that trailing window. The chart is re-based on the capital held when the window opened, so the curve starts where the account actually stood.
- **Settled Windows Table:**
  - Displays each 5-minute window slug, trade count, dollar volume, settlement outcome (Up / Down), and net PnL.

---

### 2. Live Desk (`/live`) — Real-Time Window Execution
Watch the bot make trading decisions live inside the active 5-minute window.

- **Connection Health Badges:**
  - `WSS Live (<40ms)`: Live streaming orderbook connected to Polymarket CLOB.
  - `REST Fallback`: Active background polling (1.0s–1.5s cadence) if WebSocket is stale.
- **Microprice Lean Gauge:**
  - Shows current fair value drift between BTC spot and Polymarket quotes (ranges from `-1.0` maximum Down lean to `+1.0` maximum Up lean).
- **Interactive Depth & Book Panel:**
  - Displays real-time bid/ask prices and depth for both the **Up** and **Down** contracts.
- **Live Fills Feed:**
  - Streams every execution ticket: exact minute (M0–M4), outcome, price (cents), shares, and total cost.
- **Pause / Resume Entries Button:**
  - Toggles the soft kill-switch on the fly without stopping the bot process.

---

### 3. Config (`/config`) — Parameters & Risk Guardrails
Allows adjusting strategy parameters and safety limits. All values are automatically validated and clamped to safe boundaries.

- **Entry Settings:**
  - `clipSharesDefault`: Default order clip size (default: 30 shares).
  - `medianShares`: Target median fill size (default: 13.86 shares).
  - `maxShares`: Absolute ceiling per clip (default: 50 shares).
  - `openDelaySec`: Delay after window open before entering initial lean (default: 13s).
  - `hedgeDelaySec`: Delay before taking the hedge leg for the straddle (default: 15s).
  - `stopBeforeCloseSec`: Cutoff before window expiry to hold to redeem (default: 15s).
  - `leanSource`: `microprice` (dynamic alpha) or `dumb` (neutral 50/50 straddle).
- **Risk Settings:**
  - `dailyLossCapUsd`: Cumulative daily stop-loss trigger (default: $500).
  - `maxConcurrentPositions`: Number of simultaneous windows traded (fixed at 1).
- **Emergency Kill-Switch Card:**
  - Immediate red button to freeze all new orders.

---

### 4. Strategy (`/strategy`) — Technical Breakdown
An interactive educational breakdown explaining the 5-minute window mechanics:
- **Phase 0 (13s):** Wait for initial price discovery, assess lean, and take initial position.
- **Phase 1 (15s–30s):** Take the opposing contract to form a buy-only straddle.
- **Phase 2 (M1–M3):** Event-driven clipping up to ~45 fills as liquidity refreshes.
- **Phase 3 (M4):** Fade execution before window close, hold to settlement, and redeem at $1.00 for winning shares.

---

## 3. Directory Layout & Workspace Data

All bot state, runs, and artifacts live under the `bot/` directory:

```
bot/
├── api.py               # Loopback HTTP server (port 8789)
├── live_paper.py        # Core execution loop & window manager
├── ws.py                # Polymarket CLOB & Binance WebSocket engine
├── signal.py            # Microprice & lean signal calculation
├── risk.py              # Loss caps, single-window guards, kill-switch
├── runs/                # Run-scoped session workspaces
│   ├── active_run.json  # Pointer to currently active run ID
│   └── run_20261108_... # Session folder:
│       ├── run_meta.json  # Run status, started/ended timestamps, config snapshot
│       ├── events.jsonl   # Decision journal for this session
│       ├── loop.log       # Output log of the loop process
│       └── windows/       # Settled window JSON results
├── state.json           # Live fills & heartbeat of active window
├── events.jsonl         # Global event audit trail
└── config.json          # Active parameters
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

### Running Automated Health Tests
To verify all engine components, run the test suites:

```bash
# Run all Python unit & integration tests (53 tests):
python -m unittest discover -s bot/tests

# Run frontend typecheck:
bun run typecheck
```
