from .dates import UTC, clean_user_input, parse_date_input
from .records import absorb_window, merge_records
from .windows import _finish_day, _fmt_duration, _usd, window_bounds


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
PAGE_LIMIT = 100
REQUEST_DELAY_SECONDS = 0.2
REQUEST_TIMEOUT_SECONDS = 30
USER_ADDRESS = "0xc53375ff94e96100f2b30a4b5775db35218d69a9"
WINDOW_PATTERN = re.compile(r'-(?:(\d+)m|(\d+)h)-(\d+)$')
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
