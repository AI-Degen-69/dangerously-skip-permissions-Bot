# Wallet mechanics — what `0xc533…d69a9` actually does

Source: `scratch/trades_full_history.csv` (the ledger) — 1,191,338 rows,
2026-07-17 → 2026-11-08, 31,506 markets, wallet
`0xc53375ff94e96100f2b30a4b5775db35218d69a9`.

Method: every number below is recomputed from the ledger, not from the HTML
reports. Fills only — the ledger records what was **filled**, never what was
quoted. Prices are the printed fill price. P&L treats the book as held to
resolution: `winning_shares − cost`, fees at `0.07 · p · (1−p)` per share
weighted for the taker share of cash (76.8%).

Reproduce with `docs/leaderboard-traders/scripts/analyze_mechanics.py`,
`analyze_first_leg.py`, `analyze_levels.py`, `analyze_sequence.py`.

---

## 1. Shape of the book

| | |
|---|---|
| rows | 1,135,104 BUY · **0 SELL** · 55,983 REDEEM |
| markets | 31,506, of which 27,929 bought both sides (88.6%) |
| fills per market | median **21**, mean 36 |
| redemption received | $13,764,713 |
| notional traded | $13,601,158 |

It never sells. Every position ends at resolution. That one fact rules out most
"exit management" designs: there is no exit management.

## 2. It runs both ladders at once — it is not leg-then-hedge

| test | result |
|---|---|
| both sides bought inside the same time span | **91.1%** of markets |
| mean run of consecutive same-side fills | **2.80** (1.0 = perfect alternation) |
| median gap between the two sides' *first* fills | **10 s** (p25 3 s, p90 72 s) |

The "first leg" and "second leg" are artefacts of which ladder got hit first.
There is no hedge decision to replicate.

## 3. Where the first leg lands

| p1 | opposite side's first fill | sum | the first side won |
|---|---|---|---|
| 0.21 | 0.74 | 0.94 | 26.8% |
| 0.38 | 0.58 | 0.97 | 40.7% |
| 0.50 | 0.47 | 0.97 | 52.7% |
| 0.62 | 0.35 | 0.98 | 63.3% |
| 0.79 | 0.20 | 1.00 | 75.9% |

Distribution of the first leg: min 0.01, p5 0.23, p25 0.40, **p50 0.50**,
p75 0.60, p95 0.74, max 0.94.

- **37.5%** of markets open at ≤0.45, **25.4%** in 0.45–0.55, **37.1%** at ≥0.55
- below 0.15: **1.0%** — the 7c opening is a myth, it happens 11 times in 1.19M rows

The win rate tracks the price almost one-for-one, so the extremes carry **no
directional edge**. The price of the first leg is the market's price, not a rule.

### Time explains the extremes

| first leg at | median offset after open |
|---|---|
| ≤0.25 | **+64 s** |
| 0.35–0.45 | +12 s |
| 0.45–0.55 | **+10 s** |
| 0.55–0.65 | **+10 s** |
| 0.65–0.75 | +16 s |
| >0.75 | **+50 s** |

Late = the market already moved. Sub-25c and above-75c openings are mid-window
fills, not entries.

## 4. There is no target pair cost

| second side waited | n | median p1+p2 |
|---|---|---|
| 0–1 s | 3,021 | 0.990 |
| 2–5 s | 5,957 | 0.990 |
| 6–15 s | 7,402 | 0.970 |
| 16–30 s | 4,220 | 0.960 |
| 31–60 s | 3,538 | 0.942 |
| 61–120 s | 2,524 | 0.930 |
| >120 s | 1,267 | 0.950 |

- most common pair sums: 1.01 (1,834), 1.00 (1,819), 0.99 (1,650), 0.98 (1,488)
- **sd 0.123** — a target cost would be a spike, this is a market distribution

At a 0–1 s lag the sum is 0.99: that is just crossing the spread, no edge at all.
The discount only appears when the second side waits. The pair cost is
**emergent** — the sum of two discounts caught independently — not a parameter.

## 5. Sizing: a share ladder with a 30-share floor, not a notional budget

