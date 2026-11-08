"""Real-time Polymarket CLOB WebSocket Orderbook Streamer & Health Monitor.

Subscribes to live orderbook feeds via Polymarket's public CLOB WebSocket:
  wss://ws-subscriptions-clob.polymarket.com/ws/market

Maintains an in-memory, thread-safe orderbook for Up & Down outcome tokens,
tracks microsecond ticks, monitors connection health, and falls back to
PublicClient REST transparently when disconnected or stale.
"""

import argparse
import asyncio
import collections
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.signal import LeanSignal

WS_ENDPOINT = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
STALE_THRESHOLD_S = 3.0
FALLBACK_THRESHOLD_S = 10.0
PING_INTERVAL_S = 15.0
DEFAULT_BUFFER_SIZE = 100
DEFAULT_REST_POLL_INTERVAL_S = 1.0


class ConnectionState(str, Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    STALE = "stale"
    DISCONNECTED = "disconnected"
    FALLBACK_ACTIVE = "fallback_active"


@dataclass
class TokenBook:
    asset_id: str
    outcome: str  # "Up" | "Down"
    bids: dict[float, float] = field(default_factory=dict)  # price -> size
    asks: dict[float, float] = field(default_factory=dict)  # price -> size
    best_bid: float | None = None
    best_ask: float | None = None
    midpoint: float | None = None
    last_update_ts: float = 0.0

    def _recalculate(self) -> None:
        self.best_bid = max(self.bids.keys()) if self.bids else None
        self.best_ask = min(self.asks.keys()) if self.asks else None
        if self.best_bid is not None and self.best_ask is not None:
            self.midpoint = round((self.best_bid + self.best_ask) / 2.0, 5)
        elif self.best_bid is not None:
            self.midpoint = self.best_bid
        elif self.best_ask is not None:
            self.midpoint = self.best_ask
        else:
            self.midpoint = None

    def apply_snapshot(self, bids: list[dict], asks: list[dict], ts: float | None = None) -> None:
        self.bids.clear()
        for b in bids:
            try:
                p = float(b.get("price", 0.0))
                s = float(b.get("size", 0.0))
                if s > 0:
                    self.bids[p] = s
            except (KeyError, ValueError, TypeError):
                continue
        self.asks.clear()
        for a in asks:
            try:
                p = float(a.get("price", 0.0))
                s = float(a.get("size", 0.0))
                if s > 0:
                    self.asks[p] = s
            except (KeyError, ValueError, TypeError):
                continue
        self.last_update_ts = ts if ts is not None else time.time()
        self._recalculate()

    def apply_price_change(
        self,
        side: str,
        price: float,
        size: float,
        best_bid: float | None = None,
        best_ask: float | None = None,
        ts: float | None = None,
    ) -> None:
        try:
            p = float(price)
            s = float(size)
        except (ValueError, TypeError):
            return

        side_upper = str(side).upper()
        target_dict = self.bids if side_upper in ("BUY", "BID", "BIDS") else self.asks
        if s <= 0.0:
            target_dict.pop(p, None)
        else:
            target_dict[p] = s

        self.last_update_ts = ts if ts is not None else time.time()
        self._recalculate()

        if best_bid is not None and self.best_bid is None:
            self.best_bid = float(best_bid)
        if best_ask is not None and self.best_ask is None:
            self.best_ask = float(best_ask)
        if self.midpoint is None and self.best_bid is not None and self.best_ask is not None:
            self.midpoint = round((self.best_bid + self.best_ask) / 2.0, 5)

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "outcome": self.outcome,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "midpoint": self.midpoint,
            "bid_depth": len(self.bids),
            "ask_depth": len(self.asks),
            "last_update_ts": self.last_update_ts,
        }


@dataclass
class StreamTick:
    ts: float  # epoch seconds
    time_str: str  # HH:MM:SS.mmm
    outcome: str  # "Up" | "Down"
    event_type: str  # "snapshot" | "price_change"
    side: str | None
    price: float | None
    size: float | None
    best_bid: float | None
    best_ask: float | None
    midpoint: float | None
    bid_size: float | None = None
    ask_size: float | None = None

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "time_str": self.time_str,
            "outcome": self.outcome,
            "event_type": self.event_type,
            "side": self.side,
            "price": self.price,
            "size": self.size,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "midpoint": self.midpoint,
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
        }


