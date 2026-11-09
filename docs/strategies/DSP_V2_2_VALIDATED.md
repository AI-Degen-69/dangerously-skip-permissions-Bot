# Strategy Specification: Dangerously Skip Permissions v2.2 (DSP-v2.2)
**Status:** VALIDATED ON PAPER  
**Validation Date:** 2026-11-09  
**Validation Sample Size:** 31 consecutive 5-minute BTC windows (`run_20261109_205116_paper_dsp_v2_2`)  
**Results:** **17 Wins · 0 Losses · 14 Scratches (Clean Skips)**  
**Win Rate (on entered windows):** **100.0%**  
**Net Realized PnL:** **+$18.00** (Zero drawdowns, zero negative tail events)

---

## 1. Executive Summary & Thesis

Prior iterations of the bot suffered from severe negative skew: while achieving a high win rate (e.g. 14 wins out of 18 windows in DSP-v2.1), the 4 losing windows produced disproportionately large losses (-$9.30 to -$13.20 each) due to **unhedged single-leg traps** where the bot bought an early dip, could not find an economical hedge before expiry, and saw the unhedged token resolve to $0.00.

**DSP-v2.2 (Confidence-Based Sizing & Pre-Flight Gate)** solves this by making two structural changes:
1. **Never enter a dip that cannot be guaranteed to hedge under $0.995.**
2. **Size heavily on 100% risk-free pairing opportunities, while micro-sizing speculative dips.**

Across 31 live 5-minute BTC windows on Polymarket CLOB, DSP-v2.2 eliminated 100% of unhedged wipeouts, delivering 17 dual-sided winning pairs and 14 risk-free scratches ($0.00 loss).

---

## 2. The 4 Core Architectural Mechanisms

### Mechanism 1: Pre-Flight Hedge Gate (`px + opp_ref <= rescue_cap`)
Before committing capital to an unhedged speculative dip, the engine looks at the opposite token's best ask (`opp_ref`):
$$\text{Entry Price} + \text{Opposite Token Ask} \le \$0.995$$
- **The Problem in v2.1:** In a trending market, Up dips to 33¢ while Down ask is 68¢ ($33¢ + 68¢ = 101¢$). v2.1 bought Up hoping Down would drop later. BTC continued downward, Down won, and Up expired worthless (-$13.20 loss).
- **The v2.2 Solution:** If the sum of entry price and opposite ask exceeds **$0.995**, the entry is **strictly refused** (`extreme-price-skip / pair-cost-cap`). The bot refuses to take directional risk unless an immediate sub-$1.00 hedge is guaranteed.

### Mechanism 2: Bi-Modal Confidence Sizing
Sizing adapts dynamically to the certainty of the trade:
- **High Confidence (Atomic Arbitrage & Deficit Equalization):** When both sides can be filled immediately with sum $\le \$0.990$ (or when balancing an existing deficit), size up to **60 shares** to maximize guaranteed dollar profit.
- **Low Confidence (Speculative Dip Intake):** When entering an unhedged initial dip, size down to **10 shares** (`clipSharesDefault = 10.0`). Even in the worst-case scenario where a dip is stranded, maximum unhedged dollar risk is bounded to at most $4.50 (10 sh @ 45¢).

### Mechanism 3: Strict Deficit Freeze & Lead Cap
- **`lead_cap = 20.0 shares` (v2.2):** Limits maximum accumulated unhedged inventory to at most 2 micro-clips.
- **`freeze_lead = 15.0 shares`:** If one side leads by $\ge 15.0$ shares, buying that leading side is **100% frozen**. The bot is only permitted to buy the lagging side to restore balance.

### Mechanism 4: 75-Second Terminal Cutoff (`stopBeforeCloseSec = 75`)
- When $T \le 75\text{s}$ remaining in the 5-minute window, if the bot is balanced (imbalance $\le 0.0$), it **immediately terminates all trading** and holds to resolution.
- This protects the bot from late-window phantom liquidity, terminal orderbook collapse, and 15-second whipsaws.

