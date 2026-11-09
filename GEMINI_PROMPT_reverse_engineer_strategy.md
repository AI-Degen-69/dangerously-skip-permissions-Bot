# Gemini 4 Argon — Weekly Strategy Reverse-Engineering Prompt

You are a quantitative researcher specializing in short-horizon prediction-market microstructure and market-making economics. I am giving you one dataset: the complete seven-day executed-fill ledger of a single Polymarket wallet on 5-minute Bitcoin Up/Down binaries. Recover what the bot actually did, quantify where its money came from, and hand me a concrete, deployable strategy I can run next week.

## 1. Input

File: `docs/dangerously-skip-permissions/scripts/full-week-trades_dangerously-skip-permissions_2026-11-01_to_2026-11-08.csv` (72 MB, 174,019 rows, 14 columns).

- Wallet (single, throughout): `0xc53375ff94e96100f2b30a4b5775db35218d69a9`
- Window: `2026-11-01T21:35:07+00:00` → `2026-11-08T21:33:30+00:00`
- 1,927 distinct `Condition_ID`s (5-minute slots; a full week has 2,016)

Use code execution against the uploaded file, not manual reading. 174k rows fit in memory in pandas if you set dtypes explicitly. `csv.field_size_limit` may need raising. If you must chunk, chunk by UTC day (7 chunks) and aggregate before analysis — never sample randomly, because per-market sequences are the unit of analysis.

| Column | Meaning |
|---|---|
| `Proxy_Wallet` | always the same address |
| `Timestamp_UTC` | ISO-8601, `+00:00`, **second resolution only — no milliseconds** |
| `Type` | `TRADE` (170,180), `REDEEM` (3,825), `MAKER_REBATE` (7), `TAKER_REBATE` (7) |
| `Market` | human-readable title |
| `Outcome` | `Up` or `Down` (blank on rebate rows) |
| `Side` | `BUY` on every trade row — zero `SELL` rows |
| `Price` | 0–1 fill price (implied probability); `0.0` on REDEEM rows |
| `Shares` | shares filled |
| `USD_Amount` | dollars paid on TRADE; on REDEEM, cash paid out (≈ `Shares` for the winning token, `0.0` for the losing token) |
| `Condition_ID` | one market instance |
| `Token_ID` | one side of that market |
| `Transaction_Hash` | on-chain tx; several fills share one hash |
| `Market_Slug` | `btc-updown-5m-<unix>`, `<unix>` = market **open** time (UTC) |
| `Event_Slug` | identical to `Market_Slug` |

### What is and is not in this file

Present: **every executed action** — each fill, each redemption, each rebate. This is the bot's decision result, not its intent.

Absent, and you must not pretend otherwise: **orders, quotes, cancels, order-book snapshots, fees paid, mark-to-market, BTC spot prices, and millisecond timing.** You cannot see a quote that was never filled, so you cannot directly measure maker fill rates or adverse selection from quotes — you can only infer them from fill patterns. Timestamps are second-granular, so within one second you cannot order fills reliably; order them by `Transaction_Hash` grouping and then by price, and say so.

## 2. Verified anchors — validate your pipeline against these first

I have already confirmed the following. Reproduce each number before doing anything else. If yours differs, your parsing is wrong; fix it before proceeding.

| Metric | Value |
|---|---|
| Row count | 174,019 |
| TRADE / REDEEM / rebates | 170,180 / 3,825 / 7 + 7 |
| Trade notional (cash out) | $1,419,407.65 |
| Redeem cash in | $1,418,875.70 |
| Rebate income | $16,839.98 |
| Net before rebates | ≈ **−$531.95** (flat, slightly negative) |
| Net after rebates | ≈ **+$16,308.03** |
| Markets with fills | 1,927 |
| Markets where **both** Up and Down were bought | **1,911 (99.2%)** |
| Median (avg price Up + avg price Down) per market | **0.992** (p10 0.88, p90 1.071) |
| Markets with combined cost < 1.00 | 54.7% |
| Trades per market | ~88 |

Treat the last four rows as the thesis to verify and explain, not as trivia. If the bot bought both sides of 99.2% of markets and its gross trading PnL is ~zero while rebates are ~$16.8k, then the money is not coming from prediction — it is coming from being a two-sided liquidity provider. Every subsequent analysis exists to confirm, refine, or refute that.

## 3. Non-negotiable data rules

