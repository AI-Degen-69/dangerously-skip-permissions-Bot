# Reverse-engineering `dangerously-skip-permissions`: 7-day 5-minute BTC Up/Down ledger

**Wallet:** `0xc53375ff94e96100f2b30a4b5775db35218d69a9`
**File:** `docs/leaderboard-traders/scripts/full-week-trades_dangerously-skip-permissions_2026-11-01_to_2026-11-08.csv` - 174,019 rows, 69 MB
**Window:** `2026-11-01T21:35:07+00:00` -> `2026-11-08T21:33:30+00:00`
**Markets:** 1,926 distinct `Condition_ID`s (1,915 settled, 11 unresolved at export)
**Script:** [`../scripts/analyze_weekly_strategy.py`](../scripts/analyze_weekly_strategy.py) - regenerates every table below
**Raw computed output:** [`dangerously-skip-permissions_weekly_appendix.txt`](dangerously-skip-permissions_weekly_appendix.txt)

> **Superseded in part** by the three-week analysis ([`dangerously-skip-permissions_strategy_2026-10-18_to_2026-11-08.md`](dangerously-skip-permissions_strategy_2026-10-18_to_2026-11-08.md), 486,244 rows). Two conclusions here did not survive the larger sample: net trading is **+27.9 bps (+$11,503)**, not the ~0 (+2 bps) reported below, and the residual directional book is **+26.5 bps (t = 1.43)**, not the −55 bps treated as a systematic leak. The mechanism, the 50% rebate formula, the timing fingerprint and the weekend-flow verdict all reproduced.

> **Scope correction.** The prompt names `docs/dangerously-skip-permissions/scripts/...`; that path does not exist. The file above is the only full-week export in the repo, and the anchors reproduce against it, so this is the right file. The prompt's count of 1,927 markets is 1,926 here (one off; every other anchor matches to the cent).

---

## 1. Executive summary

- **Mechanism.** A buy-only, hold-to-settlement, two-sided **inventory market maker** on every 5-minute BTC Up/Down slot. It bought both sides in **1,911 of 1,926 markets (99.2%)**, started a median **6 seconds after open**, ran a median **75 fills per market**, and never sold (zero `SELL` rows). It is not predicting direction: the first side it buys wins **50.7%** of the time.
- **Where the money comes from.** Gross trading PnL was **+$29,784.80** (214 bps of $1.39M gross notional). It paid **$29,515.37** in taker fees (212 bps) and received **$16,839.98** in rebates (121 bps). Net trading before rebates: **+$269** (2 bps - zero). Net after rebates: **+$16,308** (+1.17% of gross notional). **The rebate is the P&L.**
- **The rebate is mechanical, not alpha.** `TAKER_REBATE` paid at ~00:10 UTC on day D equals exactly **50% of day D-1's taker fees** (verified for all six complete day pairs, ratio 0.5000). Maker rewards add a further ~$1/market/day. This deterministic daily inflow is why the equity curve looks like a straight line.
- **The "pairs under $1" thesis is true on average, false per trade.** Median paired cost was **0.974 gross of fees** and **0.992 all-in**; 54.7% of markets finished below 1.00 all-in, 45.3% above. Markets below 1.00 all-in made **+$30,602** on 1,045 markets; markets at or above made **-$30,397** on 865. It is a spread-capture distribution, not a locked arbitrage.
- **Biggest fragility.** Gross edge and fees are almost exactly equal (214 vs 212 bps). The 50% fee refund is the margin of safety. If the refund is removed and gross edge stays put, the week is **+$2.4k** instead of **+$16.3k**; if gross edge also falls below ~90 bps, the strategy is loss-making. Everything else - the rebuy ladder, the phase timing, the sizing - is ordinary and copyable.

---

## 2. Anchor validation

| Metric | Prompt anchor | Measured | Verdict |
|---|---|---|---|
| Rows | 174,019 | 174,019 | match |
| TRADE / REDEEM / rebates | 170,180 / 3,825 / 7+7 | 170,180 / 3,825 / 7+7 | match |
| Cash out | $1,419,407.65 | $1,419,407.65 | match |
| Redeem in | $1,418,875.70 | $1,418,875.70 | match |
| Rebates | $16,839.98 | $16,839.98 | match |
| Net before rebates | -$531.95 | -$531.95 | match |
| Net after rebates | +$16,308.03 | +$16,308.03 | match |
| Markets with fills | 1,927 | **1,926** | **off by 1** |
| Both Up and Down bought | 1,911 (99.2%) | 1,911 (99.2%) | match |
| Median pair cost | 0.992 (p10 0.88, p90 1.071) | **0.9921** (p10 0.8798, p90 1.0707) | match, **all-in** |
| Markets with pair cost < 1.00 | 54.7% | 54.7% | match, **all-in** |
| Trades per market | ~88 | 88.4 | match |

**Two corrections to the prompt's framing:**

