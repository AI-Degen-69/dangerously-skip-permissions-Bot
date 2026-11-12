# `dangerously-skip-permissions` — three-week strategy ledger analysis

**Wallet:** `0xc53375ff94e96100f2b30a4b5775db35218d69a9`
**Window:** `2026-10-18T21:35:08+00:00` → `2026-11-08T21:33:30+00:00` (21 days)
**Dataset:** 486,244 rows after dedupe — 475,807 `TRADE`, 10,395 `REDEEM`, 21 `MAKER_REBATE`, 21 `TAKER_REBATE`
**Markets:** 5,589 traded, 5,571 settled, 18 unresolved at export ($1,506 cash)
**Script:** [`../scripts/analyze_weekly_strategy.py`](../scripts/analyze_weekly_strategy.py) — takes a `.csv` argument (or `TRADES_CSV`)
**Computed output:** `scratch/analysis_3week.txt` (610 lines, gitignored)

> **Supersedes the one-week report** ([`dangerously-skip-permissions_weekly_strategy_2026-11-01_to_2026-11-08.md`](dangerously-skip-permissions_weekly_strategy_2026-11-01_to_2026-11-08.md)) on the points listed in §4. The one-week file remains the record of that sample; this file is the current reading of the wallet.

---

## 1. Executive summary

- **Mechanism, unchanged.** A buy-only, hold-to-settlement, two-sided inventory market maker on 5-minute BTC Up/Down slots. Both sides bought in **5,557 of 5,589 markets (99.4%)**, first fill a median **6 s** after open, median **74 fills per market**, zero `SELL` rows.
- **Profit split, corrected.** Gross trading **+$105,711** (256 bps of $4,127,204 gross notional), fees **−$94,208** (228 bps) → net trading **+$11,503 (27.9 bps)**. Rebates **+$53,943 (127.8 bps)**. **Net +$66,190 (160 bps) over 21 days.** Trading is ~17% of the profit and the rebate ~83% — the rebate still dominates, but trading is *not* flat.
- **The rebate is a formula.** `TAKER_REBATE` paid on day D is **exactly 50%** of day D−1's taker fees: exact to the cent on 15 of 21 days, within 0.5% on the other 6. Maker rewards add a further **$5,861** over three weeks (~$1/market/day).
- **The edge is locked spread capture.** Locked capture **+$94,455 (+229 bps)**, 89.4% of gross trading PnL; 67.2% of markets have positive locked capture. The residual directional book is **+$10,943 (+26.5 bps), t = 1.43** — statistically indistinguishable from zero, *not* the drag the one-week sample suggested.
- **Per market:** gross **+$18.98**, fees **−$16.91**, net **+$2.06**, rebate **+$9.67** → **+$11.73**. Market win rate 49.1%, median market net −$1.31. At ~280 markets/day that is **~$3,280/day, ~$1,530 of it profit.**
- **Variance is large relative to the trading edge.** Per-market net std **$111.77** (mean +$2.06, t = 12.67 across 5,571 markets), max market-level drawdown **−$5,865**. The rebate is what keeps the daily equity curve smooth: max drawdown of the *daily* total was **−$217**.

---

## 2. Dataset and integrity

| Check | Result |
|---|---|
| Rows | 486,244 (3 × 7-day pulls tiled at 21:35 UTC boundaries, 167 boundary duplicates dropped) |
| Window | Oct 18 21:35:08 → Nov 8 21:33:30 UTC |
| Tokens per market | 11,146 / 5,589 = **1.994** |
| Truncated windows (coverage) | 5,589 of 6,048 slots (**92.4%**); gaps are restarts, not selection |
| Fills outside `[0, 300]` s before close | **0** |
| Peak fills in one second | **75** (2026-10-23 14:02:09 UTC) |
| Duplicate `(tx, token, price)` rows | 384 (split fills of one transaction) |
| Taker (fee-paying) fills | **59.1%** of fills, **75.7%** of cash |
| Fees paid | $94,235.94 embedded in fills; maker fills pay $0.00 |
| Fill price vs `USD_Amount/Shares` | deviation **≤ $0.0175**, consistent with `0.07·p·(1−p)` per share |

**Coverage caveat.** 92.4% of slots is below the 95.5% the one-week sample showed. The missing 459 slots are concentrated in a handful of days — **Oct 30 (180 markets)**, **Nov 1 (153)** and **Oct 21 (234)**, with smaller shortfalls on Oct 19 and Nov 4 — consistent with restarts or market-level outages rather than a throttle.