1. **Split the types.** TRADE = fills, REDEEM = settlement, rebates = income with no market attached. Never mix REDEEM and TRADE when computing price, shares, or size.
2. **Market clock from the slug.** `close_ts = int(Market_Slug.split('-')[-1]) + 300`. For every TRADE compute `secs_before_close = close_ts − Timestamp_UTC`. This is the most important derived variable. Positive = before close.
3. **Resolution is recoverable — use it.** Per REDEEM row: `USD_Amount ≈ Shares` ⇒ **winning** token; `USD_Amount == 0` ⇒ **losing** token. Build `{Condition_ID: winner, close_ts}`. Assert never two winners and never zero winners for a settled market. 1,927 markets traded vs ~1,900 settled means some positions were unresolved at snapshot — handle explicitly, do not drop silently.
4. **Aggregate per token before judging anything.** The bot ladder-fills: many rows per `(Condition_ID, Token_ID)`. Reduce to `{shares, cost_basis, vwap, n_fills, first_ts, last_ts, min_px, max_px}`.
5. **Hold-to-resolution accounting** (no sells): for token *t* in market *m*, `pnl = shares × (1 − vwap)` if *t* won, else `−shares × vwap`. Cross-check the per-market sum against REDEEM cash in minus TRADE cash out. Any residual > rounding must be explained (unresolved markets, redeem lag of ~1–2 minutes after close, partial redemption).
6. **Rebates are not alpha.** Report them separately and attribute them by day, hour, and market where possible (7 rows each, so mostly as a rate: rebate $ per $1M of volume).
7. **Fees are invisible.** All PnL is gross of trading fees. State this in the report headline, not a footnote.

## 4. Analysis tasks

For each: give the numbers, the table, and the implication in one sentence. Then feed the implication into the final strategy.

**A. Integrity & scale.** Reproduce the anchor table. Then: markets per UTC day (expect 230–287), fills per market (distribution, not mean), trades/second peaks, `secs_before_close` outside `[0, 300]`, duplicate `(tx, token, price)` rows, rows where `USD_Amount/Shares` deviates from `Price` by >1%, and distinct tokens (expect a 2-token market ratio near 2.0 — quantify it).

**B. Dual-sided inventory — the core mechanism.** Per market: shares and vwap on Up, shares and vwap on Down. Report:
- distribution of `vwap_Up + vwap_Down` (histogram + quantiles), and what it means economically: `< 1.00` ⇒ the paired position is locked-in profitable at settlement regardless of BTC; `> 1.00` ⇒ the pair is a loss and the bot is betting on being *net* one-sided.
- distribution of `min(shares_Up, shares_Down)` (the matched/hedged quantity) and of `|shares_Up − shares_Down|` (the residual directional exposure). Is the bot a true delta-neutral market maker, or directionally exposed by design?
- PnL decomposition per market: `locked = min(sh,sh') × (1 − (vwap+vwap'))` and `residual = pnl_total − locked`. Aggregate both across the week. This tells us whether the P&L came from spread capture or from being right on the winner.
- how the second side gets acquired: same second (simultaneous quoting), within N seconds, or minutes later after the first side moved against it.

**C. PnL attribution.** Total: trade PnL, rebate income, and the split between `locked` (spread/hedge capture) and `residual` (directional). Daily equity curve, max drawdown, best/worst market, win rate of *markets* vs win rate of *tokens held*. Answer plainly: **does this bot make money trading, or only via rebates?** If trading is ~flat, is it flat-but-positive-per-market with high variance, or genuinely zero?

**D. Timing fingerprint.** Histogram of `secs_before_close` per fill, raw and USD-weighted; split by side, by price bucket (<0.20, 0.20–0.45, 0.45–0.60, 0.60–0.80, >0.80), and by first-vs-second-side acquisition. Then per-market: `open_offset` (first fill) and `close_offset` (last fill) distributions, and whether the bot posts from market open or only in a window. Identify any hard cutoff after which it stops filling.

**E. Price behavior & calibration.** Fill price distribution; change in fill price across consecutive fills on the same token (laddering down into weakness vs averaging up vs chasing); fills at extreme prices (>0.90, <0.10) as a share of volume and their PnL contribution. Then the calibration table: conditional on buying at price `p`, how often did that token win? Buckets of 0.05 with n, hit rate, implied prob, edge, mean PnL per dollar. **And the same calibration restricted to the residual (unhedged) side only** — that is the real directional skill test.

**F. Sizing & risk.** USD per fill and per market; whether size scales with price, time-to-close, or recent win/loss (martingale test); whether there is a max exposure cap per market and per token; peak concurrent open exposure across overlapping markets (5-minute slots overlap only at edges — quantify). Infer the working bankroll from peak deployed capital and from daily turnover.

