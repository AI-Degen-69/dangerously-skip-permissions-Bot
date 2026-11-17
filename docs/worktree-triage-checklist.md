# Worktree & uncommitted-work triage checklist

Snapshot taken at `main = a880cee` (17 Nov 2026). Delete this file once every box is ticked.

## Ground rules

- Nothing is deleted before its branch exists on `origin`. Every unmerged branch is currently **local only** (`git ls-remote --heads origin` returns `refs/heads/main` and nothing else).
- Worktrees share one object store. Removing a worktree never deletes its branch; deleting a branch never deletes its commits until they are unreachable and pruned.
- Any branch that is only reachable from a worktree HEAD must be pushed **or** recorded as a tag before that worktree goes.
- `tidy-meadow` is the running session's own directory. It is always last.
- `freebuff` / Gemini worktree folders are owned by their own tools. Only touch a folder if its chat session is not in use.

## Inventory (verified)

| Worktree | Ref | Ahead of main | Content already in main? | Verdict |
|---|---|---|---|---|
| main checkout | `main` @ `a880cee` | — | — | keep |
| `.freebuff/worktrees/a14af753` | `freebuff/chat` @ `47c3b95` | 6 | yes — `katex` + A/B gate shipped by squash | leave, owned by freebuff; push branch anyway |
| `.gemini/…/microstructure_inventory_risk_engine` | branch `bd303f2` | 1 | **no** — `bot/microstructure_engine/` absent from main | protect first, decide second |
| `…/calm-harbor` | detached `90ed8fc` | 4 | yes — `hydrogen-v1.0` shipped, `hydrogen-v1.1` in `bot/config.json:10` | delete |
| `…/curious-wizard` | `feat/execution-health` @ `2d84fca` | 11 | mostly yes — Execution Health card is in `bot/api.py:944` / `Dashboard.tsx:884`; the Nov-13 placement doc `dc7cbe5` has no counterpart in `docs/` | verify `dc7cbe5`, then delete |
| `…/kind-circuit` | detached `beac431` | 1 | yes — same cleanup as `e89bd90` (#68) | delete |
| `…/tidy-meadow` | detached `dc6cbaf` | 0 | n/a | delete last |
| `…/swift-eagle` | removed from git | 0 | n/a | empty dir, locked by a process — retry, or it clears on reboot |

| Branch (no worktree) | Ahead | Content in main? | Verdict |
|---|---|---|---|
| `feat/hydrogen-v2-strategy` @ `1a7aa7f` | 2 | yes — `hydrogen-v2.0` in `bot/config.json:9`, m4 fix is `968f8df` (#66) | delete after push |
| `freebuff/chat`, `feat/execution-health`, `microstructure_inventory_risk_engine` | — | see table above | branch per row |

## Phase 1 — Back up every local-only branch

- [ ] Push each unmerged branch so nothing depends on a worktree folder:
  `git push origin feat/execution-health freebuff/chat microstructure_inventory_risk_engine feat/hydrogen-v2-strategy`
- [ ] Confirm they landed: `git ls-remote --heads origin` lists 5 heads including `main`.
- [ ] Record the detached SHAs that have no branch, so they stay reachable if any is ever needed:
  `git tag wip/calm-harbor-90ed8fc 90ed8fc` and `git push origin wip/calm-harbor-90ed8fc`
  (same pattern for `beac431` if its content is still doubted)

## Phase 2 — Decide the one branch with unique code

- [ ] Read the branch: `git log --oneline main..microstructure_inventory_risk_engine` and `git diff --stat main microstructure_inventory_risk_engine -- bot/`
- [ ] Pick one and record the choice here:
  - [ ] **Keep as work**: open a PR from `microstructure_inventory_risk_engine` (it now exists on origin, so the worktree can go regardless).
  - [ ] **Drop**: `git branch -D microstructure_inventory_risk_engine` after the worktree is removed.
- [ ] Confirm `bot/microstructure_engine/` is still absent from `main` before dropping, so the decision is not based on a stale snapshot.

## Phase 3 — Settle the uncertain commit

- [ ] Check whether the placement-rules verdict is worth keeping:
  `git show --stat dc7cbe5` and `git show dc7cbe5 --name-only`
- [ ] If yes, restore just that file from the branch into `docs/` and merge it on its own; if no, note "superseded" and continue.

## Phase 4 — Remove worktrees (one at a time, verify each)

- [ ] `git worktree remove "C:/Users/Tiger/.local/share/opencode/worktree/7c551f/calm-harbor"`
- [ ] `git worktree remove "C:/Users/Tiger/.local/share/opencode/worktree/7c551f/kind-circuit"`
- [ ] `git worktree remove "C:/Users/Tiger/.local/share/opencode/worktree/7c551f/curious-wizard"`
- [ ] `git worktree remove "C:/Users/Tiger/.gemini/antigravity/worktrees/dangerously-skip-permissions-bot/microstructure_inventory_risk_engine"` — only after Phase 2 is decided and pushed
- [ ] `git worktree prune`
- [ ] `git worktree list` shows only the main checkout, the freebuff chat checkout and `tidy-meadow`
- [ ] Retry the stuck folder: `Remove-Item "C:/Users/Tiger/.local/share/opencode/worktree/7c551f/swift-eagle" -Recurse -Force`; if it still refuses, leave a note and retry after reboot (it holds 0 files)

## Phase 5 — Delete merged branches

- [ ] `git branch -D feat/execution-health freebuff/chat feat/hydrogen-v2-strategy`
- [ ] `git branch -D microstructure_inventory_risk_engine` only if Phase 2 chose "drop"
- [ ] `git branch -vv` shows `main` plus nothing you did not consciously keep

## Phase 6 — Uncommitted / untracked work

- [ ] `docs/avellaneda-stoikov/01-architecture-overview.md` — committed as `a880cee`; `git status` clean. Nothing to do beyond confirming it is on `origin/main`.
- [ ] Rescued CSV `data/0xb55fa1…csv` (77 MB, pulled 16 Nov) — confirm it belongs with the other pulled history under `data/dangerously-skip-permissions-trades/`, move it there or keep it at the root deliberately.
- [ ] `freebuff` chat sessions (8 folders holding only `*.thread.json`) — leave them to the freebuff app; deleting a folder erases that conversation.
- [ ] `bot/tests/__pycache__`, `bot/__pycache__`, `.pytest_cache`, empty `.worktrees/` — already removed; they are regenerated by running tests.

## Phase 7 — Optional disk work (decide, do not default)

- [ ] `scratch/replay_cache/` — 3.2 GB of 13 valid pickles. Safe to delete, replays rebuild them (`python -m bot.replay --run …`). Drop only if disk pressure matters more than replay speed.
- [ ] `bot/runs/` — 9.2 GB, already pruned to replayable windows only; moves under #72, not here.
- [ ] `data/dangerously-skip-permissions-trades/` — 950 MB of pulled trade history; not stale, do not delete.

## Phase 8 — Closeout gates

- [ ] `git worktree list` matches the intended set.
- [ ] `git branch -vv` shows no branch you cannot explain.
- [ ] `git status --short` is clean on `main`.
- [ ] `main` equals `origin/main`: `git rev-parse HEAD origin/main` returns the same SHA.
- [ ] `python -m pytest bot/tests -q` passes (320 tests).
- [ ] Repo size sanity: `git count-objects -vH` — run `git gc --prune=now` only after every branch you dropped is unreachable by design.

## Sequencing with open work

- [ ] #71 (rename the flat window mirror) lands before #72 (move runtime data to `data/`), because #72 moves the folder #71 renames.
- [ ] This checklist can land in parallel: it touches `docs/` only.

## Rollback

Every deleted worktree is reconstructible while its branch still exists:
`git worktree add "C:/Users/Tiger/.local/share/opencode/worktree/<name>" <branch>`
Every deleted branch is reconstructible while it exists on `origin`.
A dropped SHA with only a tag is recoverable from the tag; a pruned, untagged, unreachable commit is not.
