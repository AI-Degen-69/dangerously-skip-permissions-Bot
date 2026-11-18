import argparse
import csv
import datetime
import os
import re
import sys
import time
from collections import defaultdict
import requests
DEFAULT_USERNAME = "dangerously-skip-permissions"
MAX_EMPTY_WINDOWS = 4  # shortcut: 4 empty windows in a row end a "max" crawl; raise for dormant accounts
MAX_WINDOWS = 3650  # safety cap for a "max" crawl (10 years of daily windows)
def fetch_max_activity(
    user_address: str,
    now: datetime.datetime,
    window_days: int = 7,
    verify_remote: bool = False,
    snap_to_window: bool = True,
    cut_first_tail: bool = True,
    autosave_path: str | None = None,
    target_ts: int | None = None,
) -> tuple[list[dict], bool]:
    """Pulls backward window by window until the account runs out of activity.

    Returns (deduped records, interrupted). Consecutive windows share their
    boundary instant, so each window's rows are merged by identity with the
    largest count any single window reported.

    autosave_path rewrites the rows pulled so far every few windows, so a crash
    or a killed terminal does not lose a long crawl. target_ts is the account's
    first activity, used only to estimate how much of the history is left.
    """
    counts: dict[tuple, int] = {}
    samples: dict[tuple, dict] = {}
    end = now
    empty_windows = 0
    interrupted = False
    window_number = 0
    crawl_start = time.monotonic()
    crawl_start_ts = int(now.timestamp())

    _section("Full history crawl")
    print(
        f"  Reads {window_days} days per request; stops after "
        f"{MAX_EMPTY_WINDOWS} stretches with no fills.",
        flush=True,
    )
    print("  Ctrl+C stops at a checkpoint.", flush=True)

    while empty_windows < MAX_EMPTY_WINDOWS and window_number < MAX_WINDOWS:
        window_number += 1
        start_ts, end_ts = window_bounds(end, window_days, snap_to_window)
        partial: list[dict] = []
        try:
            window = fetch_activity(
                user_address=user_address,
                now=end,
                snap_to_window=snap_to_window,
                cut_tails=cut_first_tail and window_number == 1,
                verify_remote=verify_remote,
                window_days=window_days,
                partial=partial,
            )
        except KeyboardInterrupt:
            interrupted = True
            if partial:
                for record in partial:
                    record.pop("timestamp", None)
                absorb_window(counts, samples, partial)
                print(f"  interrupted mid-day: kept {len(partial):,} fills pulled so far")
            break

        end = datetime.datetime.fromtimestamp(start_ts, tz=UTC)
        if not window:
            empty_windows += 1
            print(
                f"  stretch {window_number:<3} "
                f"{datetime.datetime.fromtimestamp(start_ts, tz=UTC):%Y-%m-%d} -> "
                f"{datetime.datetime.fromtimestamp(end_ts, tz=UTC):%Y-%m-%d}  "
                f"{0:>7,} fills  "
                f"(empty {empty_windows}/{MAX_EMPTY_WINDOWS})"
            )
            continue

        empty_windows = 0
        absorb_window(counts, samples, window)
        elapsed = time.monotonic() - crawl_start
        eta = _crawl_eta(crawl_start_ts, target_ts, int(end.timestamp()), elapsed)
        print(
            f"  stretch {window_number:<3} "
            f"{datetime.datetime.fromtimestamp(start_ts, tz=UTC):%Y-%m-%d} -> "
            f"{datetime.datetime.fromtimestamp(end_ts, tz=UTC):%Y-%m-%d}  "
            f"{len(window):>7,} fills  {_fmt_duration(elapsed):>6}"
            + (f"  {eta}" if eta else "")
        )

        if autosave_path and window_number % 5 == 0:
            snapshot = [samples[key] for key, n in counts.items() for _ in range(n)]
            try:
                save_to_csv(snapshot, autosave_path, announce=False)
                print(f"  autosaved {len(snapshot):,} rows -> {autosave_path}")
            except OSError as exc:
                print(f"  autosave failed ({exc}); crawl continues")

    return [samples[key] for key, n in counts.items() for _ in range(n)], interrupted
RAW_SUBDIRS = ("raw",)
DOCS_SUBDIRS = ("reports", "analysis")


def account_dirs(display_name: str) -> str:
    """Create and return data/leaderboard/<account>/ (raw CSVs under data,
    reports/ and analysis/ under docs/leaderboard-traders/ledgers/)."""
    safe = safe_account_name(display_name)
    raw_root = os.path.join(RAW_ROOT, safe)
    for sub in RAW_SUBDIRS:
        os.makedirs(os.path.join(raw_root, sub), exist_ok=True)
    docs_root = os.path.join(DOCS_ROOT, safe)
    for sub in DOCS_SUBDIRS:
        os.makedirs(os.path.join(docs_root, sub), exist_ok=True)
    return raw_root
