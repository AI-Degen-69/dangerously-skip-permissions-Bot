# Gemini 4 Argon — Strategy Reverse-Engineering Prompt

You are a quantitative researcher specializing in short-horizon prediction-market microstructure. I am giving you one dataset: the complete 24-hour on-chain trade ledger of a single Polymarket wallet. Recover the trading strategy that produced it, quantitatively, from the raw fills alone. Do not speculate where you can measure.

## 1. Dataset

File: `dangerously-skip-permissions_24h_trades.csv` (10,748 rows, 14 columns, single wallet, 24h window).

One proxy wallet throughout: `0xc53375ff94e96100f2b30a4b5775db35218d69a9`.
Window: `2026-11-07T12:25:39+00:00` → `2026-11-08T12:23:22+00:00`.

Columns:

| Column | Meaning |
|---|---|
| `Proxy_Wallet` | always the same address |
| `Timestamp_UTC` | ISO-8601 with `+00:00` offset. Parse with UTC awareness. Do not treat as naive local time. |
| `Type` | `TRADE` (10,236), `REDEEM` (510), `MAKER_REBATE` (1), `TAKER_REBATE` (1) |
| `Market` | human-readable market title |
| `Outcome` | `Up` or `Down` (blank on rebate rows) |
| `Side` | `BUY` on every trade row — there are zero `SELL` rows. Blank on REDEEM/rebate rows. |
| `Price` | 0–1, the share price paid (implied probability). `0.0` on REDEEM rows — that is not a trade price. |
| `Shares` | share count filled |
| `USD_Amount` | dollars paid on TRADE rows; on REDEEM rows this is the cash paid out (≈ `Shares` for the winning token, `0.0` for the losing token) |
| `Condition_ID` | one market instance (unique event) |
| `Token_ID` | one side of that market (Up token or Down token) |
| `Transaction_Hash` | on-chain tx; several fills often share one hash |
| `Market_Slug` | `btc-updown-5m-<unix>`, where `<unix>` is the market's **open** time in UTC |
| `Event_Slug` | identical to `Market_Slug` in this file |

All markets are Polymarket 5-minute Bitcoin Up/Down binaries. Total notional traded ≈ $130,235 across 264 distinct `Condition_ID`s (a 24h window contains at most 288 five-minute slots). Median trade is $3.33, p90 is $17.86, max is $48.50 — so size is granular and small, and there are ~39 fills per market on average.

## 2. Non-negotiable data rules

Follow these before any interpretation, and state in your report that you did:

1. **Split the types.** TRADE rows are fills. REDEEM rows are settlement. Rebate rows are income with no market attached. Never compute a trade price or a share count that mixes REDEEM and TRADE.
2. **Market clock comes from the slug.** `close_ts = int(Market_Slug.split('-')[-1]) + 300`. For every TRADE compute `seconds_before_close = close_ts - Timestamp_UTC`. This is the single most important derived variable in the file. Positive = before close, negative = after close.
3. **Resolution is recoverable — use it.** Each REDEEM row is a claim on one token. The row whose `USD_Amount ≈ Shares` is the **winning** token; the row with `USD_Amount == 0` is the **losing** token. Both are usually present in the same transaction. Build a per-`Condition_ID` resolution table: `{winner_token: Up|Down, close_ts}`. Verify your winner mapping is consistent (never two winners, never zero for a settled market).
4. **Aggregate per token.** The bot ladder-fills: many rows per `(Condition_ID, Token_ID)`. Reduce to `{shares_held, cost_basis, avg_price, n_fills, first_ts, last_ts, min_price, max_price}` before judging anything about sizing or entry price.
5. **Identify the truth gaps and label them.** There are no fee rows, no order-book snapshots, no cancel data, no mark-to-market, and no BTC spot series. Any PnL you produce is "gross of fees and slippage". 264 markets traded vs 257 with REDEEM rows means some positions were unresolved at snapshot time — handle those explicitly rather than silently dropping them.
6. **Hold-to-resolution is the accounting model** (there are no sells). For token *t* in market *m*: `pnl_gross = shares × (1 − avg_price)` if *t* won, else `pnl_gross = −shares × avg_price`. Cross-check the sum per market against the actual REDEEM cash received minus TRADE cash paid; if the two disagree by more than rounding, explain why (partial fills, unresolved markets, redeem lag).
7. Use pandas. 10,748 rows fit in memory. Show the code for every table you report.

## 3. Analysis tasks

Work in this order. For each, give the numbers, the table, and one sentence of what it implies.

