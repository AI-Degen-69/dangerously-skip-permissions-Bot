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
             patch("bot.live_paper.KILL_PATH", self.tmp_path / "kill"), \
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
        null_net = self.tmp_path / "btc-updown-5m-1700001000.json"
        null_net.write_text('{"net_usd": null}')
        bad_net = self.tmp_path / "btc-updown-5m-1700001300.json"
        bad_net.write_text('{"net_usd": "not-a-number"}')
        self.assertEqual(_settled_net_usd(good, 1700000000), -42.5)
        self.assertEqual(_settled_net_usd(pending, 1700000000), 0.0)
        self.assertEqual(_settled_net_usd(corrupt, 1700000000), 0.0)
        self.assertEqual(_settled_net_usd(null_net, 1700000000), 0.0)
        self.assertEqual(_settled_net_usd(bad_net, 1700000000), 0.0)

    def test_api_state_falls_back_to_last_state_on_transient_read_error(self):
        import bot.api as api

        st_file = self.tmp_path / "state.json"
        future_end = int((time.time() + 300) * 1000)
        st_file.write_text(f'{{"slug": "btc-updown-5m-100", "updatedAtMs": 123, "endMs": {future_end}}}')
        with patch.object(api, "STATE_PATH", st_file), patch.object(api, "is_view_only", return_value=False):
            api._LAST_STATE = None
            first = api.state()
            self.assertEqual(first["slug"], "btc-updown-5m-100")
            st_file.write_text("{partial-write")
            fallback = api.state()
            self.assertEqual(fallback["slug"], "btc-updown-5m-100")
            # Expired cached state is not reused
            api._LAST_STATE = (str(st_file), {"slug": "btc-updown-5m-100", "endMs": 1000})
            self.assertIsNone(api.state())

    def test_risk_reason_mapping(self):
        from bot.live_paper import _risk_detail, _risk_reason_code

        self.assertEqual(_risk_reason_code("killed: kill-switch file present"), "kill-switch-engaged")
        self.assertEqual(_risk_reason_code("killed: daily loss cap $500.0"), "daily-loss-cap")
        self.assertEqual(_risk_reason_code("window cost cap $4000"), "window-cost-cap")
        self.assertEqual(_risk_reason_code("window trade cap 500"), "window-trade-cap")

        st = RiskState(daily_loss_usd=-520.0)
        det = _risk_detail("killed: daily loss cap $500", st, cost=100.0, trades=10)
        self.assertEqual(det["lossUsd"], 520.0)
        self.assertEqual(det["capUsd"], 500.0)

        st2 = RiskState(daily_loss_usd=-1550.0)
        det2 = _risk_detail("killed: daily loss cap $1500.0", st2, cost=100.0, trades=10)
        self.assertEqual(det2["lossUsd"], 1550.0)
        self.assertEqual(det2["capUsd"], 1500.0)

    def test_api_events_normalizes_legacy_reasons(self):
        import bot.api as api

        ev_file = self.tmp_path / "events.jsonl"
        ev_file.write_text(
            '{"ts": "2026-11-08T07:31:01Z", "kind": "hold", "reason": "thesis-intact", "detail": {"bid": 0.58, "fills": 10}}\n'
            '{"ts": "2026-11-08T07:32:01Z", "kind": "risk", "reason": "kill-switch-file-present"}\n'
            '{"ts": "2026-11-08T07:33:01Z", "kind": "entry", "reason": "straddle-open", "detail": {"price": 0.7}}\n'
            '{"ts": "2026-11-08T07:34:01Z", "kind": "hold", "reason": "holding-to-resolution"}\n'
            '{"ts": "2026-11-08T07:35:01Z", "kind": "skip", "reason": "dust-quote"}\n'
            '{"ts": "2026-11-08T07:36:01Z", "kind": "entry", "reason": "m4-snipe"}\n'
        )
        with patch.object(api, "EVENTS_PATH", ev_file), patch.object(api, "get_selected_run_id", return_value=None):
            items = api.events()
            self.assertEqual(len(items), 6)
            self.assertEqual(items[0]["reason"], "clip-fill")
            self.assertEqual(items[0]["detail"]["price"], 0.58)
            self.assertNotIn("bid", items[0]["detail"])
            self.assertEqual(items[1]["reason"], "kill-switch-engaged")
            self.assertEqual(items[2]["reason"], "straddle-open")
            self.assertEqual(items[3]["kind"], "done")
            self.assertEqual(items[4]["kind"], "refuse")
            self.assertEqual(items[5]["kind"], "snipe")

    @patch("bot.live_paper.write_state")
    @patch("bot.live_paper.log_event")
    @patch("bot.live_paper.STATE_PATH")
    @patch("bot.live_paper.RUNS_DIR")
    @patch("bot.live_paper.get_window")
    @patch("bot.live_paper.assert_single_window")
    @patch("bot.live_paper.load_cfg")
    def test_trade_window_logs_tailored_decisions_not_thesis_intact(
        self, mock_load_cfg, mock_assert_single, mock_get_window, mock_runs_dir, mock_state_path, mock_log_event, mock_write_state
    ):
        mock_state_path.__fspath__.return_value = str(self.tmp_path / "state.json")
        mock_runs_dir.mkdir.return_value = None

        mock_load_cfg.return_value = {
            "entry": {
                "openDelaySec": 0,
                "hedgeDelaySec": 0,
                "stopBeforeCloseSec": 15,
                "minFillPrice": 0.05,
                "clipSharesDefault": 10.0,
                "medianShares": 10.0,
                "maxShares": 20.0,
                "medianFillsTarget": 4,
                "minSpacingStaticSec": 0.01,
                "minSpacingMoveSec": 0.01,
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

        def fake_time():
            clock[0] += 0.5
            return clock[0]

        def fake_sleep(dt):
            clock[0] += max(0.0, dt)

        logged_reasons = []
        mock_log_event.side_effect = lambda kind, reason, *args, **kw: logged_reasons.append((kind, reason))

        with patch("bot.live_paper.settle_slug"), \
             patch("bot.live_paper.KILL_PATH", self.tmp_path / "kill"), \
             patch("bot.live_paper.time", SimpleNamespace(time=fake_time, sleep=fake_sleep), create=True):
            trade_window(mock_client, slot=slot, origin=None, verbose=False)

        # Confirm specific straddle & clip decisions were logged
        reasons_only = [r for _, r in logged_reasons]
        self.assertIn("straddle-open", reasons_only)
        self.assertIn("hedge-leg", reasons_only)
        self.assertIn("clip-fill", reasons_only)
        self.assertIn("holding-to-resolution", reasons_only)
        kinds_by_reason = {r: k for k, r in logged_reasons}
        self.assertEqual(kinds_by_reason.get("holding-to-resolution"), "done")
        # Thesis-intact must NEVER be logged anymore
        self.assertNotIn("thesis-intact", reasons_only)

    def test_live_markets_m4_snipe_verdict(self):
        import bot.api as api

        slot = 1_700_000_000
        # 4m 15s elapsed (255s) -> 45s remaining, so in M4 and before 15s cutoff
        now_ms = (slot + 255) * 1000

        mock_spec = MagicMock()
        mock_spec.up_token_id = "tok_up"
        mock_spec.down_token_id = "tok_down"
        mock_spec.question = "Will BTC be up?"

        mock_client = MagicMock()
        mock_client.get_price.return_value = "0.50"
        mock_client.get_midpoint.return_value = "0.50"

        st = {
            "slug": f"btc-updown-5m-{slot}",
            "fills": [{"minute": 0}, {"minute": 1}, {"minute": 2}],
        }

        with patch.object(api, "visible_slots", return_value=[slot]), \
             patch("bot.discovery.get_window", return_value=mock_spec), \
             patch.object(api, "client", return_value=mock_client), \
             patch.object(api, "state", return_value=st), \
             patch("time.time", return_value=now_ms / 1000.0):
            markets = api.live_markets({})
            self.assertEqual(len(markets), 1)
            self.assertEqual(markets[0]["verdict"]["action"], "snipe")
            self.assertEqual(markets[0]["verdict"]["reason"], "m4-snipe")

    def test_enrich_fill_m4_snipe_kind(self):
        import bot.api as api

        fill = {"minute": 4, "outcome": "Up", "price": 0.10, "shares": 30.0, "usd": 3.0}
        enriched = api._enrich_fill(fill, idx=5, default_ts=1700000000000, slug="btc-updown-5m-1700000000")
        self.assertEqual(enriched["kind"], "snipe")
        self.assertEqual(enriched["reason"], "m4-snipe")


if __name__ == "__main__":
    unittest.main()
