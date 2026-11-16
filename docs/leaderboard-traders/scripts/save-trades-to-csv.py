import argparse
import csv
import datetime
import os
import re
import sys
import time
from collections import defaultdict

import requests

BASE_URL = "https://data-api.polymarket.com/v2/activity"
GAMMA_URL = "https://gamma-api.polymarket.com"
# Anchored to docs/leaderboard-traders so the output lands in the same place
# whatever directory the script is run from.
LEDGERS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ledgers"
)
ACCOUNT_SUBDIRS = ("raw", "reports", "analysis")
DEFAULT_USERNAME = "dangerously-skip-permissions"
USER_ADDRESS = "0xc53375ff94e96100f2b30a4b5775db35218d69a9"
PAGE_LIMIT = 100
REQUEST_DELAY_SECONDS = 0.2
REQUEST_TIMEOUT_SECONDS = 30
WINDOW_SIZE_SECONDS = 300  # 5 minutes
UTC = datetime.timezone.utc
MAX_EMPTY_WINDOWS = 4  # shortcut: 4 empty windows in a row end a "max" crawl; raise for dormant accounts
MAX_WINDOWS = 3650  # safety cap for a "max" crawl (10 years of daily windows)

CSV_FIELDS = [
    "Timestamp_UTC",
    "Type",
    "Market",
    "Outcome",
    "Side",
    "Price",
    "Shares",
    "USD_Amount",
    "Condition_ID",
    "Token_ID",
    "Market_Slug",
]

WINDOW_PATTERN = re.compile(r'-(?:(\d+)m|(\d+)h)-(\d+)$')


def parse_date_input(
    date_str: str | datetime.datetime | None = None,
    now: datetime.datetime | None = None,
) -> datetime.datetime:
    """
    Parses a date input into an end_dt (timezone-aware UTC) representing
    the end boundary of the requested fetch window.

    Rules:
    - If None, empty, or 'now': returns now in UTC.
    - If date-only (e.g. '06/11', '06/11/2026', '2026-11-06'):
      Returns the start of the following day (00:00:00 UTC), so the fetch
      window includes the full requested date and the preceding days.
      Example: '06/11' (DD/MM) -> 07/11 00:00:00 UTC.
    - If datetime is specified (e.g. '06/11 15:30' or ISO): returns that exact datetime.
    """
    if now is None:
        now = datetime.datetime.now(UTC)
    else:
        now = now.astimezone(UTC)

    if date_str is None:
        return now

    if isinstance(date_str, datetime.datetime):
        if date_str.tzinfo is None or date_str.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware")
        return date_str.astimezone(UTC)

    s = date_str.strip()
    if not s or s.lower() == "now":
        return now

    # 1. ISO format with T (e.g. 2026-11-06T15:00:00)
    if "T" in s:
        try:
            dt = datetime.datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except Exception:
            pass

    # 2. Date + time (e.g. "06/11/2026 15:30" or "06/11 15:30")
    parts = s.split()
    if len(parts) == 2:
        date_part, time_part = parts
        time_tokens = [int(x) for x in time_part.split(":")]
        hour = time_tokens[0]
        minute = time_tokens[1] if len(time_tokens) > 1 else 0
        second = time_tokens[2] if len(time_tokens) > 2 else 0

        day, month, year = _parse_date_components(date_part, now.year)
        return datetime.datetime(year, month, day, hour, minute, second, tzinfo=UTC)

    # 3. Date-only format -> fetch backward from (day + 1) 00:00:00 UTC
    day, month, year = _parse_date_components(s, now.year)
    target_day = datetime.datetime(year, month, day, 0, 0, 0, tzinfo=UTC)
    return target_day + datetime.timedelta(days=1)


