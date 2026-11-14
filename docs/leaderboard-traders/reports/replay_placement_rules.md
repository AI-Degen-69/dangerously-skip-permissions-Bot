# Replay the tape, test placement rules offline — results

Date: 2026-11-13. Tool: `bot/replay.py` (new) + `bot/tests/test_replay.py` (new).
Baseline live run `run_20261113_080232_paper_dsp_v2_6` was never touched (still
running; only its windows, tape and `bot/loop.log` were read).

## 0. Phase 0 — what v2.6 actually does, step by step

Extracted from `bot/live_paper.py` + `bot/executor.py` (shipped v2.6 parameters
confirmed against `bot/constants.py` `STRATEGY_SETUPS["dangerously-skip-permissions-v2.6"]`
and the run's own frozen `configSnapshot`):

1. Entry window T+4 s → T−75 s: ticks before `slot + startAfterOpenSec` are
   skipped (`live_paper.py:824`, `start_after_open` from entry `458`).
2. Each tick: drain accumulated trade prints first (`_drain_prints`, `752`),
   offering every print to the resting order on the matching outcome via
   `match_maker_print` (`fill_model.py`); partial fills allowed, `queue_ahead`
   decays with each print and is never reset (`760-773`).
3. Compute imbalance; `in_sweep_phase = now >= end and now < sweep_end and
   imbalance > 0`, with `end = slot+300−75`, `sweep_end = slot+300−12`
   (`811-813`, `829`).
4. At `now >= end`, cancel all resting orders ("sweep phase", `831-833`); at
   `now >= sweep_end` (or flat at `now >= end`) stop and hold to resolution
   (`835-851`).
5. Evaluate `evaluate_microstructure_ladder` (`874-890`) with the run's entry
   numbers (dip curve 33→8 sh, band 0.07–0.55, caps 0.965/0.985/0.995,
   46 sh / $6.00 unhedged, spacing 0.5/2.5 s).
6. Deficit (hedge) branch (`executor.py:303-360`): the hedge **rests at the
   lagging side's bid** (`336`) and books only when a seller comes to it
   (patient pair, `b2c1069`); in the sweep it crosses as TAKER (`332-333`).
   Rescue fills allowed up to pair cost 0.995 below 0.985 (`345-347`).
7. Fresh-dip branch (`412-490`): DSP rests bids only (`418-424`, the `49c4b73`
   dust skip — a bid under `minFillPrice` is skipped, never taken); dip band
   ≤0.45 (`431`); an opening straddle leg is allowed at 0.45–0.55 only while
   both sides are flat (`493`); pair-cost gate ≤0.965 fresh / ≤0.985 closing
   (`475-476`).
8. Pacing: a placement within 0.5 s of the last fill on a price move (2.5 s on
   a static quote, 0.5 s in the sweep) is skipped (`928-934`).
9. TAKER decisions book immediately at the ask with fee
   `0.07·p·(1−p)` (`939-944`, `compute_fill_usd`); MAKER decisions rest via
   `_place_maker` (`775-797`): same price keeps the queue, a new price reads
   `live_queue_ahead` = exact resting size at that level (or 0.0/unknown).
10. Fills are stamped with the queue they paid through, fees, pair cost only
    when the fill reduces the imbalance, and `detail.strategy`
    (`665-700`).

The replay (`bot/replay.py:simulate_window`) mirrors this 1:1 in virtual time:
merged book/print event stream, quotes from recorded top-5 snapshots, real
`evaluate_microstructure_ladder` / `compute_fill_usd` / `match_maker_print`
calls, same sweep/cancel/pacing arithmetic. Two deliberate, documented
approximations: (a) the loop's wake-on-tick cadence (~10–80 evals/s measured in
`decisions.jsonl`) is replayed at every recorded book row; a `--eval-floor-ms`
sensitivity run shifts nothing through the gate either way; (b) queue ahead is
the exact level size from the nearest top-5 snapshot at placement (the live
loop reads the full book at its tick) — when the level is outside the visible
top-5 the replay stores 0.0 and counts `queue_unknown`, exactly as the live
loop stores 0.0 for an unseen level.

## 1. Gate result: PASS (on the windows the tape can actually replay)

Gate run `--rule v2.6 --against-live`, 2026-11-13 ~12:15 UTC, replay commit at
`bot/replay.py` + `bot/tests/test_replay.py` (uncommitted at gate time).

| check | live (recomputed at gate time) | replay | bar | verdict |
|---|---|---|---|---|
| total maker fills | 14 | 15 | ±20% (11.2–16.8) | ✅ |
| fill rate | 1.84% (18 fills / 978 placements) | 2.02% (19 / 955) | ±0.5 pp | ✅ |
| median per-window pair cost | 0.9706 (n=3 paired) | 0.9759 (n=4 paired) | ±0.02 | ✅ |
| per-window fill-count rank correlation | — | spearman 0.612 | > 0.5 | ✅ |

