"""What the paper desk's maker fills could actually have got.

A maker fill is booked at the bid the moment the loop reads the book, so the
paper number assumes every resting order at the touch was first in line. A real
bid there sits behind whatever is already resting at that price, and only a
taker SELL can fill it. So a fill is attainable when taker SELL prints at or
below its limit, after it was booked, carry more size than the queue ahead of
it.

Prints record the taker side: a resting BUY is filled by a SELL print, never by
a BUY print. Getting that backwards inverts the whole result.

Where the queue is unknown (windows from before ``detail.queueAhead`` was
recorded) the fill is judged on sell size alone, which is an upper bound. No
prints at all in the window means the window cannot be judged: ``audit_window``
returns None rather than declaring every fill phantom.
"""

from __future__ import annotations

import bisect
import json
from pathlib import Path
from typing import Any

from bot import constants as C
from bot.runs import tape_segments
from bot.tape_verifier import fill_epoch_s


# Print prices and limits are both 3-decimal grid values, so a 1e-9 tolerance
# only absorbs float noise - it never lets a worse price through.
PRICE_EPS = 1e-9


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


def audit_window(
    fills: list[dict],
    prints: list[dict],
    window_start_s: float,
    winner: str | None,
) -> dict[str, Any] | None:
    """Compare one closed window's fills with what the tape could have filled.

    Returns None when the tape holds no print inside the window: silence is
    missing evidence, not proof that nothing traded.
    """
    start = float(window_start_s)
    end = start + C.WINDOW_S
    lo = bisect.bisect_left(prints, start, key=_print_ts)
    hi = bisect.bisect_right(prints, end, key=_print_ts)
    tape = prints[lo:hi]
    if not tape:
        return None

    maker = attainable = phantom = queue_known = 0
    assumed_shares = attainable_shares = 0.0
    attainable_cost = attainable_payout = 0.0

    for fill in fills:
        shares = _num(fill.get("shares"))
        usd = _num(fill.get("usd"))
        payout = shares if winner and fill.get("outcome") == winner else 0.0
        assumed_shares += shares
        if role_of(fill) == "TAKER":
            # A taker fill takes the ask by definition, so the queue cannot
            # block it; only the maker fills can be phantom.
            attainable_shares += shares
            attainable_cost += usd
            attainable_payout += payout
            continue

        maker += 1
        ahead = (fill.get("detail") or {}).get("queueAhead")
        if isinstance(ahead, (int, float)) and not isinstance(ahead, bool) and ahead >= 0:
            queue_known += 1
            ahead = float(ahead)
        else:
            ahead = 0.0
        sells = _sells_after(tape, fill, _num(fill.get("price")))
        if shares > 0 and sells - ahead >= shares - PRICE_EPS:
            attainable += 1
            attainable_shares += shares
            attainable_cost += usd
            attainable_payout += payout
        else:
            phantom += 1

    return {
        "makerFills": maker,
        "attainableFills": attainable,
        "phantomFills": phantom,
        "queueKnown": queue_known,
        "assumedShares": round(assumed_shares, 2),
        "attainableShares": round(attainable_shares, 2),
        "attainableCostUsd": round(attainable_cost, 2),
        "attainablePayoutUsd": round(attainable_payout, 2),
        "attainableNetUsd": round(attainable_payout - attainable_cost, 2),
    }


def _print_ts(print_row: dict) -> float:
    return _num(print_row.get("ts"))


def _sells_after(tape: list[dict], fill: dict, price: float) -> float:
    """Taker SELL size printed at or below `price` from the fill onwards."""
    outcome = fill.get("outcome")
    first = bisect.bisect_left(tape, fill_epoch_s(fill), key=_print_ts)
    total = 0.0
    for print_row in tape[first:]:
        if print_row.get("slug_outcome") != outcome:
            continue
        if str(print_row.get("side") or "").upper() != "SELL":
            continue
        if _num(print_row.get("price")) > price + PRICE_EPS:
            continue
        total += _num(print_row.get("size"))
    return total


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