def _parse_date_components(s: str, default_year: int) -> tuple[int, int, int]:
    """Parses date string with '/', '-', or '.' into (day, month, year)."""
    parts = re.split(r'[/.\-]', s)
    if len(parts) == 2:
        # DD/MM
        day = int(parts[0])
        month = int(parts[1])
        year = default_year
    elif len(parts) == 3:
        if len(parts[0]) == 4:
            # YYYY-MM-DD or YYYY/MM/DD
            year = int(parts[0])
            month = int(parts[1])
            day = int(parts[2])
        else:
            # DD/MM/YYYY or DD/MM/YY
            day = int(parts[0])
            month = int(parts[1])
            year = int(parts[2])
            if year < 100:
                year += 2000
    else:
        raise ValueError(
            f"Unrecognized date format: '{s}'. Expected DD/MM (e.g. '06/11'), "
            "DD/MM/YYYY, or YYYY-MM-DD."
        )

    # Validate valid calendar date
    datetime.date(year, month, day)
    return day, month, year


def clean_user_input(user_input: str) -> str:
    """Extract username or address from user input, @handle, or Polymarket URL."""
    val = user_input.strip()
    url_match = re.search(r'polymarket\.com/@?([a-zA-Z0-9_\-]+)', val, re.IGNORECASE)
    if url_match:
        return url_match.group(1)
    if val.startswith("@"):
        return val[1:]
    return val