1. **Fees are not invisible.** `USD_Amount / Shares - Price` is a taker fee of exactly **`0.07 x p x (1-p)` per share** (residual < $0.001, consistent with cent rounding). 93,630 fills (55.0%) carry it; 76,550 (45.0%) do not. No transaction hash mixes fee-paying and fee-free fills, so the file cleanly separates **taker** from **maker** fills. Total embedded fee: **$29,531.25, 2.12% of gross notional**.
2. **The anchor pair cost is all-in, not quote price.** On raw fill prices the median is **0.9739** (65.9% below 1.00); adding fees gives the anchor's **0.9921** (54.7%). Both are reported below.

Reconciliation: settled gross cost $1,389,090.90 + unresolved gross cost $785.51 = $1,389,876.41 gross notional; + $29,531.25 fees = $1,419,407.66 cash out (anchor $1,419,407.65). Redeem cash $1,418,875.70 - settled gross cost $1,389,090.90 - settled fees $29,515.37 = **+$269.43**. Add in-window rebates $16,839.98 = **+$17,109.41** synthetic. Subtract the $801.39 all-in cost of the 11 unresolved positions = **+$16,308.02**, the cash anchor.

---

## 3. Findings

### A. Integrity and scale

| Check | Result |
|---|---|
| Rows outside `secs_before_close` in [0,300] | **0** |
| Trades before open / after close | 0 / 0 |
| Peak fills in one second | **19** (2026-11-02 15:14:40 UTC) |
| Duplicate `(tx, token, price)` rows | 550 (split fills of one tx; different share counts, not duplicates) |
| Fills/market | median **75**, p10 22, p90 174, max 404 |
| Tokens per market | 3,837 / 1,926 = **1.992** |
| Taker fills | 93,630 = **55.0%** of fills, **71.8%** of cash |
| Fee paid | $29,531.25 (maker $0) |
| Taker rebate / maker rebate rows | 7 / 7 (daily, ~00:10 and ~00:45 UTC) |
| Redeem lag after close | median **93s**, p10 91s, p90 94s - automatic, not manual |
| Unresolved at export | 11 markets, $801.39 cash |

Per UTC day:

| day | trades | markets | cash | median price | median fill $ |
|---|---|---|---|---|---|
| Nov 1 (partial) | 2,017 | 29 | $16,024 | 0.48 | 5.08 |
| Nov 2 | 29,361 | 287 | $261,930 | 0.48 | 6.34 |
| Nov 3 | 30,332 | 278 | $270,794 | 0.48 | 6.36 |
| Nov 4 | 30,472 | 252 | $254,673 | 0.50 | 5.95 |
| Nov 5 | 32,415 | 272 | $278,203 | 0.47 | 5.90 |
| Nov 6 | 23,965 | 287 | $196,961 | 0.42 | 5.62 |
| Nov 7 | 11,505 | 280 | $76,965 | 0.38 | 3.84 |
| Nov 8 | 10,113 | 230 | $63,859 | 0.36 | 3.33 |

The bot covers 1,926 of the 2,016 slots in the window (95.5%). The 90 missing slots are a few real outages, not gradual attrition: a 36-slot gap on Nov 4 (15:45 UTC), 22 slots on Nov 8 (04:10), 10 on Nov 3, 8 on Nov 5, 7 on Nov 5, plus single-slot gaps - consistent with restarts/redeploys. It is otherwise always on.

### B. Dual-sided inventory - the core mechanism

All 1,911 two-sided markets:

| Measure | p10 | p25 | median | p75 | p90 | mean |
|---|---|---|---|---|---|---|
| `vwap_up + vwap_dn`, gross | 0.861 | 0.927 | **0.974** | 1.014 | 1.052 | 0.965 |
| `vwap_up + vwap_dn`, all-in | 0.880 | 0.945 | **0.992** | 1.035 | 1.071 | 0.983 |
| matched shares `min(sh_up, sh_dn)` | 114 | 244 | **514** | 943 | 1,441 | 665 |
| residual `abs(sh_up - sh_dn)` | 22 | 62 | **137** | 265 | 417 | 187 |

- **Paired cost below 1.00 all-in:** 54.7% of markets; above 1.00: 45.3%.
- **Residual imbalance:** median 137 shares = 22.8% of the matched quantity; 10% of markets exceed 55% imbalance. This is **not** delta-neutral. It is a two-sided quoter that tolerates a directional book.
- **Second side:** acquired a median **6s** after the first (p25 3s, p75 18s, p90 44s); 72.7% within 15s. The bot is not waiting for a price move to hedge - it is quoting both sides from the start.

**PnL decomposition, gross of fees (settled):**