**G. Regime change — mandatory.** Volume decays hard mid-week: 29.4k/30.3k/30.5k/32.4k trades on Nov 2–5, then 24.0k (Nov 6), 11.5k (Nov 7), 10.1k (Nov 8), while the market count stays at ~280/day. Nov 1 is a partial day (2,017 trades, 29 markets). Investigate: did median trade size fall (6.3 → 3.3), did price selection shift (median price 0.48 → 0.36), did fill rate per market fall, did rebates fall proportionally, did PnL per market change? Give me the before/after table and a verdict: **bankroll depletion, throttle/pacing change, parameter retune, or competitive degradation.** This matters more than any single-day statistic, because it tells me whether the bot is degrading over time.

**H. Within-market decision replay.** Reconstruct 10–15 full markets end-to-end: complete fill timeline (offset, token, price, shares, cumulative position, cash), the eventual winner, and the realized PnL split into locked vs residual. Pick a mix: a clean hedge (sum<1), a broken hedge (sum>1), a one-sided market, a late-window market, and the largest win and largest loss. Narrate each in 3–4 lines. Then generalize the decision grammar: open → add → hedge → hold to settlement? Does it ever flip? Does it ever abandon a side? Is there a time-stop?

**I. Rebate mechanics.** $16,840 on $1.42M notional = **118 bps**, but confirm it per-day and per-rebate-type. Infer what generates it: maker rebate on passive fills vs taker rebate, and how it scales with volume and with `min(shares_up, shares_down)` (hedged volume should attract rebates on both legs). Estimate the marginal rebate per extra $1M of two-sided volume. This is the actual business model; quantify the unit economics.

**J. Strategy extraction — the deliverable.** Translate everything into one deployable spec, expressed in the terms a builder needs:
- universe (which 5m slots, entry allowed window, skip rules)
- two-sided quoting logic (when to place the first side, when/at what price to place the hedge, how to handle fill asymmetry)
- price bands with measured values
- sizing rule with measured values, plus max exposure per market and per day
- exit/settlement policy (hold-to-resolve vs early unwind — note there are no sells in this file, so the observed bot never unwinds)
- expected PnL decomposition: locked spread capture + rebates + residual variance, with per-market and per-day expectations
- **kill criteria**: the conditions under which this stops making money (hedge cost drift above 1.00, rebate rate cut, competition compressing the window, bankroll below X)
- **what to drop**: anything in the observed bot that produced negative or negligible value, named explicitly

End task J with pseudocode using *measured* thresholds, and a one-week paper-trading plan with the exact metrics to check daily.

## 5. Required output

One Markdown report:

1. **Executive summary** — 5 bullets: mechanism, gross trading PnL, rebate income, whether the residual side has edge, and the biggest fragility.
2. **Anchor validation** — my table reproduced, with notes on any deviation.
3. **Findings** — one subsection per task A–I, each with its table.
4. **PnL attribution waterfall** — locked spread capture vs residual vs rebates, in dollars and bps.
5. **Regime-change table** — Nov 2–5 vs Nov 6 vs Nov 7–8, with a verdict.
6. **The strategy to run** — the task-J spec, prose + pseudocode + parameter table (parameter | measured value | tolerance | why).
7. **Confidence ledger** — per claim: High / Medium / Low, evidence, and the extra data that would raise it (be specific: order-book snapshots, BTC spot, fee schedule, memorypool/quotes).
8. **Falsifiable predictions** — 5 concrete numbers a correct implementation should reproduce on a fresh week (e.g. "median `vwap_up+vwap_down` = 0.99 ± 0.02", "locked capture ≥ 80% of gross trading PnL", "rebates ≈ 110–125 bps of notional").

## 6. Rules of engagement

- Every claim carries a number. "Trades frequently" is unacceptable; "223 fills per market, 61% USD-weighted inside the last 120s" is.
- Never invent a column, a fee, an order, or an outcome. If the file cannot answer it, write `NOT DETERMINABLE FROM THIS FILE` and name the data needed. Do not assume the bot placed quotes you cannot see.
- Do not smooth over inconsistencies. Unresolved markets, redeem lag, second-granular timestamps, and missing fees all belong in the report body.
- Reconcile: state trade cash out, redeem cash in, rebate income, and confirm your synthetic PnL closes the gap to within rounding.
- Separate measurement from hypothesis at every step. Label hypotheses `[H]`.
- Assume adversarial review: a reader should be able to re-derive every table from the CSV with your code.
