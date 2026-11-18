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

    Direct match: explicit SELL on the same outcome at or below the limit.
    Complementary binary match: explicit BUY on the opposite outcome at
    opposite_price >= (1.0 - limit) - 1e-9 (e.g., BUY Down @ 0.32 or 0.36
    matches against a resting BUY Up @ 0.68 on Polymarket's binary CLOB,
    because binary crossing requires p_up + p_down >= 1.0).
    """
    order_side = str(order.get("side") or "")
    print_outcome = str(print_row.get("outcome") or "")
    print_side = _norm_side(print_row.get("side"))
    try:
        px = float(print_row.get("price") or 0.0)
        size = float(print_row.get("size") or 0.0)
        limit = float(order.get("price") or 0.0)
    except (TypeError, ValueError):
        return None
    if size <= 0 or not (0.0 < limit < 1.0) or not (0.0 < px < 1.0):
        return None

    is_direct = (order_side == print_outcome)
    is_complementary = (order_side, print_outcome) in (("Up", "Down"), ("Down", "Up"))
    if is_direct:
        if print_side not in ("SELL", "ASK", "SELLS"):
            return None
        if px > limit + 1e-9:
            return None
    elif is_complementary:
        if print_side not in ("BUY", "BID", "BUYS"):
            return None
        if px < (1.0 - limit) - 1e-9:
            return None
    else:
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


def match_maker_book_cross(order: dict, quote: dict | None) -> dict | None:
    """Fill a resting bid when the live CLOB quote crosses or clears its price level.

    If best_ask <= limit or best_bid < limit, the market has moved through or
    cleared the resting bid's price level.
    """
    if not quote or not isinstance(quote, dict):
        return None
    try:
        limit = float(order.get("price") or 0.0)
        shares_left = float(order.get("shares_left") or 0.0)
    except (TypeError, ValueError):
        return None
    if not (0.0 < limit < 1.0) or shares_left <= 0.0:
        return None

    def _valid_px(val: object) -> float | None:
        try:
            f = float(val)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return f if 0.0 < f < 1.0 else None

    bid = _valid_px(quote.get("bid"))
    ask = _valid_px(quote.get("ask"))

    ask_crossed = (ask is not None and ask <= limit + 1e-9)
    bid_cleared = (bid is not None and bid < limit - 1e-9)
    if not (ask_crossed or bid_cleared):
        order.pop("_last_touch_ask_obs", None)
        return None

    ahead = max(0.0, float(order.get("queue_ahead") or 0.0))
    strictly_cleared = bid_cleared or (ask is not None and ask < limit - 1e-9)
    if strictly_cleared:
        order.pop("_last_touch_ask_obs", None)
        order["queue_ahead"] = 0.0
        order["shares_left"] = 0.0
        return {"fills": shares_left, "queueAhead": ahead}

    # ask touches limit (abs(ask - limit) <= 1e-9 and not bid_cleared)
    raw_ask_sz = quote.get("ask_size") if quote.get("ask_size") is not None else quote.get("askSize")
    try:
        ask_size = float(raw_ask_sz) if raw_ask_sz is not None else None
    except (TypeError, ValueError):
        ask_size = None

    if ask_size is not None and ask_size > 0.0:
        raw_ts = quote.get("ts") if quote.get("ts") is not None else quote.get("timestamp")
        obs_key = (
            round(float(ask), 6),
            round(float(ask_size), 6),
            str(raw_ts) if raw_ts is not None else None,
        )
        if order.get("_last_touch_ask_obs") == obs_key:
            return None
        order["_last_touch_ask_obs"] = obs_key
        used = min(ahead, ask_size)
        order["queue_ahead"] = ahead - used
        filled = min(ask_size - used, shares_left)
        if filled <= 0.0:
            return None
        order["shares_left"] = shares_left - filled
        return {"fills": filled, "queueAhead": ahead}

    order.pop("_last_touch_ask_obs", None)
    order["queue_ahead"] = 0.0
    order["shares_left"] = 0.0
    return {"fills": shares_left, "queueAhead": ahead}


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
