# Implementation prompt — make paper fills observable (trade prints + depth)

Paste everything below into a fresh session in this repo.

---

## Role and goal

You are working in `C:\Users\Tiger\Agents\Projects\AI Trading\dangerously-skip-permissions-bot`
(Polymarket 5-minute BTC up/down paper-trading bot, Python, Windows/PowerShell).

**Goal:** stop *asserting* that paper fills would have happened, and start *measuring* it.

Today the engine decides to buy N shares at price P from the quoted book, and the paper loop books
that as a fill. Nothing in the system observes whether anyone actually traded. Replace that belief
with evidence, in this order:

1. **Record trade prints** (`last_trade_price`) next to the book, for the same markets and windows.
2. **Record top-5 depth** per side, so clip size can be checked against what was actually resting.
3. **Define a fill as a print at or through your level, with cumulative size ≥ your clip**, and add it
   as an opt-in fill model in the replay harness.
4. **Report** what fraction of the 367 recorded dip fills are confirmable under that rule.

Do not change strategy behaviour, sizing, gates, or the live loop's trading decisions. This work is
observation and measurement only.

## Read this first

| File | Why |
|---|---|
| `bot/ws.py` | `LiveBookStreamer`, `BotBook`, `apply_price_change`, `_handle_price_change`. Subscribes to `book` / `price_change` / `snapshot` / `rest_poll` today — **no trade prints**. |
| `bot/live_paper.py` | The loop: gets quotes, calls the engine, applies fills under a spacing rule (`minSpacingMoveSec` 0.5, `minSpacingStaticSec` 2.5), writes `decisions.jsonl` + `windows/*.json`. |
| `bot/executor.py` | `evaluate_microstructure_ladder()` → `MicrostructureDecision` (action/outcome/price/shares/role/sub_reason). `compute_fill_usd()` (taker fee `0.07·p·(1−p)`), `_projected_pair_cost()`. |
| `bot/runs/<run>/decisions.jsonl` | One line per evaluation (~50/s). Flat schema: `ts, slug, minute, inSweepPhase, imbalance, fills, cost, action, outcome, price, shares, role, reason, subReason, projectedPairCost, shareDeficit, quotes`. **Decisions, not fills.** |
| `bot/runs/<run>/windows/*.json` | **Authoritative fills** for a settled window, each with `detail.{role,subReason,feeUsd,pairCost,deficit,strategy}`. |
| `scratch/sizing_sim.py` | Replay harness. `replay(..., queue_strict=False)` already has a crude prior model (§ Phase 4). Env: `DSP_CUTOFF`, `DSP_OUT`. Results cache in `%TEMP%\dsp_v24_evals.pkl`. |
| `scratch/build_sizing_report.py` | HTML report generator. Env: `DSP_SRC`, `DSP_PREV`. Output `docs/explanations/sizing-simulation-dsp-v24.html`. |
| `bot/tests/` | 124 passing tests. Add tests here. |

## Measured baseline — do not re-derive, verify

- Baseline run `run_20261110_061832_paper_dsp_v2_4` (v2.4, now stopped): **57 settled windows**, mean
  **+$0.0374**/window.
- The 47-window replay sample: net **−$6.61**, 34W/13L, **367 fresh dip fills, every one exactly 10
  shares**, 1.38¢ locked per pair, −$55.42 of naked shares at expiry.
- Crude strict-fill model (ask must reach our level): only **81 / 367** dip fills provable → net
  −$28.68, ROI −4.96% vs −0.19%. **78% of fills unverified. This is the number to replace.**
- Live paper loop is currently v2.5, run `run_20261110_183056_paper_dsp_v2_5`, pid in `bot/loop.pid`.
  Leave it running — Phase 1 is designed to attach to it without touching it.

---

## Phase 0 — confirm the feed exists (no code changes)

Before building anything on `last_trade_price`, prove it works.

