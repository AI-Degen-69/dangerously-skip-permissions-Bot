# NOTICED-BUT-NOT-TOUCHING — #29 (live probability trajectory chart)

Candidates surfaced while building and reviewing [PR #29](https://github.com/AI-Degen-69/dangerously-skip-permissions-Bot/pull/29).
No GitHub issue was linked to that work, so the PR number is used as the ledger key.

| ID | candidate | discovering station | evidence (path:line) | status | resolution |
| --- | --- | --- | --- | --- | --- |
| N1 | The Dashboard *Things to note* panel was removed, so `perf.notes` has no frontend consumer left, while `bot/api.py` still computes and ships the list (operator alarms: loop stopped, kill switch, stale heartbeat, unredeemed windows) | Station IV (spec axis) | `src/app/lib/bot.ts:369`, `bot/api.py:1116` | dismissed | Operator check 2026-11-10: the Dashboard already carries the alarms — *Kill switch* (`src/app/pages/Dashboard.tsx:156`) and *Heartbeat* (`src/app/pages/Dashboard.tsx:140`) — so the notes list was a duplicate surface, not the only one. The API may keep shipping it. Re-open with its own ticket if a note ever describes an alarm with no other Dashboard surface. |
| N2 | The Live strip no longer names the $4,000 window budget that `CONSTRAINTS.md` lists as a strictly enforced invariant; the bot still enforces it through `check_window`, but the UI no longer shows spend against the cap | Station IV (spec axis) | `src/app/botDefaults.ts:27`, `CONSTRAINTS.md:17` | dismissed | Operator decision 2026-11-10: the per-window spend cap was removed entirely in `36e3270` — no enforcement in `check_window`, no `maxUsdPerWindow` in the API/Config page, and `CONSTRAINTS.md` rewritten to state that the fill cap and the daily stop loss are the window bounds. The target of this row no longer exists. |