| price band | median shares per level | median $ per level |
|---|---|---|
| 0.00–0.10 | **30.0** | $2.4 |
| 0.20–0.30 | 39.1 | $9.8 |
| **0.40–0.50** | **48.7** | $21.9 |
| 0.60–0.70 | 39.4 | $25.3 |
| 0.80–0.90 | **30.0** | $25.5 |

Per market: **12 levels** (p25 5, p75 26), **557 shares**, **$271** (p75 $605,
p90 $1,074). Per level: 39 shares (p25 23.5, p75 61), 2.1 prints, 45.4% of levels
filled more than once. Per print: p25 5 shares, p75 30 shares at every price.

Dollars per level swing **10×** across the book, so it is emphatically **not**
fixed notional. The curve is a **hump**: smallest at both extremes, biggest at
the money.

## 6. It works inside the round nickels

Fills at prices exactly on the 5c grid: **80,548**, against ~226,000 at each of
the four other cent residues (0.35×). It sits just inside the round level, where
the queue is shortest — not on it.

## 7. Economics: the trading loses money, the rebate pays

| | |
|---|---|
| gross trading | +$161,292 (**+119 bps**) |
| fees | −$309,585 (**−228 bps**) |
| **net before rebate** | **−$148,293 (−109 bps)** |
| rebates (taker $149.7k + maker $18.4k) | +$168,081 (**+124 bps**) |
| **net** | **+$19,788 (+15 bps)** |

The taker rebate is ~48% of the modelled taker fee, which independently confirms
the fee model. This wallet is a **near-zero-sum volume machine kept alive by
rebates**. Copying its trading copies a −109 bps business.

### P&L by when the first leg happened

| first leg at | n | net > 0 | net median bps |
|---|---|---|---|
| 0–15 s | 16,909 | 45.8% | **−168** |
| 16–30 s | 4,851 | 49.4% | −41 |
| 31–60 s | 3,272 | 54.2% | +329 |
| 61–120 s | 2,773 | 56.3% | +571 |
| >120 s | 1,934 | 60.0% | **+1,091** |

Early entry is its **worst** cell. The caveat is real: when the wallet's first
trade is late it was idle in that market, so this is a selection effect as much
as timing skill. It is not a licence to build a "wait 90 s" rule.

---

## 8. v2.6 as it stands today

`dangerously-skip-permissions-v2.6` ("Patient Pair"), committed in `b2c1069` and
`49c4b73`:

| rule | value |
|---|---|
| entry window | T+4 s → T−75 s (sweep to T−12 s) |
| price band | 0.07 – 0.55 |
| dip curve | **33 sh @ 0.07 → 8 sh @ 0.45** (inverse) |
| straddle leg | 0.45–0.55, one side, 10 sh default, 45 max |
| unhedged caps | 46 sh lead, $6.00 |
| pair caps | target 0.965, max 0.985, rescue 0.995 |
| second leg | **rests at the lagging side's bid**, crossed only in the sweep |
| fill engine | maker fills only from a real print that consumes the queue |
| open orders | shown in the UI with queue-ahead |

### Live result (paper, still running)

Run `run_20261113_080232_paper_dsp_v2_6`, 23 windows at the time of writing:

| | |
|---|---|
| windows traded | 16 / 23 |
| placements | 2,357 |
| fills | 39 (37 maker, 2 taker) |
| **fill rate per placement** | **1.7%** |
| cost / payout / net | $107.55 / $111.53 / **+$8.63** |
| fees | $0.33 |
| queue ahead at placement | p50 50, 50% under 50, 14% under 10 |

**Read this number honestly: the +$8.63 is two windows.** `1794563100` (+$17.49)
and `1794560100` (+$9.90) carry it; the other fourteen sum to −$18.76. It is a
directional sample, not an edge. Fills are also fragments — 0.01 to 1.85 shares
on several of them — so the sample is smaller than the count suggests.

---

## 9. v2.6 vs the wallet — row by row

