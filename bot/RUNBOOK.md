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
- `risk`: `maxUsdPerWindow` 4000, `maxFillsPerWindow` 500,
  `dailyLossCapUsd` 500 (operator confirms before any live size),
  `maxConcurrentPositions` 1.
- Editable from the desk Config page (clamped to safe MSR-v2 bounds).

## Files

- `bot/state.json` — live fills + `updatedAtMs` heartbeat (one window owns it).
- `bot/events.jsonl` — decision journal (open / hedge / hold / settle / skip).
- `bot/paper_runs/<slug>.json` — one JSON per settled window (fills + net).
- `bot/loop.pid` / `bot/loop.log` — loop process.
- `bot/kill` — kill-switch file (present = entries paused). See below.

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
