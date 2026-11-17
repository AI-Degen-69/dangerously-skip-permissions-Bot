"""Unit tests for PolymarketFeedClient, BinanceSpotFeedClient, and UnifiedMarketFeed.
Verifies L2 book snapshot parsing, trade prints, and toxicity shock fast-path detection.
"""

import pytest
from bot.microstructure_engine.market_feed import (
    PolymarketFeedClient,
    BinanceSpotFeedClient,
    UnifiedMarketFeed,
)


class TestMarketFeed:
    def test_polymarket_book_parsing(self):
        client = PolymarketFeedClient()
        msg = {
            "asset_id": "token_yes_123",
            "bids": [{"price": "0.48", "size": "100"}, {"price": "0.47", "size": "250"}],
            "asks": [{"price": "0.52", "size": "150"}, {"price": "0.53", "size": "300"}],
            "timestamp": 1700000000.0,
        }
        snap = client.handle_book_message(msg)
        assert snap is not None
        assert snap.token_id == "token_yes_123"
        assert snap.best_bid == 0.48
        assert snap.best_ask == 0.52
        assert snap.mid_price == 0.50

    def test_binance_toxicity_shock_detection(self):
        client = BinanceSpotFeedClient(symbol="BTCUSDT", shock_threshold_usd=50.0)

        # Baseline print at t = 100.0, price = 90000.0
        client.handle_ticker_message({"c": "90000.0", "timestamp": 100.0})

        # Small move at t = 100.5, price = 90020.0 (+20 USD) -> Not a shock
        t1 = client.handle_ticker_message({"c": "90020.0", "timestamp": 100.5})
        assert not t1.is_shock
        assert t1.delta_1s == 20.0

        # Sharp move at t = 100.8, price = 90080.0 (+80 USD in <1s) -> Shock!
        t2 = client.handle_ticker_message({"c": "90080.0", "timestamp": 100.8})
        assert t2.is_shock
        assert t2.delta_1s == 80.0

    def test_unified_feed_wiring(self):
        poly = PolymarketFeedClient()
        binance = BinanceSpotFeedClient(shock_threshold_usd=40.0)
        unified = UnifiedMarketFeed(polymarket_client=poly, binance_client=binance)

        assert not unified.is_toxicity_shock()

        # Trigger shock on Binance
        binance.handle_ticker_message({"c": "90000.0", "timestamp": 100.0})
        binance.handle_ticker_message({"c": "90100.0", "timestamp": 100.5})

        assert unified.is_toxicity_shock()
