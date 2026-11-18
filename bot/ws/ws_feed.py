"""Streamer connection lifecycle, WS ingest, and REST-fallback polling."""

from __future__ import annotations

import asyncio
import collections
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .ws_models import (
    DEFAULT_BUFFER_SIZE,
    DEFAULT_REST_POLL_INTERVAL_S,
    PING_INTERVAL_S,
    STALE_THRESHOLD_S,
    WS_ENDPOINT,
    ConnectionState,
    StreamTick,
    TokenBook,
)


class StreamerFeedMixin:
    """Connection threads, payload ingest, and snapshot/price-change handling."""

    def __init__(
        self,
        up_token_id: str,
        down_token_id: str,
        rest_fallback_client=None,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
        endpoint: str = WS_ENDPOINT,
        on_tick: Callable[[StreamTick], None] | None = None,
        rest_poll_interval: float = DEFAULT_REST_POLL_INTERVAL_S,
        enable_trade_prints: bool = False,
        tape_dir: str | Path | None = None,
        on_print: Callable[["TradePrint"], None] | None = None,
    ):
        self.up_token_id = str(up_token_id)
        self.down_token_id = str(down_token_id)
        self.rest_fallback_client = rest_fallback_client
        self.endpoint = endpoint
        self.on_tick = on_tick
        self.rest_poll_interval = float(rest_poll_interval)

        self._lock = threading.RLock()
        self._tick_cond = threading.Condition(self._lock)
        self.books: dict[str, TokenBook] = {
            self.up_token_id: TokenBook(asset_id=self.up_token_id, outcome="Up"),
            self.down_token_id: TokenBook(asset_id=self.down_token_id, outcome="Down"),
        }
        self.ticks = collections.deque(maxlen=buffer_size)
        self.state = ConnectionState.DISCONNECTED
        self.last_tick_ts: float = 0.0
        self.reconnect_count: int = 0
        self.tick_count: int = 0
        # --- Trade-print (last_trade_price) observation path (issue #35) ---
        # Quote path (book / price_change / snapshot / rest_poll) is unchanged
        # when enable_trade_prints is False. When True, prints are stored,
        # queryable via depth()/get_recent_prints(), and optionally appended
        # to tape_dir/prints.jsonl + tape_dir/book.jsonl.
        self.enable_trade_prints = bool(enable_trade_prints)
        self.on_print = on_print
        self.tape_dir = Path(tape_dir) if tape_dir is not None else None
        self.prints: collections.deque[TradePrint] = collections.deque(maxlen=buffer_size * 10)
        self.print_count: int = 0
        self.last_print_ts: float = 0.0
        self._last_book_line: dict[str, str] = {}

        self._thread: threading.Thread | None = None
        self._fallback_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    def wait_for_tick(self, timeout: float = 0.25) -> bool:
        """Wait for next tick to arrive or timeout. Returns True if notified, False if timed out."""
        with self._lock:
            return self._tick_cond.wait(timeout=max(0.01, timeout))

    def start(self) -> None:
        """Start the background streamer and fallback poller threads."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="WSS-Streamer")
            self._thread.start()
            if self.rest_fallback_client is not None:
                self._fallback_thread = threading.Thread(
                    target=self._fallback_worker, daemon=True, name="WSS-FallbackPoller"
                )
                self._fallback_thread.start()

    def stop(self) -> None:
        """Stop the background streamer and fallback poller threads cleanly."""
        self._stop_event.set()
        with self._lock:
            self._tick_cond.notify_all()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._fallback_thread and self._fallback_thread.is_alive():
            self._fallback_thread.join(timeout=1.0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        with self._lock:
            self.state = ConnectionState.DISCONNECTED
            self._tick_cond.notify_all()

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._worker())
        except Exception:
            pass
        finally:
            try:
                pending = asyncio.all_tasks(self._loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                self._loop.close()
            except Exception:
                pass

    async def _worker(self) -> None:
        import websockets

        while not self._stop_event.is_set():
            with self._lock:
                self.state = ConnectionState.CONNECTING
            try:
                async with websockets.connect(
                    self.endpoint,
                    ping_interval=PING_INTERVAL_S,
                    ping_timeout=10.0,
                    close_timeout=5.0,
                ) as ws:
                    sub = {
                        "type": "market",
                        "assets_ids": [self.up_token_id, self.down_token_id],
                    }
                    await ws.send(json.dumps(sub))
                    with self._lock:
                        self.state = ConnectionState.CONNECTED

                    async def ping_loop():
                        while not self._stop_event.is_set():
                            await asyncio.sleep(PING_INTERVAL_S)
                            try:
                                await ws.send("PING")
                            except Exception:
                                break

                    ping_task = asyncio.create_task(ping_loop())
                    try:
                        async for message in ws:
                            if self._stop_event.is_set():
                                break
                            if isinstance(message, bytes):
                                message = message.decode("utf-8", errors="replace")
                            if message == "PONG":
                                continue
                            try:
                                data = json.loads(message)
                                self.process_payload(data)
                            except json.JSONDecodeError:
                                continue
                    finally:
                        ping_task.cancel()
            except Exception:
                with self._lock:
                    self.state = ConnectionState.DISCONNECTED
                    self.reconnect_count += 1
                if self._stop_event.is_set():
                    break
                backoff = min(5.0, 0.5 * (2 ** min(self.reconnect_count, 4)))
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    break

    def _fallback_worker(self) -> None:
        """Background poller when WebSocket is disconnected or stale (>3s)."""
        while not self._stop_event.is_set():
            now = time.time()
            needs_fallback = False
            with self._lock:
                is_stale = (self.last_tick_ts > 0 and (now - self.last_tick_ts) > STALE_THRESHOLD_S)
                if self.state != ConnectionState.CONNECTED or is_stale or self.last_tick_ts == 0:
                    needs_fallback = True

            if needs_fallback and self.rest_fallback_client is not None:
                self._poll_rest_fallback()

            self._stop_event.wait(self.rest_poll_interval)

    def _poll_rest_fallback(self) -> None:
        """Active fallback: query rest_fallback_client for fresh prices and emit ticks."""
        if self.rest_fallback_client is None:
            return
        for tok_id, outcome in ((self.up_token_id, "Up"), (self.down_token_id, "Down")):
            if self._stop_event.is_set():
                break
            best_ask = None
            best_bid = None
            midpoint = None
            try:
                px = float(self.rest_fallback_client.get_price(token_id=tok_id, side="BUY"))
                if 0.0 < px <= 1.0:
                    best_ask = px
            except Exception:
                pass
            try:
                px = float(self.rest_fallback_client.get_price(token_id=tok_id, side="SELL"))
                if 0.0 < px <= 1.0:
                    best_bid = px
            except Exception:
                pass
            try:
                mid = float(self.rest_fallback_client.get_midpoint(token_id=tok_id))
                if 0.0 < mid <= 1.0:
                    midpoint = mid
            except Exception:
                pass

            if midpoint is None and best_ask is not None and best_bid is not None:
                midpoint = round((best_bid + best_ask) / 2.0, 5)

            if best_ask is None and best_bid is None and midpoint is None:
                continue

            now = time.time()
            tick = None
            with self._lock:
                book = self.books[tok_id]
                if best_ask is not None:
                    book.best_ask = best_ask
                if best_bid is not None:
                    book.best_bid = best_bid
                if midpoint is not None:
                    book.midpoint = midpoint
                book.last_update_ts = now
                self.last_tick_ts = now
                self.tick_count += 1
                tick = StreamTick(
                    ts=now,
                    time_str=datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3],
                    outcome=outcome,
                    event_type="rest_poll",
                    side=None,
                    price=None,
                    size=None,
                    best_bid=book.best_bid,
                    best_ask=book.best_ask,
                    midpoint=book.midpoint,
                )
                self.ticks.append(tick)
                self._tick_cond.notify_all()

            if tick and self.on_tick:
                try:
                    self.on_tick(tick)
                except Exception:
                    pass

    def process_payload(self, data: Any) -> None:
        """Parse incoming JSON payload from WebSocket."""
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    if item.get("event_type") == "last_trade_price":
                        self._handle_trade_print(item)
                    else:
                        self._handle_snapshot_or_item(item)
        elif isinstance(data, dict):
            if data.get("event_type") == "last_trade_price":
                self._handle_trade_print(data)
            elif "price_changes" in data:
                for change in data.get("price_changes", []):
                    if isinstance(change, dict):
                        if change.get("event_type") == "last_trade_price":
                            self._handle_trade_print(change)
                        else:
                            self._handle_price_change(change)
            elif "bids" in data or "asks" in data or data.get("event_type") == "book":
                self._handle_snapshot_or_item(data)
            elif data.get("event_type") == "price_change":
                self._handle_price_change(data)

    def _handle_snapshot_or_item(self, item: dict) -> None:
        asset_id = str(item.get("asset_id", ""))
        if asset_id not in self.books:
            return
        bids = item.get("bids") or []
        asks = item.get("asks") or []
        with self._lock:
            book = self.books[asset_id]
            now = time.time()
            book.apply_snapshot(bids, asks, ts=now)
            self.last_tick_ts = now
            self.tick_count += 1
            bid_sz = book.bids.get(book.best_bid) if book.best_bid is not None else None
            ask_sz = book.asks.get(book.best_ask) if book.best_ask is not None else None
            tick = StreamTick(
                ts=now,
                time_str=datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3],
                outcome=book.outcome,
                event_type="snapshot",
                side=None,
                price=None,
                size=None,
                best_bid=book.best_bid,
                best_ask=book.best_ask,
                midpoint=book.midpoint,
                bid_size=bid_sz,
                ask_size=ask_sz,
            )
            self.ticks.append(tick)
            self._tick_cond.notify_all()
        if self.on_tick:
            try:
                self.on_tick(tick)
            except Exception:
                pass
        try:
            self._maybe_append_book_tape(asset_id)
        except Exception:
            pass

    def _handle_price_change(self, change: dict) -> None:
        asset_id = str(change.get("asset_id", ""))
        if asset_id not in self.books:
            return
        side = change.get("side", "")
        try:
            price = float(change.get("price", 0.0))
            size = float(change.get("size", 0.0))
        except (ValueError, TypeError):
            return
        best_bid = float(change["best_bid"]) if "best_bid" in change and change["best_bid"] is not None else None
        best_ask = float(change["best_ask"]) if "best_ask" in change and change["best_ask"] is not None else None

        with self._lock:
            book = self.books[asset_id]
            now = time.time()
            book.apply_price_change(
                side=side, price=price, size=size, best_bid=best_bid, best_ask=best_ask, ts=now
            )
            self.last_tick_ts = now
            self.tick_count += 1
            tick = StreamTick(
                ts=now,
                time_str=datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3],
                outcome=book.outcome,
                event_type="price_change",
                side=side,
                price=price,
                size=size,
                best_bid=book.best_bid,
                best_ask=book.best_ask,
                midpoint=book.midpoint,
            )
            self.ticks.append(tick)
            self._tick_cond.notify_all()
        if self.on_tick:
            try:
                self.on_tick(tick)
            except Exception:
                pass
        try:
            self._maybe_append_book_tape(asset_id)
        except Exception:
            pass
