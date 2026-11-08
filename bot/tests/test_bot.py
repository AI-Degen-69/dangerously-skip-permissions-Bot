"""Unit tests for the 5m paper bot — unittest + mock pattern.

Extends docs/dangerously-skip-permissions/tests/test_save_trades_to_csv.py
style: stdlib unittest, unittest.mock for network, temp dirs for files.
No keys, no funding, no network.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, ".")

from bot import constants as C
from bot.executor import plan_window
from bot.reconcile import fidelity
from bot.risk import (
    RiskState,
    assert_single_window,
    check_window,
    clip_shares,
    heartbeat,
    heartbeat_age_s,
    is_stale,
)
from bot.signal import BookMicropriceLean, DumbLean, LeanSignal


class ConstantsTests(unittest.TestCase):
    def test_frozen_moments(self):
        self.assertEqual(C.NUM_WINDOWS_24H, 288)
        self.assertEqual(C.MEDIAN_TRADES_PER_WINDOW, 45)
        self.assertEqual(C.MEAN_TRADES_PER_WINDOW, 58.5)
        self.assertEqual(C.CLIP_SHARES_DEFAULT, 30.0)
        self.assertEqual(C.MAX_SHARES, 50.0)
        self.assertTrue(C.BUY_ONLY and C.HOLD_TO_REDEEM)
        self.assertEqual(len(C.M_BUCKETS), 5)
        self.assertAlmostEqual(C.BOTH_SIDES_RATE, 0.972, places=3)


class SignalTests(unittest.TestCase):
    def test_dumb_lean_neutral(self):
        sig = DumbLean().lean_for_window("btc-updown-5m-0")
        self.assertEqual((sig.lean, sig.confidence), (0.0, 0.0))

    def test_book_microprice_stub_neutral(self):
        # Stub until CLOB book wiring lands — must not tilt size.
        sig = BookMicropriceLean().lean_for_window("btc-updown-5m-0")
        self.assertEqual((sig.lean, sig.confidence), (0.0, 0.0))

    def test_extreme_lean_keeps_both_sides(self):
        # Regression guard: tilted plans must stay straddles (CSV: 97.2%
        # both-sides). A past mapping collapsed any negative lean to Down-only.
        for lean in (-1.0, 1.0):
            plan = plan_window("w", LeanSignal(lean=lean, confidence=1.0), RiskState())
            self.assertGreater(len({f.outcome for f in plan.fills}), 1)


class RiskTests(unittest.TestCase):
    def test_clip_shares(self):
        self.assertEqual(clip_shares(30.0), 30.0)
        self.assertEqual(clip_shares(999.0), C.MAX_SHARES)
        self.assertEqual(clip_shares(-5.0), 0.0)

    def test_check_window_caps(self):
        st = RiskState()
        self.assertIsNone(check_window(10, 100.0, st))
        self.assertIn("trade cap", check_window(500, 100.0, RiskState()))
        self.assertIn("cost cap", check_window(10, 99999.0, RiskState()))

    def test_daily_loss_kills(self):
        st = RiskState(daily_loss_usd=-600.0)
        reason = check_window(1, 10.0, st)
        self.assertTrue(st.killed)
        self.assertIn("killed", reason)
        # killed state blocks everything after
        self.assertIn("killed", check_window(0, 0.0, st))

    def test_daily_loss_configurable(self):
        import bot.risk as risk
        with tempfile.TemporaryDirectory() as td:
            cfg_file = Path(td) / "config.json"
            cfg_file.write_text(json.dumps({"risk": {"dailyLossCapUsd": 1500.0}}))
            with patch.object(risk, "CONFIG_PATH", cfg_file):
                # Loss of $600 should not trigger a $1500 cap
                st = RiskState(daily_loss_usd=-600.0)
                reason = check_window(1, 10.0, st)
                self.assertIsNone(reason)
                self.assertFalse(st.killed)

                # Loss of $1501 should trigger the $1500 cap
                st2 = RiskState(daily_loss_usd=-1501.0)
                reason2 = check_window(1, 10.0, st2)
                self.assertIsNotNone(reason2)
                self.assertTrue(st2.killed)
                self.assertIn("daily loss cap $1500", reason2)

    def test_single_window_invariant(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "state.json"
            p.write_text(json.dumps({"slug": "btc-updown-5m-1"}))
            assert_single_window("btc-updown-5m-1", p)  # same owner ok
            with self.assertRaises(RuntimeError):
                assert_single_window("btc-updown-5m-2", p)  # other owner refused
            assert_single_window("btc-updown-5m-9", Path(td) / "missing.json")  # ok

    def test_heartbeat_not_stale_when_fresh(self):
        import time

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "state.json"
            p.write_text(json.dumps({"slug": "x", "updatedAtMs": int(time.time() * 1000)}))
            heartbeat(p)  # touches updatedAtMs, never raises
            age = heartbeat_age_s(p)
            self.assertIsNotNone(age)
            self.assertLess(age, 5.0)
            self.assertFalse(is_stale(p))

    def test_stale_state_detected(self):
        import time

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "state.json"
            p.write_text(json.dumps({"slug": "x", "updatedAtMs": int((time.time() - 700) * 1000)}))
            self.assertTrue(is_stale(p))


class ExecutorTests(unittest.TestCase):
    def test_dumb_plan_matches_csv_moments(self):
        plan = plan_window("paper-5m-000", DumbLean().lean_for_window("w"), RiskState())
        # M-shape weights scaled to median 45 -> 44 fills (8+10+11+10+5)
        self.assertEqual(len(plan.fills), 44)
        # both sides touched (straddle)
        self.assertGreater(len({f.outcome for f in plan.fills}), 1)
        # buy-only sizing: shares within (0, 50], cost positive
        for f in plan.fills:
            self.assertGreater(f.shares, 0)
            self.assertLessEqual(f.shares, C.MAX_SHARES)
        self.assertGreater(plan.cost, 0)
        # ~1/3 of fills are the 30-share default clip (CSV: 30.4%)
        clip_rate = sum(1 for f in plan.fills if f.shares == C.CLIP_SHARES_DEFAULT) / len(plan.fills)
        self.assertGreater(clip_rate, 0.2)
        self.assertLess(clip_rate, 0.45)

    def test_lean_tilts_up_share(self):
        down = plan_window("w", LeanSignal(lean=-1.0, confidence=1.0), RiskState())
        up = plan_window("w", LeanSignal(lean=1.0, confidence=1.0), RiskState())
        up_share = lambda p: sum(1 for f in p.fills if f.outcome == "Up") / len(p.fills)
        self.assertLess(up_share(down), up_share(up))

    def test_plan_matches_m_shape(self):
        # M_BUCKETS scaled to the 45-median target -> [8, 10, 11, 10, 5] = 44 fills.
        plan = plan_window("w", DumbLean().lean_for_window("w"), RiskState())
        per_minute = [sum(1 for f in plan.fills if f.minute == m) for m in range(5)]
        self.assertEqual(per_minute, [8, 10, 11, 10, 5])

    def test_risk_caps_stop_plan(self):
        st = RiskState(killed=True, kill_reason="test")
        plan = plan_window("w", DumbLean().lean_for_window("w"), st)
        self.assertEqual(len(plan.fills), 0)


class DiscoveryTests(unittest.TestCase):
    def test_current_slot_math(self):
        from bot.discovery import WINDOW_S, current_slot

        self.assertEqual(current_slot(300), 300)
        self.assertEqual(current_slot(599), 300)
        self.assertEqual(current_slot(600), 600)
        self.assertEqual(current_slot(0), 0)
        self.assertEqual(WINDOW_S, 300)

    def test_get_window_uses_event_markets(self):
        from bot.discovery import get_window

        c = MagicMock()
        c.get_event.return_value.model_dump.return_value = {
            "slug": "btc-updown-5m-1",
            "markets": [{
                "condition_id": "cond-1",
                "question": "Up or Down?",
                "outcomes": {"yes": {"label": "Up", "token_id": "up-1"},
                             "no": {"label": "Down", "token_id": "down-1"}},
            }],
        }
        spec = get_window(c, "btc-updown-5m-1")
        self.assertEqual((spec.up_token_id, spec.down_token_id), ("up-1", "down-1"))


class FidelityTests(unittest.TestCase):
    def _write_run(self, d: Path, slug: str, fills, pending=False):
        rec = {"event_slug": slug, "trades": len(fills), "fills": fills}
        if pending:
            rec["pending"] = True
        (d / f"{slug}.json").write_text(json.dumps(rec))

    def test_fidelity_diff_shape(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self._write_run(d, "w-001",
                            [{"outcome": "Up", "minute": 0}, {"outcome": "Down", "minute": 4}])
            self._write_run(d, "w-002",
                            [{"outcome": "Up", "minute": 1}], pending=True)  # excluded
            rep = fidelity(str(d))
            self.assertEqual(rep["windows"], 1)  # pending excluded
            self.assertEqual(rep["median_trades"], 2)
            self.assertEqual(rep["both_sides"], "1/1")
            self.assertEqual(rep["m_shape"], [1, 0, 0, 0, 1])
            self.assertEqual(rep["target"]["windows"], 288)


class MicropriceLeanTests(unittest.TestCase):
    def test_dumb_cfg_shortcircuits_book(self):
        from bot import live_paper

        c = MagicMock()
        with patch.object(live_paper, "load_cfg",
                          return_value={"entry": {"leanSource": "dumb"}}):
            sig = live_paper.microprice_lean(c, "up", "down")
        self.assertEqual(sig.source, "dumb")
        c.get_midpoint.assert_not_called()

    def test_book_lean_sign_and_neutral_on_error(self):
        from bot import live_paper

        c = MagicMock()
        c.get_midpoint.side_effect = lambda token_id: 0.60 if token_id == "up" else 0.40
        with patch.object(live_paper, "load_cfg", return_value={"entry": {}}):
            sig = live_paper.microprice_lean(c, "up", "down")
        self.assertGreater(sig.lean, 0)
        self.assertEqual(sig.source, "book-microprice")

        bad = MagicMock()
        bad.get_midpoint.side_effect = RuntimeError("no book")
        with patch.object(live_paper, "load_cfg", return_value={"entry": {}}):
            sig = live_paper.microprice_lean(bad, "up", "down")
        self.assertEqual(sig.source, "book-unavailable")
        self.assertEqual(sig.lean, 0.0)


class BuyPriceGuardTests(unittest.TestCase):
    """A $0.00 quote is an empty book, not a free fill.

    Regression: the first 6 live windows recorded 92 fills at $0.00 (91 of
    them in M4) because `get_price(side=BUY)` answers 0 for a side with no
    asks. That skewed the cadence bucket and booked free shares.
    """

    def _px(self, returned):
        from bot import live_paper

        c = MagicMock()
        c.get_price.return_value = returned
        return live_paper.live_buy_price(c, "tok")

    def test_zero_and_negative_quotes_are_no_liquidity(self):
        from decimal import Decimal

        self.assertIsNone(self._px(Decimal("0")))
        self.assertIsNone(self._px(0.0))
        self.assertIsNone(self._px(-0.01))

    def test_out_of_range_quote_rejected(self):
        self.assertIsNone(self._px(1.5))

    def test_valid_quote_is_a_float(self):
        from decimal import Decimal

        self.assertAlmostEqual(self._px(Decimal("0.42")), 0.42)
        self.assertAlmostEqual(self._px(0.57), 0.57)

    def test_book_error_is_no_liquidity(self):
        from bot import live_paper

        c = MagicMock()
        c.get_price.side_effect = RuntimeError("no book")
        self.assertIsNone(live_paper.live_buy_price(c, "tok"))


class LiveWindowVisibilityTests(unittest.TestCase):
    """The next window only appears at 4:45 (last 15s) of the current one."""

    def test_current_only_until_last_15s(self):
        from bot.api import visible_slots
        from bot.discovery import WINDOW_S

        base = 1794082800
        self.assertEqual(visible_slots(base), [base])  # window just opened
        self.assertEqual(visible_slots(base + 284), [base])  # 4:44
        self.assertEqual(visible_slots(base + 285), [base, base + WINDOW_S])  # 4:45
        self.assertEqual(visible_slots(base + 299), [base, base + WINDOW_S])
        self.assertEqual(visible_slots(base + WINDOW_S), [base + WINDOW_S])  # next is current


class TradesViewLiveTests(unittest.TestCase):
    """An open window's fills must reach the table before it closes.

    Regression: trades_view() read paper_runs/ only, so the Live fills table
    froze on the previous window's "awaiting-resolution" row for the whole
    next window.
    """

    def test_live_state_fills_appear_without_a_run_file(self):
        import bot.api as api

        with tempfile.TemporaryDirectory() as td:
            runs = Path(td) / "runs"
            runs.mkdir()
            (runs / "btc-updown-5m-100.json").write_text(json.dumps({
                "event_slug": "btc-updown-5m-100", "trades": 1, "cost_usd": 5.0,
                "payout_usd": 0.0, "net_usd": -5.0, "pending": True,
                "fills": [{"minute": 0, "outcome": "Up", "price": 0.5,
                           "shares": 10, "usd": 5.0}],
            }))
            st = Path(td) / "state.json"
            st.write_text(json.dumps({
                "slug": "btc-updown-5m-400", "updatedAtMs": 1,
                "fills": [{"minute": 2, "outcome": "Down", "price": 0.4,
                           "shares": 30, "usd": 12.0}],
            }))
            with patch.object(api, "RUNS_DIR", runs), patch.object(api, "STATE_PATH", st), patch.object(api, "resolve_run_workspace", return_value=None):
                items = api.trades_view(50)

        live = [t for t in items if t["slug"] == "btc-updown-5m-400"]
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]["price"], 0.4)
        self.assertEqual(live[0]["ts"], 400_000 + 2 * 60_000)
        # The UI reverses the list, so the open window must be last here.
        self.assertEqual(items[-1]["slug"], "btc-updown-5m-400")
        # The pending settle row is still present, just no longer newest.
        self.assertEqual([t["kind"] for t in items], ["entry", "settle", "entry"])

    def test_live_state_fills_merge_with_active_workspace_windows(self):
        import bot.api as api
        from bot.runs import RunWorkspace

        with tempfile.TemporaryDirectory() as td:
            ws = RunWorkspace("run_test", runs_root=Path(td))
            ws.init_workspace()
            (ws.windows_dir / "btc-updown-5m-100.json").write_text(json.dumps({
                "event_slug": "btc-updown-5m-100", "trades": 1, "cost_usd": 5.0,
                "payout_usd": 10.0, "net_usd": 5.0, "winner": "Up",
                "fills": [{"minute": 0, "outcome": "Up", "price": 0.5, "shares": 10, "usd": 5.0}],
            }))
            st = Path(td) / "state.json"
            st.write_text(json.dumps({
                "slug": "btc-updown-5m-400", "updatedAtMs": 1,
                "fills": [{"minute": 1, "outcome": "Down", "price": 0.4, "shares": 20, "usd": 8.0}],
            }))
            with patch.object(api, "STATE_PATH", st), \
                 patch.object(api, "resolve_run_workspace", return_value=ws), \
                 patch.object(api, "is_view_only", return_value=False):
                items = api.trades_view(50)

        slugs = [t["slug"] for t in items]
        self.assertIn("btc-updown-5m-100", slugs)
        self.assertIn("btc-updown-5m-400", slugs)

    def test_snapshot_excludes_unresolved_windows_from_loss_and_drawdown(self):
        import bot.api as api
        from bot.runs import RunWorkspace

        with tempfile.TemporaryDirectory() as td:
            ws = RunWorkspace("run_test", runs_root=Path(td))
            ws.init_workspace()
            # Pending window with $487.79 cost awaiting resolution
            (ws.windows_dir / "btc-updown-5m-1794082800.json").write_text(json.dumps({
                "event_slug": "btc-updown-5m-1794082800",
                "market": "btc-updown-5m-1794082800",
                "trades": 45,
                "cost_usd": 487.79,
                "payout_usd": None,
                "net_usd": -487.79,  # even if old format had -cost
                "winner": None,
                "pending": True,
                "fills": [{"minute": 0, "outcome": "Up", "price": 0.5, "shares": 500, "usd": 250.0}],
            }))
            with patch.object(api, "resolve_run_workspace", return_value=ws), \
                 patch.object(api, "state", return_value=None), \
                 patch.object(api, "is_view_only", return_value=False), \
                 patch.object(api, "live_markets", return_value=[]):
                snap = api.snapshot()

        bankroll = snap["bankrollUsd"]
        self.assertEqual(snap["realizedPnlUsd"], 0.0)
        self.assertEqual(snap["equityUsd"], bankroll)
        self.assertEqual(snap["risk"]["dayStartEquityUsd"], bankroll)
        self.assertEqual(snap["risk"]["highWaterEquityUsd"], bankroll)
        self.assertEqual(snap["risk"]["consecutiveLosses"], 0)

        # Frontend calculations:
        day_loss = max(0, snap["risk"]["dayStartEquityUsd"] - snap["equityUsd"])
        drawdown = max(0, snap["risk"]["highWaterEquityUsd"] - snap["equityUsd"])
        self.assertEqual(day_loss, 0.0)
        self.assertEqual(drawdown, 0.0)

    def test_snapshot_includes_configured_daily_loss_cap(self):
        import bot.api as api
        with tempfile.TemporaryDirectory() as td:
            cfg_file = Path(td) / "config.json"
            cfg_file.write_text(json.dumps({
                "bankrollUsd": 1000.0,
                "risk": {"dailyLossCapUsd": 1500.0}
            }))
            with patch.object(api, "CONFIG_PATH", cfg_file), \
                 patch.object(api, "state", return_value=None), \
                 patch.object(api, "is_view_only", return_value=False), \
                 patch.object(api, "live_markets", return_value=[]):
                snap = api.snapshot()
                self.assertEqual(snap["limits"]["dailyLossCapUsd"], 1500.0)
                self.assertEqual(snap["limits"]["dailyLossLimitPct"], 150.0)

    def test_snapshot_counts_trades_today_from_unix_timestamps(self):
        import bot.api as api
        from bot.runs import RunWorkspace
        from datetime import datetime, timezone

        now_ts = int(datetime.now(timezone.utc).timestamp())
        with tempfile.TemporaryDirectory() as td:
            ws = RunWorkspace("run_test", runs_root=Path(td))
            ws.init_workspace()
            (ws.windows_dir / f"btc-updown-5m-{now_ts}.json").write_text(json.dumps({
                "event_slug": f"btc-updown-5m-{now_ts}",
                "market": f"btc-updown-5m-{now_ts}",
                "trades": 10,
                "cost_usd": 50.0,
                "payout_usd": 60.0,
                "net_usd": 10.0,
                "winner": "Up",
            }))
            with patch.object(api, "resolve_run_workspace", return_value=ws), \
                 patch.object(api, "state", return_value=None), \
                 patch.object(api, "is_view_only", return_value=False), \
                 patch.object(api, "live_markets", return_value=[]):
                snap = api.snapshot()

        self.assertEqual(snap["risk"]["tradesToday"], 1)
        self.assertEqual(snap["realizedPnlUsd"], 10.0)
        self.assertEqual(snap["equityUsd"], snap["bankrollUsd"] + 10.0)
        self.assertEqual(snap["risk"]["consecutiveLosses"], 0)

    def test_snapshot_position_active_when_price_zero_and_window_running(self):
        import time
        import bot.api as api
        from types import SimpleNamespace

        now_ms = int(time.time() * 1000)
        st = {
            "slug": "btc-updown-5m-123",
            "endMs": now_ms + 60_000,
            "startedAtMs": now_ms - 240_000,
            "fills": [
                {"outcome": "Down", "shares": 90, "usd": 34.20},
            ],
        }
        mock_spec = SimpleNamespace(up_token_id="tok_up", down_token_id="tok_down")
        mock_c = MagicMock()
        # Price is 0 for BUY and SELL
        mock_c.get_price.return_value = 0.0
        mock_c.get_midpoint.side_effect = RuntimeError("no midpoint")

        with patch.object(api, "state", return_value=st), \
             patch.object(api, "client", return_value=mock_c), \
             patch("bot.discovery.get_window", return_value=mock_spec), \
             patch.object(api, "is_view_only", return_value=False), \
             patch.object(api, "live_markets", return_value=[]):
            snap = api.snapshot()

        positions = snap["positions"]
        self.assertEqual(len(positions), 1)
        pos = positions[0]
        self.assertEqual(pos["side"], "Down")
        self.assertFalse(pos["resolving"])
        self.assertGreater(pos["secondsLeft"], 0)
        self.assertEqual(pos["mark"], 0.0)
        self.assertEqual(pos["unrealizedPnlUsd"], -34.20)

    def test_snapshot_position_uses_bid_when_ask_is_zero(self):
        import time
        import bot.api as api
        from types import SimpleNamespace

        now_ms = int(time.time() * 1000)
        st = {
            "slug": "btc-updown-5m-123",
            "endMs": now_ms + 53_000,
            "startedAtMs": now_ms - 247_000,
            "fills": [
                {"outcome": "Down", "shares": 90, "usd": 34.20},
            ],
        }
        mock_spec = SimpleNamespace(up_token_id="tok_up", down_token_id="tok_down")
        mock_c = MagicMock()
        # Ask is 0, Bid is 0.01 (1¢)
        def _get_price(token_id, side):
            if side == "BUY":
                return 0.0
            return 0.01
        mock_c.get_price.side_effect = _get_price

        with patch.object(api, "state", return_value=st), \
             patch.object(api, "client", return_value=mock_c), \
             patch("bot.discovery.get_window", return_value=mock_spec), \
             patch.object(api, "is_view_only", return_value=False), \
             patch.object(api, "live_markets", return_value=[]):
            snap = api.snapshot()

        positions = snap["positions"]
        self.assertEqual(len(positions), 1)
        pos = positions[0]
        self.assertEqual(pos["side"], "Down")
        self.assertFalse(pos["resolving"])
        self.assertGreater(pos["secondsLeft"], 0)
        self.assertEqual(pos["mark"], 0.01)
        self.assertEqual(pos["unrealizedPnlUsd"], round(0.01 * 90 - 34.20, 2))

    def test_snapshot_position_resolving_when_window_ended(self):
        import time
        import bot.api as api
        from types import SimpleNamespace

        now_ms = int(time.time() * 1000)
        st = {
            "slug": "btc-updown-5m-123",
            "endMs": now_ms - 5_000,  # window ended 5s ago
            "startedAtMs": now_ms - 305_000,
            "fills": [
                {"outcome": "Down", "shares": 90, "usd": 34.20},
            ],
        }
        mock_spec = SimpleNamespace(up_token_id="tok_up", down_token_id="tok_down")
        mock_c = MagicMock()

        with patch.object(api, "state", return_value=st), \
             patch.object(api, "client", return_value=mock_c), \
             patch("bot.discovery.get_window", return_value=mock_spec), \
             patch.object(api, "is_view_only", return_value=False), \
             patch.object(api, "live_markets", return_value=[]):
            snap = api.snapshot()

        positions = snap["positions"]
        self.assertEqual(len(positions), 1)
        pos = positions[0]
        self.assertEqual(pos["side"], "Down")
        self.assertTrue(pos["resolving"])
        self.assertEqual(pos["secondsLeft"], 0)
        self.assertIsNone(pos["mark"])
        self.assertIsNone(pos["unrealizedPnlUsd"])

    def test_snapshot_position_active_when_get_window_fails(self):
        import time
        import bot.api as api

        now_ms = int(time.time() * 1000)
        st = {
            "slug": "btc-updown-5m-123",
            "endMs": now_ms + 60_000,
            "startedAtMs": now_ms - 240_000,
            "fills": [
                {"outcome": "Up", "shares": 320.88, "usd": 137.98},
            ],
        }

        with patch.object(api, "state", return_value=st), \
             patch("bot.discovery.get_window", side_effect=RuntimeError("Gamma down")), \
             patch.object(api, "is_view_only", return_value=False), \
             patch.object(api, "live_markets", return_value=[]):
            snap = api.snapshot()

        positions = snap["positions"]
        self.assertEqual(len(positions), 1)
        pos = positions[0]
        self.assertEqual(pos["side"], "Up")
        self.assertFalse(pos["resolving"])
        self.assertGreater(pos["secondsLeft"], 0)
        self.assertEqual(pos["mark"], 0.0)
        self.assertEqual(pos["unrealizedPnlUsd"], -137.98)

    def test_snapshot_position_uses_ws_orderbook(self):
        import time
        import bot.api as api

        now_ms = int(time.time() * 1000)
        st = {
            "slug": "btc-updown-5m-123",
            "endMs": now_ms + 60_000,
            "startedAtMs": now_ms - 240_000,
            "fills": [
                {"outcome": "Up", "shares": 100, "usd": 40.0},
            ],
            "ws": {
                "up_book": {"best_bid": 0.25, "best_ask": 0.26, "midpoint": 0.255},
            },
        }

        with patch.object(api, "state", return_value=st), \
             patch.object(api, "is_view_only", return_value=False), \
             patch.object(api, "live_markets", return_value=[]):
            snap = api.snapshot()

        positions = snap["positions"]
        self.assertEqual(len(positions), 1)
        pos = positions[0]
        self.assertEqual(pos["side"], "Up")
        self.assertFalse(pos["resolving"])
        self.assertEqual(pos["mark"], 0.25)
        self.assertEqual(pos["unrealizedPnlUsd"], -15.0)

    def test_snapshot_position_uses_live_markets_quotes(self):
        import time
        import bot.api as api

        now_ms = int(time.time() * 1000)
        slug = "btc-updown-5m-123"
        st = {
            "slug": slug,
            "endMs": now_ms + 60_000,
            "startedAtMs": now_ms - 240_000,
            "fills": [
                {"outcome": "Down", "shares": 100, "usd": 50.0},
            ],
        }
        markets = [{
            "slug": slug,
            "quotes": {
                "Down": {"bid": 0.85, "ask": 0.86},
            },
        }]

        with patch.object(api, "state", return_value=st), \
             patch.object(api, "is_view_only", return_value=False), \
             patch.object(api, "live_markets", return_value=markets):
            snap = api.snapshot()

        positions = snap["positions"]
        self.assertEqual(len(positions), 1)
        pos = positions[0]
        self.assertEqual(pos["side"], "Down")
        self.assertFalse(pos["resolving"])
        self.assertEqual(pos["mark"], 0.85)
        self.assertEqual(pos["unrealizedPnlUsd"], 35.0)


if __name__ == "__main__":
    unittest.main()