class LiveBookStreamer:
    """Thread-safe WebSocket orderbook streamer for a 5-minute market window."""

    def __init__(
        self,
        up_token_id: str,
        down_token_id: str,
        rest_fallback_client=None,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
        endpoint: str = WS_ENDPOINT,
        on_tick: Callable[[StreamTick], None] | None = None,
        rest_poll_interval: float = DEFAULT_REST_POLL_INTERVAL_S,
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
                    self._handle_snapshot_or_item(item)
        elif isinstance(data, dict):
            if "price_changes" in data:
                for change in data.get("price_changes", []):
                    if isinstance(change, dict):
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
        lean = max(-1.0, min(1.0, edge * 4.0))
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
        return LeanSignal(lean=lean, confidence=confidence, source=source)


def watch_cli(slot: int | None = None, limit: int | None = None) -> None:
    """CLI stream watcher for live Polymarket CLOB book ticks."""
    from polymarket import PublicClient
    from bot.discovery import current_slot, get_window

    target_slot = slot if slot is not None else current_slot()
    slug = f"btc-updown-5m-{target_slot}"
    client = PublicClient()

    print(f"\033[1;36m=== Polymarket CLOB WebSocket Orderbook Watcher ===\033[0m")
    print(f"Target Window: \033[1m{slug}\033[0m")
    try:
        spec = get_window(client, slug)
        print(f"Question:      {spec.question}")
        print(f"Up Token:      \033[32m{spec.up_token_id}\033[0m")
        print(f"Down Token:    \033[35m{spec.down_token_id}\033[0m")
    except Exception as ex:
        print(f"\033[31mFailed to fetch window details for {slug}: {ex}\033[0m")
        sys.exit(1)

    print(f"Connecting to: \033[34m{WS_ENDPOINT}\033[0m\n")

    tick_count = 0
    stop_flag = threading.Event()

    def on_tick(tick: StreamTick):
        nonlocal tick_count
        tick_count += 1
        age_ms = int((time.time() - tick.ts) * 1000)
        outcome_color = "\033[32m" if tick.outcome == "Up" else "\033[31m"
        reset = "\033[0m"
        outcome_padded = f"{tick.outcome:<4}"
        outcome_str = f"{outcome_color}{outcome_padded}{reset}"

        if tick.event_type == "snapshot":
            bid_str = f"{tick.best_bid:>5.2f}" if tick.best_bid is not None else "   --"
            ask_str = f"{tick.best_ask:>5.2f}" if tick.best_ask is not None else "   --"
            bid_sz_str = f"({tick.bid_size:.0f} sh)" if tick.bid_size is not None else ""
            ask_sz_str = f"({tick.ask_size:.0f} sh)" if tick.ask_size is not None else ""
            bid_block = f"bid: \033[1m{bid_str}\033[0m {bid_sz_str:<12}"
            ask_block = f"ask: \033[1m{ask_str}\033[0m {ask_sz_str:<12}"
            mid_str = f"{tick.midpoint:>5.3f}" if tick.midpoint is not None else "  ---"
            print(
                f"[{tick.time_str}] 📦 SNAPSHOT {outcome_str} {bid_block} | {ask_block} | mid: \033[1m{mid_str}\033[0m"
            )
        else:
            side_color = "\033[32m" if str(tick.side).upper() in ("BUY", "BID") else "\033[31m"
            raw_side = tick.side or "TICK"
            side_padded = f"{raw_side:<4}"
            side_str = f"{side_color}{side_padded}{reset}"
            px_val = f"{tick.price:>5.2f}" if tick.price is not None else "   --"
            px_str = f"\033[1m{px_val}\033[0m"
            sz_val = f"{tick.size:.1f}" if tick.size is not None else "--"
            size_block = f"(size: {sz_val})"
            size_padded = f"{size_block:<18}"
            mid_val = f"{tick.midpoint:>5.3f}" if tick.midpoint is not None else "  ---"
            mid_str = f"\033[1m{mid_val}\033[0m"
            age_str = f"{age_ms:>3}ms"
            print(
                f"[{tick.time_str}] ⚡ TICK {outcome_str} {side_str} {px_str} {size_padded} | mid: {mid_str} | age: {age_str}"
            )

        if limit is not None and tick_count >= limit:
            stop_flag.set()

    streamer = LiveBookStreamer(
        up_token_id=spec.up_token_id,
        down_token_id=spec.down_token_id,
        rest_fallback_client=client,
        on_tick=on_tick,
    )
    streamer.start()

    last_stale_warning = 0.0
    last_state = ConnectionState.CONNECTING

    try:
        while not stop_flag.is_set():
            time.sleep(0.5)
            status = streamer.get_status()
            now = time.time()
            now_str = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]

            if status["state"] == ConnectionState.CONNECTED and last_state != ConnectionState.CONNECTED:
                print(f"[{now_str}] 🟢 \033[32mCONNECTED\033[0m ({WS_ENDPOINT})")
                last_state = ConnectionState.CONNECTED

            if status["is_stale"] and now - last_stale_warning > 3.0:
                age_ms = status["age_ms"] or 0
                print(f"[{now_str}] ⚠️ \033[33mSTALE: no ticks for {age_ms}ms\033[0m")
                last_stale_warning = now

            if (
                status["state"] in (ConnectionState.DISCONNECTED, ConnectionState.FALLBACK_ACTIVE)
                and last_state == ConnectionState.CONNECTED
            ):
                print(f"[{now_str}] 🚨 \033[31mDISCONNECTED: reconnecting... [FALLBACK TO REST ACTIVE]\033[0m")
                last_state = ConnectionState.DISCONNECTED
    except KeyboardInterrupt:
        print("\nStopping watcher...")
    finally:
        streamer.stop()
        print("Watcher stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Polymarket CLOB WebSocket Orderbook Streamer & Watcher")
    parser.add_argument("--watch", action="store_true", help="Run terminal real-time watcher")
    parser.add_argument("--slot", type=int, default=None, help="Window epoch slot (defaults to current)")
    parser.add_argument("--limit", type=int, default=None, help="Stop after N ticks")
    args = parser.parse_args()

    if args.watch:
        watch_cli(slot=args.slot, limit=args.limit)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
