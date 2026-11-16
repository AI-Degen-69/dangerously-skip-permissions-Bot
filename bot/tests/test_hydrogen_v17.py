"""Hydrogen v1.7: 2-level off-touch split ladder + ATM balanced band."""
import unittest

from bot import constants as C
from bot.executor import (
    H17_LADDER_LEVELS,
    H17_LADDER_SPACING,
    H17_LEAD_TOLERANCE_MAX,
    H17_LEAD_TOLERANCE_MIN,
    _h17_atm,
    _h17_tolerance,
    evaluate_microstructure_ladder,
)
from bot.live_paper import cancel_side_orders, ladder_keys, update_maker_order


def _inv(up, up_cost, down, down_cost):
    return {
        "Up": {"shares": float(up), "cost": float(up_cost)},
        "Down": {"shares": float(down), "cost": float(down_cost)},
    }


def _q(up_bid, up_ask, dn_bid, dn_ask):
    return {"Up": {"bid": up_bid, "ask": up_ask},
            "Down": {"bid": dn_bid, "ask": dn_ask}}


def _dec(quotes, inv, fill_idx=0, **over):
    kw = dict(inv=inv, fill_idx=fill_idx, minute=1, strategy_id="hydrogen-v1.7",
              min_fill=0.07, max_fill=0.85, default_clip=10.0, max_clip=10.0,
              max_unhedged_usd=15.0, max_unhedged_shares=25.0)
    kw.update(over)
    return evaluate_microstructure_ladder(quotes=quotes, **kw)


class TestHydrogenV17Registry(unittest.TestCase):
    def test_entry_matches_spec(self):
        entry = C.STRATEGY_SETUPS["hydrogen-v1.7"]["entry"]
        self.assertEqual(entry["clipSchedule"], [[0, 10.0], [120, 8.0]])
        self.assertEqual(entry["maxUnhedgedShares"], 25.0)
        self.assertEqual(entry["maxUnhedgedUsd"], 15.0)
        self.assertEqual(entry["maxFillPrice"], 0.85)

    def test_ladder_shape_configured(self):
        entry = C.STRATEGY_SETUPS["hydrogen-v1.7"]["entry"]
        self.assertEqual(entry["levelsPerSide"], H17_LADDER_LEVELS)
        self.assertEqual(entry["levelSpacing"], H17_LADDER_SPACING)


class TestToleranceScaling(unittest.TestCase):
    def test_floor_below_33_shares(self):
        # 15% of 20 sh is 3 sh: the 5-sh floor wins.
        self.assertEqual(_h17_tolerance(0.0), H17_LEAD_TOLERANCE_MIN)
        self.assertEqual(_h17_tolerance(20.0), H17_LEAD_TOLERANCE_MIN)
        self.assertEqual(_h17_tolerance(33.0), H17_LEAD_TOLERANCE_MIN)

    def test_scales_with_matched_book(self):
        self.assertAlmostEqual(_h17_tolerance(40.0), 6.0, places=4)
        self.assertAlmostEqual(_h17_tolerance(60.0), 9.0, places=4)

    def test_capped_at_twelve(self):
        self.assertEqual(_h17_tolerance(80.0), H17_LEAD_TOLERANCE_MAX)
        self.assertEqual(_h17_tolerance(700.0), H17_LEAD_TOLERANCE_MAX)

    def test_eleven_share_lead_stays_balanced_on_big_book(self):
        # matched 100 -> tol 12, lead 11 is inside: balanced ladder, no top-up.
        d = _dec(_q(0.45, 0.47, 0.56, 0.58), _inv(111, 55.0, 100, 50.0))
        self.assertEqual(d.reason, "clip-fill")
        self.assertEqual(d.sub_reason, "split-ladder-maker")

    def test_fifteen_share_lead_on_tiny_book_rebalances(self):
        # matched 10 -> tol 5, lead 8 is over: the lighter side is topped up.
        d = _dec(_q(0.38, 0.40, 0.45, 0.52), _inv(18, 9.0, 10, 5.0))
        self.assertEqual(d.reason, "balance-topup")
        self.assertEqual(d.outcome, "Down")


class TestAtmBandGating(unittest.TestCase):
    def test_band_limits(self):
        self.assertTrue(_h17_atm(0.42))
        self.assertTrue(_h17_atm(0.58))
        self.assertFalse(_h17_atm(0.41))
        self.assertFalse(_h17_atm(0.59))
        self.assertFalse(_h17_atm(None))

    def test_inside_band_quotes_maker(self):
        d = _dec(_q(0.45, 0.48, 0.55, 0.58), _inv(0, 0, 0, 0), fill_idx=2)
        self.assertEqual(d.action, "fill")
        self.assertEqual(d.outcome, "Up")
        self.assertEqual(d.role, "MAKER")

    def test_upper_band_quotes(self):
        # Down at 0.58 is the cheaper leg inside the band.
        d = _dec(_q(0.58, 0.60, 0.57, 0.59), _inv(0, 0, 0, 0), fill_idx=1)
        self.assertEqual(d.action, "fill")
        self.assertEqual(d.outcome, "Down")
        self.assertEqual(d.price, 0.56)

    def test_outside_band_skips(self):
        d = _dec(_q(0.20, 0.22, 0.80, 0.82), _inv(0, 0, 0, 0))
        self.assertEqual(d.action, "skip")
        self.assertEqual(d.reason, "off-atm-skip")

    def test_one_side_in_band_is_enough(self):
        d = _dec(_q(0.39, 0.41, 0.58, 0.60), _inv(0, 0, 0, 0), fill_idx=3)
        self.assertEqual((d.action, d.outcome), ("fill", "Down"))

    def test_sweep_phase_stops_quoting(self):
        d = _dec(_q(0.45, 0.48, 0.55, 0.58), _inv(10, 4.5, 10, 5.5),
                 in_sweep_phase=True)
        self.assertEqual(d.action, "skip")
        self.assertEqual(d.reason, "sweep-balanced")


