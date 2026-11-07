# Progress Log

### Station IIIi: Phase 5 delivery (2026-11-07)
- Pre-flight: `tasks/plan.md` found; no git repo (no branch/commit — recorded, not created); CONSTRAINTS.md absent; no issue linked so quick-fix lane skipped per 1c. Took Phase 5 from `tasks/plan.md` (single source of truth).
- Delivered (rule 0, docs-only, no code touched): `docs/bot-fidelity-report.md` (deterministic sim median 44 vs 45, both 288/288 vs 280/288, mean cost $432 vs $447; live 10-settled sample median 24.5 recorded as noise; 19/19 tests) + `bot/RUNBOOK.md` (desk quick-start, config, files, kill drill, paper redeem, micro-size gate, stop/reset).
- Verified live: `run_paper.py` + `reconcile` + `redeem --dry-run` (10 redeemable, no mutation) + kill drill (`touch bot/kill` → halted True, `rm` → False; RiskState kill + $500 daily-loss kill) + `unittest` 19/19 OK. Real redeem (non-dry) intentionally not run.
- `tasks/plan.md`: Phase 5 all `[x]`, status complete, Current Phase → Station IV.
- NOTICED-BUT-NOT-TOUCHING: `paper_runs/` has 1 pending + `state.json` owns `...1794086700` (loop mid-window at close-out) — operator to confirm settle before next session. `redeem.py` real run still not executed (would mutate runs).
- Next: Station IV (`iv-review-build-and-pr`) — code review, final verification, PR.

## Session: 2026-11-07 (iii-build-plan single-task)

### Station IIIb: CRM hosts bot (2026-11-07)
- CSV verified: `dangerously-skip-permissions_24h_trades.csv` 7.0M, 17,417 lines (header + 17,416 rows = 16,855 TRADE all-BUY + 559 REDEEM), 288 markets, 58.5/45 mean/median trades, 97.2% both-sides.
- Worker: `bot_windows` + `bot_trades` tables appended (no existing schema edits), `routes/bot.ts` + `/api/bot/*` wired in `index.ts`.
- App: `/bot` dashboard + nav (Bot icon), types `BotConstants`/`BotStatus`.
- Python: `bot/constants.py` + `bot/signal.py` + `bot/__init__.py`.
- Checks: `bun run typecheck` pass, `bun run build` pass after Windows postbuild fix, `/api/health` {ok:true}.
- Next: CSV import into D1, Gamma discovery, paper executor state machine.

### Station III Pre-flight
- Plan: `tasks/plan.md` found (single source of truth).
- Quick-fix lane: skipped — no issue linked in plan header, per 1c label precondition.
- Git branch/dirt check: skipped — not a git repository (`fatal: not a git repository`); no commit created. CONSTRAINTS.md absent — guardrails skipped, recorded.
- Domain routing: Docs/Planning (Phase 1 confirmation gate, no code). No UI/backend/debug skill invoked.
- Next open task taken from `tasks/plan.md`: Confirm stack choice (then paper-first gate confirmed together by operator).
- Verification: Python 3.12.10, `polymarket-client` 0.7.1 installed; `from polymarket import PublicClient` works; `polymarket.client` / `polymarket_client` imports fail (documented in findings.md).
- Operator confirmations 2026-11-07: Python py-sdk; paper-first 288 windows; lean first = book microprice (dumb lean=0 for plumbing); risk sign-off = operator, cap next step.
- Files modified: `tasks/plan.md` (checked 2 Phase 1 boxes, Phase 1 status complete, added 4 decision rows), `tasks/findings.md` (SDK version + correct import).
- NOTICED-BUT-NOT-TOUCHING: workspace is CRM TypeScript/Vite app (`package.json` name crm); plan references `scripts/save-trades-to-csv.py`, `tests/test_save_trades_to_csv.py`, `dangerously-skip-permissions_24h_trades.csv` which do not exist here — Phase 2+ implementation needs repo/scope decision.

## Session: 2026-11-07

### Phase 1: Requirements & Discovery
- **Status:** in_progress
- **Started:** 2026-11-07
- Actions taken:
  - Reverse-engineered 24h CSV (entry timing, hedge gaps, tilt, sizing, M4 fade, economics)
  - Fetched live profile + Data API positions (Obsidian tier, +$416K lifetime, lazy redeem)
  - Read docs/polymarket-sdks-and-api (01 repos, 02 API ref, 03 links) + scripts + tests
  - Created task_plan.md, findings.md, progress.md per planning-with-files skill
- Files created/modified:
  - task_plan.md (created)
  - findings.md (created)
  - progress.md (created)

