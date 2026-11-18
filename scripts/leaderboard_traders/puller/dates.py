import argparse
import csv
import datetime
import os
import re
import sys
import time
from collections import defaultdict
import requests
UTC = datetime.timezone.utc
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
