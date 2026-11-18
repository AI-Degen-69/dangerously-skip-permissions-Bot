import argparse
import csv
import datetime
import os
import re
import sys
import time
from collections import defaultdict
import requests
WINDOW_SIZE_SECONDS = 300  # 5 minutes
SECTION_WIDTH = 74
def window_bounds(
    now: datetime.datetime,
    window_days: int,
    snap_to_window: bool = True,
) -> tuple[int, int]:
    """Returns (start_ts, end_ts) for the window ending at `now`."""
    now_ts = int(now.timestamp())
    if snap_to_window:
        end_ts = (now_ts // WINDOW_SIZE_SECONDS) * WINDOW_SIZE_SECONDS
    else:
        end_ts = now_ts
    return end_ts - window_days * 24 * 60 * 60, end_ts
def _fmt_duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m{secs:02d}s" if minutes else f"{secs}s"
def _section(title: str) -> None:
    """A titled rule with a blank line first, so long output reads in blocks."""
    print()
    print(f"  {title} " + "=" * max(4, SECTION_WIDTH - len(title) - 3))
def _usd(record: dict) -> float:
    try:
        return float(record.get("USD_Amount") or 0)
    except (TypeError, ValueError):
        return 0.0
def _finish_day(day, fills, usd, windows, started_at, interactive) -> None:
    summary = (
        f"{day} | {fills:,} fills in {len(windows):,} market windows | "
        f"${usd:>9,.0f} traded | {_fmt_duration(time.monotonic() - started_at):>7}"
    )
    if interactive:
        print("\r" + " " * 110 + "\r" + "  " + summary, flush=True)
    else:
        print("  " + summary, flush=True)
    print("  " + "-" * 70, flush=True)
def _crawl_eta(crawl_start_ts: int, target_ts: int | None, end_ts: int, elapsed: float) -> str:
    """Share of the account's history already covered, plus the crawl's ETA.

    Needs the account's first activity (target_ts); until it is known the crawl
    has no denominator, so the ETA is left out rather than guessed.
    """
    if not target_ts or target_ts >= crawl_start_ts or elapsed <= 0:
        return ""
    covered = crawl_start_ts - end_ts
    if covered <= 0:
        return ""
    pct = min(covered / (crawl_start_ts - target_ts), 1.0)
    eta = elapsed * (1 - pct) / pct
    return f"~{_fmt_duration(eta)} left"
