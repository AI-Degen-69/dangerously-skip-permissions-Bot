"""Tape verification engine — checks assumed paper fills against real trade prints.

For each MAKER fill at limit price L with clip size C:
  1. Collect prints for the same outcome token with ts >= fill_ts and price <= L
  2. Sum their sizes
  3. If cumulative size >= C → verified
     If cumulative size > 0 but < C → partial
     If no prints → unverified

TAKER fills are always stamped 'unverified-taker' — in paper mode our
hypothetical crossing order never enters the real book.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bot.runs import tape_segments


GRACE_PERIOD_S = 5.0  # fills younger than this stay "pending"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fill_epoch_s(fill: dict) -> float:
    """Extract fill timestamp as epoch seconds."""
    ts = fill.get("ts", 0)
    if isinstance(ts, (int, float)):
        return ts / 1000.0 if ts > 1e12 else float(ts)
    return 0.0


def load_prints_for_window(tape_dir: Path, window_start_s: float, window_end_s: float) -> list[dict]:
    """Load prints that fall within [window_start_s, window_end_s].

    Walks every tape segment oldest-first (the recorder rotates prints.jsonl by
    size), skipping records before the window and stopping once the segments run
    past it — records are append-ordered, so nothing later can qualify.
    """
    result: list[dict] = []
    for prints_path in tape_segments(tape_dir, "prints"):
        try:
            with open(prints_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    ts = rec.get("ts", 0)
                    if ts < window_start_s:
                        continue
                    if ts > window_end_s:
                        return result
                    result.append(rec)
        except OSError:
            continue
    return result


def verify_single_fill(
    fill: dict,
    prints: list[dict],
    now_s: float | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Verify one fill against a list of prints for the same window.

    Returns a dict of detail fields to merge into fill['detail']:
      tapeStatus, tapePrintSize, tapePrintCount, tapeCheckedAt

    If force=True, the grace period is bypassed so a recent fill that is never
    revisited (the window-close final pass) still gets a definitive status.
    """
    if now_s is None:
        now_s = time.time()

    fill_ts_s = _fill_epoch_s(fill)
    detail = fill.get("detail") or {}
    role = str(detail.get("role", "")).upper()
    outcome = fill.get("outcome")
    price = fill.get("price")
    shares = fill.get("shares", 0)

    # TAKER fills cannot be self-verified in paper mode
    if role == "TAKER":
        return {
            "tapeStatus": "unverified-taker",
            "tapePrintSize": 0,
            "tapePrintCount": 0,
            "tapeCheckedAt": _utc_now_iso(),
        }

    # Grace period: too recent to verify (bypassed by the forced final pass)
    if not force and now_s - fill_ts_s < GRACE_PERIOD_S:
        return {
            "tapeStatus": "pending",
            "tapePrintSize": 0,
            "tapePrintCount": 0,
            "tapeCheckedAt": _utc_now_iso(),
        }

    if price is None or outcome is None:
        return {
            "tapeStatus": "unverified",
            "tapePrintSize": 0,
            "tapePrintCount": 0,
            "tapeCheckedAt": _utc_now_iso(),
        }

    # Filter prints: same outcome, ts >= fill ts, price <= fill price (price priority)
    confirming = [
        p for p in prints
        if p.get("slug_outcome") == outcome
        and p.get("ts", 0) >= fill_ts_s
        and p.get("price", 999) <= price
    ]

    cumm_size = sum(p.get("size", 0) for p in confirming)

    if cumm_size >= shares:
        status = "verified"
    elif cumm_size > 0:
        status = "partial"
    else:
        status = "unverified"

    return {
        "tapeStatus": status,
        "tapePrintSize": round(cumm_size, 2),
        "tapePrintCount": len(confirming),
        "tapeCheckedAt": _utc_now_iso(),
    }


def verify_fills(
    fills: list[dict],
    tape_dir: Path | None,
    window_start_s: float = 0,
    window_end_s: float = 0,
    force: bool = False,
) -> int:
    """Verify all fills in the list against tape prints.

    Mutates fill['detail'] in-place with tapeStatus fields.
    Returns the number of fills whose status changed.

    If force=True, re-verifies all fills regardless of current status.
    Otherwise skips already-verified fills.
    """
    if tape_dir is None or not fills:
        return 0

    # Determine window bounds from fills if not provided
    if window_start_s <= 0:
        fill_times = [_fill_epoch_s(f) for f in fills]
        window_start_s = min(fill_times) - 10  # small lookback
    if window_end_s <= 0:
        window_end_s = time.time() + 60  # future buffer for live windows

    prints = load_prints_for_window(tape_dir, window_start_s, window_end_s)
    now_s = time.time()
    changed = 0

    for fill in fills:
        detail = fill.setdefault("detail", {})
        current = detail.get("tapeStatus")

        # Skip already-verified unless forcing
        if not force and current == "verified":
            continue
        # Skip taker fills unless forcing
        if not force and current == "unverified-taker":
            continue

        result = verify_single_fill(fill, prints, now_s=now_s, force=force)

        # Check if status actually changed
        if result["tapeStatus"] != current:
            changed += 1

        detail.update(result)

    return changed


def verification_summary(fills: list[dict]) -> dict[str, Any]:
    """Aggregate verification stats across a list of fills."""
    counts: dict[str, int] = {
        "verified": 0,
        "partial": 0,
        "unverified": 0,
        "unverifiedTaker": 0,
        "pending": 0,
        "unknown": 0,
    }
    for fill in fills:
        detail = fill.get("detail") or {}
        status = detail.get("tapeStatus", "unknown")
        if status == "verified":
            counts["verified"] += 1
        elif status == "partial":
            counts["partial"] += 1
        elif status == "unverified":
            counts["unverified"] += 1
        elif status == "unverified-taker":
            counts["unverifiedTaker"] += 1
        elif status == "pending":
            counts["pending"] += 1
        else:
            counts["unknown"] += 1

    total = sum(counts.values())
    checkable = counts["verified"] + counts["partial"] + counts["unverified"]
    return {
        **counts,
        "total": total,
        "verifiedPct": round(counts["verified"] / checkable * 100, 1) if checkable > 0 else 0.0,
    }
