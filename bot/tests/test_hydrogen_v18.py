"""Hydrogen v1.8: 3-layer defense against breakout stranding."""
import unittest

from bot import ab_test as ab
from bot import replay
from bot.executor import (
    H18_BREAKOUT_ASK_MAX,
    H18_BREAKOUT_ASK_MIN,
    H18_HEAVY_FLOOR_BID,
    H18_HEAVY_FLOOR_DIFF,
    evaluate_microstructure_ladder,
)


def _inv(up, up_cost, down, down_cost):
    return {
        "Up": {"shares": float(up), "cost": float(up_cost)},
        "Down": {"shares": float(down), "cost": float(down_cost)},
    }


def _q(up_bid, up_ask, dn_bid, dn_ask):
    return {
        "Up": {"bid": up_bid, "ask": up_ask},
        "Down": {"bid": dn_bid, "ask": dn_ask},
    }


def _dec(quotes, inv, fill_idx=0, **over):
    kw = dict(
        inv=inv,
        fill_idx=fill_idx,
        minute=1,
        strategy_id="hydrogen-v1.8",
        min_fill=0.07,
        max_fill=0.85,
        default_clip=10.0,
        max_clip=10.0,
        max_unhedged_usd=15.0,
        max_unhedged_shares=25.0,
    )
    kw.update(over)
    return evaluate_microstructure_ladder(quotes=quotes, **kw)


class TestHydrogenV18Wiring(unittest.TestCase):
    def test_replay_and_ab_test_mapping(self):
        self.assertIn(replay.STRATEGY_HYDROGEN, ("hydrogen-v1.8", "hydrogen-v1.9"))
        self.assertEqual(
            ab._run_strategy_id("run_20261116_120000_paper_hydrogen_v1_8"),
            "hydrogen-v1.8",
        )


class TestLayer1HeavySideFloorGate(unittest.TestCase):
    def test_blocks_heavy_side_below_45c_in_balanced_mode(self):
        # matched=70 -> tol=10.5; lead=+10 is inside tolerance (balanced mode).
        # Up is cheaper (0.43 < 0.56), so v1.7 would rest more Up; L1 blocks
        # Up (>= 10 sh lead and bid < 0.45) and quotes Down inside ATM instead.
        self.assertEqual(H18_HEAVY_FLOOR_DIFF, 10.0)
        self.assertEqual(H18_HEAVY_FLOOR_BID, 0.45)
        d = _dec(_q(0.43, 0.45, 0.56, 0.58), _inv(80, 36.0, 70, 35.0))
        self.assertEqual(d.action, "fill")
        self.assertEqual(d.outcome, "Down")
        self.assertEqual(d.sub_reason, "split-ladder-maker")
        self.assertEqual(d.price, 0.55)

    def test_reports_heavy_floor_skip_when_opposite_side_unavailable(self):
        # matched=70 -> tol=10.5; lead=+10 inside tol; Up heavy at 0.43, Down has no liquidity.
        d = _dec(_q(0.43, 0.45, None, None), _inv(80, 36.0, 70, 35.0))
        self.assertEqual(d.action, "skip")
        self.assertEqual(d.reason, "heavy-floor-skip")
        self.assertEqual(d.sub_reason, "heavy-floor-gate")

    def test_allows_heavy_side_at_or_above_45c(self):
        # Bid at 0.45 is not < 0.45, so balanced ladder still quotes cheaper Up.
        d = _dec(_q(0.45, 0.47, 0.54, 0.56), _inv(80, 36.0, 70, 35.0))
        self.assertEqual(d.action, "fill")
        self.assertEqual(d.outcome, "Up")
        self.assertEqual(d.price, 0.44)

    def test_allows_small_lead_under_threshold_below_45c(self):
        # lead=+8 < 10 is allowed to rest on cheaper side even at 0.43.
        d = _dec(_q(0.43, 0.45, 0.56, 0.58), _inv(78, 35.0, 70, 35.0))
        self.assertEqual(d.action, "fill")
        self.assertEqual(d.outcome, "Up")
        self.assertEqual(d.price, 0.42)


