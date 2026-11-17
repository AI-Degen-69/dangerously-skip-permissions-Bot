"""Real-time market feed streaming client for Polymarket L2 books and external spot tickers.

Handles:
- Polymarket CLOB WebSocket L2 orderbook & trade streams.
- Binance / Bybit BTC spot WebSocket ticker for cross-asset covariance updates.
- Toxicity Fast-Path detector for spot price shocks.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class OrderBookSnapshot:
    """L2 orderbook snapshot for a specific outcome token."""
    token_id: str
    bids: List[Tuple[float, float]] = field(default_factory=list)  # (price, size) desc
    asks: List[Tuple[float, float]] = field(default_factory=list)  # (price, size) asc
    timestamp: float = 0.0

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0][0] if self.asks else None

    @property
    def mid_price(self) -> Optional[float]:
        if self.bids and self.asks:
            return round((self.bids[0][0] + self.asks[0][0]) / 2.0, 4)
        if self.bids:
            return self.bids[0][0]
        if self.asks:
            return self.asks[0][0]
        return None


@dataclass
class TradePrint:
    """Trade execution print from the tape."""
    token_id: str
    price: float
    size: float
    side: str  # "BUY" or "SELL"
    timestamp: float


@dataclass
class ExternalSpotTicker:
    """External reference market ticker (e.g. Binance BTC/USDT)."""
    symbol: str
    price: float
    delta_1s: float = 0.0
    timestamp: float = 0.0
    is_shock: bool = False


class PolymarketFeedClient:
    """Streams Polymarket CLOB L2 depth and trade executions."""

    def __init__(
        self,
        ws_url: str = "wss://ws-subscriptions.polymarket.com",
        on_book_update: Optional[Callable[[OrderBookSnapshot], None]] = None,
        on_trade: Optional[Callable[[TradePrint], None]] = None,
    ) -> None:
        self.ws_url = ws_url
        self.on_book_update = on_book_update
        self.on_trade = on_trade
        self.books: Dict[str, OrderBookSnapshot] = {}
        self.is_connected = False
        self._running = False

    def handle_book_message(self, data: Dict[str, Any]) -> Optional[OrderBookSnapshot]:
        """Process raw orderbook snapshot/delta message."""
        token_id = str(data.get("asset_id", data.get("token_id", "")))
        if not token_id:
            return None

        raw_bids = data.get("bids", [])
        raw_asks = data.get("asks", [])

        bids = []
        for b in raw_bids:
            if isinstance(b, dict):
                p = float(b.get("price", 0.0))
                sz = float(b.get("size", 0.0))
            elif isinstance(b, (list, tuple)) and len(b) >= 2:
                p = float(b[0])
                sz = float(b[1])
            else:
                continue
            bids.append((p, sz))

        asks = []
        for a in raw_asks:
            if isinstance(a, dict):
                p = float(a.get("price", 0.0))
                sz = float(a.get("size", 0.0))
            elif isinstance(a, (list, tuple)) and len(a) >= 2:
                p = float(a[0])
                sz = float(a[1])
            else:
                continue
            asks.append((p, sz))

        bids.sort(key=lambda x: x[0], reverse=True)
        asks.sort(key=lambda x: x[0])

        snapshot = OrderBookSnapshot(
            token_id=token_id,
            bids=bids,
            asks=asks,
            timestamp=float(data.get("timestamp", 0.0)),
        )
        self.books[token_id] = snapshot

        if self.on_book_update:
            self.on_book_update(snapshot)

        return snapshot

    def handle_trade_message(self, data: Dict[str, Any]) -> Optional[TradePrint]:
        """Process raw trade print message."""
        token_id = str(data.get("asset_id", data.get("token_id", "")))
        price = float(data.get("price", 0.0))
        size = float(data.get("size", 0.0))
        side = str(data.get("side", "BUY")).upper()
        ts = float(data.get("timestamp", 0.0))

        trade = TradePrint(
            token_id=token_id,
            price=price,
            size=size,
            side=side,
            timestamp=ts,
        )

        if self.on_trade:
            self.on_trade(trade)

        return trade


class BinanceSpotFeedClient:
    """Streams Binance spot tickers and calculates rolling delta for toxicity fast-path."""

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        ws_url: str = "wss://stream.binance.com:9443/ws",
        shock_threshold_usd: float = 65.0,
        on_ticker: Optional[Callable[[ExternalSpotTicker], None]] = None,
    ) -> None:
        self.symbol = symbol.upper()
        self.ws_url = ws_url
        self.shock_threshold_usd = shock_threshold_usd
        self.on_ticker = on_ticker
        self.last_price: Optional[float] = None
        self.last_timestamp: float = 0.0
        self.rolling_prices: List[Tuple[float, float]] = []  # (timestamp, price)

    def handle_ticker_message(self, data: Dict[str, Any]) -> ExternalSpotTicker:
        """Process incoming ticker or trade print and detect sharp price momentum breaks."""
        # Binance ticker format: "c" = current close/last price, "E" = event time
        price = float(data.get("c", data.get("p", data.get("price", 0.0))))
        ts = float(data.get("E", data.get("timestamp", 0.0))) / 1000.0 if "E" in data else float(data.get("timestamp", 0.0))

        # Update 1-second rolling window
        self.rolling_prices.append((ts, price))
        cutoff = ts - 1.0
        self.rolling_prices = [p for p in self.rolling_prices if p[0] >= cutoff]

        delta_1s = price - self.rolling_prices[0][1] if self.rolling_prices else 0.0
        is_shock = abs(delta_1s) >= self.shock_threshold_usd

        ticker = ExternalSpotTicker(
            symbol=self.symbol,
            price=price,
            delta_1s=round(delta_1s, 2),
            timestamp=ts,
            is_shock=is_shock,
        )

        self.last_price = price
        self.last_timestamp = ts

        if self.on_ticker:
            self.on_ticker(ticker)

        return ticker


class UnifiedMarketFeed:
    """Synchronized market feed aggregating Polymarket books and Binance spot reference."""

    def __init__(
        self,
        polymarket_client: Optional[PolymarketFeedClient] = None,
        binance_client: Optional[BinanceSpotFeedClient] = None,
    ) -> None:
        self.polymarket = polymarket_client or PolymarketFeedClient()
        self.binance = binance_client or BinanceSpotFeedClient()
        self.toxicity_shock_active = False

        # Wire up shock detector
        orig_on_ticker = self.binance.on_ticker

        def wrapped_ticker(ticker: ExternalSpotTicker):
            self.toxicity_shock_active = ticker.is_shock
            if orig_on_ticker:
                orig_on_ticker(ticker)

        self.binance.on_ticker = wrapped_ticker

    def get_latest_book(self, token_id: str) -> Optional[OrderBookSnapshot]:
        return self.polymarket.books.get(token_id)

    def is_toxicity_shock(self) -> bool:
        return self.toxicity_shock_active
