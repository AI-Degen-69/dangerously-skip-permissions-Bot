from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PrintFillResult:
    status: str  # confirmed | partial | unconfirmed | unverified-taker
    filled_shares: float
    covering_size: float


def _norm_side(side: str | None) -> str:
    return str(side or '').upper()


def confirm_maker_buy(
    limit: float,
    clip: float,
    prints: list[dict],
    decision_ts: float | None = None,
) -> PrintFillResult:
    covering = 0.0
    try:
        lim = float(limit)
        want = float(clip)
    except Exception:
        return PrintFillResult(status='unconfirmed', filled_shares=0.0, covering_size=0.0)
    if not (0.0 < lim < 1.0 and want > 0):
        return PrintFillResult(status='unconfirmed', filled_shares=0.0, covering_size=0.0)
    if not prints:
        return PrintFillResult(status='unconfirmed', filled_shares=0.0, covering_size=0.0)
    for p in prints:
        try:
            px = float(p.get('price', 0.0))
            sz = float(p.get('size', 0.0))
        except Exception:
            continue
        if sz <= 0:
            continue
        if decision_ts is not None:
            try:
                if p.get('ts') is not None:
                    pts = float(p['ts'])
                else:
                    raw = p.get('timestamp_raw') or p.get('timestamp')
                    pts = int(str(raw)) / 1000.0
            except (TypeError, ValueError):
                pts = None
            # Unknown or older timestamp: do not count it (conservative).
            if pts is None or pts < float(decision_ts) - 0.001:
                continue
        side = _norm_side(p.get('side'))
        if side not in ('', 'UNKNOWN', 'SELL', 'ASK', 'SELLS'):
            if side in ('BUY', 'BID', 'BUYS'):
                continue
        if px <= lim + 1e-9:
            covering += sz
    if covering >= want - 1e-9:
        return PrintFillResult(status='confirmed', filled_shares=want, covering_size=covering)
    if covering > 0:
        return PrintFillResult(status='partial', filled_shares=covering, covering_size=covering)
    return PrintFillResult(status='unconfirmed', filled_shares=0.0, covering_size=0.0)


def match_maker_print(order: dict, print_row: dict) -> dict | None:
    """Fill a resting bid from one tape print, behind whatever was already there.

    `order` is mutated: the queue at the limit is consumed first, then the
    order's own shares. Returns {"fills", "queueAhead"} for the fill, or None.

    Only an explicit SELL fills a resting buy, and only at or below the limit.
    A print with no side is passed over: after the fill audit, an unexplained
    fill is the one mistake this engine must not repeat.
    """
    if str(order.get("side")) != str(print_row.get("outcome")):
        return None
    if _norm_side(print_row.get("side")) not in ("SELL", "ASK", "SELLS"):
        return None
    try:
        px = float(print_row.get("price") or 0.0)
        size = float(print_row.get("size") or 0.0)
        limit = float(order.get("price") or 0.0)
    except (TypeError, ValueError):
        return None
    if size <= 0 or limit <= 0 or px > limit + 1e-9:
        return None
    ahead = max(0.0, float(order.get("queue_ahead") or 0.0))
    used = min(ahead, size)
    order["queue_ahead"] = ahead - used
    right = min(size - used, max(0.0, float(order.get("shares_left") or 0.0)))
    if right <= 0:
        return None
    order["shares_left"] = float(order.get("shares_left") or 0.0) - right
    # The queue as it stood when this print arrived: stamping the original value
    # would make the audit re-charge a queue this fill already paid.
    return {"fills": right, "queueAhead": ahead}


def label_taker_fill(clip: float) -> PrintFillResult:
    try:
        want = float(clip)
    except Exception:
        want = 0.0
    return PrintFillResult(status='unverified-taker', filled_shares=want, covering_size=0.0)


def bucket_for_price(price: float) -> str:
    try:
        p = float(price)
    except Exception:
        return 'unknown'
    cents = p * 100.0
    if 7 <= cents <= 15:
        return '7-15c'
    if 16 <= cents <= 38:
        return '16-38c'
    if 39 <= cents <= 45:
        return '39-45c'
    return 'other'