def print_checkpoint(records: list[dict], output_file: str, interrupted: bool) -> None:
    if records:
        dates = sorted(record["Timestamp_UTC"][:10] for record in records)
        span = f"{dates[0]} -> {dates[-1]}"
    else:
        span = "no activity"
    windows, days = pull_stats(records)
    label = "CHECKPOINT (interrupted)" if interrupted else "CHECKPOINT"
    print()
    print("=" * SECTION_WIDTH)
    print(f"  {label}")
    print(f"  rows     {len(records):,}")
    print(f"  span     {span}")
    print(f"  markets  {windows:,} windows across {days:,} days")
    print(f"  file     {output_file}")
    if interrupted:
        print("  Note: the interrupted day is partial; its market windows may be incomplete.")
    print("=" * SECTION_WIDTH)
def main():
    parser = argparse.ArgumentParser(
        description="Save Polymarket activity to CSV."
    )
    parser.add_argument(
        "-u", "--user",
        help="Polymarket username, @handle, profile URL, or wallet address (e.g. 'Tokor' or '0xa19cb...')"
    )
    parser.add_argument(
        "-d", "--date", "--start-date",
        dest="date",
        help=(
            "Target date/time ending the fetch window, or 'max' to pull backward "
            "until the account runs out of activity. A date-only value fetches "
            "that full UTC date and preceding days; default: now"
        )
    )
    parser.add_argument(
        "--days",
        type=int,
        choices=(1, 7),
        default=7,
        help="Number of days to fetch (1 or 7; default: 7)",
    )
    parser.add_argument(
        "-o", "--output",
        help="Custom output path (default: data/leaderboard/<account>/raw/<tag>_<range>.csv)"
    )
    parser.add_argument(
        "--no-snap",
        action="store_true",
        help="Disable 5-minute window boundary snapping"
    )
    parser.add_argument(
        "--no-cut-tails",
        action="store_true",
        help="Disable cutting incomplete/partial markets in the tails"
    )
    parser.add_argument(
        "--no-autosave",
        action="store_true",
        help="Disable the periodic partial CSV written during a 'max' crawl"
    )
    parser.add_argument(
        "--verify-remote",
        action="store_true",
        default=True,
        help="Verify market completion with Gamma API for non-window markets (default: True)"
    )

    args = parser.parse_args()

    user_input = args.user
    if not user_input:
        try:
            prompt_val = input(f"Enter Polymarket username or wallet address [{DEFAULT_USERNAME}]: ").strip()
            user_input = prompt_val if prompt_val else DEFAULT_USERNAME
        except (EOFError, KeyboardInterrupt):
            user_input = DEFAULT_USERNAME
            print()

    date_input = args.date
    if not date_input and sys.stdin.isatty():
        try:
            prompt_date = input(
                "Enter date (DD/MM, DD/MM/YYYY, 'now', 'max' for full history, "
                "'cancel' to quit) [now]: "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            sys.exit(0)
        if prompt_date.lower() in ("cancel", "q", "quit", "exit"):
            print("  Cancelled.")
            sys.exit(0)
        date_input = prompt_date if prompt_date else "now"
    elif not date_input:
        date_input = "now"

    _section("Polymarket activity export")
    print(f"  Resolving '{user_input}'...")
    try:
        resolved_address, display_name = resolve_user_address(user_input)
    except Exception as exc:
        print(f"  Error: could not resolve '{user_input}': {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"  Account   {display_name}")
    print(f"  Wallet    {resolved_address}")

    is_max = date_input.strip().lower() == "max"
    try:
        target_dt = parse_date_input("now" if is_max else date_input)
    except Exception as exc:
        print(f"  Error: could not parse date '{date_input}': {exc}", file=sys.stderr)
        sys.exit(1)

    autosave_file = None
    account_root = account_dirs(display_name)

    if is_max:
        if not args.no_autosave:
            autosave_file = os.path.join(
                account_root,
                "raw",
                f"{short_account_tag(display_name)}_{target_dt:%Y-%m-%d}_partial.csv",
            )
        target_ts = probe_oldest_activity(resolved_address)
        if target_ts:
            print(
                "  Oldest fill  "
                f"{datetime.datetime.fromtimestamp(target_ts, tz=UTC):%Y-%m-%d}"
            )
        activity, interrupted = fetch_max_activity(
            resolved_address,
            now=target_dt,
            window_days=args.days,
            verify_remote=args.verify_remote,
            snap_to_window=not args.no_snap,
            cut_first_tail=not args.no_cut_tails,
            autosave_path=autosave_file,
            target_ts=target_ts,
        )
        while True:
            if args.output:
                output_file = args.output
            else:
                output_file = os.path.join(
                    account_root,
                    "raw",
                    max_output_filename(display_name, activity),
                )
            print_checkpoint(activity, output_file, interrupted)
            if not sys.stdin.isatty():
                break
            try:
                choice = input(
                    "Press Enter to save and exit, or 'c' to keep pulling older data: "
                )
            except (EOFError, KeyboardInterrupt):
                choice = ""
                print()
            if choice.strip().lower() not in ("c", "continue"):
                break
            oldest = min((r["Timestamp_UTC"] for r in activity), default=None)
            if oldest is None:
                break
            resumed, interrupted = fetch_max_activity(
                resolved_address,
                now=datetime.datetime.fromisoformat(oldest),
                window_days=args.days,
                verify_remote=args.verify_remote,
                snap_to_window=not args.no_snap,
                cut_first_tail=not args.no_cut_tails,
                target_ts=target_ts,
                # no autosave here: this segment would overwrite the first one's partial
            )
            activity = merge_records(activity, resumed)
    else:
        # Determine default CSV output name
        if args.output:
            output_file = args.output
        else:
            normalized_date_input = date_input.strip()
            date_only = (
                normalized_date_input.lower() != "now"
                and "T" not in normalized_date_input
                and len(normalized_date_input.split()) == 1
            )
            output_file = os.path.join(
                account_root,
                "raw",
                default_output_filename(
                    display_name,
                    target_dt,
                    window_days=args.days,
                    date_only=date_only,
                ),
            )
        print(f"  Output    {output_file}")

        activity = fetch_activity(
            user_address=resolved_address,
            now=target_dt,
            snap_to_window=not args.no_snap,
            cut_tails=not args.no_cut_tails,
            verify_remote=args.verify_remote,
            window_days=args.days,
        )

        if not activity:
            print(f"  No activity in the {args.days}-day window.")

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    save_to_csv(activity, output_path=output_file)
    if autosave_file and os.path.exists(autosave_file):
        os.remove(autosave_file)
        print(f"  Removed partial autosave: {autosave_file}")

from ..report_kit import DOCS_ROOT, RAW_ROOT

from .accounts import (
    default_output_filename,
    max_output_filename,
    safe_account_name,
    short_account_tag,
)
from .api import (
    BASE_URL,
    GAMMA_URL,
    PAGE_LIMIT,
    REQUEST_DELAY_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    USER_ADDRESS,
    WINDOW_PATTERN,
    _window_label,
    cut_tail_markets,
    fetch_activity,
    get_window_meta,
    is_market_completed_via_gamma,
    probe_oldest_activity,
    resolve_user_address,
)
from .dates import UTC, clean_user_input, parse_date_input
from .records import (
    CSV_FIELDS,
    absorb_window,
    merge_records,
    pull_stats,
    record_key,
    save_to_csv,
)
from .windows import (
    SECTION_WIDTH,
    WINDOW_SIZE_SECONDS,
    _crawl_eta,
    _finish_day,
    _fmt_duration,
    _section,
    _usd,
    window_bounds,
)

__all__ = [
    "DEFAULT_USERNAME", "MAX_EMPTY_WINDOWS", "MAX_WINDOWS",
    "RAW_ROOT", "RAW_SUBDIRS", "DOCS_ROOT", "DOCS_SUBDIRS",
    "BASE_URL", "GAMMA_URL", "PAGE_LIMIT",
    "REQUEST_DELAY_SECONDS", "REQUEST_TIMEOUT_SECONDS",
    "USER_ADDRESS", "UTC", "WINDOW_PATTERN", "WINDOW_SIZE_SECONDS",
    "CSV_FIELDS", "SECTION_WIDTH",
    "absorb_window", "account_dirs", "clean_user_input",
    "cut_tail_markets", "default_output_filename", "fetch_activity",
    "fetch_max_activity", "get_window_meta",
    "is_market_completed_via_gamma", "main", "max_output_filename",
    "merge_records", "parse_date_input", "print_checkpoint",
    "probe_oldest_activity", "pull_stats", "record_key",
    "resolve_user_address", "safe_account_name", "save_to_csv",
    "short_account_tag",
    "_crawl_eta", "_finish_day", "_fmt_duration", "_section", "_usd",
    "_window_label", "window_bounds",
]
