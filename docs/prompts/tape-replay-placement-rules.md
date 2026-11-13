# Implementation prompt — replay the tape, then test placement rules offline

Paste everything below into a fresh session in this repo.

---

## Role and goal

You are working in `C:\Users\Tiger\Agents\Projects\AI Trading\dangerously-skip-permissions-bot`
(Polymarket 5-minute BTC up/down paper bot, Python, Windows/PowerShell).

**Goal:** stop tuning the strategy against a few dozen live fills, and start replaying the tape we
already own. Build `bot/replay.py`, prove it reproduces what v2.6 actually did, then use it to settle
four placement questions in minutes instead of weeks.

The live run `run_20261113_080232_paper_dsp_v2_6` stays running and untouched while you do this. It is
the baseline the replay must be validated against, and it is the only clean sample after the dust fix.

There is a much better instrument sitting unused: **172 recorded market-windows** (119k prints, book
snapshots, winners) across four runs. Tape was made mandatory precisely so this would be possible.
Nothing has used it this way yet.

## Non-goals — do not do these

- **Do not modify** `bot/executor.py`, `bot/live_paper.py`, `bot/fill_model.py`, `bot/constants.py`,
  `bot/config.json`, `src/app/botDefaults.ts`, `src/app/lib/bot.ts`. No strategy edits at all.
