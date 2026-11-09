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
        """Atomic Arb: When Up is 45c and Down is 53c (sum=0.98 <= 0.990), size heavy (60 sh)!"""
        inv = {
            "Up": {"shares": 0.0, "cost": 0.0},
            "Down": {"shares": 0.0, "cost": 0.0},
        }
        quotes = {
            "Up": {"bid": 0.45, "ask": 0.46},
            "Down": {"bid": 0.53, "ask": 0.54},
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

    def test_speculative_dip_micro_sizing(self):
        """Speculative Dip: When Up is 44c and Down ask is 55c (sum=0.991 <= 0.995), size micro (10 sh)!"""
        inv = {
            "Up": {"shares": 0.0, "cost": 0.0},
            "Down": {"shares": 0.0, "cost": 0.0},
        }
        quotes = {
            "Up": {"bid": 0.44, "ask": 0.45},
            "Down": {"bid": 0.54, "ask": 0.551},
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
        self.assertEqual(dec.shares, 10.0)

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


if __name__ == "__main__":
    unittest.main()