| Component | USD | bps of gross notional | per market |
|---|---|---|---|
| Locked spread capture `min(sh) x (1 - pair_cost)` | **+$37,400.91** | +269 | +$19.53 |
| Residual directional | **-$7,682.80** | -55 | -$4.01 |
| One-sided markets (5 settled of 15) | **+$66.69** | +0.5 | +$0.03 |
| **Gross trading** | **+$29,784.80** | **+214** | **+$15.55** |
| Fees | -$29,515.37 | -212 | -$15.42 |
| **Net trading** | **+$269.43** | **+2** | **+$0.14** |

**PnL by final all-in pair cost** - the single most important table in the report:

| All-in pair cost | markets | mean locked | mean residual | mean net | total net | market win % |
|---|---|---|---|---|---|---|
| < 0.90 | 250 | +73.24 | -6.30 | **+58.44** | **+14,609** | 81.6% |
| 0.90-0.95 | 258 | +52.21 | +0.13 | +39.40 | +10,165 | 64.3% |
| 0.95-0.98 | 307 | +37.78 | +1.10 | +22.93 | +7,041 | 56.0% |
| 0.98-1.00 | 230 | +24.19 | -11.18 | -5.28 | -1,213 | 45.2% |
| 1.00-1.02 | 227 | +9.02 | +3.41 | -6.09 | -1,382 | 41.0% |
| 1.02-1.05 | 321 | -9.38 | -9.17 | -37.86 | -12,153 | 33.3% |
| 1.05-1.10 | 234 | -33.22 | -6.84 | -57.01 | -13,340 | 20.9% |
| > 1.10 | 83 | -33.79 | -1.66 | -42.43 | -3,521 | 21.7% |

The profitable half of the distribution pays for the unprofitable half, and the sum is ~zero. **The bot does not control the final pair cost**; it is the outcome of how the price path interacted with its resting orders. The practical edge is that its average fill is 2-3 cents below fair, which is enough to make the *average* pair cost 0.974 - not enough to make every pair a winner.

### C. PnL attribution

| Metric | Value |
|---|---|
| Gross trading PnL (settled) | **+$29,784.80** |
| Fees | -$29,515.37 |
| Net trading | **+$269.43** |
| Rebates | **+$16,839.98** |
| Net cash | **+$16,308.03** |
| Market win rate (net > 0) | 47.9% |
| Median market net | -$3.30 |
| Mean market net | +$0.14 |
| Per-market gross std | $112.79 (naive t = 6.03; ignores cross-market correlation) |
| Per-market residual std | $101.97 (t = -1.73) |
| Best market | +$555.84 net |
| Worst market | -$724.41 net |
| % of shares held that finished on the winner | 48.9% |
| Max market-level drawdown (fees, no rebates) | **-$5,241.88** |
| Max drawdown of daily total (with rebates) | **$0.00** |

**Answer to the prompt's question:** the bot does **not** make money trading. It makes money collecting a 50% refund on the fees it pays to trade. Trading is flat with high variance: 1,915 markets, mean +$0.14, standard deviation $113, and a $5.2k peak-to-trough drawdown inside the week. The daily total is positive every single day only because the rebate is a deterministic function of yesterday's fees.

Daily:

| day | markets | gross | fees | net | locked | residual | rebates | total |
|---|---|---|---|---|---|---|---|---|
| Nov 1 | 29 | +438 | -310 | +129 | +214 | +224 | 0 | +129 |
| Nov 2 | 287 | +6,330 | -5,692 | +638 | +4,057 | +2,273 | +671 | +1,310 |
| Nov 3 | 278 | +7,885 | -5,837 | +2,048 | +4,549 | +3,336 | +3,194 | +5,242 |
| Nov 4 | 252 | +3,983 | -5,425 | -1,443 | +998 | +2,985 | +3,317 | +1,874 |
| Nov 5 | 272 | +4,287 | -5,790 | -1,503 | +5,452 | -1,165 | +3,063 | +1,560 |
| Nov 6 | 287 | +3,917 | -4,420 | -504 | +11,437 | -7,528 | +3,313 | +2,810 |
| Nov 7 | 280 | +1,965 | -1,125 | +840 | +5,579 | -3,666 | +2,493 | +3,333 |
| Nov 8 | 230 | +979 | -916 | +63 | +5,114 | -4,142 | +789 | +853 |

### D. Timing fingerprint

| Seconds before close | % of fills | % of cash |
|---|---|---|
| 0-15 | 0.1% | 0.1% |
| 15-30 | 1.3% | 1.6% |
| 30-60 | 6.6% | 8.5% |
| 60-90 | 9.6% | 10.7% |
| 90-120 | 11.0% | 11.2% |
| 120-180 | 23.0% | 21.5% |
| 180-240 | 24.0% | 22.1% |
| 240-300 | 24.4% | 24.3% |