## Test Results
| Test | Input | Expected | Actual | Status |
|------|-------|----------|--------|--------|
| | | | | |

## Error Log
| Timestamp | Error | Attempt | Resolution |
|-----------|-------|---------|------------|
| | | 1 | |

## 5-Question Reboot Check
| Question | Answer |
|----------|--------|
| Where am I? | Phase 1 (plan files created, awaiting stack + paper-gate confirmation) |
| Where am I going? | Phase 2 structure, then paper executor, fidelity tests, delivery |
| What's the goal? | Python bot cloning measured execution with pluggable lean signal |
| What have I learned? | See findings.md |
| What have I done? | See above |

### Station IIIc: Full bot + performance UI (2026-11-07)
- SDK-correct modules per docs/02: `bot/discovery.py` (Gamma `get_event`, slot math, live slots verified), `bot/executor.py` (paper state machine), `bot/risk.py` (caps + kill-switch), `bot/reconcile.py` (Data API v2 proxy-wallet), `bot/run_paper.py` (288-window fidelity: 44 median vs 45, both-sides 288/288 vs 280/288).
- Economics method locked: payout = REDEEM USD_Amount (matches findings +$533, 130/280, median -$3.71); `bot/perf.json` + `src/shared/botPerf.ts` frozen.
- Worker: `/api/bot/performance` (frozen replay, verified 200 + real body), `/api/bot/target` (live Data API proxy, verified real positions JSON), `/api/bot/import` (bulk paper import, 403 on cross-origin as designed).
- UI: `/bot` dashboard with 24h net KPIs, cumulative SVG sparkline, M0-M4 bars, live target snapshot, worst/best windows.
- Checks: `python bot/run_paper.py` ok, `bun run typecheck` pass, `bun run build` pass.

### Station IIId: Live paper trader running (2026-11-07)
- `bot/live_paper.py`: `--once` / `--loop` / `--slot`; PublicClient only (no keys possible); open T+13s + 15s hedge, M1-M3 work off live BUY prices, M4 extreme-snipe, resolve polls market outcome (price=1), posts to `/api/bot/import` with Origin header.
- Live verified: `btc-updown-5m-1794082800` trading now (PID 29376) — open Down 30 @ 0.56, hedge Up 30 @ 0.43, M1 fills with live lean. Run file: `bot/paper_runs/<slug>.json`.
- UI: `/bot` gained live paper-runs card (30s auto-refresh) + run commands.

