"""Real-time Polymarket CLOB WebSocket Orderbook Streamer & Health Monitor.

Subscribes to live orderbook feeds via Polymarket's public CLOB WebSocket:
  wss://ws-subscriptions-clob.polymarket.com/ws/market

Maintains an in-memory, thread-safe orderbook for Up & Down outcome tokens,
tracks microsecond ticks, monitors connection health, and falls back to
PublicClient REST transparently when disconnected or stale.

Shell: public names and the CLI entry live here; pure logic lives in
ws_models / ws_feed / ws_tape / ws_quotes.
"""

import argparse
import sys
import threading
import time
from datetime import datetime, timezone

from .ws_feed import StreamerFeedMixin
from .ws_models import (
    DEFAULT_BUFFER_SIZE,
    DEFAULT_REST_POLL_INTERVAL_S,
    FALLBACK_THRESHOLD_S,
    PING_INTERVAL_S,
    STALE_THRESHOLD_S,
    WS_ENDPOINT,
    ConnectionState,
    StreamTick,
    TokenBook,
    TradePrint,
)
from .ws_quotes import StreamerQuotesMixin
from .ws_tape import (
    TAPE_ARCHIVE_BYTES,
    TAPE_MAX_ARCHIVES,
    TAPE_RETENTION_S,
    TAPE_SEGMENT_BYTES,
    StreamerTapeMixin,
)


class LiveBookStreamer(StreamerFeedMixin, StreamerTapeMixin, StreamerQuotesMixin):
    """Thread-safe WebSocket orderbook streamer for a 5-minute market window."""


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

__all__ = [
    "DEFAULT_BUFFER_SIZE",
    "DEFAULT_REST_POLL_INTERVAL_S",
    "FALLBACK_THRESHOLD_S",
    "PING_INTERVAL_S",
    "STALE_THRESHOLD_S",
    "TAPE_ARCHIVE_BYTES",
    "TAPE_MAX_ARCHIVES",
    "TAPE_RETENTION_S",
    "TAPE_SEGMENT_BYTES",
    "WS_ENDPOINT",
    "ConnectionState",
    "LiveBookStreamer",
    "StreamTick",
    "TokenBook",
    "TradePrint",
    "main",
    "watch_cli",
]


if __name__ == "__main__":
    main()
