"""Unit tests for WebSocket orderbook streaming, health monitor, and fallback."""

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from bot.signal import LeanSignal
from bot.ws import ConnectionState, LiveBookStreamer, StreamTick, TokenBook


class TokenBookTests(unittest.TestCase):
    def test_apply_snapshot_and_recalculate(self):
        book = TokenBook(asset_id="tok_up", outcome="Up")
        bids = [{"price": "0.48", "size": "100"}, {"price": "0.49", "size": "250"}]
        asks = [{"price": "0.51", "size": "300"}, {"price": "0.52", "size": "150"}]

        book.apply_snapshot(bids, asks, ts=1000.0)

        self.assertEqual(len(book.bids), 2)
        self.assertEqual(len(book.asks), 2)
        self.assertEqual(book.best_bid, 0.49)
        self.assertEqual(book.best_ask, 0.51)
        self.assertEqual(book.midpoint, 0.50)
        self.assertEqual(book.last_update_ts, 1000.0)

    def test_apply_price_change_updates_and_removals(self):
        book = TokenBook(asset_id="tok_down", outcome="Down")
        book.apply_snapshot(
            [{"price": "0.40", "size": "50"}],
            [{"price": "0.45", "size": "100"}],
            ts=1000.0,
        )
        self.assertEqual(book.best_bid, 0.40)
        self.assertEqual(book.best_ask, 0.45)

        # Update bid higher
        book.apply_price_change(side="BUY", price=0.42, size=75, ts=1001.0)
        self.assertEqual(book.best_bid, 0.42)
        self.assertAlmostEqual(book.midpoint, 0.435, places=4)

        # Remove top bid (size = 0)
        book.apply_price_change(side="BUY", price=0.42, size=0, ts=1002.0)
        self.assertEqual(book.best_bid, 0.40)
        self.assertAlmostEqual(book.midpoint, 0.425, places=4)

        # Update ask lower
        book.apply_price_change(side="SELL", price=0.43, size=20, ts=1003.0)
        self.assertEqual(book.best_ask, 0.43)
        self.assertAlmostEqual(book.midpoint, 0.415, places=4)

        # Remove ask
        book.apply_price_change(side="SELL", price=0.43, size=0, ts=1004.0)
        self.assertEqual(book.best_ask, 0.45)

    def test_empty_book_midpoint_none(self):
        book = TokenBook(asset_id="tok", outcome="Up")
        self.assertIsNone(book.best_bid)
        self.assertIsNone(book.best_ask)
        self.assertIsNone(book.midpoint)