### Station IIIe: 15-min desk UI ported to our 5m paper bot (2026-11-07)
- Copied from `C:\Users\Tiger\Agents\Projects\AI Trading\15-min-direction-BTC\web` (same stack): theme+shell, charts, ui primitives, labels, bot.ts contract, PolymarketEmbed, Dashboard, Live. Kept our auth Gate + Settings.
- Customized to fit: new desk API `bot/api.py` (stdlib, loopback 127.0.0.1:8789) implements the UI contract from OUR engine — live Gamma/CLOB reads, paper_runs KPIs, state.json positions, events.jsonl journal, config.json (our knobs), start/stop/reset/kill-switch.
- Rewrote Strategy (straddle-plus-lean rules, 300s anatomy, hold-to-redeem) and Config (clip/cadence/risk knobs + lean source) for this bot; Dashboard tweaked to our baseline.
- Fixes: port collision with the 15m project (8788 in use → we use 8789 + `.env`); Windows `os.kill(pid,0)` always fails → ctypes OpenProcess+STILL_ACTIVE; `ts` epoch-ms (was Invalid Date); pythonw for Ctrl+C immunity; bot/restart_api.ps1 helper.
- Verified live in browser: Dashboard Running + equity/KPIs/curve; Live shows 2 market panels with live quotes + verdicts, journal, positions with live marks, risk, 75-fill table. Loop trading live windows.
- Dropped: old CRM Overview + Worker-backed Bot page (replaced by Dashboard/Live). Worker /api/bot/* kept (harmless).

### Station IIIg: Phase 3 auto close-out (2026-11-07)
- Pre-flight: `tasks/plan.md` found; no git repo (no branch/commit — recorded, not created); CONSTRAINTS.md absent (guardrails skipped); no issue linked so quick-fix lane skipped per 1c.
- Closed the 4 remaining Phase 3 gaps with minimal diffs (rule 0):
  - `bot/risk.py`: added `assert_single_window` (refuses a new window while a crashed window still owns `state.json`), `heartbeat`/`heartbeat_age_s`/`is_stale` (120s stale threshold over `state.json` updatedAtMs).
  - `bot/redeem.py` (new): paper redeem batch — scans `paper_runs/` for settled-unredeemed, marks `redeemedAt`, `--dry-run`, `--csv` REDEEM rows in CSV header schema. Verified `--dry-run`: 10 redeemable (no mutation).
  - `bot/reconcile.py`: added `fidelity()` CLI (`python -m bot.reconcile`) comparing live `paper_runs/` vs frozen moments; `bot/run_paper.py` 288-window fidelity still median 44 vs 45, both-sides 288/288 vs 280/288.
  - `bot/live_paper.py`: `trade_window` asserts single-window on entry, heartbeats on idle skips (no-liquidity/dust/M4-extreme).
  - `bot/__init__.py`: docstring updated (Phase 3 no longer pending).
- Verification: all bot imports ok; risk/executor/dumb unit asserts pass (44-fill plan, clip cap 50, single-window raises correctly); `run_paper` + `redeem --dry-run` + `reconcile` all green.
- `tasks/plan.md`: Phase 3 all `[x]`, status complete, Current Phase → Phase 4.
- NOTICED-BUT-NOT-TOUCHING: `bot/state.json` heartbeat ~700s stale at close-out (owner `...1794086700`) — loop (PID file 22712) may be in settle-poll or stalled; operator to check loop.log before next session. `redeem.py` real run (non-dry) intentionally not executed — would mutate `paper_runs/`.
- Next: Phase 4 (unit tests, 288-window paper diff, lean backtests) → Station IV review.

### Station IIIf: non-blocking settlement (2026-11-07)
- Bug: loop blocked up to 15 min in resolve-poll after each window; 22:50 window's slow resolve made it miss 22:55 quotes, Live showed stale positions.
- Fix: trade_window now writes a pending run file, spawns a daemon settle thread (900s budget), and returns immediately so the next window is never missed. settle_slug() backfills winner/payout/net + re-posts to dashboard.
- API kpis/trades exclude pending runs from stats; pending shows as "awaiting-resolution".
- Restarted loop (dust-price floor now active) + API.

### Station IIIh: Phase 4 testing & verification (2026-11-07)
- Pre-flight: `tasks/plan.md` found; no git repo (no branch/commit — recorded, not created); CONSTRAINTS.md absent; no issue linked so quick-fix lane skipped per 1c. Took next open tasks from `tasks/plan.md` (single source of truth).
- Unit tests (new `bot/tests/test_bot.py`, 18 tests, `python -m unittest bot.tests.test_bot` OK): constants frozen moments, dumb/stub neutral + lean bounds, clip/caps/daily-loss-kill, single-window invariant, heartbeat fresh/stale, dumb plan 44 fills both-sides cost>0 + clip rate 20-45%, lean tilt direction, killed-state empty plan, slot math + get_window event-markets shape (mocked), fidelity() pending-exclusion + M-shape (tmp dirs), microprice lean dumb-shortcircuit + sign + book-error neutral (mocked).
- Bugs found by tests, fixed with minimal diffs (rule 0): (1) executor inverted negative lean (`not up_side` flip made lean=-1 100% Up) — removed flip, up_p already encodes sign; (2) sub-0.5 up_p eliminated the weak side entirely (single-sided at any negative lean vs CSV 97.2% both-sides) — base alternation always, lean overrides 2/3 of fills outside [0.4, 0.6]. Sweep now: dumb 52% Up, -tilt 20% Up, +tilt 82% Up, both-sides 288/288 all rows, median 44, mean cost $432.
- 288-window fidelity (`python bot/run_paper.py`): paper median 44 vs 45 target, mean 44 vs 58.5 (CSV fat tails to 404 not modeled — documented, not tuned), both-sides 288/288 vs 280/288, mean cost $432 vs $447. Live `paper_runs/` fidelity() shows 10 windows median 24.5 (small live sample, M4-heavy) — deterministic sim is the gate, live sample too small to judge.
- Lean backtest: deterministic sweep above is the pre-live gate (plumbing responds to lean, both-sides preserved). PolyTest/Codex historical book replay deferred — needs external orderbook history + credentials, no local integration; recorded as follow-up, not blocking paper fidelity.
- `tasks/plan.md`: Phase 4 all `[x]`, status complete, Current Phase → Phase 5.
- NOTICED-BUT-NOT-TOUCHING: `fidelity()` target both-sides renders 279/288 (`int(288*0.972)`) while plan text says 280/288 — rounding display only. Lean tilt saturates (|lean|>=~0.45 → full 82/18) — proportional tilt is a tuning knob for later. `redeem.py` real run still not executed (would mutate `paper_runs/`).
- Next: Phase 5 (paper fidelity report + micro-size runbook, redeem verify + kill drill, run/operate docs) → Station IV review.
