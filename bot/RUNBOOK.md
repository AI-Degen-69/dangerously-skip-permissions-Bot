# BTC 5m Paper Bot — Run & Operate (Phase 5 handoff)

Paper-only. No live keys, no funding. Target behavior: buy-only
straddle-plus-lean, ~30-share clips, every 5-min BTC window, hold-to-redeem.

## Quick start (desk UI)

```sh
python bot/api.py            # desk API on 127.0.0.1:8789 (loopback only, no keys)
# open the dashboard (Dashboard / Live / Config / Strategy), Start button runs:
python bot/live_paper.py --loop
```

Single window / explicit slot:

```sh
python bot/live_paper.py --once
python bot/live_paper.py --slot <epoch>
```

## Config (`bot/config.json`)

- `entry`: `startAfterOpenSec` 4 (T+4s opening buffer, sbc 296–300),
  `stopBeforeCloseSec` 12 (T−12s settlement cutoff, sbc 0–12),
  `clipSharesDefault` 30 (30.4% signature), `maxShares` 50,
  `minFillPrice` 0.07 (dust floor), `maxFillPrice` 0.95 (favorite cap),
  `targetPairCost` 0.965 ($0.9654 measured median), `maxPairCost` 0.990 (sub-$1.00 hard cap),
  `maxShareLead` 90 (anti-runaway lead cap),
  `minSpacingMoveSec` 0.5, `minSpacingStaticSec` 2.5,
  `includeTakerFee` true, `wholeLadderClips` true.
- `risk`: `maxFillsPerWindow` 500,
  `dailyLossCapUsd` 500 (operator confirms before any live size),
  `maxConcurrentPositions` 1.
- Editable from the desk Config page (clamped to safe MSR-v2 bounds).

## Files

- `bot/state.json` — live fills + `updatedAtMs` heartbeat (one window owns it).
- `bot/events.jsonl` — decision journal (open / hedge / hold / settle / skip).
- `bot/paper_runs/<slug>.json` — one JSON per settled window (fills + net).
- `bot/loop.pid` / `bot/loop.log` — loop process.
- `bot/kill` — kill-switch file (present = entries paused). See below.

## Tape verification (paper fills vs the real book)

The recorder writes every trade print the bot sees. Recording is not optional:
the loop creates the run's tape dir before its first window and refuses to start
if it cannot, because the fill engine, the verification and the attainable-fill
audit below all read back from it.

A maker order is not a fill. The loop rests it at its price and it only becomes a
fill when a taker SELL prints at or below that price, behind whatever was already
resting there; a partial print fills partially, and re-pricing an order sends it
to the back of the queue. Taker orders execute at once, because a market order
really does. Trading starts `startAfterOpenSec` after the bell: Phase 0 warms the
streamer before it, but nothing is booked against the pre-open book.

A speculative leg also has to be hedgeable *now*: the executor only opens one when
the opposite ask plus its taker fee still forms a pair under `maxPairCost`. It no
longer enters on the hope that a cheap second leg shows up later. Closing an
existing deficit is different — that fill is the hedge.

The verifier stamps each fill with what the tape corroborates: a maker fill at
limit L counts as `verified` when the tape printed at least the clip's size at or
below L inside that window. Taker fills stay `unverified-taker` — paper mode has
no real book to check them against.

The live loop stamps the window it is trading. A run that started before the
verifier existed keeps its older fills unstamped, so the desk's "Verified Only"
view would cover a slice of the tape instead of the tape. Re-stamp the run
against the recorded prints:

```sh
python bot/verify_run.py --dry-run   # report the coverage, change nothing
python bot/verify_run.py             # re-stamp every settled window
python bot/verify_run.py --audit     # re-stamp, and record what could actually fill
```

It rewrites only the `detail.tapeStatus` fields of the fills; cost, payout and
net are untouched.

`--audit` writes each window's `fidelity`: the same fills judged by the only
trade that can fill a resting bid — a taker SELL at or below the limit, after
the fill. The live loop runs that same rule every 5 s while a window trades and
finalizes it when the window closes, stamping each fill's `detail.attainable` so
the desk shows the verdict during the run, not only at the end. Because the fill
engine itself now books a maker fill only on that print, the two should agree;
the audit is the independent check that they do. When the loop recorded
`detail.queueAhead` (the size already resting at that price), the flow has to
outlast it; older fills pass on sell size alone, so their attainable number is an
upper bound. Taker fills always count. The desk shows the result as the
"attainable" number beside the net, before rebates.

## Kill-switch drill (verified 2026-11-07)

Loop checks `bot/kill` between windows (`wait_while_killed`, 30s poll);
desk shows `killSwitch: true / risk.halted: true` while present.

```sh
touch bot/kill   # pause entries — loop prints "kill-switch present", desk halts
rm bot/kill      # resume
```

Also via desk: Config / risk panel → kill-switch toggle (`POST /api/bot/kill-switch`).
Unit level: `kill(state, reason)` blocks all further fills;
`daily_loss_usd <= -DAILY_LOSS_CAP_USD` ($500) auto-kills — both covered by
`bot/tests/test_bot.py` and re-drilled live (file present → halted True,
removed → False).

Stale-loop check: `python -c "from bot.risk import is_stale; print(is_stale())"`.
Stale = `state.json updatedAtMs` older than 120s → restart the loop, do not
delete state mid-window (`assert_single_window` refuses a new window while a
crashed window still owns state).

## Redeem (paper, verified 2026-11-07)

```sh
python bot/redeem.py --dry-run   # list settled-unredeemed (10 on 2026-11-07, no mutation)
python bot/redeem.py              # mark redeemedAt (mutates paper_runs/)
python bot/redeem.py --csv out.csv  # also append REDEEM rows (CSV header schema)
python -m bot.reconcile           # fidelity vs frozen moments
```

Real on-chain redeem needs live keys and stays out of paper.
Weekly cadence is acceptable (target account leaves winners unclaimed for weeks).
The `--dry-run` real run (non-dry) is intentionally not executed in paper —
it would mutate `paper_runs/`.

## Live micro-size runbook (gate before any funding)

Do NOT fund until ALL pass:

1. `python -m unittest bot.tests.test_bot` — 19/19 green.
2. `python -m unittest discover -s bot/tests` — all unit tests green.
3. Desk loop paper ≥ 24h (`paper_runs/` ≥ ~288 settled) with market-neutral
   sub-$1.00 pair-cost arbitrage and both-sides fill rate matching reconstructed tape.
4. `python bot/redeem.py --dry-run` clean + kill-switch drill above green.
5. Operator approves: live keys, `dailyLossCapUsd`, max per-window USD.

Micro-size start: 1 window, dust-size clips (`clipSharesDefault` 1),
kill file within reach.
Scale only after a profitable held-to-redeem window reconciles end-to-end.

## Stop / reset

Desk Stop button (`POST /api/bot/stop`) or kill the loop PID.
`POST /api/bot/reset` clears `paper_runs/`, `state.json`, `events.jsonl`.