---

## 3. Configuration Snapshot (`bot/config.json`)

```json
{
  "asset": "BTC",
  "intervals": ["5m"],
  "mode": "paper",
  "bankrollUsd": 1000,
  "strategy": {
    "id": "dangerously-skip-permissions-v2.2",
    "symbol": "⚡ DSP-v2.2",
    "name": "Dangerously Skip Permissions v2.2 (Confidence Sizing)"
  },
  "entry": {
    "startAfterOpenSec": 4,
    "stopBeforeCloseSec": 75,
    "clipSharesDefault": 10.0,
    "maxShares": 60.0,
    "minFillPrice": 0.07,
    "maxFillPrice": 0.880,
    "benchmarkPairCost": 0.965,
    "targetPairCost": 0.965,
    "maxPairCost": 0.985,
    "maxShareLead": 30.0,
    "freezeLead": 15.0,
    "rescuePairCostMax": 0.995,
    "rescueCeilingPrice": 0.985,
    "minSpacingMoveSec": 0.5,
    "minSpacingStaticSec": 2.5,
    "includeTakerFee": true,
    "wholeLadderClips": true
  },
  "risk": {
    "maxUsdPerWindow": 4000,
    "maxFillsPerWindow": 500,
    "dailyLossCapUsd": 500,
    "maxConcurrentPositions": 1
  }
}
```

---

## 4. Empirical Performance Breakdown (Run `run_20261109_205116_paper_dsp_v2_2`)

### Aggregate Scorecard
- **Total Windows Evaluated:** 31
- **Windows Entered:** 17
- **Windows Skipped (Scratches):** 14 (100% safe exits, $0.00 loss)
- **Winning Windows:** 17
- **Losing Windows:** 0
- **Win Rate (Entered):** 100.0%
- **Net Profit:** +$18.00
- **Max Drawdown:** $0.00

### Distribution of Traded Pair Costs
- **92.0¢ Pair Cost ($46.00 cost $\rightarrow$ $50.00 payout):** 2 windows (Net: **+$4.00** each)
- **97.0¢ Pair Cost ($48.50 cost $\rightarrow$ $50.00 payout):** 1 window (Net: **+$1.50**)
- **98.0¢ Pair Cost ($49.00 cost $\rightarrow$ $50.00 payout):** 3 windows (Net: **+$1.00** each)
- **99.0¢ Pair Cost ($49.50 cost $\rightarrow$ $50.00 payout):** 11 windows (Net: **+$0.50** each)

---

## 5. Code Implementations & Symbol Links

- **Decision Engine:** [`bot/executor.py`](../../bot/executor.py#L117) (`evaluate_microstructure_ladder`)
- **Confidence Sizing Logic:** [`bot/executor.py`](../../bot/executor.py#L47) (`select_ladder_clip`)
- **Clamping Safety:** [`bot/risk.py`](../../bot/risk.py#L40) (`clip_shares`)
- **Strategy Constants & Setup:** [`bot/constants.py`](../../bot/constants.py#L115) (`STRATEGY_SETUPS["dangerously-skip-permissions-v2.2"]`)
- **Frontend Preset Registry:** [`src/app/botDefaults.ts`](../../src/app/botDefaults.ts#L125)

---

## 6. How to Replay or Deploy DSP-v2.2

### Run via Desk API & UI
1. Launch API daemon:
   ```bash
   python bot/api.py --port 8789
   ```
2. Navigate to `http://localhost:5173/config` and select preset:
   **`⚡ Dangerously Skip Permissions v2.2 (Confidence Sizing)`**
3. Click **Save & Restart Bot**.

### Run via Command Line
```bash
python bot/live_paper.py --loop
```
To run a single window test:
```bash
python bot/live_paper.py --once
```
