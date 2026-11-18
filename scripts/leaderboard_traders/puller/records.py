import argparse
import csv
import datetime
import os
import re
import sys
import time
from collections import defaultdict
import requests
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
