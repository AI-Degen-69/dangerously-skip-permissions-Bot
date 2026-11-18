from .records import pull_stats


import argparse
import csv
import datetime
import os
import re
import sys
import time
from collections import defaultdict
import requests
def safe_account_name(display_name: str) -> str:
    """Filesystem-safe folder name for an account."""
    return re.sub(r'[^a-zA-Z0-9_\-]', '_', display_name).lower()
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
def max_output_filename(
    display_name: str,
    records: list[dict],
) -> str:
    """Names the file after what was pulled, not the requested date range."""
    windows, days = pull_stats(records)
    return f"{short_account_tag(display_name)}_{windows}-windows_{days}-days.csv"