- First fill: median **offset 6s**, p25 4s, p90 30s; **80.6%** of markets have a fill within 15s of open.
- Last fill: median **offset 215s**, p75 250s, p90 271s; only **3.6%** of markets trade in the final 15s. Effective hard cutoff is **~11s before close** (minimum observed `secs_before_close` = 11).
- Median `secs_before_close` by price: 0.0-0.2 -> 129s; 0.2-0.45 -> 185s; 0.45-0.6 -> 212s; 0.6-0.8 -> 185s; 0.8-1.0 -> 123s. The extremes cluster late; the body of the book trades all window.
- Taker fills happen closer to close than maker fills in the high-price bucket (median 110s before close vs 138s), i.e. it crosses to complete positions near the end.

**Implication:** always-on quoting from T+4s, with a hard stop near T-12s. There is no entry filter by time and no "late snipe only" regime.

### E. Price behavior and calibration

- Fill price distribution: p10 0.16, p25 0.29, median **0.46**, p75 0.64, p90 0.79; mean 0.467. The bot lives in the middle of the book.
- Fills below 0.10: 2.7% of fills, 0.4% of cash, **-$235 gross (-396 bps)**. Fills above 0.90: 1.8% of fills, 3.8% of cash, **+$1,281 gross (+238 bps)**.
- Consecutive same-token price changes: mean **+0.0006**, median 0.0; 42.7% up, 35.6% down, 19.4% flat. It does not systematically average down; it follows the price and buys whichever side is cheap at that moment.
- Fill-level calibration (fill price vs eventual win): hit rate tracks price within **-0.3 to +3.1pp** in every bucket between 0.05 and 0.95. There is a small, consistent positive edge - the signature of buying at or below fair value - but no large mispricing. Worst bucket: 0.55-0.60, **-0.3pp** (n=10,561); best: 0.40-0.45, **+3.1pp** (n=13,268).
- By fill type, gross of fees:

| type (settled markets) | fills | cash | gross PnL | bps | avg price |
|---|---|---|---|---|---|
| Maker (0 fee) | 76,431 | $399,969 | **+$5,332** | **+133** | 0.448 |
| Taker (0.07 p(1-p)) | 93,576 | $1,018,637 | **+$24,453** | **+240** | 0.482 |

Taker fills have higher gross edge per dollar than maker fills in this tape, because they are concentrated at low prices (0.2-0.4) where a 1-2c discount is a large percentage. Fees of 290 bps on taker notional turn that +240 bps into -50 bps before the 50% rebate.

- Marginal (imbalance-widening) fills: 94,808 fills, 56.1% of shares, $792,894, gross **+$6,882 (0.87%)**. Directional adds are roughly fair, not a source of edge.

### F. Sizing and risk

| Metric | Value |
|---|---|
| Shares per fill | median **15**, mean 17.1; 30.5% are exactly **30.0** |
| USD per fill | median **$5.68**, mean $8.34 |
| USD per market | mean **$737**, median $559, p90 $1,561, max **$3,846** |
| Shares per market | median 1,177, max 7,840 |
| Largest single ticket | $95.33 / 100 shares |
| Largest one-side cost | $2,737 |
| Peak concurrent cash committed | **$3,846** (windows are sequential; the "overlap" is only at the boundary) |
| Daily turnover | **$202,773** |
| Martingale test | $751 mean market cost after a win vs $732 after a loss - **none** |

