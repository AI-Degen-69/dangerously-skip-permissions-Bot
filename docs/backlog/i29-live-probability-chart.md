# NOTICED-BUT-NOT-TOUCHING — #29 (live probability trajectory chart)

Candidates surfaced while building and reviewing [PR #29](https://github.com/AI-Degen-69/dangerously-skip-permissions-Bot/pull/29).
No GitHub issue was linked to that work, so the PR number is used as the ledger key.

| ID | candidate | discovering station | evidence (path:line) | status | resolution |
| --- | --- | --- | --- | --- | --- |
| N1 | The Dashboard *Things to note* panel was removed, so `perf.notes` has no frontend consumer left, while `bot/api.py` still computes and ships the list (operator alarms: loop stopped, kill switch, stale heartbeat, unredeemed windows) | Station IV (spec axis) | `src/app/lib/bot.ts:369`, `bot/api.py:1116` | open | — |
| N2 | The Live strip no longer names the $4,000 window budget that `CONSTRAINTS.md` lists as a strictly enforced invariant; the bot still enforces it through `check_window`, but the UI no longer shows spend against the cap | Station IV (spec axis) | `src/app/botDefaults.ts:27`, `CONSTRAINTS.md:17` | open | — |