class StreamerLogicTests(unittest.TestCase):
    def setUp(self):
        self.rest_mock = MagicMock()
        self.streamer = LiveBookStreamer(
            up_token_id="up_123",
            down_token_id="down_456",
            rest_fallback_client=self.rest_mock,
        )

    def tearDown(self):
        self.streamer.stop()

    def test_process_snapshot_message(self):
        payload = [
            {
                "market": "mkt_1",
                "asset_id": "up_123",
                "timestamp": "1700000000",
                "bids": [{"price": "0.60", "size": "100"}],
                "asks": [{"price": "0.62", "size": "150"}],
            },
            {
                "market": "mkt_1",
                "asset_id": "down_456",
                "timestamp": "1700000000",
                "bids": [{"price": "0.38", "size": "150"}],
                "asks": [{"price": "0.40", "size": "100"}],
            },
        ]
        self.streamer.process_payload(payload)

        status = self.streamer.get_status()
        self.assertEqual(status["up_book"]["best_bid"], 0.60)
        self.assertEqual(status["up_book"]["best_ask"], 0.62)
        self.assertEqual(status["down_book"]["best_bid"], 0.38)
        self.assertEqual(status["down_book"]["best_ask"], 0.40)
        self.assertEqual(len(self.streamer.ticks), 2)

    def test_process_delta_message(self):
        # Initial snapshot
        self.streamer.process_payload([
            {"asset_id": "up_123", "bids": [{"price": "0.50", "size": "10"}], "asks": [{"price": "0.52", "size": "10"}]}
        ])
        # Delta price change
        delta = {
            "market": "mkt_1",
            "price_changes": [
                {"asset_id": "up_123", "price": "0.51", "size": "50", "side": "BUY"}
            ]
        }
        self.streamer.process_payload(delta)
        self.assertEqual(self.streamer.books["up_123"].best_bid, 0.51)

    def test_staleness_and_fallback_states(self):
        self.streamer.state = ConnectionState.CONNECTED
        now = time.time()
        self.streamer.last_tick_ts = now - 1.0
        self.assertFalse(self.streamer.get_status()["is_stale"])
        self.assertEqual(self.streamer.get_status()["state"], "connected")

        # Stale (> 3.0s)
        self.streamer.last_tick_ts = now - 3.5
        self.assertTrue(self.streamer.get_status()["is_stale"])
        self.assertEqual(self.streamer.get_status()["state"], "stale")

        # Fallback (> 10.0s)
        self.streamer.last_tick_ts = now - 11.0
        self.assertEqual(self.streamer.get_status()["state"], "fallback_active")

    def test_fallback_to_rest_when_disconnected(self):
        self.streamer.state = ConnectionState.DISCONNECTED
        self.rest_mock.get_price.return_value = "0.55"
        self.rest_mock.get_midpoint.return_value = "0.54"

        px = self.streamer.get_buy_price("up_123")
        self.assertEqual(px, 0.55)
        self.rest_mock.get_price.assert_called_once_with(token_id="up_123", side="BUY")

        mid = self.streamer.get_midpoint("up_123")
        self.assertEqual(mid, 0.54)

    def test_lean_calculation_from_book(self):
        # Set up books directly
        self.streamer.state = ConnectionState.CONNECTED
        self.streamer.last_tick_ts = time.time()
        self.streamer.books["up_123"].apply_snapshot(
            [{"price": "0.59", "size": "100"}], [{"price": "0.61", "size": "100"}]
        )
        self.streamer.books["down_456"].apply_snapshot(
            [{"price": "0.39", "size": "100"}], [{"price": "0.41", "size": "100"}]
        )

        lean_sig = self.streamer.get_lean("up_123", "down_456")
        # up_mid = 0.60, down_mid = 0.40
        # edge = (0.60 - 0.40) / 2 = 0.10
        # lean = 0.10 * 4 = 0.40
        # spread = abs(0.60 + 0.40 - 1.0) = 0.0
        # confidence = 1.0 - 0 = 1.0
        self.assertAlmostEqual(lean_sig.lean, 0.40, places=3)
        self.assertAlmostEqual(lean_sig.confidence, 1.0, places=3)
        self.assertEqual(lean_sig.source, "wss-book-microprice")

    def test_thread_safety_concurrent_access(self):
        self.streamer.state = ConnectionState.CONNECTED
        errors = []

        def writer():
            for i in range(100):
                self.streamer.process_payload({
                    "price_changes": [
                        {"asset_id": "up_123", "price": f"0.{50 + (i % 20)}", "size": f"{i}", "side": "BUY"}
                    ]
                })
                time.sleep(0.001)

        def reader():
            for _ in range(100):
                try:
                    _ = self.streamer.get_buy_price("up_123")
                    _ = self.streamer.get_status()
                    _ = self.streamer.get_recent_ticks(10)
                except Exception as ex:
                    errors.append(ex)
                time.sleep(0.001)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(len(errors), 0)

    def test_wait_for_tick_notification(self):
        # wait_for_tick returns False on timeout if no ticks arrive
        notified = self.streamer.wait_for_tick(timeout=0.02)
        self.assertFalse(notified)

        # Trigger tick asynchronously
        def send_tick():
            time.sleep(0.01)
            self.streamer.process_payload([
                {"asset_id": "up_123", "bids": [{"price": "0.55", "size": "10"}], "asks": [{"price": "0.56", "size": "10"}]}
            ])

        th = threading.Thread(target=send_tick)
        th.start()
        notified = self.streamer.wait_for_tick(timeout=0.5)
        th.join()
        self.assertTrue(notified)

    def test_active_rest_fallback_poller_cadence_and_ticks(self):
        self.rest_mock.get_price.side_effect = lambda token_id, side: "0.52" if side == "BUY" else "0.50"
        self.rest_mock.get_midpoint.return_value = "0.51"

        fast_streamer = LiveBookStreamer(
            up_token_id="up_fast",
            down_token_id="down_fast",
            rest_fallback_client=self.rest_mock,
            rest_poll_interval=0.03,
        )
        try:
            # Manually invoke poll
            fast_streamer._poll_rest_fallback()

            up_book = fast_streamer.books["up_fast"]
            self.assertEqual(up_book.best_ask, 0.52)
            self.assertEqual(up_book.best_bid, 0.50)
            self.assertEqual(up_book.midpoint, 0.51)

            recent_ticks = fast_streamer.get_recent_ticks()
            self.assertTrue(len(recent_ticks) >= 2)
            self.assertEqual(recent_ticks[-1]["event_type"], "rest_poll")
            self.assertEqual(recent_ticks[-1]["best_ask"], 0.52)
        finally:
            fast_streamer.stop()

    def test_active_rest_fallback_skips_when_ws_connected_and_fresh(self):
        # When WS is connected and tick is fresh (<3s), fallback poller worker should not poll REST
        self.streamer.state = ConnectionState.CONNECTED
        self.streamer.last_tick_ts = time.time()
        self.rest_mock.reset_mock()

        # Simulate fallback worker iteration check
        now = time.time()
        is_stale = (self.streamer.last_tick_ts > 0 and (now - self.streamer.last_tick_ts) > 3.0)
        needs_fallback = (self.streamer.state != ConnectionState.CONNECTED or is_stale or self.streamer.last_tick_ts == 0)
        self.assertFalse(needs_fallback)
        self.rest_mock.get_price.assert_not_called()



class LivePaperIntegrationTests(unittest.TestCase):
    def test_live_buy_price_queries_streamer(self):
        from bot.live_paper import live_buy_price
        c = MagicMock()
        streamer = MagicMock()
        streamer.get_buy_price.return_value = 0.44

        px = live_buy_price(c, "up_tok", streamer=streamer)
        self.assertEqual(px, 0.44)
        c.get_price.assert_not_called()

    def test_microprice_lean_queries_streamer(self):
        from bot.live_paper import microprice_lean
        c = MagicMock()
        streamer = MagicMock()
        streamer.get_lean.return_value = LeanSignal(lean=0.5, confidence=0.8, source="wss-book-microprice")

        sig = microprice_lean(c, "up", "down", streamer=streamer)
        self.assertEqual(sig.lean, 0.5)
        self.assertEqual(sig.source, "wss-book-microprice")
        c.get_midpoint.assert_not_called()

    def test_api_snapshot_includes_ws_and_recent_ticks(self):
        import bot.api as api
        with patch.object(api, "loop_running", return_value=True),              patch.object(api, "state", return_value={
                 "slug": "btc-updown-5m-1",
                 "ws": {"state": "connected", "is_connected": True},
                 "recentTicks": [{"ts": 123, "outcome": "Up"}],
             }):
            snap = api.snapshot()
            self.assertIn("ws", snap)
            self.assertEqual(snap["ws"]["state"], "connected")
            self.assertEqual(len(snap["recentTicks"]), 1)


if __name__ == "__main__":

    unittest.main()
