import unittest

from bot.executor import evaluate_microstructure_ladder


class TestDspV21Family(unittest.TestCase):
    def test_v21_is_treated_as_dsp_and_never_adds_to_naked_leader(self):
        """Regression: v2.1 id must get DSP rules (lead freeze) — it once fell through to HAPCS rules."""
        inv = {
            "Up": {"shares": 30.0, "cost": 8.4},
            "Down": {"shares": 0.0, "cost": 0.0},
        }
        # Up is cheap (dip-buyable) but already leads by 30; Down too expensive to hedge under the 0.995 cap.
        quotes = {
            "Up": {"bid": 0.27, "ask": 0.28},
            "Down": {"bid": 0.71, "ask": 0.72},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv,
            fill_idx=3,
            minute=1,
            strategy_id="dangerously-skip-permissions-v2.1",
            min_fill=0.07,
            max_fill=0.88,
            max_pair_cost=0.985,
            rescue_max_pair_cost=0.995,
            max_share_lead=30.0,
        )
        self.assertNotEqual((dec.action, dec.outcome), ("fill", "Up"))


if __name__ == "__main__":
    unittest.main()