Size is set in **shares, not dollars**: median 30 shares early (0-60s), falling to 12-14 shares after 120s. USD per fill therefore scales with price ($1.52 below 0.2, $14.65 above 0.8). There is a hard per-market budget (the observed max is $3,846, essentially the repo's $4,000 window cap) and a soft ladder that tops up small clips late.

The working bankroll is small: **$3.8k peak deployed**, $203k/day turnover. This is a capital-light, high-turnover book, not a balance-sheet strategy.

### G. Regime change - mandatory

| day | trades | markets | trades/mkt | median fill $ | median price | taker % | gross bps | net bps | rebate bps | cost/market |
|---|---|---|---|---|---|---|---|---|---|---|
| Nov 2 | 29,361 | 287 | 102 | 6.34 | 0.48 | 59.6 | 242 | +24 | 26 | $913 |
| Nov 3 | 30,332 | 278 | 109 | 6.36 | 0.48 | 58.4 | 291 | +76 | 118 | $974 |
| Nov 4 | 30,472 | 252 | 121 | 5.95 | 0.50 | 59.8 | 156 | -57 | 130 | $1,011 |
| Nov 5 | 32,415 | 272 | 119 | 5.90 | 0.47 | 56.6 | 154 | -54 | 110 | $1,023 |
| Nov 6 | 23,965 | 287 | 84 | 5.62 | 0.42 | 58.0 | 199 | -26 | 168 | $686 |
| Nov 7 | 11,505 | 280 | 41 | 3.84 | 0.38 | 32.9 | 255 | +109 | 324 | $274 |
| Nov 8 | 10,113 | 230 | 44 | 3.33 | 0.36 | 31.4 | 153 | +10 | 124 | $275 |

Phases:

| phase | trades/mkt | median fill $ | median price | taker % | gross bps | net bps | rebate bps | net per market |
|---|---|---|---|---|---|---|---|---|
| Nov 2-5 (weekdays) | 112.6 | 6.14 | 0.48 | 58.6 | 211 | -3 | 96 | -$0.24 |
| Nov 6 (Friday) | 83.5 | 5.62 | 0.42 | 58.0 | 199 | -26 | 168 | -$1.75 |
| Nov 7-8 (weekend) | 42.4 | 3.59 | 0.37 | 32.2 | 204 | +60 | 224 | +$1.77 |

**Verdict: weekend liquidity cycle, not degradation, and not bankroll depletion.** Nov 7 is Saturday and Nov 8 is Sunday; Nov 1 (the partial start) is also a Sunday. The bot still covers every slot, its gross edge per dollar is unchanged (phase averages 199-211 bps), and its capital deployed falls to $274/market because there is less flow to fill against. Taker share halves because the bot stops crossing when there is nothing to hedge against - a rational response, not a throttle. `[H]` The market-level win rate is stable (43-54%).

Two caveats: (a) with no market-wide volume data in this file, "weekend flow" is an inference from the calendar, not measured; (b) per-market net turns *positive* on the low-volume days because fees fall faster than gross, so a thin market is not necessarily a worse market for this strategy.

### H. Within-market replay

Six markets, condensed to 15-second buckets (full timelines in the appendix):

**Clean hedge, largest locked capture - 2026-11-04 13:45 UTC, Down won.** VWAP Up 0.400 / Down 0.431, 2,032 / 1,805 shares, gross pair cost 0.831. It bought Down at 0.19-0.30 and Up at 0.70-0.82 early, then flipped as the price whipsawed; the final inventory was nearly balanced at a 0.83 pair. Locked +$305, residual -$91, net +$179. This is the business model working: accumulate both sides across oscillations at an average discount.

**Broken hedge, worst locked - 2026-11-05 16:00 UTC, Down won.** It bought both sides at ~0.50 all window (VWAP 0.522 / 0.552, pair 1.074) and finished 3,463 Up / 3,291 Down. Locked **-$245**, residual -$90, net -$410. This is the failure mode: a trending, low-volatility window where both sides are expensive and the price never gives you a discount.

**Largest net win - 2026-11-04 13:20 UTC, Up won.** Pair cost 0.966, but it ended with 3,921 Up vs 2,730 Down; the 1,191-share net-long Up position paid +$549. Gross +$643, net +$556. Most of this "win" is directional luck, not spread.

**Largest net loss - 2026-11-06 20:50 UTC, Down won.** Pair cost 0.988 (looks fine), but it was net long 1,032 Up shares at 0.677 average; the residual cost -$699. Net -$724. Mirror image of the previous case.

**Largest one-sided market - 2026-11-07 16:45 UTC.** Only Down fills (116 shares, VWAP 0.630); Down won; +$42 gross. Rare (0.8% of markets) and small.

**Latest entry - 2026-11-08 00:50 UTC.** First fill at offset 180s, after a large move: Down at 0.76, then Up at 0.21. Pair 0.978, net +$7.5. Late entry is allowed, not a separate regime.

**Decision grammar (observed):** quote both sides from T+4s -> accumulate whichever side is offered below the current mid -> keep a share lead under ~25% of the matched book -> top up in 10-30 share clips -> stop near T-12s -> hold to settlement -> auto-redeem at T+93s. No flips, no sells, no abandonment, no time-stop other than the cutoff.

### I. Rebate mechanics

| day | maker rebate | taker rebate | notional | maker bps | taker bps | total bps |
|---|---|---|---|---|---|---|
| Nov 2 | 114.84 | 556.32 | $261,930 | 4.4 | 21.2 | 25.6 |
| Nov 3 | 347.72 | 2,845.81 | $270,794 | 12.8 | 105.1 | 117.9 |
| Nov 4 | 398.51 | 2,918.65 | $254,673 | 15.7 | 114.6 | 130.3 |
| Nov 5 | 349.94 | 2,712.61 | $278,203 | 12.6 | 97.5 | 110.1 |
| Nov 6 | 418.36 | 2,894.90 | $196,961 | 21.2 | 147.0 | 168.2 |
| Nov 7 | 282.58 | 2,210.23 | $76,965 | 36.7 | 287.2 | 323.9 |
| Nov 8 | 224.03 | 565.46 | $63,859 | 35.1 | 88.6 | 123.6 |

- **Taker rebate is a formula, not a reward:** rebate(D) / fees(D-1) = **0.5000** for every complete pair (Nov 3-8). It is paid at ~00:10 UTC the next day. The Nov 2 row covers pre-window Oct 31/Nov 1 activity, which is why it does not fit.
- **Maker rebate is a separate ~$1/market/day reward**, 45-84 bps of maker notional on full days. It does not fit a fee-refund formula; treat it as a liquidity-rewards program `[H]`.
- Total rebates **118.6 bps of cash notional**; they cover **57%** of the fees paid inside the window. In steady state the correct number is **50% of fees = $14,766/week**, plus ~$2.1k maker rewards.
- Marginal economics: **~$11,900 of rebate per extra $1M of two-sided notional**.

**Unit economics per $1M traded:** gross +$20,978, fees -$20,800, taker rebate +$10,400, maker reward +$1,500 -> **+$12,080**. That is the whole business.

---

## 4. PnL attribution waterfall

```
bps of $1,389,876 gross notional
Gross spread capture (locked)            +37,401     +269 bps
Residual directional                     -7,683      -55 bps
One-sided markets                            +67      +0.5 bps
-------------------------------------------------------------
Gross trading                            +29,785     +214 bps
Taker fees                               -29,515     -212 bps
-------------------------------------------------------------
Net trading (before rebates)                +269       +2 bps
Taker rebate (50% of prior-day fees)     +14,704     +106 bps
Maker reward                              +2,136      +15 bps
-------------------------------------------------------------
Net cash                                 +17,109     +123 bps
Unresolved positions at export              -801       -6 bps
-------------------------------------------------------------
Cash reconciliation                      +16,308     +117 bps
```

The waterfall makes the design target explicit: **maximise gross spread capture per dollar, keep fees at or below it, and let the rebate be the profit.** Any change that raises taker share without raising gross edge destroys the business.

---

## 5. Regime-change table

Covered in G. One-line verdict: **weekend flow, not decay.** The full-day trade count falls ~62% from the weekday average to Saturday while markets stay at ~280/day, taker share halves, and gross edge per dollar is unchanged. The bot remains profitable per market on the thin days because fees fall faster than gross. Do not read the Nov 7-8 drop as bankroll depletion: peak capital deployed was $3.8k all week.

---

## 6. The strategy to run

### 6.1 What the observed bot actually is

A **fee-aware, buy-only, two-sided inventory market maker** on 5-minute BTC Up/Down binaries, holding every position to settlement. It does not forecast BTC, does not arb a locked pair, and does not unwind. Its edge is buying both sides at an average combined cost below $1, then collecting the exchange's 50% taker-fee refund.

### 6.2 Universe and schedule

| Rule | Measured value |
|---|---|
| Instrument | `btc-updown-5m-<epoch>` only |
| Slot coverage | every slot; 95.5% observed (90 slots lost to a few restarts, not selection) |
| First quote | T+4s (p25 of first fill = 4s, median 6s) |
| Last new fill | T-12s hard stop (observed min `secs_before_close` = 11) |
| Hold | to settlement; zero sells |
| Redeem | automatic at T+93s median; batch is fine |

### 6.3 Two-sided quoting logic

1. At T+4s, register the book and place resting bids on **both** tokens.
2. Maintain a ladder of 10-30 share clips. The modal clip is **30 shares**; late-window clips shrink to 12-14.
3. Let fills arrive. Do **not** require the instantaneous pair sum to be below 1.00 - the target bot bought both sides in 45% of markets whose final pair cost was above 1.00. Enforcing a hard 0.99 cap changes the strategy; treat it as an A/B, not a fidelity fix.
4. Keep the share imbalance inside ~25% of the matched book; the observed median is 22.8% and the p90 is 55%. If one side runs ahead, bias new quotes to the lagging side rather than crossing aggressively.
5. Prefer maker fills. 45% of fills (28% of cash) were maker and paid **zero** fee; maker fills still earned +133 bps gross.
6. Cross only to repair a large imbalance or to complete a position near the end. Taker fills are +240 bps gross but -290 bps in fees; without the 50% refund they are loss-making.
7. Stop at T-12s. Do not add in the last 10 seconds.

### 6.4 Price bands

| Band | Measured behaviour | Action |
|---|---|---|
| < 0.07 | 59 fills, -$81 gross (-9,470 bps) | **skip** (the repo already does) |
| 0.07-0.10 | 4,610 fills, -$153 gross (-262 bps) | skip or halve size; measured negative |
| 0.10-0.20 | 18,245 fills, +$1,499 gross (+353 bps) | small clips |
| 0.20-0.80 | 131,522 fills, +$25,205 gross (+223 bps) | **core book** |
| 0.80-0.90 | 12,535 fills, +$2,034 gross (+108 bps) | small clips; late-window |
| 0.90-0.95 | 3,004 fills, +$1,244 gross (+234 bps) | certainty snipe, small |
| > 0.95 | 32 fills, +$37 | ignore |

### 6.5 Sizing and risk

| Parameter | Measured value | Tolerance | Why |
|---|---|---|---|
| Clip size | 30 shares (30.5% of fills) | 20-40 | modal order signature |
| Late clip | 10-15 shares after T-120s | 8-20 | observed decay |
| Max shares per ticket | 100 | 50-100 | observed max |
| Max cost per market | $3,846 observed | $3,500-4,000 | hard budget; peak capital |
| Max one-side cost | $2,737 | $2,500-3,000 | residual risk cap |
| Max share imbalance | 25% of matched (p90 55%) | 20-30% | avoids directional blowups |
| Daily loss stop | -$2,000 cash (trading days hit -$1,503) | -$1,500 to -$2,500 | repo's -$500 would halt a faithful bot |
| Bankroll | $8,000-10,000 | >= 2x peak | $3.8k peak + variance buffer |
| Martingale | none | - | $751 vs $732 after win/loss |

### 6.6 Expected economics

Per market (1,915 settled): gross **+$15.55**, fees **-$15.42**, net **+$0.14**, rebate **+$8.79**, total **+$8.93**.
Per day (~270 markets): **+$2,410**, of which **~$2,370 is rebate**.
Per $1M of two-sided notional: **+$12,080**.

Variance: per-market net std **$113**, so a 280-market day has a trading-PnL std of ~**$1,900** - the daily rebate is larger than one standard deviation of the trading book. This is why the equity line is smooth.

### 6.7 Kill criteria

| Condition | Threshold | Consequence |
|---|---|---|
| Taker rebate cut | 50% -> 0% | weekly PnL falls to ~+$2.4k (17 bps); strategy no longer worth the risk |
| Fee coefficient raised | 0.07 -> 0.10 | margin halves to ~$8.7k/week with the 50% refund; -$12k/week with no refund |
| Gross edge compressed | below ~90 bps | breakeven after fees and rebates; stop |
| Pair cost drift | median all-in > 1.00 for 3 days | locked capture goes to ~0; the residual and rebate become the whole P&L |
| Taker share | > 65% of cash with no rebate | fee drag exceeds edge |
| Bankroll | below $4k | cannot fund the $3.8k peak window plus variance |

### 6.8 What to drop

| Item | Measured value | Verdict |
|---|---|---|
| Sub-7c lottery tail | 59 fills, -$81 (-9,470 bps) | drop |
| 7-10c band | 4,610 fills, -$153 (-262 bps) | drop or halve |
| Late certainty snipe above 0.90 | 3,036 fills, +$1,281 (+238 bps) | keep, but it is <5% of P&L |
| Chasing both sides at pair > 1.05 | 317 markets, -$16,861 | the main loss source; don't add size into it |
| Martingale / loss-chasing | none observed | keep none |

### 6.9 Pseudocode (measured thresholds)

```python
# per 5-minute slot; buy-only; hold to settlement
on_slot_open(slot):
    wait(4)                                  # T+4s
    register_book(slot)
    target_clip = 30                         # shares
    while secs_before_close(slot) > 12:
        bid_up, bid_dn = best_quotes(slot)
        # keep a two-sided book; bias to the lagging side
        if shares_up - shares_dn > 0.25 * min(shares_up, shares_dn):
            favour = "Down"
        elif shares_dn - shares_up > 0.25 * min(shares_up, shares_dn):
            favour = "Up"
        else:
            favour = "both"

        px = limit_price(side, book)         # passive, below mid; no chasing
        if px < 0.10:                        # measured negative
            continue
        if cost_this_market + clip_usd(target_clip, px) > 3800:
            break
        place_or_topup(side, target_clip, px, post_only=(side != favour))
        sleep_until_next_tick()

    # no sells, no unwind
    hold_to_settlement(slot)
    redeem_after(93)                         # median observed lag

# accounting: charge taker fee 0.07*p*(1-p)*shares on crossing fills only;
# accrue taker rebate = 0.50 * prior_day_taker_fees, paid next day 00:10 UTC;
# accrue maker reward ~= 1.0 USD per market per day.
# PnL is only meaningful if the rebate is booked; without it the strategy is ~0.
```

### 6.10 One-week paper-trading plan

Run the bot for 7 days, all slots, with the fee/rebate accounting above. Check daily:

1. **Coverage** - slots traded / 288 >= 0.95.
2. **Both sides** - markets with both sides >= 0.97.
3. **Pair cost** - median all-in `vwap_up + vwap_dn` in **0.99 +/- 0.02**; gross in **0.97 +/- 0.02**.
4. **Fee ratio** - taker fees / cash in **190-230 bps**; taker share of cash **65-75%**.
5. **Rebate** - received rebate / prior-day fees in **0.48-0.52**.
6. **Net** - gross bps **180-240**, net trading **-30 to +30 bps**, total **+90 to +150 bps**.
7. **Size** - median cost per market **$500-800**; max <= $4,000; no martingale (post-win vs post-loss cost within 10%).
8. **Timing** - median first fill <= 15s; last fill <= T-12s; <5% of fills in the last 15s.

If (3), (4) and (5) are inside tolerance, the mechanism is reproduced even if the week's total PnL is noisy. If (5) fails, the exchange has changed the rebate and the strategy needs re-pricing before any live capital.

### 6.11 What to change in this repo (fidelity gaps)

1. **Model the rebate.** `bot/` models the 0.07 taker fee but not the 50% refund. A faithful paper run currently shows ~$0/week and will look broken. Add `taker_rebate = 0.50 * prior_day_taker_fees` at T+1 00:10 UTC, and a maker reward of ~$1/market/day.
2. **Report both pair-cost measures.** `constants.py` has `MEAN_PAIR_COST = 0.9462`; the weekly file gives **0.9651 gross / 0.9832 all-in**. Use all-in for the go/no-go, gross for the spread measurement.
3. **Re-benchmark maker share.** `MAKER_SHARE_TARGET = 0.70` conflicts with the weekly tape: **45% of fills and 28% of cash** are maker. Either the 24h tape was different or the metric was measured by count of orders, not fills.
4. **Revisit the 0.99 pair-cost cap.** The target buys both sides even when the instantaneous pair sum is above 1.00 (the worst-locked replay did it all window). A hard cap is a strategy change; A/B it, don't assume fidelity.
5. **Raise the daily loss cap.** A $500 cap would have stopped the bot on Nov 4 and Nov 5 (trading -$1.4k and -$1.5k). The target's own stop, if any, is on cash including rebates; every day was positive on that basis.

---

## 7. Confidence ledger

| Claim | Confidence | Evidence | What would raise it |
|---|---|---|---|
| Gross spread capture ~214 bps; net trading ~0 | **High** | Cash flows reconcile to the cent; fee formula exact | - |
| Profit is the 50% taker rebate | **High** | rebate(D)/fees(D-1) = 0.5000 for 6/6 complete pairs | Exchange fee schedule / rebate terms |
| Bot is buy-only, holds to settlement | **High** | 0 SELL rows, 3,825 redeems, median 93s lag | - |
| No directional alpha | **High** | First side wins 50.7%; residual t = -1.73 | Mark-to-market mid prices |
| Median pair cost 0.992 all-in / 0.974 gross | **High** | 1,911 two-sided markets | - |
| Average fill edge +1-3pp over price | **Medium** | Fill-level calibration; outcome is binary and noisy | Order-book snapshots at fill time |
| Maker share 45% of fills / 28% of cash | **Medium** | Fee = 0 classification is exact, but maker/taker labels are inferred from the fee | Exchange order-level data |
| Peak capital $3.8k, bankroll $8-10k | **Medium** | Sequential windows; cost-based, not mark-to-market | Wallet balance history |
| Weekend flow explains the Nov 7-8 drop | **Medium** | Calendar + constant gross bps + halved taker share | Market-wide volume by day |
| Maker rebate is a liquidity reward | **Low** | No formula fits; ~$1/market/day | Exchange rewards documentation |
| Sub-10c fills are negative | **Medium** | 4,669 fills, -$234 gross; small sample at the extreme | More weeks |

## 8. Falsifiable predictions

A faithful reimplementation on a fresh week should reproduce:

1. Median all-in paired cost **0.992 +/- 0.02**; gross **0.974 +/- 0.02**.
2. Taker fees **190-230 bps** of cash out; taker share **65-75%** of cash.
3. Received taker rebate **= 50% +/- 2pp** of the prior UTC day's taker fees.
4. Net trading before rebates **between -30 and +30 bps**; total after rebates **+90 to +150 bps**.
5. **>= 97%** of markets have both sides; median first fill **<= 15s** after open; **< 5%** of fills in the final 15s.
6. Per-market net standard deviation **$90-140**; per-market mean **-2 to +20 USD**.
7. Peak cost in any single market **<= $4,000**; no post-win size escalation **> 10%**.

## 9. What this file cannot answer

- **Quotes that never filled.** Fill rates, cancel behaviour and queue position are invisible. Every "it quotes both sides" statement is an inference from fills, not observation.
- **Mark-to-market risk.** The book is valued only at settlement. Intra-window drawdown could be larger than the $5.2k market-level equity drawdown shown here.
- **Adverse selection.** Second-granular timestamps and no book snapshots mean we cannot measure how far the mid moved after each fill beyond the next same-token fill (maker -0.4c, taker +0.2c over 30s).
- **Fees on redemption / gas.** Not in the file; assumed zero.
- **Maker-rebate formula.** 14 daily rows are not enough to identify it.

## 10. Reproduction

```bash
python docs/leaderboard-traders/scripts/analyze_weekly_strategy.py
```

The script reads the CSV, derives the market clock from `Market_Slug`, recovers resolution from `REDEEM`, reconstructs the taker fee from `USD_Amount - Price x Shares`, and prints every table above. `docs/leaderboard-traders/reports/dangerously-skip-permissions_weekly_appendix.txt` is the exact output used for this report.