- **Do not** touch, restart, or kill the running loop (pid in that run's `loop.pid`).
- **Do not** register a v2.7 setup or change the active setup.
- **Do not** copy the tracked wallet's taker flow — it runs −109 bps before a rebate we do not get.
- **Do not** hard-code a time gate. It is confounded (see § Context).
- No new dependencies. Stdlib plus what the repo already installs.

## Read this first

| File | Why |
|---|---|
| `docs/leaderboard-traders/reports/dangerously-skip-permissions_wallet_mechanics.md` | The findings this work tests. §8 is v2.6 as it stands, §9 is the row-by-row gap table, §11 is the ranked implication list. |
| `bot/fill_model.py` | `match_maker_print(order, print_row)` — **the matcher the replay must reuse**. Only an explicit `SELL` print fills a resting bid, behind `queue_ahead`, partial fills allowed, order dict mutated. Do not write a second fill model. |
| `bot/live_paper.py` | The loop to mirror: `trade_window` (entry/sweep/stop timing), `_place_maker` (re-quote cadence, `minSpacingMoveSec` 0.5), `_cancel_orders("sweep phase")`, `_open_order_rows`, `_queue_print`. `sweep_end = slot + 300 − 12`. |
| `bot/executor.py` | `dip_curve_shares(curve, price, max_clip)`, `select_ladder_clip`, `evaluate_microstructure_ladder`, `compute_fill_usd` (taker fee `0.07·p·(1−p)`), `_projected_pair_cost`. The rule under test lives here; the replay calls it, it does not re-implement it. |
| `bot/constants.py` | `STRATEGY_SETUPS["dangerously-skip-permissions-v2.6"]` (line ~252) and `_SETUP_FEATURES` (line ~327). Mirror of the shipped config. |
| `bot/tape_verifier.py` | `load_prints_for_window(tape_dir, start_s, end_s)` — how the repo already slices a window out of a rotating tape. |
| `bot/runs.py` | `tape_segments(tape_dir, stem)` — the recorder rotates `prints.<epoch>.jsonl` / `book.<epoch>.jsonl` by size, so readers must walk archives before the active file. |
| `bot/fill_audit.py` | `audit_window`, `_queue_ahead_recorded`, `_sell_flow`, `_spend` — existing attainability logic; reuse the arithmetic rather than inventing another. |
| `bot/ab_test.py` | `pair_cost = total_cost / min(shares_up, shares_down)` (line 74). Use this definition; do not invent one. |
| `scratch/sizing_sim.py` | Prior replay harness (~22 KB) from the v2.4 era. Read it for the loop shape, then **ignore its fill model** — that crude model is exactly what this task replaces. It is gitignored; do not move it into `bot/`. |
| `bot/tests/` | 223 passing tests. Add `bot/tests/test_replay.py` here. |

## The tape: schema and corpus (verified, do not re-derive)

`bot/runs/<run_id>/tape/` holds two append-only files per run, plus size-rotated archives.

`prints.jsonl` — one line per real trade print:

```json
{"ts": 1794504592.038, "asset_id": "9315…817", "price": 0.49, "size": 6.1, "side": "BUY",
 "timestamp": "1794504592038", "fee_rate_bps": "0", "market": "0x7eda…bd3", "slug_outcome": "Down"}
```

`book.jsonl` — one line per book change, top 5 only:

```json
{"ts": 1794542230.2896855, "asset_id": "1507…951", "outcome": "Down",
 "bids": [[0.19, 155.57], [0.18, 65.0], [0.17, 2165.56], [0.16, 909.1], [0.15, 827.27]],
 "asks": [[0.2, 400.0], [0.21, 25.91], [0.22, 229.38], [0.23, 271.0], [0.24, 243.1]]}
```

Corpus available today:

| run | prints | markets | book |
|---|---|---|---|
| `run_20261110_183056_paper_dsp_v2_5` | 93,986 | 126 | 134 MB + 23 MB segments |
| `run_20261113_080232_paper_dsp_v2_6` | 18,704 | 28 | present |
| `run_20261113_061914_paper_dsp_v2_6` | 5,917 | 12 | present |
| `run_20261113_073610_paper_dsp_v2_6` | 1,581 | 6 | present |

Two joins you must get right:

- **Prints carry no slug, only `market` = condition id.** Join to the window file by
  `print["market"] == window["condition_id"]` and clip `ts ∈ [start, start+300]`.
- **Window start epoch is the suffix of `event_slug`**: `btc-updown-5m-1794563700` → `1794563700`
  (`datetime.fromisoformat` on the stamp is *not* on the window; the slug is the authority).

## Fixture: what v2.6 did (the acceptance target)

Run `run_20261113_080232_paper_dsp_v2_6`. **Recompute these at gate time — the run is live and the
numbers drift.** As of the last session:

| | |
|---|---|
| windows in folder | 27 → 29 while this was written |
| v2.6 windows traded | 16 → 21 |
| placements logged | 2,357 |
| fills | 39 → 53 (49 maker, 4 taker) |
| fill rate | 1.7% |
| cost / payout / net | $107.55 / $111.53 / +$8.63 → $124.90 / $122.08 / **−$2.82** |
| fees | $0.33 → $0.45 |
| median per-window pair cost | 0.9698 (n=8 paired windows) |
| queue ahead at placement | p50 50, 50% under 50, 14% under 10 |
| fragments (<1 share) | 13 of 53 |

**Two traps in that table, both fatal if missed:**

1. **The window-level `strategy` field is unreliable.** 28 of 29 windows in this folder say
   `hapcs-v1` while every one of the 53 fills is stamped
   `detail.strategy == "dangerously-skip-permissions-v2.6"`. Filter on the **fill's**
   `detail.strategy`, never the window's. Filtering on the window field yields zero windows and a
   replay that "matches" by being empty.
2. **Window `pair_cost` is null on most windows.** Compute
   `sum(fill.usd) / min(up_shares, down_shares)` yourself over the v2.6 fills (`bot/ab_test.py:74`).

The +$8.63 is two windows (`1794563100` +$17.49, `1794560100` +$9.90); the other fourteen sum to
−$18.76, and by the time you read this the run may well be negative. Judge the replay on **fill rate
and pair cost**, not dollars.

Exact recompute (`python -c "..."` or a scratch script; do not commit it):

```python
S = 'dangerously-skip-permissions-v2.6'
# per window: fills = [f for f in w['fills'] if f['detail'].get('strategy') == S]
# cost = sum(f['usd']); up/down shares; payout = winner_shares; pair = cost / min(up, down)
```

Placements come from `loop.log`: lines containing ` rest ` and `behind`, after the last
`session initialized:` marker. Fill rate = booked fills / placements for the same slice.

## Phase 0 — read the loop, write down the rule (no code)

Before building, extract the exact v2.6 decision sequence from `bot/live_paper.py` + `bot/executor.py`
and write it as a numbered list in your working notes: when an order is placed, at what price, at what
size, when it is cancelled, when the sweep fires, what the taker fallback is.

Shipped v2.6 parameters (confirm against `constants.py`, do not trust this list blindly):

| rule | value |
|---|---|
| entry window | T+4 s → T−75 s |
| sweep / hard cutoff | T−12 s |
| price band | 0.07 – 0.55 |
| dip curve | 33 sh @ 0.07 → 8 sh @ 0.45 (inverse) |
| straddle leg | 0.45–0.55, 10 sh default, 45 max |
| unhedged caps | 46 sh lead, $6.00 |
| pair caps | target 0.965, max 0.985, rescue 0.995 |
| second leg | rests at the lagging side's bid, crossed only in the sweep |
| re-quote cadence | 0.5 s on price move |

**Acceptance:** your numbered list, pasted in the final report, matches the code line-for-line with
file:line references for each step.

## Phase 1 — build `bot/replay.py`

Replay one recorded window: walk its clock, take quotes from the `book.jsonl` snapshots, apply a
placement rule, book fills from `prints.jsonl` via `match_maker_print`, score the window.

### CLI

```
python -m bot.replay --run bot/runs/run_20261113_080232_paper_dsp_v2_6 --rule v2.6
python -m bot.replay --runs all --rule hump --ceiling 0.75 --levels 2 --spacing 0.02
python -m bot.replay --runs all --rule v2.6 --against-live       # gate mode
```

Flags: `--run <id>` (repeatable) or `--runs all`; `--rule {v2.6,hump}`; `--ceiling`; `--levels`;
`--spacing`; `--out <path.json>`; `--against-live`; `--limit N` for a quick pass.

### Simulation loop (per window)

1. Load the window: `condition_id`, `event_slug` → start epoch, `winner`.
2. Build two event streams, merged and sorted by `ts`: book rows (for `outcome` Up/Down) and prints.
3. At each book row, evaluate the rule (call the real `executor` helpers with a config dict, do not
   fork the logic) and produce desired orders per side.
4. Diff against resting orders: place, cancel, or replace. On placement, set
   `queue_ahead = sum(size for price >= limit in that side's bids)` from the snapshot — mirroring
   `live_paper.live_queue_ahead`. If the price is **not** in the top-5 book, record the placement as
   `queue_unknown` and choose one stated convention (either skip or a sentinel), then report how many
   placements that affects. Do not silently invent a queue.
5. For each print, in `ts` order, offer it to every resting order on the matching outcome via
   `match_maker_print`. Partial fills allowed. `queue_ahead` decays with each print, which is the
   whole point — do not reset it on re-quote at the same price.
6. Stop opening at T−75 s; fire the sweep at the recorded sweep rule; apply the taker fallback only
   where v2.6 does (the DSP dust skip at `bid < minFillPrice` must survive — that was `49c4b73`; a
   regression here means the replay is wrong, not the bot).
7. Score: `cost`, `payout` (winner shares × 1), `net`, `fees`, `pair_cost = cost / min(up_sh, down_sh)`,
   `fills`, `maker/taker` split, `fragment share` (fills < 1 share), `placements`, `queue_unknown`.

### Hard rules

- **The replay must not read the window's own `fills` to drive the simulation.** Only `winner`,
  `condition_id`, `event_slug`. Reading the answers makes the gate meaningless.
- Deterministic: same inputs → same output, no wall-clock, no randomness.
- Stream the tape per window; never load a whole `book.jsonl` into memory (the v2.5 one is 134 MB and
  a past run passed 5 GB). Target: all 172 windows in **under 60 s** total.
- Tolerate a partially written last line (the tape is append-only and the live run is writing).
- Cache parsed per-window slices under `scratch/` or `%TEMP%`, never inside a run folder.

## Phase 2 — the acceptance gate (this decides whether the rest is allowed)

Run `--rule v2.6 --against-live` over the v2.6 windows and compare to the live fixture you just
recomputed.

**Pass conditions** (expressed against the recomputed numbers, so they hold as the run grows):

- total maker fills within **±20%** of the live count (37 at last check → 29–44)
- fill rate within **±0.5 pp** of 1.7%
- median pair cost within **±0.02** of the live windows' median
- per-window fill counts correlate with live (`spearman > 0.5` or eyeball the table and say so)

**If it fails, stop.** Do not tune the rule to match — tune the *simulation* until it reproduces the
mechanism, and log every discrepancy as a class: queue source, replace cadence, sweep timing, missing
prints, book gaps. Report which class dominated. A replay that does not reproduce reality has no
opinions worth reading, and any table it prints afterwards is fiction.

## Phase 3 — the four candidates (only after the gate passes)

Run each against the full corpus (`--runs all`, 172 windows). Change one thing at a time, then the
combination that matters.

| # | question | arms | why it is first/second |
|---|---|---|---|
| 1 | size curve | `inverse` (33→8, shipped) vs `hump` (30 sh @≤0.10 → 48.7 @0.40–0.50 → 30 @≥0.70) | Clearest error: we put the largest clip where the wallet puts its smallest. Parameter swap, no engine change. |
| 2 | ceiling | 0.55 (shipped) vs 0.75, **with hump** | 37% of the wallet's markets open above 0.55, the only positive-median band. Test after the curve so the band is not filled at 8 shares. |
| 3 | levels per side | 1 (shipped) vs 2 vs 3, spacing 2c; then 1c/3c if the direction is clear | The real question. 1.7% fill rate is structural — one order that chases. Only this fixes it, and it is the expensive change. |
| 4 | time gate | none | Do **not** add one. The late-entry advantage is confounded by market selection. Only revisit if a fixed-rule replay shows it surviving on the same windows. |

Report **fills/window, median pair cost, gross bps** — and be explicit that 172 windows settles fill
rate and pair cost, not directional P&L.

## Phase 4 — report

One markdown file, `docs/leaderboard-traders/reports/replay_placement_rules.md`, containing:

1. The gate result first (pass/fail, the four numbers, the discrepancy classes found).
2. One table across candidates: `rule | ceiling | levels | fills/window | fill rate | median pair cost | gross bps | windows traded`.
3. Per candidate, one paragraph: what moved, what did not, and what it would cost to ship.
4. **What this does not prove** — stated plainly: the clip does not move the flow at 10–50 shares but
   would at 1,000+; queue-ahead is stale between book snapshots so fills are slightly overstated; 172
   windows is noisier than it looks because several runs share the same market hours.

Then one paragraph of recommendation for what a v2.7 would have to earn its number with.

## Verification

- `python -m pytest bot/tests -q` — all existing tests still pass, plus new ones.
- `bot/tests/test_replay.py`: (a) a resting bid fills only on a `SELL` print at or below the limit and
  only after `queue_ahead` is consumed; (b) no fills before the window opens or after the stop, except
  the sweep; (c) a dust bid (`bid < minFillPrice`) is skipped, not taken at the ask — the `49c4b73`
  regression test; (d) the same input twice gives byte-identical output.
- No `@ts-ignore`, no skipped tests, no `except: pass` hiding a failure path.

## Commit style

Repo prefixes: `[FEAT]`, `[FIX]`, `[ADD]`, `[DOCS]`. Use `[ADD] Replay recorded tape to test placement
rules offline` for the tool, then one commit for the report. Do not push until the gate result is in
the report — a replay that has not been validated must not travel alone.

## Context you need but should not re-derive

From the ledger (1.19M rows, 31,506 markets, the tracked wallet `0xc533…d69a9`):

- It **never sells**: 1,135,104 BUY, 0 SELL, 55,983 REDEEM. Everything resolves.
- It runs **both ladders at once** (91.1% overlap), ~12 levels per market, 21 fills/window. Our ~2.5
  fills/window is the gap this replay exists to close.
- **No target pair cost exists.** Pair sums run 0.93–1.01, sd 0.123, no spike. The 0.965/0.985 gates
  suppress exactly the trades that produce the discount.
- Sizing is a **hump**, not a curve: 30 sh at the extremes, 48.7 sh at 0.40–0.50, 557 sh / $271 per
  market. Not fixed shares, not fixed notional.
- Its trading nets **−109 bps** before rebate, +15 bps after. Do not copy its flow; copy its placement.

Our own live numbers to beat: 1.7% fill rate, median queue ahead 50 shares, ~2.5 fills/window.

---

Report back with: the gate result, the candidate table, and your recommendation. If the gate fails,
report that instead, with the discrepancy classes — that is a valid and useful outcome.
