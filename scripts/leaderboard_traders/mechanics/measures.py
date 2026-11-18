import csv
import io
import os
import pathlib
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
__all__ = [
    "MIN_RATE_N", "SLUG_RE", "bucket", "held", "market_clock",
    "med", "money", "pnl_range", "rate", "secs", "wilson",
]


SLUG_RE = re.compile(r"-(\d+)([mh])-(\d+)$")
MIN_RATE_N = 5           # below this a rate is printed as n=x, not a percentage
def secs(iso):
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp()
def med(v):
    return st.median(v) if v else float("nan")
def bucket(p):
    for hi, name in ((0.25, "<=0.25"), (0.45, "0.25-0.45"), (0.55, "0.45-0.55"),
                     (0.75, "0.55-0.75"), (1.01, ">0.75")):
        if p <= hi:
            return name
    return ">0.75"
def market_clock(slug):
    """(open epoch, duration seconds) from a slug like ...-5m-1794000000."""
    match = SLUG_RE.search(slug)
    if not match:
        return None, None
    size, unit, epoch = match.groups()
    return int(epoch), int(size) * (3600 if unit == "h" else 60)
def wilson(k, n):
    """95% Wilson score interval for a proportion, so small samples show it."""
    if n == 0:
        return float("nan"), float("nan")
    z = 1.96
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / denom
    return max(0.0, centre - half), min(1.0, centre + half)
def rate(k, n):
    """Percentage with its Wilson 95% CI, or the sample size when it is too small."""
    if n == 0:
        return "n/a"
    if n < MIN_RATE_N:
        return "n=%d" % n
    lo, hi = wilson(k, n)
    return "%5.1f%% [%2.0f-%2.0f]" % (100.0 * k / n, 100 * lo, 100 * hi)
def pnl_range(low, high):
    return "%.0f" % low if abs(high - low) < 0.5 else "%.0f..%.0f" % (low, high)
def money(d):
    """(cash in, cash out, fees) for one market."""
    cash_in = d["sell_usd"][0] + d["sell_usd"][1] + d["red_usd"][0] + d["red_usd"][1] + d["merge_usd"]
    return cash_in, d["buy_usd"][0] + d["buy_usd"][1], d["fee"]
def held(d):
    """Shares still held per side after sells, redeems and merges."""
    return [d["buy_sh"][i] - d["sell_sh"][i] - d["red_sh"][i] - d["merge_sh"] for i in (0, 1)]
