"""Unit tests for the dynamic live paper trading loop and anti-runaway guards."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from bot.live_paper import live_buy_price, microprice_lean, trade_window
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

        slot = int(time.time())
        t0 = time.time()
        with patch("bot.live_paper.settle_slug"):
            res = trade_window(mock_client, slot=slot, origin=None, verbose=False)
        elapsed = time.time() - t0

        self.assertEqual(res["trades"], 4)
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


if __name__ == "__main__":
    unittest.main()