---

## 3. What the wallet does

### 3.1 Dual-sided inventory

| Measure (5,557 two-sided markets) | p10 | p25 | median | p75 | p90 |
|---|---|---|---|---|---|
| `vwap_up + vwap_dn`, gross | 0.889 | 0.940 | **0.977** | 1.012 | 1.046 |
| `vwap_up + vwap_dn`, all-in | 0.909 | 0.960 | **0.998** | 1.033 | 1.067 |
| matched shares `min(sh_up, sh_dn)` | 138 | 274 | **542** | 953 | 1,417 |
| residual `abs(sh_up − sh_dn)` | 25 | 64 | **143** | 270 | 416 |

- Mean all-in pair cost **0.9924**; **51.5%** of markets finish under 1.00 all-in, **48.5%** above.
- Relative imbalance: median **21.6%** of the matched book, p90 **52.9%**. This is not delta-neutral; it is a two-sided quoter that tolerates a directional book.
- Second side arrives a median **6 s** after the first (48.3% within 5 s, 79.7% within 15 s). It quotes both sides from the start rather than waiting for a move.

### 3.2 PnL attribution (settled markets, gross of fees)

| Component | USD | bps of gross notional | per market |
|---|---|---|---|
| Locked spread capture `min(sh) × (1 − pair_cost)` | **+$94,455** | +229 | +$16.95 |
| Residual directional | **+$10,943** | +26.5 | +$1.96 |
| One-sided markets | +$313 | +0.8 | +$0.06 |
| **Gross trading** | **+$105,711** | **+256** | **+$18.98** |
| Fees | −$94,208 | −228 | −$16.91 |
| **Net trading** | **+$11,503** | **+27.9** | **+$2.06** |

The residual line is the correction that matters: over one week it read **−$7,683 (−55 bps)**, which looked like a controllable leak. Over three weeks it is **+$10,943 with t = 1.43** — noise with a slight positive drift. Do not engineer against it.

### 3.3 PnL by final all-in pair cost

| All-in pair cost | markets | mean net | total net | market win % |
|---|---|---|---|---|
| < 0.90 | 461 | **+$64.65** | **+$29,803** | 79.8% |
| 0.90–0.95 | 700 | +$45.21 | +$31,645 | 66.9% |
| 0.95–0.98 | 914 | +$25.79 | +$23,574 | 57.2% |
| 0.98–1.00 | 786 | +$2.41 | +$1,891 | 45.7% |
| 1.00–1.02 | 822 | −$6.20 | −$5,097 | 42.9% |
| 1.02–1.05 | 990 | −$31.28 | −$30,964 | 38.3% |
| 1.05–1.10 | 677 | −$47.53 | −$32,180 | 30.0% |
| > 1.10 | 204 | −$36.64 | −$7,474 | 30.9% |

Unchanged conclusion: **the profitable half of the distribution pays for the unprofitable half.** The bot does not control final pair cost; it controls the *average* fill discount (2–3¢ below fair), which is enough to make the median pair land at 0.998 all-in.

### 3.4 Timing fingerprint

| Seconds before close | % fills | % cash |
|---|---|---|
| 0–15 | 0.06% | 0.06% |
| 15–30 | 0.83% | 0.97% |
| 30–60 | 6.11% | 7.76% |
| 60–90 | 9.32% | 10.41% |
| 90–120 | 10.73% | 11.09% |
| 120–180 | 22.70% | 21.53% |
| 180–240 | 24.07% | 22.21% |
| 240–300 | 26.17% | 25.97% |

- First fill: median offset **6 s**, p90 18 s, max 234 s (late entries exist but are rare — 87.8% of markets have a fill within 15 s).
- Last fill: median offset **209 s**, p90 267 s, max 290 s → effective hard cutoff **~10 s before close**; only **2.0%** of fills land in the final 15 s.
- Fill price distribution: p10 0.19, p25 0.31, median **0.47**, p75 0.64, p90 0.77 (mean 0.476). It lives in the middle of the book.

### 3.5 Price bands and calibration

| Band | fills | gross PnL | bps | verdict |
|---|---|---|---|---|
| < 0.05 | 6 | −$6 | −9,370 | ignore |
| 0.05–0.10 | 6,599 | +$114 | +133 | neutral |
| 0.10–0.20 | 45,844 | +$6,151 | +518 | small clips |
| 0.20–0.80 | 384,857 | +$86,048 | +245 | **core book** |
| 0.80–0.90 | 32,933 | +$11,947 | +237 | small clips |
| 0.90–0.95 | 4,273 | +$1,427 | +186 | certainty snipe |
| > 0.95 | 54 | +$29 | +207 | negligible |

