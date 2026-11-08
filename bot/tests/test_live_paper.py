"""Unit tests for the dynamic live paper trading loop and anti-runaway guards."""

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bot.executor import m_quotas, pick_side
from bot.live_paper import live_buy_price, microprice_lean, trade_window
from bot.risk import RiskState, check_window
from bot.signal import LeanSignal
from bot.ws import ConnectionState, LiveBookStreamer, TokenBook


class LivePaperLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    @patch("bot.live_paper.write_state")
    @patch("bot.live_paper.log_event")
    @patch("bot.live_paper.STATE_PATH")
    @patch("bot.live_paper.RUNS_DIR")
    @patch("bot.live_paper.get_window")
    @patch("bot.live_paper.assert_single_window")
    @patch("bot.live_paper.load_cfg")
    def test_trade_window_completes_dynamically_without_blocking_sleeps(
        self, mock_load_cfg, mock_assert_single, mock_get_window, mock_runs_dir, mock_state_path, mock_log_event, mock_write_state
    ):
        mock_state_path.__fspath__.return_value = str(self.tmp_path / "state.json")
        mock_runs_dir.mkdir.return_value = None

        mock_load_cfg.return_value = {
            "entry": {
                "openDelaySec": 0,
                "hedgeDelaySec": 0,
                "stopBeforeCloseSec": 0,
                "minFillPrice": 0.05,
                "clipSharesDefault": 10.0,
                "medianShares": 10.0,
                "maxShares": 20.0,
                "medianFillsTarget": 4,
                "minSpacingStaticSec": 0.1,
                "minSpacingMoveSec": 0.05,
            }
        }

        mock_spec = MagicMock()
        mock_spec.up_token_id = "tok_up"
        mock_spec.down_token_id = "tok_down"
        mock_spec.question = "Will BTC be up?"
        mock_get_window.return_value = mock_spec

        mock_client = MagicMock()
        mock_client.get_price.return_value = "0.50"
        mock_client.get_midpoint.return_value = "0.50"

        slot = 1_700_000_100
        clock = [float(slot)]
        real_time = time.time

        def fake_time():
            clock[0] += 0.2
            return clock[0]

        def fake_sleep(dt):
            clock[0] += max(0.0, dt)

        t0 = real_time()
        with patch("bot.live_paper.settle_slug"), \
             patch("bot.live_paper.time", SimpleNamespace(time=fake_time, sleep=fake_sleep), create=True):
            res = trade_window(mock_client, slot=slot, origin=None, verbose=False)
        elapsed = real_time() - t0

        self.assertEqual(res["trades"], 4)
        self.assertGreaterEqual(int(clock[0]), slot + 300)
        self.assertLess(elapsed, 3.5)

    @patch("bot.live_paper.write_state")
    @patch("bot.live_paper.log_event")
    @patch("bot.live_paper.STATE_PATH")
    @patch("bot.live_paper.RUNS_DIR")
    @patch("bot.live_paper.get_window")
    @patch("bot.live_paper.assert_single_window")
    @patch("bot.live_paper.load_cfg")
    def test_trade_window_skips_dust_responsively_without_five_second_sleep(
        self, mock_load_cfg, mock_assert_single, mock_get_window, mock_runs_dir, mock_state_path, mock_log_event, mock_write_state
    ):
        mock_state_path.__fspath__.return_value = str(self.tmp_path / "state.json")
        mock_runs_dir.mkdir.return_value = None

        slot = int(time.time()) - 299  # 1s left in 300s window

        mock_load_cfg.return_value = {
            "entry": {
                "openDelaySec": 0,
                "hedgeDelaySec": 0,
                "stopBeforeCloseSec": 0,
                "minFillPrice": 0.10,
                "medianFillsTarget": 50,
            }
        }

        mock_spec = MagicMock()
        mock_spec.up_token_id = "tok_up"
        mock_spec.down_token_id = "tok_down"
        mock_spec.question = "Will BTC be up?"
        mock_get_window.return_value = mock_spec

        mock_client = MagicMock()
        mock_client.get_price.return_value = "0.02"
        mock_client.get_midpoint.return_value = "0.02"

        t0 = time.time()
        with patch("bot.live_paper.settle_slug"):
            res = trade_window(mock_client, slot=slot, origin=None, verbose=False)
        elapsed = time.time() - t0

        # Loop promptly breaks on window close without a 5s blocking sleep
        self.assertLess(elapsed, 2.5)

    def test_fix1_m_quotas_matches_frozen_shape_and_floors_at_one(self):
        self.assertEqual(m_quotas(45), [8, 10, 11, 10, 5])
        self.assertEqual(m_quotas(4), [1, 1, 1, 1, 1])

    def test_fix2_pick_side_tilts_down_on_negative_lean(self):
        down_lean = LeanSignal(lean=-1.0, confidence=1.0, source="test")
        up_lean = LeanSignal(lean=1.0, confidence=1.0, source="test")
        down_outcomes = [pick_side(i, minute=1, lean=down_lean) for i in range(12)]
        up_outcomes = [pick_side(i, minute=1, lean=up_lean) for i in range(12)]
        self.assertEqual(down_outcomes.count("Down"), 10)  # 83% Down, not 0%
        self.assertEqual(up_outcomes.count("Up"), 10)      # symmetric 83% Up

    def test_fix3_check_window_honors_kill_file_and_daily_loss(self):
        kill_file = self.tmp_path / "kill"
        kill_file.write_text("stop")
        self.assertIn("kill-switch", check_window(0, 0.0, RiskState(), kill_path=kill_file))
        kill_file.unlink()
        self.assertIn("daily loss cap", check_window(0, 0.0, RiskState(daily_loss_usd=-500.0), kill_path=kill_file))

    def test_settled_net_usd_ignores_malformed_and_pending_files(self):
        from bot.live_paper import _settled_net_usd

        good = self.tmp_path / "btc-updown-5m-1700000100.json"
        good.write_text('{"net_usd": -42.5}')
        pending = self.tmp_path / "btc-updown-5m-1700000400.json"
        pending.write_text('{"net_usd": -100.0, "pending": true}')
        corrupt = self.tmp_path / "btc-updown-5m-1700000700.json"
        corrupt.write_text("{corrupt")
        self.assertEqual(_settled_net_usd(good, 1700000000), -42.5)
        self.assertEqual(_settled_net_usd(pending, 1700000000), 0.0)
        self.assertEqual(_settled_net_usd(corrupt, 1700000000), 0.0)

    def test_api_state_falls_back_to_last_state_on_transient_read_error(self):
        import bot.api as api

        st_file = self.tmp_path / "state.json"
        st_file.write_text('{"slug": "btc-updown-5m-100", "updatedAtMs": 123}')
        with patch.object(api, "STATE_PATH", st_file), patch.object(api, "is_view_only", return_value=False):
            api._LAST_STATE = None
            first = api.state()
            self.assertEqual(first["slug"], "btc-updown-5m-100")
            st_file.write_text("{partial-write")
            fallback = api.state()
            self.assertEqual(fallback["slug"], "btc-updown-5m-100")


if __name__ == "__main__":
    unittest.main()
