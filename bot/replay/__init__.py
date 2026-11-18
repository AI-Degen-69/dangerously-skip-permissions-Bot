"""Replay the recorded tape to test placement rules offline.

Replays one recorded market window at a time: walks the window's clock, takes
quotes from the recorded ``book.jsonl`` snapshots, applies a placement rule by
calling the REAL ``bot.executor`` helpers, and books fills from the recorded
``prints.jsonl`` via ``bot.fill_audit.fill_model.match_maker_print``.

The replay never reads a window's own fills to drive the simulation -- only
``condition_id``, ``event_slug`` (start epoch) and ``winner`` (for scoring).

Usage:
    python -m bot.replay --run data/runs/run_20261113_080232_paper_dsp_v2_6 --rule v2.6
    python -m bot.replay --runs all --rule hump --ceiling 0.75 --levels 2 --spacing 0.02
    python -m bot.replay --runs all --rule v2.6 --against-live       # gate mode

Shell: public names and CLI entry live here; pure logic lives in
replay_consts / replay_sizing / replay_slices / replay_sim /
replay_analysis / replay_cli.
"""

from .replay_analysis import (
    count_live_placements,
    coverage_ok,
    gate,
    live_fixture,
    resolve_runs,
    run_rule,
    spearman,
    summarize,
)
from .replay_cli import main
from .replay_consts import (
    BASELINE_RUN,
    FOUR_RUNS,
    LOOP_LOG,
    STRATEGY_HYDROGEN,
    STRATEGY_V26,
    STRATEGY_V27,
    WINDOW_S,
)
from .replay_sim import simulate_window
from .replay_sizing import HUMP_ANCHORS, hump_shares, make_hump_sizing
from .replay_slices import (
    build_slices,
    cache_dir,
    list_run_windows,
    load_prints_grouped,
    load_run_entry,
    load_slices,
)

__all__ = [
    "BASELINE_RUN",
    "FOUR_RUNS",
    "HUMP_ANCHORS",
    "LOOP_LOG",
    "STRATEGY_HYDROGEN",
    "STRATEGY_V26",
    "STRATEGY_V27",
    "WINDOW_S",
    "build_slices",
    "cache_dir",
    "count_live_placements",
    "coverage_ok",
    "gate",
    "hump_shares",
    "list_run_windows",
    "live_fixture",
    "load_prints_grouped",
    "load_run_entry",
    "load_slices",
    "main",
    "make_hump_sizing",
    "resolve_runs",
    "run_rule",
    "simulate_window",
    "spearman",
    "summarize",
]


if __name__ == "__main__":
    raise SystemExit(main())
