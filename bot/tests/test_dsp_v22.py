import unittest

from bot.executor import evaluate_microstructure_ladder, select_ladder_clip


class TestDspV22ConfidenceSizing(unittest.TestCase):
    def test_preflight_gate_blocks_stranded_dip(self):
        """Pre-Flight Gate: When Up is 44c and Down ask is 57c (sum=1.01 > 0.995), skip!"""
        inv = {
            "Up": {"shares": 0.0, "cost": 0.0},
            "Down": {"shares": 0.0, "cost": 0.0},
        }
        quotes = {
            "Up": {"bid": 0.44, "ask": 0.45},
            "Down": {"bid": 0.56, "ask": 0.57},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv,
            fill_idx=0,
            minute=0,
            strategy_id="dangerously-skip-permissions-v2.2",
            min_fill=0.07,
            max_fill=0.88,
            max_pair_cost=0.985,
            rescue_max_pair_cost=0.995,
        )
        self.assertEqual(dec.action, "skip")
        self.assertEqual(dec.sub_reason, "pair-cost-cap")

    def test_atomic_arb_heavy_sizing(self):
        """Atomic Arb: when the hedge really is there (0.45 bid + 0.51 ask + fee < 0.985), size heavy (60 sh)."""
        inv = {
            "Up": {"shares": 0.0, "cost": 0.0},
            "Down": {"shares": 0.0, "cost": 0.0},
        }
        quotes = {
            "Up": {"bid": 0.45, "ask": 0.46},
            "Down": {"bid": 0.50, "ask": 0.51},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv,
            fill_idx=0,
            minute=0,
            strategy_id="dangerously-skip-permissions-v2.2",
            min_fill=0.07,
            max_fill=0.88,
            max_pair_cost=0.985,
            rescue_max_pair_cost=0.995,
            max_clip=60.0,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.shares, 60.0)

    def test_hedge_that_only_pays_above_the_pair_cap_is_refused(self):
        """0.44 bid + 0.55 ask + fee > 0.985: the old rescue band (0.995) no longer opens the trade.

        This is the assumption that was removed: a leg only opens when the
        hedge that exists right now still forms a pair under the cap.
        """
        inv = {
            "Up": {"shares": 0.0, "cost": 0.0},
            "Down": {"shares": 0.0, "cost": 0.0},
        }
        quotes = {
            "Up": {"bid": 0.44, "ask": 0.45},
            "Down": {"bid": 0.54, "ask": 0.55},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv,
            fill_idx=0,
            minute=0,
            strategy_id="dangerously-skip-permissions-v2.2",
            min_fill=0.07,
            max_fill=0.88,
            max_pair_cost=0.985,
            rescue_max_pair_cost=0.995,
            max_clip=60.0,
        )
        self.assertEqual(dec.action, "skip")
        self.assertEqual(dec.sub_reason, "pair-cost-cap")

    def test_deficit_hedging_snaps_to_deficit(self):
        """When deficit is 30 sh, equalizer snaps directly to 30 sh."""
        inv = {
            "Up": {"shares": 30.0, "cost": 10.0},
            "Down": {"shares": 0.0, "cost": 0.0},
        }
        quotes = {
            "Up": {"bid": 0.35, "ask": 0.36},
            "Down": {"bid": 0.62, "ask": 0.63},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv,
            fill_idx=1,
            minute=1,
            strategy_id="dangerously-skip-permissions-v2.2",
            min_fill=0.07,
            max_fill=0.88,
            max_pair_cost=0.985,
            rescue_max_pair_cost=0.995,
            max_clip=60.0,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Down")
        self.assertEqual(dec.shares, 30.0)


    def test_the_taker_fee_counts_toward_the_pair(self):
        """0.45 + 0.52 = 0.97 looks like a pair; the hedge's taker fee takes it to 0.9875."""
        quotes = {
            "Up": {"bid": 0.45, "ask": 0.46},
            "Down": {"bid": 0.51, "ask": 0.52},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv={"Up": {"shares": 0.0, "cost": 0.0}, "Down": {"shares": 0.0, "cost": 0.0}},
            fill_idx=0,
            minute=0,
            strategy_id="dangerously-skip-permissions-v2.5",
            min_fill=0.07,
            max_fill=0.88,
            max_pair_cost=0.985,
        )
        self.assertEqual(dec.action, "skip")
        self.assertEqual(dec.sub_reason, "pair-cost-cap")


if __name__ == "__main__":
    unittest.main()