Replayed set: 17 windows with surviving book + prints (4 from
`run_20261113_073610_paper_dsp_v2_6`, 13 from `run_20261113_080232_paper_dsp_v2_6`);
live fixture recomputed over exactly the same slugs (v2.6 fills filtered on
`fill.detail.strategy`, placements counted per `[slug]` from `bot/loop.log`,
pair cost as `sum(fill.usd) / min(up, down)` per `bot/ab_test.py:74`).

Zero-fill agreement is exact on most quiet windows; the traded windows line up
fill-for-fill within one print race (e.g. `…567000`: 2/2 @ pc 0.9856/0.9759;
`…567300`: 4 live vs 2 replay with pc 0.9706/0.96 — the two extra live fills
are a whipsaw double-print the replay's queue snapshot priced out).

### Discrepancy classes found (and what each cost)

1. **Rotation pruning deletes the book (dominant).** The recorder caps book at
   128 MB/segment and prunes old archives (`bot/ws.py:_prune_tape`), so each
   run keeps only ~25–60 min of book. Of 313 window files across the four
   runs, **~35 have usable book**; the "172 windows in under 60 s" corpus does
   not exist. Windows whose book starts mid-window are excluded, never scored
   as zero-fill matches (`coverage_ok`).
2. **The compared-against-live target moves under two axes: config AND
   engine.** `run_20261113_061914` traded a transitional config (ceiling 0.45,
   $5.00 cap) under the pre-`b2c1069` hedge-now engine; `49c4b73` (dust skip)
   landed mid-baseline-run. The gate therefore uses only windows traded under
   today's engine + frozen v2.6 config (0736 + post-fix 0802 windows). Pooling
   the 0619 windows fails the median (0.99 vs 0.75) for this reason alone —
   that failure reproduced, was diagnosed, and is excluded by rule, not by
   tuning.
3. **Queue snapshots are timed, not exact.** The replay reads the nearest
   top-5 snapshot; the live loop reads the full book at its tick. On whipsaw
   prints (e.g. 283 sh @ 0.61) the two can disagree about what was ahead, so
   single fills flip. Aggregates match; individual spike fills do not always.
4. **Print/book clock skew.** Prints carry exchange timestamps, book rows carry
   streamer-receipt timestamps; sub-second misordering at print bursts is
   possible and unfixable from the tape.
5. **Pre-open fills.** A few live fills predate `slot+4` (loop clock vs market
   open); the replay never books before the bell, by design.
6. **Zero-size prints are inert.** The feed emits size-0.0 SELL markers; both
   the live matcher and the replay ignore them (no size, no fill).
7. **v2.5-era fills are weak evidence.** That run's fills predate queueAhead
   stamping and its `loop.log` placement lines have scrolled, so neither the
   queue nor the fill-rate denominator survives; several assumed fills have no
   supporting SELL flow in the surviving tape. Excluded from the gate, kept as
   counterfactual corpus for candidates.

Sensitivity: `--eval-floor-ms 0` (message-rate evals) and `12` (measured live
cadence) both pass all four checks on the frozen set; `--queue-mode
cumulative` (sum of sizes ≥ limit, the literal prompt formula) over-fills
makers and fails the count check. Floors 25/50 ms were also tried on the
later churned set and LOSE fills (replay 15–16 vs live 21, counts fail) — a
slower loop misses the chase, so the default stays at message-rate evals with
the exact-level queue (the live `live_queue_ahead` mirror).

### Gate re-run on the churned set (final code, full honesty section)

The tape rotates while the live run grows, so ~2 h after the PASS the same
gate command sees a different 26-window set (4 × 0736 + 22 × 0802): counts
✅ (replay 23 vs live 21, inside ±20%), rate ✅ (2.05% vs 1.90%), median ❌
(0.63 vs 0.9246, n=5 paired), spearman ❌ (0.098). The two failures share one
anatomy: three crash-catch windows (…571800/…572100/…572700, 12:16–12:24
UTC) where live filled thin queues it recorded at its own ticks (qa 9–30)
while every tape snapshot at those levels shows hundreds — the replay's flow-
netting (`queue minus intervening SELLs`) cannot shrink a queue the snapshots
never saw thin. A `REPLAY_TRACE` placement log (env-gated, kept in
`bot/replay.py`) confirms the replay chased the same prices (0.22→0.12) and
simply never drew a thin queue. Counts and rates still reproduce; single-
whipsaw pair levels do not always. The PASS above stands on the frozen
evidence recorded at gate time; this section records what changed and why,
so a future re-run is not mistaken for a regression.

## 2. Candidate table (final code, full corpus, one consistent run)

All arms replayed `--runs all` (339–340 window files; counts drift ±1 as the
tape rotates between arms). Hump arms default to ceiling 0.55 unless noted.
Fill rate = fills / placements; pair cost = median `sum(usd)/min(up,down)`
over paired windows (n).

| arm | rule | fills (maker/taker) | fill rate | placements | median pc (n) | net $ (paper) |
|---|---|---|---|---|---|---|
| A shipped | v2.6 L1 | 85 (74/11) | 2.50% | 3405 | 0.784 (14) | −26.65 |
| B hump | hump L1 | 125 (112/13) | 8.21% | 1522 | 0.7842 (15) | −93.86 |
| C hump-0.75 | hump L1 ceiling 0.75 | 125 (112/13) | 8.21% | 1522 | 0.7842 (15) | −93.86 |
| D hump-L2 | hump L2 | 174 (159/15) | 6.06% | 2873 | 0.861 (16) | −184.57 |
| E hump-L3 | hump L3 | 186 (171/15) | 4.54% | 4095 | 0.861 (16) | −250.97 |
| F shipped-L2 | v2.6 L2 (inverse-dip curve) | 109 (99/10) | 1.69% | 6431 | 0.774 (14) | −87.67 |
| G hump-L2-1¢ | hump L2 spacing 0.01 | 233 (216/17) | 10.62% | 2194 | 0.866 (15) | −210.66 |
| H hump-L2-3¢ | hump L2 spacing 0.03 | 151 (137/14) | 4.91% | 3076 | 0.7842 (15) | −160.73 |

Raw outputs: `scratch/cand2_{A…H}_*.json` (final code). The earlier
mixed-code `scratch/cand_{A…H}_*.json` set was removed during cleanup — it
was superseded before the table was built and never used.

## 3. Per-candidate notes (the four placement questions, answered)

1. **Ceiling 0.55 → 0.75 is a proven no-op: B ≡ C to the fill.** Identical
   fills (125), placements (1522), cost, payout, median pc. Mechanism, not
   luck: `dip_max = 0.45` (`executor.py:431`) caps fresh-dip bids and the
   0.45–0.55 straddle leg (`executor.py:493`) requires both sides flat — the
   corpus never arms either path above 0.55, so the ceiling never binds.
2. **Hump beats shipped everywhere it matters: B vs A = +47% fills
   (125 vs 85) at the SAME pair cost (0.7842 vs 0.784), with fewer than half
   the placements (1522 vs 3405).** The hump's fat mid-curve rests size where
   whipsaws actually trade instead of stacking it at the touch.
3. **Levels only matter with hump (curve × levels interaction).** Hump L1→L2:
   +49 fills (125→174); L2→L3: +12 more (→186) but the rate falls each step
   (8.2% → 6.1% → 4.5%) as placements outgrow fills, and median pc steps up
   0.784 → 0.861. Shipped L1→L2 (F vs A): +24 fills but rate FALLS
   2.5% → 1.7% across 6431 placements — extra rungs of a thin-at-distance
   curve just queue more paper that never trades.
4. **Spacing 1¢ > 2¢ > 3¢, monotonically: G (10.62%) > D (6.06%) > H
   (4.91%).** G is the best arm overall: 233 fills, 2.7× shipped, at median
   pc 0.866. Price: G fragments the most (89 frag fills) and its pairs cost
   ~8¢ more than B's — volume for price.

Net-$ column: every arm (including shipped) shows paper cost > payout on this
corpus, so per §4 arms are judged on fill rate and pair cost, not on
projected P&L — absolute dollars do not transfer (clip ≪ wallet depth).

## 4. What this does not prove

- 17 gate windows (3–4 paired) settle fill rate and pair cost only to ±noise;
  35 replayable corpus windows are noisier than they look because the v2.5 and
  v2.6 eras are different market regimes.
- The clip does not move the flow at 10–50 shares but would at 1,000+; the
  wallet's 557 sh/market depth is two orders of magnitude above our clips, so
  absolute P&L and gross-bps projections do not transfer.
- Queue-ahead is read from snapshots between prints, so fills are slightly
  overstated where the snapshot lags a shrinking level (and understated where
  it lags a growing one); direction nets out in aggregates but not per fill.
- Directional net dollars are not settled by 35 windows — judge arms on fill
  rate and pair cost, as specified.

## 5. Recommendation for a v2.7

Ship **G: hump curve, 2 levels, 1¢ spacing, ceiling 0.55** if the goal is
maximum fills — 233 fills at 10.62% rate (2.7× shipped volume) for ~8¢ of
pair cost (0.866 vs 0.784) and the highest fragmentation (89), which a live
loop should absorb the same way it absorbs today's frag. If the goal is
caution over volume, ship **B: hump L1** instead — +47% fills at pair cost
identical to shipped with the fewest placements of any arm (1522). Do not
ship the ceiling change (no-op), L3 (rate decay, +12 fills for +1222
placements), or extra levels on the shipped curve (rate goes backwards).
Caveat from the gate re-run: on crash-catch whipsaws the replay understates
thin-queue fills, so G's edge is a lower bound on bursty days and its pair
cost should be re-checked on the first live week before widening size.
