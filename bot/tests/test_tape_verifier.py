"""Unit tests for the tape verification engine (bot/tape_verifier.py)."""

import json
import tempfile
import time
import unittest
from pathlib import Path

from bot.tape_verifier import (
    verify_single_fill,
    verify_fills,
    verification_summary,
    load_prints_for_window,
    GRACE_PERIOD_S,
)


def _make_fill(outcome="Down", price=0.42, shares=10, role="MAKER", ts_ms=None):
    if ts_ms is None:
        ts_ms = int((time.time() - 60) * 1000)  # 1 min ago
    return {
        "minute": 0,
        "ts": ts_ms,
        "outcome": outcome,
        "price": price,
        "shares": shares,
        "usd": round(shares * price, 2),
        "reason": "maker-dip-ladder",
        "detail": {
            "role": role,
            "subReason": "maker-dip-ladder",
        },
    }


def _make_print(outcome="Down", price=0.42, size=50.0, ts=None):
    if ts is None:
        ts = time.time() - 30  # 30s ago
    return {
        "ts": ts,
        "slug_outcome": outcome,
        "price": price,
        "size": size,
        "side": "BUY",
    }


class TestVerifySingleFill(unittest.TestCase):

    def test_maker_verified_print_at_level(self):
        fill = _make_fill(price=0.42, shares=10, ts_ms=int((time.time() - 60) * 1000))
        prints = [_make_print(price=0.42, size=50.0, ts=time.time() - 30)]
        result = verify_single_fill(fill, prints)
        self.assertEqual(result["tapeStatus"], "verified")
        self.assertGreaterEqual(result["tapePrintSize"], 10)

    def test_maker_verified_print_through_level(self):
        fill = _make_fill(price=0.42, shares=10, ts_ms=int((time.time() - 60) * 1000))
        prints = [_make_print(price=0.40, size=20.0, ts=time.time() - 30)]
        result = verify_single_fill(fill, prints)
        self.assertEqual(result["tapeStatus"], "verified")

    def test_maker_partial_insufficient_size(self):
        fill = _make_fill(price=0.42, shares=10, ts_ms=int((time.time() - 60) * 1000))
        prints = [_make_print(price=0.42, size=5.0, ts=time.time() - 30)]
        result = verify_single_fill(fill, prints)
        self.assertEqual(result["tapeStatus"], "partial")
        self.assertEqual(result["tapePrintSize"], 5.0)

    def test_maker_unverified_no_prints(self):
        fill = _make_fill(price=0.42, shares=10, ts_ms=int((time.time() - 60) * 1000))
        result = verify_single_fill(fill, [])
        self.assertEqual(result["tapeStatus"], "unverified")

    def test_maker_unverified_prints_above_level(self):
        fill = _make_fill(price=0.42, shares=10, ts_ms=int((time.time() - 60) * 1000))
        prints = [_make_print(price=0.45, size=100.0, ts=time.time() - 30)]
        result = verify_single_fill(fill, prints)
        self.assertEqual(result["tapeStatus"], "unverified")

    def test_maker_unverified_prints_before_fill(self):
        fill_ts = time.time() - 60
        fill = _make_fill(price=0.42, shares=10, ts_ms=int(fill_ts * 1000))
        prints = [_make_print(price=0.42, size=100.0, ts=fill_ts - 10)]
        result = verify_single_fill(fill, prints)
        self.assertEqual(result["tapeStatus"], "unverified")

    def test_maker_cumulative_size_across_prints(self):
        fill = _make_fill(price=0.42, shares=10, ts_ms=int((time.time() - 60) * 1000))
        prints = [
            _make_print(price=0.42, size=4.0, ts=time.time() - 50),
            _make_print(price=0.41, size=3.0, ts=time.time() - 40),
            _make_print(price=0.42, size=5.0, ts=time.time() - 30),
        ]
        result = verify_single_fill(fill, prints)
        self.assertEqual(result["tapeStatus"], "verified")
        self.assertEqual(result["tapePrintSize"], 12.0)
        self.assertEqual(result["tapePrintCount"], 3)

    def test_taker_always_unverified(self):
        fill = _make_fill(role="TAKER", ts_ms=int((time.time() - 60) * 1000))
        prints = [_make_print(price=0.42, size=100.0, ts=time.time() - 30)]
        result = verify_single_fill(fill, prints)
        self.assertEqual(result["tapeStatus"], "unverified-taker")

    def test_grace_period_pending(self):
        fill = _make_fill(ts_ms=int(time.time() * 1000))  # just now
        prints = [_make_print(price=0.42, size=100.0, ts=time.time())]
        result = verify_single_fill(fill, prints)
        self.assertEqual(result["tapeStatus"], "pending")

    def test_grace_period_bypassed_when_forced(self):
        # The window-close final pass force-verifies, so a fill younger than
        # the grace period must still get a definitive status.
        fill = _make_fill(ts_ms=int(time.time() * 1000))  # just now
        prints = [_make_print(price=0.42, size=100.0, ts=time.time())]
        result = verify_single_fill(fill, prints, force=True)
        self.assertEqual(result["tapeStatus"], "verified")

    def test_wrong_outcome_ignored(self):
        fill = _make_fill(outcome="Down", price=0.42, shares=10, ts_ms=int((time.time() - 60) * 1000))
        prints = [_make_print(outcome="Up", price=0.42, size=100.0, ts=time.time() - 30)]
        result = verify_single_fill(fill, prints)
        self.assertEqual(result["tapeStatus"], "unverified")


