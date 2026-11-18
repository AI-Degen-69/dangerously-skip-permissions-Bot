"""Run-scoped session workspace manager for dangerously-skip-permissions paper bot.

Provides deterministic run sessions under `data/runs/<run_id>/`:
  data/runs/
    run_20261108_044500_paper_default/
      run_meta.json      (config snapshot, startedAt, endedAt, status)
      loop.log           (process output)
      loop.pid           (process ID)
      events.jsonl       (session decision journal)
      decisions.jsonl    (uncensored per-evaluation engine log: quotes + guard)
      windows/           (settled window json files)
      summary.json       (session KPIs / metrics)

The active run is tracked by `data/runs/active_run.json` (see `runs_query`)

Shell: public names live here; pure logic lives in runs_paths /
runs_tape / runs_workspace / runs_query.
"""

from .runs_paths import (
    ACTIVE_RUN_POINTER,
    BOT_DIR,
    CONFIG_PATH,
    DATA_DIR,
    EVENTS_PATH,
    KILL_PATH,
    LOG_PATH,
    PID_PATH,
    ROOT,
    RUNS_DIR,
    STATE_PATH,
    WINDOWS_MIRROR_DIR,
    AB_STATE_PATH,
    _WINDOWS_MIRROR_LEGACY_DIR,
    ensure_data_dir,
    make_run_id,
    migrate_windows_mirror,
    utc_now_iso,
)
from .runs_query import (
    find_run_id,
    get_active_run_id,
    list_all_runs,
    resolve_run_workspace,
    set_active_run_id,
)
from .runs_tape import (
    _TAPE_COUNTS,
    _TAPE_LOADED,
    _TAPE_LOCK,
    _count_appended_lines,
    _load_tape_counts,
    _save_tape_counts,
    _tape_cache_file,
    tape_segments,
)
from .runs_workspace import RunMeta, RunWorkspace

__all__ = [
    "AB_STATE_PATH",
    "ACTIVE_RUN_POINTER",
    "BOT_DIR",
    "CONFIG_PATH",
    "DATA_DIR",
    "EVENTS_PATH",
    "KILL_PATH",
    "LOG_PATH",
    "PID_PATH",
    "ROOT",
    "RUNS_DIR",
    "STATE_PATH",
    "WINDOWS_MIRROR_DIR",
    "_TAPE_COUNTS",
    "_TAPE_LOADED",
    "_TAPE_LOCK",
    "_WINDOWS_MIRROR_LEGACY_DIR",
    "_count_appended_lines",
    "_load_tape_counts",
    "_save_tape_counts",
    "_tape_cache_file",
    "ensure_data_dir",
    "find_run_id",
    "get_active_run_id",
    "list_all_runs",
    "make_run_id",
    "migrate_windows_mirror",
    "resolve_run_workspace",
    "RunMeta",
    "RunWorkspace",
    "set_active_run_id",
    "tape_segments",
    "utc_now_iso",
]