def resolve_user_address(user_input: str, session: requests.Session | None = None) -> tuple[str, str]:
    """
    Resolves user input (username, @handle, URL, or EVM address)
    to (proxy_wallet_address, display_name).
    """
    cleaned = clean_user_input(user_input)
    req = session if session is not None else requests

    # 1. If input is already an EVM address
    if re.fullmatch(r'0x[a-fA-F0-9]{40}', cleaned):
        address = cleaned.lower()
        display_name = address
        try:
            r = req.get(
                f"{GAMMA_URL}/public-profile?address={address}",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if r.status_code == 200:
                prof = r.json()
                display_name = prof.get("name") or prof.get("pseudonym") or address
        except Exception:
            pass
        return address, display_name

    # 2. Input is a username: scrape public profile page
    username = cleaned
    profile_url = f"https://polymarket.com/@{username}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        resp = req.get(profile_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except Exception as exc:
        raise ValueError(f"Failed to fetch profile page for '{username}': {exc}") from exc

    # Search for proxyWallet inside HTML / React Server Components stream
    matches = re.findall(r'\\*"proxyWallet\\*":\s*\\*"(0x[a-fA-F0-9]{40})\\*"', resp.text)
    if not matches:
        matches = re.findall(r'0x[a-fA-F0-9]{40}', resp.text)
        if not matches:
            raise ValueError(f"Could not resolve wallet address for Polymarket user '{username}'")

    address = matches[0].lower()
    display_name = username
    try:
        r = req.get(
            f"{GAMMA_URL}/public-profile?address={address}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if r.status_code == 200:
            prof = r.json()
            display_name = prof.get("name") or prof.get("pseudonym") or username
    except Exception:
        pass

    return address, display_name


def get_window_meta(slug_or_title: str) -> tuple[int, int] | None:
    """Extracts (slot_start_epoch, duration_seconds) if matching recurring window pattern."""
    if not slug_or_title:
        return None
    m = WINDOW_PATTERN.search(str(slug_or_title))
    if m:
        mins = int(m.group(1)) if m.group(1) else int(m.group(2)) * 60
        duration = mins * 60
        slot_start = int(m.group(3))
        return slot_start, duration
    return None


def is_market_completed_via_gamma(
    event_slug: str | None,
    condition_id: str | None,
    now_ts: int,
    session: requests.Session | None = None,
) -> bool | None:
    """
    Checks Gamma API to see if event/market has closed or ended.
    Returns True if completed, False if active/uncompleted, None if unknown/failed.
    """
    req = session if session is not None else requests
    try:
        if event_slug:
            r = req.get(
                f"{GAMMA_URL}/events?slug={event_slug}",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=5,
            )
            if r.status_code == 200:
                events = r.json()
                if isinstance(events, list) and events:
                    ev = events[0]
                    if ev.get("closed") is True:
                        return True
                    end_date_str = ev.get("endDate")
                    if end_date_str:
                        end_dt = datetime.datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                        if end_dt.timestamp() <= now_ts:
                            return True
                    if ev.get("closed") is False:
                        return False
        if condition_id:
            r = req.get(
                f"{GAMMA_URL}/markets?condition_id={condition_id}",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=5,
            )
            if r.status_code == 200:
                markets = r.json()
                if isinstance(markets, list) and markets:
                    m = markets[0]
                    if m.get("closed") is True:
                        return True
                    end_date_str = m.get("endDate")
                    if end_date_str:
                        end_dt = datetime.datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                        if end_dt.timestamp() <= now_ts:
                            return True
                    if m.get("closed") is False or m.get("active") is True:
                        return False
    except Exception:
        pass
    return None


def cut_tail_markets(
    records: list[dict],
    start_ts: int,
    end_ts: int,
    user_address: str | None = None,
    now_ts: int | None = None,
    verify_remote: bool = False,
    session: requests.Session | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Removes markets in the tails that:
    1. Upper tail: Have not completed (in-progress window or active/unclosed market).
    2. Lower tail: Have not been fully pulled (window started before start_ts or earlier trades missing).
    Returns (cleaned_records, removed_records).
    """
    if not records:
        return records, []

    if now_ts is None:
        now_ts = int(datetime.datetime.now(UTC).timestamp())

    market_records = defaultdict(list)
    for r in records:
        key = r.get("Market_Slug") or r.get("Condition_ID") or r.get("Market")
        market_records[key].append(r)

    markets_to_remove = set()
    removal_reasons = {}

    market_stats = {}
    for key, items in market_records.items():
        if not key:
            continue
        timestamps = []
        for x in items:
            ts_val = x.get("timestamp")
            if ts_val is not None and isinstance(ts_val, (int, float)):
                timestamps.append(float(ts_val))
            elif isinstance(x.get("Timestamp_UTC"), str):
                try:
                    timestamps.append(datetime.datetime.fromisoformat(x["Timestamp_UTC"]).timestamp())
                except Exception:
                    pass
        if not timestamps:
            continue
        market_stats[key] = {
            "min_ts": min(timestamps),
            "max_ts": max(timestamps),
            "count": len(items),
            "sample": items[0],
        }

    # 1. Check Newest Tail (markets near end_ts or now_ts)
    for key, stats in market_stats.items():
        sample = stats["sample"]
        slug = sample.get("Market_Slug") or key
        w_meta = get_window_meta(slug)
        if w_meta:
            slot_start, duration = w_meta
            slot_end = slot_start + duration
            # Window ended after the pull boundary or after current time
            if slot_end > end_ts or slot_end > now_ts:
                markets_to_remove.add(key)
                removal_reasons[key] = (
                    f"Incomplete window in newest tail (window ends at "
                    f"{datetime.datetime.fromtimestamp(slot_end, tz=UTC).isoformat()}, "
                    f"pull end={datetime.datetime.fromtimestamp(end_ts, tz=UTC).isoformat()})"
                )
                continue
        elif verify_remote and stats["max_ts"] >= end_ts - 3600:
            cond_id = sample.get("Condition_ID")
            completed = is_market_completed_via_gamma(slug, cond_id, now_ts, session=session)
            if completed is False:
                markets_to_remove.add(key)
                removal_reasons[key] = "Uncompleted/active market in newest tail (market still open)"
                continue

    # 2. Check Oldest Tail (markets near start_ts)
    req = session if session is not None else requests
    for key, stats in market_stats.items():
        if key in markets_to_remove:
            continue
        sample = stats["sample"]
        slug = sample.get("Market_Slug") or key
        w_meta = get_window_meta(slug)
        if w_meta:
            slot_start, duration = w_meta
            # Window started before the pull boundary, so earlier trades were not pulled
            if slot_start < start_ts:
                markets_to_remove.add(key)
                removal_reasons[key] = (
                    f"Partially pulled window in oldest tail (window started at "
                    f"{datetime.datetime.fromtimestamp(slot_start, tz=UTC).isoformat()} "
                    f"before pull start={datetime.datetime.fromtimestamp(start_ts, tz=UTC).isoformat()})"
                )
                continue
        elif verify_remote and stats["min_ts"] <= start_ts + 1800 and user_address:
            try:
                r = req.get(
                    BASE_URL,
                    params={"user": user_address, "end": int(start_ts), "limit": 10},
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=5,
                )
                if r.status_code == 200:
                    prior_acts = r.json().get("data", [])
                    for pa in prior_acts:
                        pa_key = pa.get("event_slug") or pa.get("slug") or pa.get("condition_id") or pa.get("title")
                        if pa_key == key or pa.get("condition_id") == sample.get("Condition_ID"):
                            markets_to_remove.add(key)
                            removal_reasons[key] = "Partially pulled market in oldest tail (found earlier trades before start_ts)"
                            break
            except Exception:
                pass

    cleaned_records = []
    removed_records = []
    for r in records:
        key = r.get("Market_Slug") or r.get("Condition_ID") or r.get("Market")
        if key in markets_to_remove:
            removed_records.append(r)
        else:
            cleaned_records.append(r)

    if removal_reasons:
        print(
            f"  Tail cut: dropped {len(removal_reasons):,} incomplete/partial "
            f"market(s) ({len(removed_records):,} fills)"
        )
        for k, reason in removal_reasons.items():
            print(f"    - {k}: {reason}")
    else:
        print("  Tail check: every market in the window is complete.")

    return cleaned_records, removed_records


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


SECTION_WIDTH = 74


def _section(title: str) -> None:
    """A titled rule with a blank line first, so long output reads in blocks."""
    print()
    print(f"  {title} " + "=" * max(4, SECTION_WIDTH - len(title) - 3))


def _usd(record: dict) -> float:
    try:
        return float(record.get("USD_Amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def _window_label(slug: str | None) -> str:
    """A 5m market window in clock time, e.g. '07:35 (5m)'."""
    meta = get_window_meta(slug or "")
    if meta:
        slot, duration = meta
        return (
            datetime.datetime.fromtimestamp(slot, tz=UTC).strftime("%H:%M")
            + f" ({duration // 60}m)"
        )
    return (slug or "")[:18] or "unknown"


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


def probe_oldest_activity(user_address: str) -> int | None:
    """Timestamp of the account's first activity, or None if the probe fails.

    The crawl needs a denominator for an ETA; one ascending request is cheaper
    than crawling to the account's first fill just to learn where it is.
    """
    try:
        response = requests.get(
            BASE_URL,
            params={
                "user": user_address,
                "limit": 1,
                "sortBy": "TIMESTAMP",
                "sortDirection": "ASC",
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        page = response.json().get("data")
        timestamp = page[0]["timestamp"]
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            return None
        return int(timestamp)
    except Exception:
        return None


def fetch_activity(
    user_address: str | None = None,
    now: datetime.datetime | str | None = None,
    snap_to_window: bool = True,
    cut_tails: bool = True,
    verify_remote: bool = False,
    window_days: int = 7,
    partial: list[dict] | None = None,
) -> list[dict]:
    """
    Fetches one or seven days of activity backward from the end boundary.
    Supports user address resolution, target date parsing, full window alignment, and tail cutting.

    ``partial`` collects rows as they arrive so a Ctrl+C mid-window does not
    discard the work already done; the caller can merge them on interrupt.
    """
    if window_days not in (1, 7):
        raise ValueError("window_days must be 1 or 7")

    # Backward compatibility: if caller passed 'now' positionally as first arg
    if isinstance(user_address, datetime.datetime) or (
        isinstance(user_address, str)
        and not re.fullmatch(r'0x[a-fA-F0-9]{40}', user_address)
        and (any(c in user_address for c in ["/", "-", "."]) or user_address.lower() == "now")
    ):
        now = user_address
        user_address = None

    if user_address is None:
        user_address = USER_ADDRESS

    if now is None or isinstance(now, str):
        now = parse_date_input(now)
    elif now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    else:
        now = now.astimezone(UTC)

    now_ts = int(now.timestamp())
    start_ts, end_ts = window_bounds(now, window_days, snap_to_window)

    print(
        f"  Checking {datetime.datetime.fromtimestamp(end_ts, tz=UTC):%Y-%m-%d} back to "
        f"{datetime.datetime.fromtimestamp(start_ts, tz=UTC):%Y-%m-%d} for fills "
        f"({window_days} days requested)",
        flush=True,
    )

    records = []
    cursor = None
    seen_cursors = set()
    day = None
    day_fills = 0
    day_usd = 0.0
    day_windows: set[str] = set()
    current_window = "unknown"
    started = time.monotonic()
    day_started = started
    last_live = 0.0
    interactive = getattr(sys.stdout, "isatty", lambda: False)()

    while True:
        params = {
            "user": user_address,
            "start": start_ts,
            "end": end_ts,
            "limit": PAGE_LIMIT,
        }
        if cursor is not None:
            params["cursor"] = cursor

        response = requests.get(
            BASE_URL,
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()

        if not isinstance(payload, dict):
            raise ValueError("Polymarket activity response must be a JSON object")

        page = payload.get("data")
        pagination = payload.get("pagination")
        if not isinstance(page, list) or not isinstance(pagination, dict):
            raise ValueError(
                "Polymarket activity response must contain data and pagination"
            )
        if "next_cursor" not in pagination:
            raise ValueError(
                "Polymarket activity pagination is missing next_cursor"
            )

        for activity in page:
            if not isinstance(activity, dict):
                raise ValueError("Polymarket activity records must be JSON objects")

            timestamp = activity.get("timestamp")
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                raise ValueError("Polymarket activity timestamp must be numeric")
            if timestamp < start_ts or timestamp > end_ts:
                continue

            iso = datetime.datetime.fromtimestamp(timestamp, tz=UTC).isoformat()
            record_day = iso[:10]
            if record_day != day:
                if day is not None:
                    _finish_day(day, day_fills, day_usd, day_windows, day_started, interactive)
                day = record_day
                day_fills = 0
                day_usd = 0.0
                day_windows = set()
                day_started = time.monotonic()
                if interactive:
                    print("\r" + " " * 110 + "\r", end="", flush=True)
                print(flush=True)
                print(f"  --- {day} " + "-" * max(4, 60 - len(day)), flush=True)

            record = {
                "Timestamp_UTC": iso,
                "Type": activity.get("type"),
                "Market": activity.get("title"),
                "Outcome": activity.get("outcome"),
                "Side": activity.get("side"),
                "Price": activity.get("price"),
                "Shares": activity.get("size"),
                "USD_Amount": activity.get("usdc_size"),
                "Condition_ID": activity.get("condition_id"),
                "Token_ID": activity.get("token_id"),
                "Market_Slug": activity.get("slug"),
                "timestamp": timestamp,
            }
            records.append(record)
            if partial is not None:
                partial.append(record)
            day_fills += 1
            day_usd += _usd(record)
            if record["Market_Slug"]:
                day_windows.add(record["Market_Slug"])
                current_window = _window_label(record["Market_Slug"])

        next_cursor = pagination["next_cursor"]
        # A terminal gets one rewritten line; a log gets one line every 10s.
        now = time.monotonic()
        if day and (interactive or now - last_live >= 10):
            live = (
                f"  {day} | market window {current_window} | "
                f"{day_fills:,} fills so far | ${day_usd:>9,.0f} | "
                f"{_fmt_duration(now - day_started):>7}"
            )
            # Only a terminal needs padding to erase a longer previous line.
            print(
                live.ljust(102) if interactive else live,
                end="\r" if interactive else "\n",
                flush=True,
            )
            last_live = now

        if next_cursor is None:
            break
        if not isinstance(next_cursor, str) or not next_cursor:
            raise ValueError("Polymarket next_cursor must be a non-empty string or null")
        if next_cursor in seen_cursors:
            raise ValueError("Polymarket returned a repeated activity cursor")

        seen_cursors.add(next_cursor)
        cursor = next_cursor
        time.sleep(REQUEST_DELAY_SECONDS)

    if day is not None:
        _finish_day(day, day_fills, day_usd, day_windows, day_started, interactive)
    elif interactive:
        print("\r" + " " * 110 + "\r", end="", flush=True)
    in_range = len(records)

    if cut_tails and records:
        records, _ = cut_tail_markets(
            records,
            start_ts=start_ts,
            end_ts=end_ts,
            user_address=user_address,
            now_ts=now_ts,
            verify_remote=verify_remote,
        )

    # Clean internal helper fields before returning
    for r in records:
        r.pop("timestamp", None)

    if in_range:
        days_count = len({r["Timestamp_UTC"][:10] for r in records})
        usd_total = sum(_usd(r) for r in records)
        print()
        print(
            f"  Fetched {in_range:,} fills on {days_count:,} days | "
            f"${usd_total:>9,.0f} traded | "
            f"{_fmt_duration(time.monotonic() - started):>7}",
            flush=True,
        )
    return records


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


def record_key(record: dict) -> tuple:
    """Identity of a fill across overlapping windows."""
    return tuple(record[field] for field in CSV_FIELDS)


def absorb_window(counts: dict, samples: dict, window: list[dict]) -> int:
    """Adds one window to the running multiset and returns the running total.

    Adjacent windows overlap, so the same fill can arrive twice. Keeping the
    largest count any one window reported removes that overlap without
    collapsing genuinely identical fills inside a window.
    """
    seen: dict[tuple, int] = {}
    for record in window:
        key = record_key(record)
        seen[key] = seen.get(key, 0) + 1
        samples.setdefault(key, record)
    # shortcut: identical fills split across a boundary keep the larger count, not the sum
    for key, n in seen.items():
        if n > counts.get(key, 0):
            counts[key] = n
    return sum(counts.values())


def merge_records(*groups: list[dict]) -> list[dict]:
    """Merges window results, deduping on full CSV identity."""
    counts: dict[tuple, int] = {}
    samples: dict[tuple, dict] = {}
    for group in groups:
        absorb_window(counts, samples, group)
    return [samples[key] for key, n in counts.items() for _ in range(n)]


def save_to_csv(records: list[dict], output_path: str, announce: bool = True):
    """Saves activity records to a CSV file. Written to .tmp then renamed, so a
    kill mid-write never leaves a truncated ledger behind."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    tmp_path = f"{output_path}.tmp"
    with open(tmp_path, "w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    os.replace(tmp_path, output_path)

    if announce:
        print()
        print(f"  Saved {len(records):,} rows -> {output_path}")


def safe_account_name(display_name: str) -> str:
    """Filesystem-safe folder name for an account."""
    return re.sub(r'[^a-zA-Z0-9_\-]', '_', display_name).lower()


def account_dirs(display_name: str) -> str:
    """Create and return ledgers/<account>/ with its raw/, reports/ and analysis/."""
    root = os.path.join(LEDGERS_DIR, safe_account_name(display_name))
    for sub in ACCOUNT_SUBDIRS:
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    return root


def short_account_tag(display_name: str) -> str:
    """Short filename prefix: the account folder already carries the full name."""
    safe = safe_account_name(display_name)
    if safe.startswith("0x"):
        return safe[:3]
    head = safe.split("-", 1)[0]
    return head[:12] if len(head) >= 3 else safe[:3]


def default_output_filename(
    display_name: str,
    target_dt: datetime.datetime,
    window_days: int,
    date_only: bool,
) -> str:
    tag = short_account_tag(display_name)
    target_date = target_dt.date()
    if date_only:
        target_date -= datetime.timedelta(days=1)

    if window_days == 1:
        return f"{tag}_{target_date:%Y-%m-%d}.csv"

    start_date = (
        target_date - datetime.timedelta(days=window_days - 1)
        if date_only
        else (target_dt - datetime.timedelta(days=window_days)).date()
    )
    return f"{tag}_{start_date:%Y-%m-%d}_to_{target_date:%Y-%m-%d}.csv"


def pull_stats(records: list[dict]) -> tuple[int, int]:
    """Distinct market windows and UTC days in a pulled file."""
    days = {record["Timestamp_UTC"][:10] for record in records}
    windows = {
        record.get("Market_Slug") or record.get("Condition_ID")
        for record in records
    }
    windows.discard(None)
    windows.discard("")
    return len(windows), len(days)


def max_output_filename(
    display_name: str,
    records: list[dict],
) -> str:
    """Names the file after what was pulled, not the requested date range."""
    windows, days = pull_stats(records)
    return f"{short_account_tag(display_name)}_{windows}-windows_{days}-days.csv"


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
        help="Custom output path (default: ledgers/<account>/raw/<tag>_<range>.csv)"
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


if __name__ == "__main__":
    main()
