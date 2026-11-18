"""Streamer data layer: connection state, order-book models, shared constants."""

from dataclasses import dataclass, field
from enum import Enum
import time


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
class TradePrint:
    """A single matched trade observed on the CLOB market channel.

    Schema proof (docs.polymarket.com → Market Channel, verified 2026-11-10):
    ``event_type`` is ``last_trade_price`` on ``wss://ws-subscriptions-clob.polymarket.com/ws/market``
    with the same ``assets_ids`` subscription as the book feed. Required fields are
    ``asset_id``, ``market`` (condition id), ``price``, ``size``, ``side``, ``timestamp``
    (all strings); ``fee_rate_bps`` and ``transaction_hash`` are optional.

    ``side`` is **from the taker's perspective** (AsyncAPI: BUY | SELL). A resting
    BUY (maker bid) is therefore only filled by a taker ``SELL`` print, and a
    resting SELL only by a taker ``BUY`` print. Getting this backwards silently
    inverts the whole fill-verification result.
    """

    ts: float  # epoch seconds (converted from ms string when available)
    asset_id: str
    price: float
    size: float
    side: str  # "BUY" | "SELL" (taker side)
    timestamp_raw: str = ""
    fee_rate_bps: str = ""
    market: str = ""

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "asset_id": self.asset_id,
            "price": round(self.price, 4),
            "size": self.size,
            "side": self.side,
            "timestamp": self.timestamp_raw,
            "fee_rate_bps": self.fee_rate_bps,
            "market": self.market,
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
