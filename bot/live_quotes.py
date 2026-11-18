"""Pure live quote helpers — no `bot.live_paper` imports.

The shell (`bot/live_paper.py`) owns config/workspace seams and delegates here
with explicit args so these builders stay deterministic and patch-safe.
"""

from bot.signal import LeanSignal


def microprice_lean_pure(c, up_id: str, down_id: str, streamer=None, lean_source: str = "microprice") -> LeanSignal:
    """Lean probe with explicit `lean_source` (shell reads cfg)."""
    if lean_source == "dumb":
        return LeanSignal(lean=0.0, confidence=0.0, source="dumb")
    if streamer is not None:
        try:
            return streamer.get_lean(up_id, down_id)
        except Exception:
            pass
    try:
        up_mid = float(c.get_midpoint(token_id=up_id))
        down_mid = float(c.get_midpoint(token_id=down_id))
    except Exception:
        return LeanSignal(lean=0.0, confidence=0.0, source="book-unavailable")
    edge = (up_mid - down_mid) / 2.0
    raw = edge * 4.0
    lean = max(-1.0, min(1.0, raw))
    spread = abs(up_mid + down_mid - 1.0)
    confidence = max(0.0, min(1.0, 1.0 - spread * 5.0))
    return LeanSignal(lean=lean, confidence=confidence, source="book-microprice", raw=round(raw, 3))


def live_buy_price_pure(c, token_id: str, streamer=None) -> float | None:
    """Best executable BUY price, or None when the book has no usable ask."""
    if streamer is not None:
        try:
            px = streamer.get_buy_price(token_id)
            if px is not None and 0.0 < px <= 1.0:
                return px
        except Exception:
            pass
    try:
        px = float(c.get_price(token_id=token_id, side="BUY"))
    except Exception:
        return None
    if not 0.0 < px <= 1.0:
        return None
    return px


def live_bid_price_pure(c, token_id: str, streamer=None) -> float | None:
    """Best resting bid price from WS memory."""
    if streamer is not None:
        try:
            with streamer._lock:
                book = streamer.books.get(str(token_id))
                if book and book.best_bid is not None and 0.0 < book.best_bid < 1.0:
                    return book.best_bid
        except Exception:
            pass
    return None


def live_queue_ahead_pure(streamer, token_id: str, price: float) -> float | None:
    """Shares already resting at `price`. None when level data is missing."""
    if streamer is None:
        return None
    try:
        with streamer._lock:
            book = streamer.books.get(str(token_id))
            if book is None:
                return None
            return float(book.bids.get(price, 0.0))
    except Exception:
        return None


def live_quote_pair_pure(c, up_id: str, down_id: str, streamer=None) -> dict:
    """Fetch {Up: {bid, ask}, Down: {bid, ask}} without extra REST calls."""
    up_ask = live_buy_price_pure(c, up_id, streamer=streamer)
    down_ask = live_buy_price_pure(c, down_id, streamer=streamer)
    up_bid = live_bid_price_pure(c, up_id, streamer=streamer)
    down_bid = live_bid_price_pure(c, down_id, streamer=streamer)
    return {
        "Up": {"bid": up_bid if up_bid is not None else up_ask, "ask": up_ask},
        "Down": {"bid": down_bid if down_bid is not None else down_ask, "ask": down_ask},
    }
