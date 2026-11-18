"""Paper economics: rebate tiers, rebated stats, wallet benchmark, archive isolation."""
import unittest
from unittest.mock import patch
import bot.live_paper as lp
from bot import ab_test as ab
from bot import constants as C


class TestArchivedRunExclusion(unittest.TestCase):
    def test_archived_prefix_detected(self):
        # Non-existent / empty runs are not archived.
        self.assertFalse(ab._is_archived_run("run_20990101_000000_paper_hydrogen_v9_9"))
        self.assertFalse(ab._is_archived_run(None))
        self.assertFalse(ab._is_archived_run(""))

    def test_run_name_labels_retired_arm_version(self):
        # Meta-less archived runs must keep their own version, not the candidate id.
        self.assertEqual(
            ab._run_strategy_id("run_20261116_020000_paper_hydrogen_v1_4"),
            "hydrogen-v1.4",
        )
        self.assertEqual(ab._run_strategy_id("run_20261117_005536_paper_hydrogen_v2_0"),
                         "hydrogen-v2.0")


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
        self.assertEqual(C.PAPER_REBATE_TIER_RANGE, (0.25, 0.40, 0.50, 0.60))


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