**A. Integrity pass.** Row counts by `Type`, distinct wallets/markets/tokens, markets per hour, gaps in the 5-minute sequence (which slots did the bot skip?), trades with `seconds_before_close` outside `[0, 300]`, duplicate `(tx, token, price)` fills, and any row where `USD_Amount / Shares` disagrees with `Price` by more than 1%.

**B. Resolution table.** Winner (`Up`/`Down`) per market, plus base rates. Is the bot's side correlated with the winner? Report: overall hit rate of the side held, and hit rate weighted by dollars at risk.

**C. PnL reconstruction.** Per market and in aggregate: cash out (REDEEM), cash in (TRADEs), gross PnL, ROI on capital deployed, cumulative equity curve over the 24h, max drawdown, best/worst market, count of winning vs losing markets. Add the two rebate rows to gross PnL but report them separately — they are maker/taker incentive income of $789.49 combined and must not be mistaken for trading edge.

**D. Entry timing — the core fingerprint.** Histogram of `seconds_before_close` for all fills, and again weighted by USD. Then the same histogram split by side (`Up` vs `Down`) and by price bucket. Answer precisely: does the bot enter early in the window, mid-window, or in the final seconds? Does timing differ between cheap entries (< 0.20) and mid-price entries (0.45–0.65)? Is there a hard cutoff offset after which it never trades?

**E. Price behavior.** Distribution of fill prices; histogram of the *change* in fill price across consecutive fills on the same token (is it laddering down into weakness, averaging up, or chasing?); relationship between `avg_price` and outcome — the calibration question: **conditional on buying at price p, how often did that token actually win?** Build a calibration table by price bucket (0.00–0.05, 0.05–0.10, … 0.90–1.00) with n, hit rate, implied prob, edge, and mean PnL per dollar. This table is the highest-value output in the entire report: a real edge shows as hit rate systematically above the price paid, especially in the tails.

**F. Position sizing.** Distribution of USD per fill and USD per market; whether size scales with price (cheap = larger share count?), with time-to-close, or with recent losses/wins (gambler's-ruin style martingale?). Test for a max exposure cap per market and per token. Reconstruct the bankroll implied by peak concurrent open exposure.

**G. Market selection.** Of ~288 available 5-minute slots, which were traded and which were skipped? Was the bot continuously active, or did it operate in bursts? Any time-of-day pattern, or any pattern in skipping after losses? Did it trade both sides of the same market, and if so, was that a hedge or an accidental double-exposure?

**H. Within-market decision sequence.** For a handful of representative markets, lay out the full fill timeline (offset, token, price, shares) and narrate the decision sequence. Then generalize: does it open one position and add, or enter once? Does it ever buy the opposite side (a true hedge, or a late flip)? Is there evidence of a stop, a cap, or a time-based exit?

**I. Execution quality.** Compare fills clustered in the same second, and the gap between the price paid and the implied probability implied by the eventual resolution. Cheap longshot buys that won, and expensive favorites that lost, are the two diagnostics for whether this is directional prediction or mispricing capture.

**J. Verdict.** State the strategy in one paragraph a trader would recognize, then specify it as a rule set: universe filter, entry trigger, price band, timing window, sizing rule, exit/settlement, risk limits. Give it as pseudocode with the thresholds you actually measured, not invented ones.

## 4. Required output

A single Markdown report:

1. **Executive summary** — 5 bullets: what the strategy is, measured edge, hit rate, capital efficiency, biggest risk.
2. **Data integrity & method** — what you verified, what you had to assume.
3. **Findings**, one subsection per task A–J, each with its table.
4. **The calibration table** (task E) as its own highlighted section — it is the evidence for or against edge.
5. **Strategy specification** — prose + pseudocode.
6. **Confidence ledger** — for each major claim: `High / Medium / Low`, the evidence, and the specific extra data that would raise it.
7. **Falsifiable predictions** — 3–5 concrete numbers this strategy should produce on a fresh 24h window (e.g. "median entry 90s before close", "hit rate at price 0.10 ≈ 15%"). If your own reconstruction cannot produce these, say the model is underdetermined.

## 5. Rules of engagement

- Every claim gets a number attached. "Often trades late" is unacceptable; "62% of fills land in the last 90 seconds" is.
- Never invent a column, a fee, or an outcome. If the data cannot answer something, write `NOT DETERMINABLE FROM THIS FILE` and say what would be needed.
- Do not smooth over inconsistencies — unresolved markets, redeem lag, and missing fee data must appear in the report.
- Check your work: state total TRADE cash out, total REDEEM cash in, and confirm they reconcile with your synthetic PnL to within rounding.
- Assume adversarial review. A reader should be able to re-derive every table from the CSV and your code.
