"""Hydrogen v1.3 promotion: post-PR #56 candidate registry + archive isolation."""
import unittest
from unittest.mock import patch
import bot.live_paper as lp
from bot import ab_test as ab
from bot import constants as C


class TestHydrogenV13Registry(unittest.TestCase):
    def test_v13_registered_with_v12_identical_params(self):
        v12 = C.STRATEGY_SETUPS.get("hydrogen-v1.2")
        v13 = C.STRATEGY_SETUPS.get("hydrogen-v1.3")
        self.assertIsNotNone(v12)
        self.assertIsNotNone(v13)
        # v1.3 is a build/engine bump, NOT a parameter change.
        self.assertEqual(v13["entry"], v12["entry"])
        self.assertNotIn("maxShareLead", v13["entry"])
        self.assertTrue(v13["entry"]["takerDipBalancedOnly"])
        self.assertEqual(v13["name"], "Hydrogen v1.3")

    def test_v13_superseded_but_registered(self):
        # v1.4 is now the default candidate; v1.3 stays frozen and registered.
        self.assertEqual(ab.DEFAULT_CANDIDATE_ID, "hydrogen-v1.5")
        self.assertIn("hydrogen-v1.3", C.STRATEGY_SETUPS)


class TestArchivedRunExclusion(unittest.TestCase):
    def test_archived_prefix_detected(self):
        # Non-existent / empty runs are not archived.
        self.assertFalse(ab._is_archived_run("run_20990101_000000_paper_hydrogen_v9_9"))
        self.assertFalse(ab._is_archived_run(None))
        self.assertFalse(ab._is_archived_run(""))

    def test_strategy_id_mapping_covers_v13(self):
        self.assertEqual(
            ab._run_strategy_id("run_20261116_120000_paper_hydrogen_v1_3"),
            "hydrogen-v1.3",
        )
        self.assertEqual(
            ab._run_strategy_id("run_20261115_233630_paper_hydrogen_v1_2"),
            "hydrogen-v1.2",
        )


class TestPaperRebate(unittest.TestCase):
    def test_rate_from_config(self):
        with patch.object(lp, "load_cfg", return_value={"rebate": {"takerRate": 0.44}}):
            self.assertEqual(lp.paper_rebate_rate(), 0.44)

    def test_rate_clamped_to_unit_interval(self):
        with patch.object(lp, "load_cfg", return_value={"rebate": {"takerRate": 2.0}}):
            self.assertEqual(lp.paper_rebate_rate(), 1.0)
        with patch.object(lp, "load_cfg", return_value={"rebate": {"takerRate": -1.0}}):
            self.assertEqual(lp.paper_rebate_rate(), 0.0)

    def test_rate_defaults_to_top_tier_when_unconfigured(self):
        with patch.object(lp, "load_cfg", return_value={}):
            self.assertEqual(lp.paper_rebate_rate(), C.PAPER_REBATE_TAKER_RATE)
            self.assertEqual(C.PAPER_REBATE_TAKER_RATE, 0.50)

    def test_tier_range_documents_volume_ladder(self):
        self.assertEqual(C.PAPER_REBATE_TIER_RANGE, (0.32, 0.44, 0.50))


class TestRebatedStats(unittest.TestCase):
    def _rec(self, slug, net, rebate, pair_cost=0.97):
        return {
            "slug": slug, "epoch": 0, "net": net, "payout": 5.0,
            "cost": 4.0, "pairCost": pair_cost, "imbalance": 0.0,
            "fills": 2, "upShares": 5.0, "downShares": 5.0,
            "winner": "Up", "feesUsd": 0.10, "makerFeeBaseUsd": 0.0,
            "rebate": rebate,
        }

    def test_stats_carry_rebate_and_rebated_net(self):
        recs = [self._rec("a", 1.0, 0.05), self._rec("b", -2.0, 0.10)]
        stats = ab._compute_distribution_stats(recs, observed_windows=2)
        self.assertEqual(stats["netPnl"], -1.0)
        self.assertEqual(stats["rebateUsd"], 0.15)
        self.assertEqual(stats["netRebated"], -0.85)


class TestWalletBenchmark(unittest.TestCase):
    def test_benchmark_is_measured_median(self):
        self.assertEqual(C.WALLET_MEDIAN_PAIR_COST, 0.977)
        self.assertEqual(ab.get_ab_test_data()["walletBenchmarkPairCost"], 0.977)


if __name__ == "__main__":
    unittest.main()