class TestLayer2UnblockedPassiveRebalance(unittest.TestCase):
    def test_rebalances_58_68_below_breakout_band(self):
        # Reproduce Up=58 (56c), Down=68 (42c) stranding where Up rises to 0.59 ask:
        # v1.8 passively rebalances at bid (0.57) before the 0.60 breakout band.
        inv = _inv(58, 58 * 0.56, 68, 68 * 0.42)
        d = _dec(_q(0.57, 0.59, 0.41, 0.43), inv)
        self.assertEqual(d.action, "fill")
        self.assertEqual(d.outcome, "Up")
        self.assertEqual(d.role, "MAKER")
        self.assertEqual(d.sub_reason, "rebalance-maker")
        self.assertEqual(d.price, 0.57)
        # 10-share deficit split evenly over 2 ladder rungs -> 5.0 per rung.
        self.assertEqual(d.shares, 5.0)

    def test_bypasses_pair_cost_ceiling_above_995(self):
        # Even when projected pair cost > 0.995 (1.016), v1.8 MUST NOT emit pair-cost-skip.
        inv = _inv(58, 58 * 0.60, 68, 68 * 0.42)
        d = _dec(_q(0.57, 0.59, 0.41, 0.43), inv)
        self.assertEqual(d.action, "fill")
        self.assertEqual(d.outcome, "Up")
        self.assertEqual(d.role, "MAKER")
        self.assertEqual(d.sub_reason, "rebalance-maker")
        self.assertGreater(d.projected_pair_cost, 0.995)

    def test_rebalances_outside_atm_even_when_lead_below_big_book_tol(self):
        # matched=100 -> tol=12, so abs(lead)=5 is under tol inside ATM, but the
        # quotes have already left the 42-58c band and the light ask is still
        # below the 0.60 breakout taker band, so the passive maker rebalances.
        d = _dec(_q(0.39, 0.41, 0.57, 0.59), _inv(105, 45.0, 100, 50.0))
        self.assertEqual(d.action, "fill")
        self.assertEqual(d.outcome, "Down")
        self.assertEqual(d.role, "MAKER")
        self.assertEqual(d.sub_reason, "rebalance-maker")
        self.assertEqual(d.shares, 2.5)  # 5 sh deficit split over 2 rungs

    def test_respects_max_fill_ceiling_of_85c(self):
        d = _dec(_q(0.86, 0.88, 0.12, 0.14), _inv(0, 0.0, 10, 4.2))
        self.assertEqual(d.action, "skip")
        self.assertEqual(d.reason, "extreme-price-skip")


class TestLayer3BreakoutEqualizerTaker(unittest.TestCase):
    def test_fires_taker_across_breakout_band_boundaries(self):
        self.assertEqual(H18_BREAKOUT_ASK_MIN, 0.60)
        self.assertEqual(H18_BREAKOUT_ASK_MAX, 0.68)
        inv = _inv(58, 58 * 0.56, 68, 68 * 0.42)
        for ask in (0.60, 0.64, 0.68):
            with self.subTest(ask=ask):
                d = _dec(_q(round(ask - 0.02, 2), ask, 0.30, 0.32), inv)
                self.assertEqual(d.action, "fill")
                self.assertEqual(d.outcome, "Up")
                self.assertEqual(d.role, "TAKER")
                self.assertEqual(d.reason, "balance-topup")
                self.assertEqual(d.sub_reason, "rebalance-taker")
                self.assertEqual(d.price, ask)
                self.assertEqual(d.shares, 10.0)

    def test_above_68c_falls_back_to_passive_maker_up_to_85c(self):
        inv = _inv(58, 58 * 0.56, 68, 68 * 0.42)
        d = _dec(_q(0.70, 0.72, 0.28, 0.30), inv)
        self.assertEqual(d.action, "fill")
        self.assertEqual(d.outcome, "Up")
        self.assertEqual(d.role, "MAKER")
        self.assertEqual(d.sub_reason, "rebalance-maker")
        self.assertEqual(d.price, 0.70)
        self.assertEqual(d.shares, 5.0)

    def test_lead_under_five_does_not_fire_breakout_taker(self):
        # 4-share lead even at 0.64 ask must NOT fire breakout taker (< 5 sh floor).
        d = _dec(_q(0.62, 0.64, 0.36, 0.38), _inv(50, 25.0, 54, 24.0))
        self.assertNotEqual(d.sub_reason, "rebalance-taker")


if __name__ == "__main__":
    unittest.main()
