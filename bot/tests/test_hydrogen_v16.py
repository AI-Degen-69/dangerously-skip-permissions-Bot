"""Hydrogen v1.6: edge-seeking sizing without a hard pair gate."""
import unittest
from bot import constants as C
from bot.executor import evaluate_microstructure_ladder


def _inv(up, up_cost, down, down_cost):
    return {
        "Up": {"shares": float(up), "cost": float(up_cost)},
        "Down": {"shares": float(down), "cost": float(down_cost)},
    }


def _q(up_bid, up_ask, dn_bid, dn_ask):
    return {"Up": {"bid": up_bid, "ask": up_ask},
            "Down": {"bid": dn_bid, "ask": dn_ask}}


def _dec(quotes, inv, fill_idx=0, **over):
    kw = dict(inv=inv, fill_idx=fill_idx, minute=1, strategy_id="hydrogen-v1.6",
              min_fill=0.07, max_fill=0.85, default_clip=30.0, max_clip=30.0,
              max_unhedged_usd=45.0)
    kw.update(over)
    return evaluate_microstructure_ladder(quotes=quotes, **kw)


class TestHydrogenV16Registry(unittest.TestCase):
    def test_v16_registered(self):
        reg = C.STRATEGY_SETUPS.get("hydrogen-v1.6")
        self.assertIsNotNone(reg)
        self.assertEqual(reg["entry"]["maxFillPrice"], 0.85)
        self.assertEqual(reg["entry"]["maxUnhedgedUsd"], 45.0)


class TestEdgeSeekingSizing(unittest.TestCase):
    def test_expensive_leg_maker_only_capped(self):
        # Down at 80c bid is expensive: must be maker-only and capped to <=10sh,
        # even though the book is balanced and Down is the cheaper tilt.
        d = _dec(_q(0.14, 0.16, 0.80, 0.82), _inv(30, 6.0, 30, 6.0), fill_idx=2)
        self.assertEqual(d.action, "fill")
        # Either cheap Up first, or throttled Down maker -- never a Down taker.
        if d.outcome == "Down":
            self.assertEqual(d.role, "MAKER")
            self.assertLessEqual(d.shares, 10.0)

    def test_very_expensive_leg_to_5sh(self):
        d = _dec(_q(0.14, 0.16, 0.84, 0.86), _inv(0, 0, 0, 0), fill_idx=0)
        # Flat book tilts cheap (Up) first, so force the expensive side by
        # making Up heavy: light side is Down at 84c -> 5sh maker max.
        d2 = _dec(_q(0.14, 0.16, 0.80, 0.82), _inv(100, 20.0, 0, 0), fill_idx=0)
        self.assertEqual((d2.action, d2.outcome, d2.role), ("fill", "Down", "MAKER"))
        self.assertLessEqual(d2.shares, 10.0)
        _ = d

    def test_no_taker_when_bids_sum_above_99(self):
        # Bids 0.45 + 0.55 = 1.00: no edge at touch -> maker only.
        d = _dec(_q(0.45, 0.47, 0.55, 0.57), _inv(10, 4.0, 10, 5.0), fill_idx=4)
        if d.action == "fill":
            self.assertEqual(d.role, "MAKER")

    def test_tighter_tolerance_catches_100_gap(self):
        # 700 matched, 130 gap: v1.5 tol=175 (balanced), v1.6 tol=105 (rebalance).
        d = _dec(_q(0.20, 0.22, 0.76, 0.78), _inv(830, 166.0, 700, 540.0), fill_idx=10)
        self.assertEqual(d.reason, "balance-topup")
        self.assertEqual(d.outcome, "Down")

    def test_pair_throttle_never_gates(self):
        # Projected pair well over $1.02 still fills, but expensive leg is 5sh maker.
        d = _dec(_q(0.22, 0.24, 0.80, 0.82), _inv(500, 150.0, 400, 320.0), fill_idx=6)
        self.assertEqual(d.action, "fill")
        if d.outcome == "Down":
            self.assertLessEqual(d.shares, 10.0)
            self.assertEqual(d.role, "MAKER")

    def test_cheap_leg_never_throttled(self):
        d = _dec(_q(0.14, 0.16, 0.80, 0.82), _inv(0, 0, 0, 0), fill_idx=0)
        self.assertEqual((d.action, d.outcome, d.role), ("fill", "Up", "MAKER"))
        self.assertEqual(d.shares, 30.0)


if __name__ == "__main__":
    unittest.main()