- Query the CLOB docs (repo has a Polymarket docs MCP; also `docs.polymarket.com`) for the market
  WebSocket channels. Confirm the channel name, the exact event type string, and the field names.
  Expected shape — **verify, do not trust this prompt's memory**: `event_type: "last_trade_price"`,
  `asset_id`, `price`, `size`, `side`, `fee_rate_bps`, `timestamp`.
- Confirm which side `side` refers to (taker vs maker). This decides the comparison direction in
  Phase 4 — getting it backwards silently inverts the whole result.
- Confirm `price_change` events carry enough depth (`changes[]` with price/size/side) to maintain a
  top-5 book, or whether you need a periodic `/book` REST snapshot to resync.
- If `last_trade_price` is unavailable on the current connection type, fall back to polling the CLOB
  REST `/trades?market=<condition_id>` at 1s and say so in your report. Do not guess.

**Acceptance:** a scratch script that subscribes to one live token for 60s and prints ≥ 1 real print
event. Paste one raw event into your report as evidence.

## Phase 1 — sidecar recorder (zero risk to the running bot)

Build `scratch/tape_recorder.py`. A **separate process**, separate WebSocket connection, read-only.
It must not import or touch the live loop's state.

- Discover the active 5m market(s) the same way the bot does (`bot/` already has market discovery —
  reuse it; do not write a second one).
- Subscribe to `book` (snapshot + price_change) **and** `last_trade_price` for both tokens.
- Write two append-only files under `bot/runs/<run-id>/` (or `bot/tape/<date>/` if you prefer to keep
  run dirs clean — state which you chose and why):
  - `tape/book.jsonl` — one line per price_change batch: `{ts, slug, asset, bids:[[p,s]...5], asks:[[p,s]...5]}`
  - `tape/prints.jsonl` — one line per print: `{ts, slug, asset, price, size, side, fee_rate_bps}`
- **Size discipline matters.** `decisions.jsonl` already grows ~33 MB per 10 minutes for one slug.
  Budget: the recorder must stay **under 20 MB/hour**. Sample depth on change only (never on a
  timer), top 5 levels, rounded to 3dp, and skip repeats identical to the previous line for that
  asset. Print a `--max-mb` guard that stops cleanly rather than filling the disk.
- Guard against the recorder dying silently: log a heartbeat line every 30s and exit non-zero if no
  frame arrives for 120s (matching `C.HEARTBEAT_STALE_S`).

**Acceptance:** run it for 10+ minutes alongside the live bot and show: print count > 0, book lines
> 0, MB/hour measured, and that no print timestamp has a matching book gap (every print falls inside
a book window you recorded).

## Phase 2 — fold the subscription into `bot/ws.py`

Once the schema is confirmed, extend `LiveBookStreamer` so the *bot itself* records prints and depth
(new optional flag, default **off** so nothing changes unless enabled):

- Add `event_type="last_trade_price"` handling that appends to the same `prints.jsonl`.
- Maintain a top-5 book; expose it via a single accessor (`streamer.depth(asset, levels=5)`).
- Keep the existing `book`/`price_change` paths byte-identical. Do not reorder or restructure them.

**Acceptance:** with the flag off, `git diff` shows no behavioural change in the quote path; with it
on, the recorder and the bot write identical print lines for the same window (compare 100 lines).

## Phase 3 — depth-aware clip cap (opt-in)

In `bot/executor.py`, add an optional `max_depth_shares` parameter to
`evaluate_microstructure_ladder()`. When supplied and > 0, the clip for a **MAKER** fill is
`min(clip, resting_size_at_my_level)`. TAKER fills are unaffected (they cross the spread).

- Wire it from `bot/config.json` as `entry.maxDepthShares` (default `0` = off) and from the registry
  entry in `bot/constants.py`.
- Extend `describe_setup()` in `bot/constants.py` to mention the depth cap **only when it is on**.
  That function is the single source of truth for UI copy — never hand-edit per-setup strings.

**Acceptance:** unit test that a 33-share clip against 12 shares of resting depth produces a 12-share
decision, and that `maxDepthShares=0` reproduces today's numbers exactly.