class TestSplitLadderExecution(unittest.TestCase):
    def test_two_rungs_split_the_clip_one_cent_apart(self):
        d = _dec(_q(0.45, 0.48, 0.55, 0.58), _inv(0, 0, 0, 0), fill_idx=2)
        self.assertEqual(d.price, 0.44)          # -1c off the 0.45 touch
        self.assertEqual(d.shares, 5.0)          # 10-share clip split over 2 rungs
        self.assertEqual(d.price - H17_LADDER_SPACING, 0.43)  # -2c rung

    def test_clip_schedule_governs_per_level_size(self):
        d = _dec(_q(0.45, 0.48, 0.55, 0.58), _inv(0, 0, 0, 0),
                 default_clip=8.0, max_clip=8.0)
        self.assertEqual(d.shares, 4.0)

    def test_balanced_mode_never_takes(self):
        # Wide book with a tempting ask: a taker probe is exactly what v1.7 drops.
        d = _dec(_q(0.45, 0.70, 0.55, 0.72), _inv(0, 0, 0, 0), fill_idx=0)
        self.assertEqual(d.action, "fill")
        self.assertEqual(d.role, "MAKER")
        self.assertEqual(d.price, 0.44)

    def test_ladder_rungs_rest_independently(self):
        orders: dict[str, dict] = {}
        update_maker_order(orders, "Up", 0.44, 5.0, 0, "clip-fill",
                           "split-ladder-maker", 0.0, 10.0, 1000.0, order_key="Up")
        update_maker_order(orders, "Up", 0.43, 5.0, 0, "clip-fill",
                           "split-ladder-maker", 0.0, 12.0, 1000.0, order_key="Up#1")
        update_maker_order(orders, "Down", 0.55, 5.0, 0, "clip-fill",
                           "split-ladder-maker", 0.0, 8.0, 1000.0)
        self.assertEqual(ladder_keys(orders, "Up"), ["Up", "Up#1"])
        self.assertEqual(ladder_keys(orders, "Down"), ["Down"])
        # Rungs report their real side, so the fill loops can match them.
        self.assertEqual(orders["Up#1"]["side"], "Up")
        self.assertEqual(orders["Up"]["shares_left"], 5.0)
        self.assertEqual(orders["Up#1"]["price"], 0.43)

    def test_cancel_side_pulls_every_rung_only(self):
        orders: dict[str, dict] = {}
        for key, px in (("Up", 0.44), ("Up#1", 0.43)):
            update_maker_order(orders, "Up", px, 5.0, 0, "clip-fill",
                               "split-ladder-maker", 0.0, 1.0, 1000.0, order_key=key)
        update_maker_order(orders, "Down", 0.55, 5.0, 0, "clip-fill",
                           "split-ladder-maker", 0.0, 1.0, 1000.0)
        pulled = cancel_side_orders(orders, "Up")
        self.assertEqual(len(pulled), 2)
        self.assertEqual(set(orders), {"Down"})


class TestUnhedgedCaps(unittest.TestCase):
    def test_share_cap_blocks_top_up(self):
        # Balanced book, cheaper Up tilt, but the extra rung would leave a
        # 6-share unhedged lead against a 2-share cap.
        d = _dec(_q(0.40, 0.42, 0.58, 0.60), _inv(101, 40.4, 100, 50.0),
                 max_unhedged_shares=2.0)
        self.assertEqual(d.action, "skip")
        self.assertEqual(d.reason, "unhedged-cap-skip")

    def test_usd_cap_blocks_top_up(self):
        d = _dec(_q(0.40, 0.42, 0.58, 0.60), _inv(101, 40.4, 100, 50.0),
                 max_unhedged_shares=0.0, max_unhedged_usd=0.5)
        self.assertEqual(d.action, "skip")
        self.assertEqual(d.reason, "unhedged-cap-skip")

    def test_hedging_the_light_side_is_never_capped(self):
        # Over tolerance: buying Down shrinks the lead, so the caps must not fire.
        d = _dec(_q(0.45, 0.47, 0.56, 0.58), _inv(60, 27.0, 10, 5.0),
                 max_unhedged_shares=1.0, max_unhedged_usd=0.1)
        self.assertEqual(d.action, "fill")
        self.assertEqual(d.outcome, "Down")

    def test_pair_ceiling_blocks_overpriced_rung(self):
        # Up averaged 0.70 with Down at 0.55: the ladder's projected pair is
        # 1.15, over the 0.995 balanced ceiling.
        d = _dec(_q(0.45, 0.47, 0.55, 0.57), _inv(100, 70.0, 100, 55.0))
        self.assertEqual(d.action, "skip")
        self.assertEqual(d.reason, "pair-cost-skip")


if __name__ == "__main__":
    unittest.main()
