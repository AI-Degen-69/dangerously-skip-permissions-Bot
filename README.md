# dangerously-skip-permissions — BTC 5m Paper Bot & Up/Down Desk

A paper-only research desk for Polymarket's 5-minute Bitcoin **Up/Down** markets.
The strategy is reverse-engineered from the fills of one target wallet
(`0xc53375ff94e96100f2b30a4b5775db35218d69a9`): a maker-first straddle across both
outcomes, a lagging-leg equalizer, and hold-to-redeem. No private keys, no
funding, no on-chain actions — every fill is simulated against the recorded book
and trade prints.

Two halves:

- **`bot/`** — the Python engine: window discovery, executor, fill model, tape
  recorder, verification/audit, replay, A/B statistics, and a stdlib-only desk API.
- **`src/app/`** — the **Up/Down Desk**, a React + Vite dashboard (Dashboard,
  Live, A/B Lab, Config, Strategy, Settings) that reads the engine through the
  local desk API.

## Quick start

Requirements: Python 3.12 (stdlib only — no pip installs) and Bun (or npm) for the UI.

```sh
# 1. Desk API on loopback (default 127.0.0.1:8789)
python bot/api.py
# check: http://127.0.0.1:8789/api/bot/control

# 2. Desk UI
bun install
bun run dev            # http://localhost:5173

# 3. Start the paper loop — "Start bot" in the UI, or headless:
python bot/live_paper.py --loop
```

The UI talks to `http://127.0.0.1:8789` by default; override with
`VITE_BOT_ORIGIN=http://127.0.0.1:8789 bun run dev` (the API's own port is set by
`python bot/api.py --port <n>`). On Windows, `bot/restart_api.ps1` stops whatever
holds the port and starts a fresh API instance.

Single window instead of a loop:

```sh
python bot/live_paper.py --once
python bot/live_paper.py --slot <epoch>
```

## What the engine does

`bot/live_paper.py` runs the window lifecycle (pre-open book discovery, oracle
anchor, maker dip grid + lagging-leg equalizer, late-window resolution snipe,
settlement lock); `bot/executor.py` holds the ladder, pair-cost gates and maker
rebalance; `bot/constants.py` is the versioned strategy registry
(`dsp-v2.x` → `hydrogen-v1.9`, the current default in `bot/config.json`).

Risk rails: `maxFillsPerWindow` (500), `dailyLossCapUsd` ($500),
`maxConcurrentPositions`, and the kill switch — the presence of `bot/kill` pauses
entries between windows (also toggled from Config → risk).

## Runs and data

Each loop session owns `bot/runs/<run_id>/`:

```
run_meta.json     config snapshot, status, summary
windows/*.json    settled window results (fills, cost, payout, net)
tape/             recorded book + print segments (required for replay)
events.jsonl      decision journal  (open / hedge / hold / settle / skip)
loop.pid          loop process id
```

Everything under `bot/runs/` is runtime output and gitignored, as are
`bot/state.json`, `bot/events.jsonl`, `bot/paper_runs/`, `bot/kill` and
`scratch/`. The one recorded run kept in the repo carries its `run_meta.json` and
`windows/`; its journal has been pruned.

## Tape, verification and replay

The recorder writes every book snapshot and trade print the bot sees, and the loop
refuses to start a window without its tape dir — the fill engine, the verifier and
the attainable-fill audit all read back from it.

A maker order is not a fill. `bot/fill_model.py` books a resting bid only when a
taker **SELL** prints at or below its limit, after whatever was already resting
there; taker orders fill at once. Fills are stamped:

```sh
python bot/verify_run.py --dry-run   # coverage report, changes nothing
python bot/verify_run.py             # re-stamp the active run's windows
python bot/verify_run.py --audit     # also record what could actually fill
```

`bot/fill_audit.py` is the independent check of the same rule (queue-ahead aware),
surfaced in the desk as the "attainable" figure beside net. Replay a recorded run
offline through `bot/executor.py` and `bot/fill_model.py`:

```sh
python -m bot.replay --run bot/runs/<run_id> --rule v2.6
```

Replay needs both `windows/` and `tape/` in the run. Runs recorded without tape
can be analysed from their window files but not replayed. Gate mode compares a
replay against the live run on the same windows:

```sh
python -m bot.replay --runs all --rule v2.6 --against-live
```

`bot/ab_test.py` (A/B Lab) runs Welch comparisons between a baseline and a
candidate strategy.

## Tests and checks

```sh
python -m unittest discover -s bot/tests   # engine suite
bun run typecheck                          # tsc --noEmit
bun run check:chart                        # chart math
bun run check:pnl                          # P&L scoping
bun run check:windows                      # window navigation
```

Other operator tools: `python bot/redeem.py --dry-run` (paper redeem batch),
`python -m bot.reconcile` (public Data API fidelity), `python bot/run_paper.py`
(288-window fidelity sweep).

## Docs

| Path | Contents |
|---|---|
| `bot/RUNBOOK.md` | Operating the loop: config, tape verification, kill-switch drill, redeem, live-gate checklist |
| `docs/architecture.md` | Engine/UI architecture and data flow |
| `docs/usage-guide.md` | Step-by-step desk guide (API, UI, loop, A/B, config) |
| `docs/explanations/` | Strategy and mechanic write-ups (sizing, rebates, verified-only, DSP v2.3/v2.4) |
| `docs/pr-presentations/` | Visual showcases shipped with PRs |
| `docs/polymarket-sdks-and-api/` | Polymarket repositories, API and resource reference |
| `docs/leaderboard-traders/` | Wallet reverse-engineering: pull/analysis scripts, tests and per-account ledgers |

## Hosted desk (optional)

The same UI can run on Freebuff Sites behind sign-in, with D1 holding the
imported windows (`src/worker/` is the Hono Worker; it exposes `/api/bot/*` plus
the Freebuff auth wrapper).

```sh
bun run build    # dist/client (assets) + dist/crm/index.js (Worker)
```

`deploy.json` points the upload at those two paths, and Sites attaches `DB` on
deploy. The build still carries the starter template's `crm` naming — the Worker
name in `wrangler.jsonc`, the D1 name and the `dist/crm/` output path — which is
harmless, but do not rename one without the others.

## Paper-only boundary

Nothing here touches funds or keys. Settlement is modeled from the resolved window,
`bot/redeem.py` only marks `redeemedAt` in paper runs, and the live micro-size
gate (funding, keys, per-window dollar caps) stays closed until the runbook's
checklist passes.