class TestVerifyFills(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.tape_dir = self.tmp / "tape"
        self.tape_dir.mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_prints(self, prints):
        with open(self.tape_dir / "prints.jsonl", "w") as f:
            for p in prints:
                f.write(json.dumps(p) + "\n")

    def test_verify_fills_stamps_all(self):
        now = time.time()
        fills = [
            _make_fill(outcome="Down", price=0.42, shares=10, ts_ms=int((now - 60) * 1000)),
            _make_fill(outcome="Up", price=0.55, shares=10, role="TAKER", ts_ms=int((now - 55) * 1000)),
        ]
        self._write_prints([
            _make_print(outcome="Down", price=0.42, size=50.0, ts=now - 30),
        ])
        changed = verify_fills(fills, self.tape_dir, window_start_s=now - 120)
        self.assertEqual(fills[0]["detail"]["tapeStatus"], "verified")
        self.assertEqual(fills[1]["detail"]["tapeStatus"], "unverified-taker")

    def test_skip_already_verified(self):
        now = time.time()
        fill = _make_fill(ts_ms=int((now - 60) * 1000))
        fill["detail"]["tapeStatus"] = "verified"
        self._write_prints([])
        changed = verify_fills([fill], self.tape_dir, window_start_s=now - 120)
        self.assertEqual(changed, 0)
        self.assertEqual(fill["detail"]["tapeStatus"], "verified")

    def test_force_reverifies(self):
        now = time.time()
        fill = _make_fill(ts_ms=int((now - 60) * 1000))
        fill["detail"]["tapeStatus"] = "verified"
        self._write_prints([])  # no prints → should become unverified
        changed = verify_fills([fill], self.tape_dir, window_start_s=now - 120, force=True)
        self.assertEqual(fill["detail"]["tapeStatus"], "unverified")
        self.assertEqual(changed, 1)


class TestVerificationSummary(unittest.TestCase):

    def test_summary_counts(self):
        fills = [
            {"detail": {"tapeStatus": "verified"}},
            {"detail": {"tapeStatus": "verified"}},
            {"detail": {"tapeStatus": "partial"}},
            {"detail": {"tapeStatus": "unverified"}},
            {"detail": {"tapeStatus": "unverified-taker"}},
            {"detail": {"tapeStatus": "pending"}},
            {"detail": {}},
        ]
        s = verification_summary(fills)
        self.assertEqual(s["verified"], 2)
        self.assertEqual(s["partial"], 1)
        self.assertEqual(s["unverified"], 1)
        self.assertEqual(s["unverifiedTaker"], 1)
        self.assertEqual(s["pending"], 1)
        self.assertEqual(s["unknown"], 1)
        self.assertEqual(s["total"], 7)
        # verifiedPct = 2/(2+1+1) = 66.7%
        self.assertAlmostEqual(s["verifiedPct"], 50.0, places=1)

    def test_empty(self):
        s = verification_summary([])
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["verifiedPct"], 0.0)


class TestLoadPrints(unittest.TestCase):

    def test_filters_by_window(self):
        tmp = Path(tempfile.mkdtemp())
        tape = tmp / "tape"
        tape.mkdir()
        prints = [
            {"ts": 100, "slug_outcome": "Down", "price": 0.4, "size": 10},
            {"ts": 200, "slug_outcome": "Down", "price": 0.4, "size": 20},
            {"ts": 300, "slug_outcome": "Down", "price": 0.4, "size": 30},
        ]
        with open(tape / "prints.jsonl", "w") as f:
            for p in prints:
                f.write(json.dumps(p) + "\n")

        result = load_prints_for_window(tape, 150, 250)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ts"], 200)

        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
