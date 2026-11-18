"""Pure dashboard view builders for the desk API.

No imports from bot.api and no hidden globals. Every input arrives as
an explicit argument; bot/api.py (the shell) gathers paths, run
workspaces, caches, and the network client, then passes values in.

Shell: public names live here; pure logic lives in views_common /
views_snapshot / views_perf / views_trades.
"""

from .views_common import (
    _enrich_fill,
    _mean,
    _median,
    _minute_shape,
    _num,
    _window_row,
    slot_ms,
)
from .views_perf import build_perf
from .views_snapshot import build_kpis, build_snapshot
from .views_trades import build_trades_view

# bot/api.py delegates ``_window_row`` through this public alias.
build_window_row = _window_row

__all__ = [
    "_enrich_fill",
    "_mean",
    "_median",
    "_minute_shape",
    "_num",
    "_window_row",
    "build_kpis",
    "build_perf",
    "build_snapshot",
    "build_trades_view",
    "build_window_row",
    "slot_ms",
]