| dimension | v2.6 today | the wallet | verdict |
|---|---|---|---|
| order structure | one order per side, re-quoted on a 0.5 s price move | ~12 simultaneous levels per market, both tokens | **different — ours is serial, theirs is parallel** |
| leg 2 | placed *after* leg 1 fills, at the lagging bid | no leg 2; the other ladder was always resting | **different by design** |
| pair cost | enforced as a gate (≤0.985) | emergent, 0.93–0.99, no gate | **different — we suppress exactly the trades that produce their discount** |
| first-leg band | 0.07–0.55 | 0.01–0.94, p25–p75 0.40–0.60 | **ours is truncated: misses 37% of their openings above 0.55** |
| size curve | 33 sh @7c → 8 sh @45c | 30 sh @≤0.10 → 48.7 sh @0.40–0.50 → 30 sh @≥0.70 | **ours is inverted** |
| clip / market | 45 sh cap, 10 sh default | 557 sh median, 12 levels | **12× smaller** |
| fills per window | 2.4 | 21 | **9× fewer** |
| fill rate | 1.7% of placements | — | queue-bound |
| exit | hold to resolution, no sells | hold to resolution, no sells | **same** |
| taker share | 2 of 39 fills | 58.6% of fills / 76.8% of cash (earlier estimate) | **ours is far more passive than the target** |
| timing | opens at T+4 s | median first fill +13 s, best cells after +30 s | similar entry, but ours sits in their worst cell |

### Why our fill rate is 1.7%

The engine holds a single order per side and replaces it whenever the bid moves.
Their edge comes from having a dozen levels down at once, so whichever dip
happens is caught. We have to guess the one price, and then we sit behind a
median queue of 50 shares with a 10-share clip.

---

## 10. Corrections to earlier claims in this session

Recorded because they shaped v2.6 and are now known to be wrong.

| earlier claim | what the ledger says |
|---|---|
| "the wallet enters at the money immediately; first fill 0.50 at +13 s" | true as a median, **but that is its worst-performing cell** (0–15 s, net med −168 bps) |
| "net-of-fee trading +88 bps" | **−109 bps before rebate**, +15 bps with it. The +88 figure does not survive recomputation |
| "queue at the touch is 1,000+ shares, a clip can never fill" | that was one cherry-picked level. Aggregate queue at our placements is **p50 50 shares**, 14% under 10 |
| "the 7c ladder belongs to the completing side" | the wallet never buys 33 sh at 7c. It buys **30 sh at every extreme** and **48.7 sh at the money** — the curve is a hump |
| "the hedge should rest and wait, so move the entry band to 0.55" | the resting hedge is right for *pair completion*; the 0.55 ceiling is still wrong, and the **sizing curve matters more than the ceiling** |
| "a target pair cost near 0.965 is the thing to hit" | no target exists. Pair sums run 0.93–1.01 with sd 0.123 |

---

## 11. Design implications (groundwork, not a spec)

Ranked by evidence strength, not by size of change.

1. **Fix the size curve first.** Evidence: strongest and clearest. Ours is
   inverted against a 1.19M-row record. A hump — ~30 sh at the extremes,
   ~45–50 sh at 0.40–0.60 — replaces the inverse dip curve.
2. **Then widen the ceiling past 0.55.** 34% of their markets open in 0.55–0.75,
   the only mid-band with a positive median. Do this after the curve, so the
   extra band is not filled at 8 shares.
3. **Then go parallel.** Two or three simultaneous levels per side instead of
   one order that chases. This is what turns a 1.7% fill rate into something
   that samples the book. It is also the largest engineering change: the desk
   currently models one open order per side.
4. **Do not add a time gate yet.** The late-entry advantage is confounded by
   market selection. Test it on the paper desk by recording the counterfactual,
   not by hard-coding +90 s.
5. **Do not copy the taker behaviour.** At ~$5/window our fee arithmetic cannot
   absorb it; their taker business is what the rebate subsidises.

## 12. Open questions

- Is the 30-share floor a venue minimum or a choice?
- What sets levels-per-market (5–26)? Nothing in the data explains the spread.
- Do the late >0.75 entries stay positive net of rebate once rebates are
  allocated per market instead of uniformly?
- Their fills show no `SELL` rows at all — how do they handle a position that is
  still unbalanced at resolution? It shows up as a REDEEM, but we cannot see the
  decision to accept it.