The bands sum exactly to gross trading PnL ($105,711). Fill-level calibration is **positive in every bucket from 0.10 to 0.95** (+0.31 to +2.38 pp of hit-rate over price), weakest at 0.20–0.25 (+0.31 pp) and strongest at 0.40–0.45 (+2.38 pp). There is a small, consistent edge — buying at or below fair — and no large mispricing anywhere.

By fill type, gross of fees: **maker 194,590 fills / $1.03M / +$17,641 (+172 bps)**; **taker 280,976 fills / $3.19M / +$88,070 (+276 bps)**. On the same token, maker VWAP is **1.4¢ cheaper** than taker VWAP (mean +0.0142). Taker fills carry more gross edge per dollar but pay 290 bps in fees — without the 50% refund they lose money.

### 3.6 Sizing and risk

| Metric | Value |
|---|---|
| Shares per fill | median **15**, mean 18.0; **34.4% exactly 30** |
| USD per fill | median **$6.40**, mean $8.87 |
| USD per market | mean **$755**, median $616, p90 $1,550, max **$3,846** |
| Largest single ticket | **$162.24 / 200 shares** |
| Peak concurrent cash committed | **$3,845.90** |
| Daily turnover | **$201,021** (Σ market cost ÷ 21) |
| Martingale check | $762.84 mean market cost after a win vs $752.49 after a loss (**+1.4% — none**) |

Size is set in **shares, not dollars**: 30 shares in the first 60 s, decaying to ~14–15 shares after 120 s. USD per fill therefore scales with price ($1.82 below 0.20, $14.65 above 0.80). Hard per-market budget ≈ $3,850, matching the repo's $4,000 window cap.

> The analyzer's `turnover/day` line divides by 7 (it was written for a one-week file); for this 21-day ledger the figure above is the correct one.

---

## 4. What changed versus the one-week report

| One-week claim | Three weeks | Verdict |
|---|---|---|
| Net trading **+2 bps** ("the bot does not make money trading") | **+27.9 bps, +$11,503** | **overturned** |
| Residual directional **−$7,683 (−55 bps)** | **+$10,943 (+26.5 bps), t = 1.43** | **overturned — noise** |
| Marginal adds **+0.87%** | **+1.77%** | understated |
| "Every day was positive" | Oct 19 **−$217**, Oct 18 −$764 (partial day) | **overturned** |
| Median pair cost 0.992 all-in | **0.998 all-in**, 48.5% above 1.00 | **worse than sampled** |
| Taker 55% fills / 71.8% cash | **59.1% / 75.7%** | taker-heavier |
| Maker 45% fills / 28% cash | **40.9% / 24.3%** | taker-heavier |
| Max single ticket 100 shares | **200 shares** | sample limit |
| Peak 19 fills/second | **75** | sample limit |
| Rebate = 50% of prior-day fees | 15/21 exact, 6 within 0.5% | **confirmed** |
| Both sides 99.2% | 99.4% | confirmed |
| Median 75 fills/market | 74 | confirmed |
| First fill T+6 s, hard stop ~T−12 s | 6 s / ~T−10 s, 2% in final 15 s | confirmed |
| ~$737/market, $4k cap | $755 mean, max $3,846 | confirmed |
| Locked ≈ 89% of gross | 89.4% | confirmed |
| "Weekend flow, not decay" | 3 weekends, gross bps flat 140–400 | confirmed (§6) |

**Net effect:** the mechanism section of the one-week report stands. The *attribution* section overstated how close to zero trading is, and invented a systematic residual leak that three weeks of data does not support.

---

## 5. Rebate mechanics — exact within a tier

`TAKER_REBATE(D) / fees(D−1)` for every complete day pair:

