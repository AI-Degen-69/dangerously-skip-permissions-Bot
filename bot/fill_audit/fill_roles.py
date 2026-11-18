"""Fill role classification: who made, who took, and print loading."""

from __future__ import annotations


import json
from pathlib import Path

from .fill_util import _print_ts
from bot.runs import tape_segments


def load_prints(tape_dir: Path) -> list[dict]:
    """Every print recorded for the run, oldest first."""
    prints: list[dict] = []
    for path in tape_segments(tape_dir, "prints"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        prints.append(json.loads(line))
                    except (json.JSONDecodeError, ValueError):
                        continue
        except OSError:
            continue
    prints.sort(key=_print_ts)
    return prints

def role_of(fill: dict) -> str:
    """MAKER or TAKER, with the same precedence the desk uses for fees.

    A recorded role wins, then a recorded fee, then the legacy reason text:
    equalizer and snipe fills were taker fills before roles were stamped.
    """
    detail = fill.get("detail") or {}
    role = str(detail.get("role") or "").upper()
    if role in ("MAKER", "TAKER"):
        return role
    fee = detail.get("feeUsd")
    if isinstance(fee, (int, float)) and not isinstance(fee, bool):
        return "TAKER" if fee > 0 else "MAKER"
    reason = str(fill.get("reason") or "").lower()
    return "TAKER" if ("equalizer" in reason or "snipe" in reason) else "MAKER"
