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
DEFAULT_USERNAME = "dangerously-skip-permissions"
USER_ADDRESS = "0xc53375ff94e96100f2b30a4b5775db35218d69a9"
OUTPUT_CSV = "dangerously-skip-permissions_24h_trades.csv"
PAGE_LIMIT = 100
REQUEST_DELAY_SECONDS = 0.2
REQUEST_TIMEOUT_SECONDS = 30
WINDOW_SIZE_SECONDS = 300  # 5 minutes
UTC = datetime.timezone.utc

CSV_FIELDS = [
    "Proxy_Wallet",
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
    "Transaction_Hash",
    "Market_Slug",
    "Event_Slug",
]

WINDOW_PATTERN = re.compile(r'-(?:(\d+)m|(\d+)h)-(\d+)$')


def parse_date_input(
    date_str: str | datetime.datetime | None = None,
    now: datetime.datetime | None = None,
) -> datetime.datetime:
    """
    Parses a date input into an end_dt (timezone-aware UTC) representing
    the ceiling from which to fetch 24 hours backward.

    Rules:
    - If None, empty, or 'now': returns now in UTC.
    - If date-only (e.g. '06/11', '06/11/2026', '2026-11-06'):
      Starts from the end of that day (day + 1 at 00:00:00 UTC) to capture
      the whole 24 hours of that date backward to day 00:00:00 UTC.
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
        key = r.get("Event_Slug") or r.get("Market_Slug") or r.get("Condition_ID") or r.get("Market")
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
        slug = sample.get("Event_Slug") or sample.get("Market_Slug") or key
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
        slug = sample.get("Event_Slug") or sample.get("Market_Slug") or key
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
        key = r.get("Event_Slug") or r.get("Market_Slug") or r.get("Condition_ID") or r.get("Market")
        if key in markets_to_remove:
            removed_records.append(r)
        else:
            cleaned_records.append(r)

    if removal_reasons:
        print(f"Tail cut: filtered out {len(removal_reasons)} incomplete/partial markets ({len(removed_records)} trades removed):")
        for k, reason in removal_reasons.items():
            print(f"  - [{k}]: {reason}")
    else:
        print("Tail check: all markets in range are fully completed and pulled.")

    return cleaned_records, removed_records


def fetch_24h_activity(
    user_address: str | None = None,
    now: datetime.datetime | str | None = None,
    snap_to_window: bool = True,
    cut_tails: bool = True,
    verify_remote: bool = False,
):
    """
    Fetches 24-hour activity from Polymarket Data API v2 backward from the end boundary.
    Supports user address resolution, target date parsing, full window alignment, and tail cutting.
    """
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
    if snap_to_window:
        end_ts = (now_ts // WINDOW_SIZE_SECONDS) * WINDOW_SIZE_SECONDS
    else:
        end_ts = now_ts
    start_ts = end_ts - 24 * 60 * 60

    print(
        f"Fetching activity for {user_address} backward from "
        f"{datetime.datetime.fromtimestamp(end_ts, tz=UTC).isoformat()} "
        f"to {datetime.datetime.fromtimestamp(start_ts, tz=UTC).isoformat()} (24-hour window)..."
    )

    records = []
    cursor = None
    seen_cursors = set()

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

            records.append(
                {
                    "Proxy_Wallet": activity.get("proxy_wallet"),
                    "Timestamp_UTC": datetime.datetime.fromtimestamp(
                        timestamp, tz=UTC
                    ).isoformat(),
                    "Type": activity.get("type"),
                    "Market": activity.get("title"),
                    "Outcome": activity.get("outcome"),
                    "Side": activity.get("side"),
                    "Price": activity.get("price"),
                    "Shares": activity.get("size"),
                    "USD_Amount": activity.get("usdc_size"),
                    "Condition_ID": activity.get("condition_id"),
                    "Token_ID": activity.get("token_id"),
                    "Transaction_Hash": activity.get("transaction_hash"),
                    "Market_Slug": activity.get("slug"),
                    "Event_Slug": activity.get("event_slug"),
                    "timestamp": timestamp,
                }
            )

        next_cursor = pagination["next_cursor"]
        if next_cursor is None:
            break
        if not isinstance(next_cursor, str) or not next_cursor:
            raise ValueError("Polymarket next_cursor must be a non-empty string or null")
        if next_cursor in seen_cursors:
            raise ValueError("Polymarket returned a repeated activity cursor")

        seen_cursors.add(next_cursor)
        cursor = next_cursor
        time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Retrieved {len(records)} raw activity records.")

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

    print(f"Final activity record count: {len(records)}.")
    return records


def save_to_csv(records: list[dict], output_path: str | None = None):
    """Saves activity records to a CSV file."""
    if output_path is None:
        output_path = OUTPUT_CSV

    with open(output_path, "w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    print(f"Successfully saved {len(records)} activity records to '{output_path}'.")


def main():
    parser = argparse.ArgumentParser(description="Save 24-hour Polymarket trade activity to CSV.")
    parser.add_argument(
        "-u", "--user",
        help="Polymarket username, @handle, profile URL, or wallet address (e.g. 'Tokor' or '0xa19cb...')"
    )
    parser.add_argument(
        "-d", "--date", "--start-date",
        dest="date",
        help="Target date to fetch 24 hours backward from (e.g. '06/11' -> whole day of Nov 6, 'YYYY-MM-DD', or 'now'). Default: now"
    )
    parser.add_argument(
        "-o", "--output",
        help="Custom output CSV filename"
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
            prompt_date = input("Enter target date (DD/MM, DD/MM/YYYY, or 'now') [now]: ").strip()
            date_input = prompt_date if prompt_date else "now"
        except (EOFError, KeyboardInterrupt):
            date_input = "now"
            print()
    elif not date_input:
        date_input = "now"

    print(f"Resolving '{user_input}'...")
    try:
        resolved_address, display_name = resolve_user_address(user_input)
    except Exception as exc:
        print(f"Error resolving user: {exc}")
        sys.exit(1)

    print(f"Target account: {display_name} -> {resolved_address}")

    try:
        target_dt = parse_date_input(date_input)
    except Exception as exc:
        print(f"Error parsing date '{date_input}': {exc}")
        sys.exit(1)

    # Determine default CSV output name
    if args.output:
        output_file = args.output
    else:
        safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', display_name).lower()
        if date_input and date_input.strip().lower() != "now":
            date_label = (target_dt - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
            output_file = f"{safe_name}_{date_label}_24h_trades.csv"
        else:
            output_file = f"{safe_name}_24h_trades.csv"

    activity = fetch_24h_activity(
        user_address=resolved_address,
        now=target_dt,
        snap_to_window=not args.no_snap,
        cut_tails=not args.no_cut_tails,
        verify_remote=args.verify_remote,
    )

    if not activity:
        print("No account activity found within the 24-hour window.")
    save_to_csv(activity, output_path=output_file)


if __name__ == "__main__":
    main()
