"""Streamer quote readers: depth, status, price accessors, lean."""

from __future__ import annotations

import time

from .signal import LeanSignal
from .ws_models import FALLBACK_THRESHOLD_S, STALE_THRESHOLD_S, ConnectionState


class StreamerQuotesMixin:
    """Read-only book/quote accessors over the live books."""

    def depth(self, asset_id: str, levels: int = 5) -> dict:
        with self._lock:
            book = self.books.get(str(asset_id))
            if book is None:
                return {'bids': [], 'asks': []}
            bids = sorted(book.bids.items(), reverse=True)[:max(1, levels)]
            asks = sorted(book.asks.items())[:max(1, levels)]
            return {'bids': [[round(p, 3), s] for p, s in bids], 'asks': [[round(p, 3), s] for p, s in asks]}

    def get_recent_prints(self, limit: int = 100) -> list:
        with self._lock:
            recent = list(self.prints)[-max(1, limit):]
            return [p.to_dict() for p in recent]

    def get_status(self) -> dict:
        """Inspect current connection health and book snapshot."""
        with self._lock:
            now = time.time()
            age = (now - self.last_tick_ts) if self.last_tick_ts > 0 else None
            age_ms = int(age * 1000) if age is not None else None

            is_stale = age is not None and age > STALE_THRESHOLD_S
            is_fallback = age is not None and age > FALLBACK_THRESHOLD_S

            if self.state == ConnectionState.CONNECTED:
                if is_fallback:
                    effective_state = ConnectionState.FALLBACK_ACTIVE
                elif is_stale:
                    effective_state = ConnectionState.STALE
                else:
                    effective_state = ConnectionState.CONNECTED
            elif self.state == ConnectionState.DISCONNECTED and self.rest_fallback_client is not None:
                effective_state = ConnectionState.FALLBACK_ACTIVE
            else:
                effective_state = self.state

            return {
                "state": effective_state.value,
                "is_connected": self.state == ConnectionState.CONNECTED,
                "is_stale": is_stale,
                "age_ms": age_ms,
                "reconnect_count": self.reconnect_count,
                "tick_count": self.tick_count,
                "print_count": self.print_count,
                "up_book": self.books[self.up_token_id].to_dict(),
                "down_book": self.books[self.down_token_id].to_dict(),
            }

    def get_recent_ticks(self, limit: int = 50) -> list[dict]:
        with self._lock:
            recent = list(self.ticks)[-max(1, limit) :]
            return [t.to_dict() for t in recent]

    def get_buy_price(self, token_id: str) -> float | None:
        """Best executable BUY price (best ask) or REST fallback."""
        token_id = str(token_id)
        with self._lock:
            book = self.books.get(token_id)
            now = time.time()
            is_fresh = (
                book is not None
                and (
                    (self.state == ConnectionState.CONNECTED and self.last_tick_ts > 0 and (now - self.last_tick_ts) <= FALLBACK_THRESHOLD_S)
                    or (book.last_update_ts > 0 and (now - book.last_update_ts) <= STALE_THRESHOLD_S)
                )
            )
            if is_fresh and book and book.best_ask is not None:
                if 0.0 < book.best_ask <= 1.0:
                    return book.best_ask

        if self.rest_fallback_client is not None:
            try:
                px = float(self.rest_fallback_client.get_price(token_id=token_id, side="BUY"))
                if 0.0 < px <= 1.0:
                    return px
            except Exception:
                pass

        with self._lock:
            if book and book.best_ask is not None and 0.0 < book.best_ask <= 1.0:
                return book.best_ask
        return None

    def get_sell_price(self, token_id: str) -> float | None:
        """Best executable SELL price (best bid) or REST fallback."""
        token_id = str(token_id)
        with self._lock:
            book = self.books.get(token_id)
            now = time.time()
            is_fresh = (
                book is not None
                and (
                    (self.state == ConnectionState.CONNECTED and self.last_tick_ts > 0 and (now - self.last_tick_ts) <= FALLBACK_THRESHOLD_S)
                    or (book.last_update_ts > 0 and (now - book.last_update_ts) <= STALE_THRESHOLD_S)
                )
            )
            if is_fresh and book and book.best_bid is not None:
                if 0.0 < book.best_bid <= 1.0:
                    return book.best_bid

        if self.rest_fallback_client is not None:
            try:
                px = float(self.rest_fallback_client.get_price(token_id=token_id, side="SELL"))
                if 0.0 < px <= 1.0:
                    return px
            except Exception:
                pass

        with self._lock:
            if book and book.best_bid is not None and 0.0 < book.best_bid <= 1.0:
                return book.best_bid
        return None

    def get_midpoint(self, token_id: str) -> float | None:
        """Midpoint between bid and ask, or REST fallback."""
        token_id = str(token_id)
        with self._lock:
            book = self.books.get(token_id)
            now = time.time()
            is_fresh = (
                book is not None
                and (
                    (self.state == ConnectionState.CONNECTED and self.last_tick_ts > 0 and (now - self.last_tick_ts) <= FALLBACK_THRESHOLD_S)
                    or (book.last_update_ts > 0 and (now - book.last_update_ts) <= STALE_THRESHOLD_S)
                )
            )
            if is_fresh and book and book.midpoint is not None:
                if 0.0 < book.midpoint <= 1.0:
                    return book.midpoint

        if self.rest_fallback_client is not None:
            try:
                mid = float(self.rest_fallback_client.get_midpoint(token_id=token_id))
                if 0.0 < mid <= 1.0:
                    return mid
            except Exception:
                pass

        with self._lock:
            if book and book.midpoint is not None and 0.0 < book.midpoint <= 1.0:
                return book.midpoint
        return None

    def get_lean(self, up_id: str, down_id: str) -> LeanSignal:
        """Derive straddle lean from orderbook midpoints."""
        up_mid = self.get_midpoint(up_id)
        down_mid = self.get_midpoint(down_id)
        if up_mid is None or down_mid is None:
            return LeanSignal(lean=0.0, confidence=0.0, source="book-unavailable")

        edge = (up_mid - down_mid) / 2.0  # >0 favors Up
        raw = edge * 4.0
        lean = max(-1.0, min(1.0, raw))
        spread = abs(up_mid + down_mid - 1.0)
        confidence = max(0.0, min(1.0, 1.0 - spread * 5.0))

        with self._lock:
            now = time.time()
            is_fresh = (
                self.state == ConnectionState.CONNECTED
                and self.last_tick_ts > 0
                and (now - self.last_tick_ts) <= STALE_THRESHOLD_S
            )
        source = "wss-book-microprice" if is_fresh else "rest-fallback-microprice"
        return LeanSignal(lean=lean, confidence=confidence, source=source, raw=round(raw, 3))
