"""Hydrogen v1.4: wallet-timed, wallet-sized candidate (no share veto)."""
import unittest
from bot import ab_test as ab
from bot import constants as C
from bot.executor import evaluate_microstructure_ladder


def _inv(up, up_cost, down, down_cost):
    return {
        "Up": {"shares": float(up), "cost": float(up_cost)},
        "Down": {"shares": float(down), "cost": float(down_cost)},
    }


class TestHydrogenV14Registry(unittest.TestCase):
    def test_v14_registered_with_wallet_timing_and_sizing(self):
        reg = C.STRATEGY_SETUPS.get("hydrogen-v1.4")
        self.assertIsNotNone(reg)
        e = reg["entry"]
        # Wallet median first fill is T+6s: open at T+4s, not T+15s.
        self.assertEqual(e["startAfterOpenSec"], 4)
        # Wallet measured: 30-share clips at the open, ~15 after T+120s.
        self.assertEqual(e["clipSharesDefault"], 30.0)
        self.assertEqual(e["maxShares"], 30.0)
        self.assertEqual(e["clipSchedule"], [[0, 30.0], [120, 15.0]])
        self.assertEqual(e["unhedgedProbeShares"], 30.0)
        # Pair gates and risk controls carry over from v1.3 unchanged.
        self.assertEqual(e["maxPairCost"], 0.985)
        self.assertEqual(e["maxUnhedgedUsd"], 45.0)
        self.assertNotIn("maxShareLead", e)

    def test_v14_is_default_candidate(self):
        self.assertEqual(ab.DEFAULT_CANDIDATE_ID, "hydrogen-v1.4")
        self.assertEqual(ab.CANDIDATE_DISPLAY_NAME, "Hydrogen v1.4")
        self.assertIn("hydrogen-v1.4", C.STRATEGY_SETUPS)
        # v1.3 stays registered as a frozen setup.
        self.assertIsNotNone(C.STRATEGY_SETUPS.get("hydrogen-v1.3"))


class TestClipSchedule(unittest.TestCase):
    def _decide(self, elapsed, **over):
        kw = dict(
            quotes={"Up": {"bid": 0.33, "ask": 0.34}, "Down": {"bid": 0.60, "ask": 0.62}},
            inv=_inv(0, 0.0, 0, 0.0),
            fill_idx=0, minute=1, strategy_id="hydrogen-v1.4",
            min_fill=0.07, max_fill=0.48, default_clip=30.0, max_clip=30.0,
            max_pair_cost=0.985, elapsed_sec=elapsed,
            clip_schedule=[[0, 30.0], [120, 15.0]],
        )
        kw.update(over)
        return evaluate_microstructure_ladder(**kw)

    def test_opening_clip_is_30(self):
        dec = self._decide(0.0)
        self.assertEqual((dec.action, dec.outcome, dec.shares), ("fill", "Up", 30.0))

    def test_late_clip_decays_to_15(self):
        dec = self._decide(150.0)
        self.assertEqual((dec.action, dec.outcome, dec.shares), ("fill", "Up", 15.0))

    def test_midpoint_interpolates(self):
        dec = self._decide(60.0)
        self.assertEqual((dec.action, dec.outcome, dec.shares), ("fill", "Up", 22.5))

    def test_no_schedule_keeps_flat_default(self):
        dec = evaluate_microstructure_ladder(
            quotes={"Up": {"bid": 0.33, "ask": 0.34}, "Down": {"bid": 0.60, "ask": 0.62}},
            inv=_inv(0, 0.0, 0, 0.0),
            fill_idx=0, minute=1, strategy_id="hydrogen-v1.3",
            min_fill=0.07, max_fill=0.48, default_clip=10.0, max_clip=10.0,
            max_pair_cost=0.985,
        )
        self.assertEqual((dec.action, dec.outcome, dec.shares), ("fill", "Up", 10.0))

    def test_strategy_id_mapping_covers_v14(self):
        self.assertEqual(
            ab._run_strategy_id("run_20261116_020000_paper_hydrogen_v1_4"),
            "hydrogen-v1.4",
        )


if __name__ == "__main__":
    unittest.main()