| Day | Taker rebate | Prior-day fees | Ratio |
|---|---|---|---|
| 2026-10-20 | $2,715.79 | $5,431.57 | **0.5000** |
| 2026-10-21 | $3,314.63 | $6,629.26 | **0.5000** |
| 2026-10-22 | $2,457.55 | $4,915.10 | **0.5000** |
| 2026-10-23 | $2,897.70 | $5,795.40 | **0.5000** |
| 2026-10-24 | $3,186.54 | $6,373.08 | **0.5000** |
| 2026-10-25 | $1,695.84 | $3,391.67 | **0.5000** |
| 2026-10-26 | $1,580.11 | $3,154.61 | 0.5009 |
| 2026-10-27 | $2,904.06 | $5,808.12 | **0.5000** |
| 2026-10-28 | $2,540.16 | $5,080.31 | **0.5000** |
| 2026-10-29 | $2,666.62 | $5,333.25 | **0.5000** |
| 2026-10-30 | $2,939.70 | $5,878.05 | 0.5001 |
| 2026-10-31 | $1,719.41 | $3,438.82 | **0.5000** |
| 2026-11-01 | $1,100.15 | $2,199.67 | 0.5001 |
| 2026-11-02 | $556.32 | $1,107.73 | 0.5022 |
| 2026-11-03 | $2,845.81 | $5,691.63 | **0.5000** |
| 2026-11-04 | $2,918.65 | $5,837.31 | **0.5000** |
| 2026-11-05 | $2,712.61 | $5,425.22 | **0.5000** |
| 2026-11-06 | $2,894.90 | $5,789.81 | **0.5000** |
| 2026-11-07 | $2,210.23 | $4,420.46 | **0.5000** |
| 2026-11-08 | $565.46 | $1,125.34 | 0.5025 |

Total rebates **$53,942.51 = 127.8 bps of cash notional** (maker $5,861, taker $48,081); they cover **57.2%** of embedded fees. Marginal economics: **~$12,778 of rebate per extra $1M of two-sided notional**.

The residual 0.1–0.25% deviations are day-boundary effects (fills landing either side of 00:00 UTC), not a change in the formula. **This is stable only while the account stays in the same volume tier — across the full 16 weeks the rate climbed 8% → 32% → 44% → 50% as 30-day volume grew**, and it is the number to re-check first if live results diverge.

---

## 6. Regime: weekday vs weekend (three weekends now)

| Phase | days | notional/day | taker % cash | gross bps | net bps |
|---|---|---|---|---|---|
| Mon–Fri | 15 | **$237,334** | 56–71% | 140–398 | −97 to +167 |
| Sat–Sun | 6 | **$106,879** | 32–54% | 142–318 | −46 to +118 |

- Weekend notional runs at **~45% of weekdays**, and the two most recent weekends (Oct 31–Nov 1: $125k/$59k; Nov 7–8: $76k/$63k) were the thinnest in the sample — Oct 24–25 was $165k/$154k. There is a downward drift in weekend flow within the window, or normal variance; three weekends cannot separate those.
- **Gross edge per dollar does not decay** on thin days (142–318 bps vs 140–398 bps), and taker share falls because there is less to hedge against. This reproduces the one-week "weekend flow, not decay" verdict.
- On low-volume days per-market net actually *turns positive* more often, because fees fall faster than gross. A thin market is not a worse market for this strategy.
- Not every day is profitable once rebates are excluded: 7 of 21 days had net trading worse than −$500, with the worst at **−$2,329** (Oct 22). Including rebates, only two days closed negative (−$764 partial-day Oct 18, −$217 Oct 19).

---

## 7. Implications for DSP-v2.5

The bot is **not** configured as a clone of this wallet — it runs an inverse-dip curve with tighter gates. That is a deliberate strategy choice, so only the items where the three-week evidence changes the argument are listed.

| Setting | v2.5 | Wallet (21 days) | Assessment |
|---|---|---|---|
| `dailyLossCapUsd` | **500** | worst net trading day −$2,329; 7 of 21 days beyond −$500 | **too tight** — a $500 cap would have halted a third of days. Cash including rebates never fell below −$764. Defensible range **$1,500–2,500**. |
| `bankrollUsd` | **1,000** | peak capital $3,846/market; $201k/day turnover | fine at v2.5's $30/market size, binding the moment it scales |
| `maxFillPrice` | **0.45** | edges positive 0.10–0.95; mean fill 0.476 | **forgoes the 0.45–0.80 core of the book** — a strategy choice, not fidelity |
| `maxShareLead` | **46 shares** | median residual 143 shares (21.6%), p90 53% | much tighter than the wallet; since residual is noise (t = 1.43), the cap suppresses fills without buying safety |
| `stopBeforeCloseSec` | **75** | last fill median T−91 s, hard stop ~T−10 s | close enough; slightly early |
| `startAfterOpenSec` | **4** | first fill median T+6 s | matches |
| `minFillPrice` | **0.07** | sub-0.10 fills ≈ neutral (+133 bps on the 0.05–0.10 band) | matches; the "sub-10¢ is negative" claim weakened with 3 weeks of data |
| `benchmarkPairCost` | **0.965** | median gross pair 0.977 | v2.5 targets a slightly better pair than the wallet achieves — plausible as an improved variant, but not the wallet's behaviour |
| Rebate accounting | **absent** | +127.8 bps of notional | **the largest gap**: paper P&L books +$2.06/market trading and $0 rebate, understating the strategy by ~83% of its return |

