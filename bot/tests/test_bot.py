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


if __name__ == "__main__":
    unittest.main()
