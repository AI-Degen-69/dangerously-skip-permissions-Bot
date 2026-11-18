"""Leaf fill-audit helpers: numeric coercion, print timestamps, epsilon."""

from __future__ import annotations

from typing import Any


# Print prices and limits are both 3-decimal grid values, so a 1e-9 tolerance
# only absorbs float noise - it never lets a worse price through.
PRICE_EPS = 1e-9

def _print_ts(print_row: dict) -> float:
    return _num(print_row.get("ts"))

def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