**Priority.** (1) model the rebate — nothing else can be judged until paper P&L includes it; (2) raise the daily loss cap to the measured band; (3) treat the 0.45 price ceiling and the 46-share lead cap as explicit strategy deviations to A/B, not as fidelity parameters.

---

## 8. Kill criteria (updated)

| Condition | Threshold | Consequence |
|---|---|---|
| Taker rebate cut | 50% → 0% | 21-day PnL falls from +$66.2k to +$12.2k (~29 bps); the strategy stops being worth the variance |
| Fee coefficient raised | 0.07 → 0.10 | margin halves with the refund, negative without |
| Gross edge compressed | below ~230 bps **and** locked capture below fees | breakeven after rebates; stop |
| **Rebate tier** | 30-day weighted volume drops below the current tier threshold | the rate steps down (50 → 44 → 32% …) with no change in strategy — re-price at the lower rate |
| Pair cost drift | median all-in > 1.00 for 3 consecutive days | locked capture → 0; residual and rebate become the whole P&L |
| Bankroll | below $4k at wallet scale | cannot fund the $3.8k peak window plus variance |

---

## 9. Confidence and limits

| Claim | Confidence | Basis |
|---|---|---|
| Net trading ≈ +28 bps over 21 days | **High** | cash flows reconcile to the cent across 486k rows |
| Rebate = 50% of prior-day fees **at the top tier** | **High** | 15/21 exact, 6 within 0.5%; the 16-week history shows this is Obsidian, the top of a 30-day volume ladder |
| Residual directional ≈ 0 | **High** | t = 1.43 on 5,571 markets; opposite sign from the one-week sample |
| Locked capture ≈ 89% of gross | **High** | decomposition arithmetic, not inference |
| Weekend-flow explanation | **Medium** | three weekends, no market-wide volume data |
| Maker/taker split 41/59 | **Medium** | labels inferred from the fee, not from exchange order data |
| Peak capital $3.8k / bankroll $8–10k | **Medium** | cost-based, not mark-to-market |
| Maker rebate is a liquidity reward | **Low** | no formula fits; ~$1/market/day |

**What this file cannot answer:** unfilled quotes (fill rates, queue position), intra-window mark-to-market drawdown, adverse selection beyond the next same-token fill, fees on redemption/gas, and the maker-reward formula. Slots with no activity are invisible — 459 missing slots are inferred to be outages, not proven.

---

## 10. Reproduction

The pull script accepts only 1- or 7-day windows, so the sample is three tiled pulls:

```bash
python docs/leaderboard-traders/scripts/save-trades-to-csv.py -u 0xc53375ff94e96100f2b30a4b5775db35218d69a9 -d "2026-10-25 21:35" --days 7 -o scratch/trades_2026-10-18_to_2026-10-25.csv
python docs/leaderboard-traders/scripts/save-trades-to-csv.py -u 0xc53375ff94e96100f2b30a4b5775db35218d69a9 -d "2026-11-01 21:35" --days 7 -o scratch/trades_2026-10-25_to_2026-11-01.csv
python docs/leaderboard-traders/scripts/save-trades-to-csv.py -u 0xc53375ff94e96100f2b30a4b5775db35218d69a9 -d "2026-11-08 21:35" --days 7 -o scratch/trades_2026-11-01_to_2026-11-08.csv

python scratch/combine_trades.py          # -> scratch/trades_2026-10-18_to_2026-11-08.csv (486,244 rows)
python docs/leaderboard-traders/scripts/analyze_weekly_strategy.py scratch/trades_2026-10-18_to_2026-11-08.csv > scratch/analysis_3week.txt
```

Sanity anchor: the third pull reproduces the committed one-week file **exactly (174,019 rows, 72,744,461 bytes)**, so the sample is API-consistent across runs.

The analysis script derives the market clock from `Market_Slug`, resolution from `REDEEM` rows, and the taker fee from `USD_Amount − Price × Shares`. `scratch/` is gitignored; the 486k-row CSV (~200 MB) is intentionally not committed, unlike the original 69 MB one-week export.