## Phase 4 — the print-confirmed fill model

Add `fill_model="prints"` alongside the existing `queue_strict` in `scratch/sizing_sim.py::replay`.

**Rule for a resting BUY at limit L on token T** (this is the one that matters — MAKER fills):

```
confirmable = prints on T, timestamp >= decision_ts, price <= L
cumm = sum(size for p in confirmable)
if cumm >= clip:      fill the full clip at L
elif cumm > 0:        PARTIAL fill of cumm shares at L
else:                 no fill
```

Rationale to preserve in a comment: price priority means a print **below** your limit proves the
level was traded through you; a print at exactly L proves the level traded, with the caveat that
another order may have been ahead of you in the queue (which is why this is still a bound, not truth).

**TAKER fills are different and must not be validated the same way.** A taker buy crosses the spread
and, in live trading, *our own order creates the print*. In paper mode we are not in the book, so we
cannot distinguish our hypothetical print from someone else's. Treat taker fills as filled if the ask
was still present at `size >= clip` in the book snapshot at decision time, and label them
`unverified-taker` in the results. Do not silently count them as confirmed.

**Guardrails:**
- `fill_model` defaults to today's optimistic behaviour. The existing 47-window calibration
  (**0/47 mismatches** against recorded windows) must still pass unchanged. If it stops passing, you
  broke the harness — stop and investigate before proceeding.
- Keep `queue_strict` working; it is the crude prior model and stays comparable.
- Unknown/None depth or missing prints must degrade to "unconfirmed", never to "filled".

**Acceptance:** a table of the 367 baseline dip fills bucketed by `confirmed / partial / unconfirmed`,
plus the resulting net for the baseline and v2.5 arms under `fill_model="prints"`. Add the totals to
the results JSON so the report can use them.

## Phase 5 — report and verdict

Regenerate the report (`scratch/build_sizing_report.py`, `DSP_SRC=sizing_sim_results_49w.json`,
`DSP_PREV=sizing_sim_results.json`) with a new section replacing §6's crude bound:

- Confirmable-fill rate overall and split by price bucket (7–15¢ / 16–38¢ / 39–45¢). The 7–15¢ bucket
  is the one the inverse-dip curve is supposed to exploit — state explicitly whether those fills are
  confirmable, because if they are not, the curve's fat end is untestable.
- Distribution of `clip / resting_size_at_touch`. Anything routinely > 1 means the current paper model
  is filling more than the book could have given it.
- Net and ROI for baseline vs v2.5 under all three models: optimistic, `queue_strict`, `prints`.
  If the ranking flips between models, say so plainly — that is the finding.

## Non-goals

- Do not change sizing rules, pair gates, ceilings, the gap cap, or the live loop's decisions.
- Do not commit the data files (`tape/`, `decisions.jsonl`, `windows/`).
- Do not edit generated docs by hand; regenerate them.
- Do not "fix" the optimistic model. It stays as the default so historical comparisons remain valid.

## Definition of done

1. `prints.jsonl` and `book.jsonl` exist for ≥ 5 consecutive 5-minute windows, recorded next to a live
   bot run, with the disk budget respected.
2. Unit tests cover: print-at-limit, print-through-limit, cumulative-size shortfall (partial),
   no-print (no fill), depth cap on/off, and taker-labelled-unverified.
3. `python -X utf8 -m pytest bot/tests -q` passes, with the previous 124 still green.
4. The 47-window calibration still shows **0/47 mismatches** under the default model.
5. A written answer to: *"what fraction of the recorded dip fills could actually have been filled,
   and does the v2.5 vs v2.4 ranking survive that model?"* — with the numbers, not adjectives.

## Report back with

- The raw print event you captured in Phase 0 (schema proof).
- Measured MB/hour for the recorder.
- The confirmed / partial / unconfirmed breakdown and the three-model comparison table.
- Anything you had to assume, and what data would remove the assumption.
