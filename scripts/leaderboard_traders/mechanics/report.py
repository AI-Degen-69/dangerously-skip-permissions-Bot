from .measures import med, pnl_range, rate


__all__ = [
    "HDR", "SECTION_WIDTH", "Tee", "_Indent", "_section",
    "line", "md_table", "show", "show_group",
]


import csv
import io
import os
import pathlib
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
SECTION_WIDTH = 74
HDR = ("bucket", "n", "known", "net>0 [95% CI]", "$pnl", "medBps", "bps", "netMed", "netBps")
class _Indent:
    """Prefix every printed line with two spaces.

    The puller indents its status blocks; doing it at the stream keeps each
    analysis table's own column alignment exactly as written.
    """

    def __init__(self, stream):
        self.stream = stream
        self.start = True

    def write(self, data):
        for ch in data:
            if self.start and ch != "\n":
                self.stream.write("  ")
            self.stream.write(ch)
            self.start = ch == "\n"
        return len(data)

    def flush(self):
        self.stream.flush()
def _section(title):
    """A rule then a Markdown heading, so the terminal and saved report agree."""
    print()
    print("=" * SECTION_WIDTH)
    print(f"\n## {title}\n")
class Tee:
    """Duplicates stdout into the in-memory report."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
        return len(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()
def md_table(headers, rows):
    """A Markdown table from preformatted cell strings; blank line separates blocks."""
    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join("---" for _ in headers) + "|")
    for row in rows:
        print("| " + " | ".join(row) + " |")
def show(label, sel):
    """One Markdown row of first-leg statistics, or None for an empty bucket."""
    if not sel:
        return None
    known = [r for r in sel if r["known"]]
    kcost = sum(r["cost"] for r in known)
    bps = [r["gross_low"] / r["cost"] * 1e4 for r in known if r["cost"] > 0]
    net = [r["net_low"] / r["cost"] * 1e4 for r in known if r["cost"] > 0]
    won = sum(1 for r in known if r["net_low"] > 0)
    gross_bps = sum(r["gross_low"] for r in known) / kcost * 1e4 if kcost else float("nan")
    net_bps = sum(r["net_low"] for r in known) / kcost * 1e4 if kcost else float("nan")
    return (label, f"{len(sel)}", f"{len(known)}", rate(won, len(known)),
            pnl_range(sum(r["net_low"] for r in sel), sum(r["net_high"] for r in sel)),
            f"{med(bps):.0f}", f"{gross_bps:.0f}", f"{med(net):.0f}", f"{net_bps:.0f}")
def show_group(groups):
    """Print the buckets that have data as one Markdown table."""
    md_table(HDR, [row for row in (show(label, sel) for label, sel in groups) if row])
def line(label, xs):
    """One Markdown row of a distribution, or a no-data row."""
    if not xs:
        return (label, "0", "-", "-", "-", "-", "-", "-", "-")
    xs = sorted(xs)
    q = lambda x: xs[min(len(xs) - 1, int(x * len(xs)))]
    return (label, str(len(xs)), f"{xs[0]:.2f}", f"{q(.10):.2f}", f"{q(.25):.2f}",
            f"{q(.5):.2f}", f"{q(.75):.2f}", f"{q(.90):.2f}", f"{xs[-1]:.2f}")
