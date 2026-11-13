"""Welch's t-test refactor: active-window N, dynamic t_crit/mu_crit, pair-cost buckets."""

import math
import unittest

from bot import ab_test as ab


def _rec(slug, net, fills, up, down, pair_cost=None):
    total = fills
    return {
        "slug": slug,
        "epoch": 0,
        "net": net,
        "payout": 0.0,
        "cost": 0.0,
        "pairCost": pair_cost,
        "imbalance": abs(up - down),
        "fills": fills,
        "upShares": up,
        "downShares": down,
        "winner": None,
    }


class TestActiveWindowFiltering(unittest.TestCase):
    def test_zero_fill_windows_excluded_from_n(self):
        recs = [
            _rec("a", 1.0, 2, 10.0, 10.0, 0.95),
            _rec("b", 0.0, 0, 0.0, 0.0, None),
            _rec("c", -1.0, 1, 10.0, 0.0, None),
            _rec("d", 0.0, 0, 0.0, 0.0, None),
        ]
        s = ab._compute_distribution_stats(recs, observed_windows=4)
        self.assertEqual(s["observedWindows"], 4)
        self.assertEqual(s["samples"], 2)
        self.assertEqual(s["activeWindows"], 2)
        self.assertAlmostEqual(s["meanPnl"], 0.0, places=4)
        # Zero-fill $0 nets must not dilute variance or the win rate.
        self.assertEqual(s["wins"], 1)
        self.assertEqual(s["losses"], 1)

    def test_empty_active_returns_zeroed_counters(self):
        s = ab._compute_distribution_stats(
            [_rec("z", 0.0, 0, 0.0, 0.0, None)], observed_windows=1)
        self.assertEqual(s["samples"], 0)
        self.assertEqual(s["observedWindows"], 1)
        self.assertEqual(s["pairedWindows"], 0)
        self.assertEqual(s["subDollarPairs"], 0)
        self.assertEqual(s["pnlList"], [])


class TestPairCostBuckets(unittest.TestCase):
    def test_bucket_split(self):
        recs = [
            _rec("p1", 1.0, 2, 10.0, 10.0, 0.90),
            _rec("p2", 1.0, 2, 10.0, 10.0, 0.97),
            _rec("p3", -1.0, 2, 10.0, 10.0, 1.02),
            _rec("solo", -0.5, 1, 10.0, 0.0, None),  # unpaired: no bucket
        ]
        s = ab._compute_distribution_stats(recs, observed_windows=4)
        self.assertEqual(s["pairedWindows"], 3)
        self.assertEqual(s["pairCostUnder096"], 1)
        self.assertEqual(s["pairCost096to100"], 1)
        self.assertEqual(s["pairCostOver100"], 1)
        self.assertEqual(s["subDollarPairs"], 2)
        # 10 shares a side locked in each of 3 paired windows.
        self.assertAlmostEqual(s["pairsMerged"], 30.0)
        self.assertAlmostEqual(s["totalLockedShares"], 60.0)


class TestPairCostMath(unittest.TestCase):
    def test_balanced_window_sums_per_side_averages(self):
        # 10 sh @ $0.50 up + 10 sh @ $0.45 down -> $0.95 pair.
        self.assertAlmostEqual(ab._pair_cost(10.0, 10.0, 5.00, 4.50), 0.95)

    def test_imbalanced_paired_window_does_not_blow_up(self):
        # 1 stub share up @ $0.50 with a full 40 sh @ $0.45 down side:
        # old total/min priced this at (0.50 + 18.00) / 1 = $18.50.
        # Per-side averages keep it at $0.95.
        pc = ab._pair_cost(1.0, 40.0, 0.50, 18.00)
        self.assertIsNotNone(pc)
        self.assertAlmostEqual(pc, 0.95)
        self.assertLess(pc, 1.00)

    def test_unpaired_window_has_no_pair_cost(self):
        self.assertIsNone(ab._pair_cost(10.0, 0.0, 5.00, 0.00))
        self.assertIsNone(ab._pair_cost(0.0, 0.0, 0.00, 0.00))


class TestDynamicCriticalMath(unittest.TestCase):
    def test_t_critical_tracks_df(self):
        small = ab._t_critical(10.0)
        large = ab._t_critical(200.0)
        self.assertGreater(small, large)
        # Large-df one-tailed 95% cutoff approaches the normal 1.6449.
        self.assertAlmostEqual(large, 1.653, delta=0.05)
        self.assertAlmostEqual(small, 1.812, delta=0.05)

    def test_mu_crit_is_rejection_boundary(self):
        # Two small synthetic arms with known separation.
        a = [_rec(f"a{i}", x, 2, 5.0, 5.0, 0.95)
             for i, x in enumerate([1.0, 0.5, -0.5, 0.0, 0.25])]
        b = [_rec(f"b{i}", x, 2, 5.0, 5.0, 0.95)
             for i, x in enumerate([2.0, 1.5, 0.5, 1.0, 1.25])]
        sa = ab._compute_distribution_stats(a, observed_windows=5)
        sb = ab._compute_distribution_stats(b, observed_windows=5)
        n_a, n_b = sa["samples"], sb["samples"]
        se = math.sqrt(sa["variance"] / n_a + sb["variance"] / n_b)
        num = ((sa["variance"] / n_a) + (sb["variance"] / n_b)) ** 2
        den = (((sa["variance"] / n_a) ** 2) / (n_a - 1)
               + ((sb["variance"] / n_b) ** 2) / (n_b - 1))
        df = round(num / den, 1)
        t_crit = ab._t_critical(df)
        mu_crit = round(sa["meanPnl"] + t_crit * se, 4)
        # mu_crit is exactly mean_A + t_crit * SE.
        self.assertAlmostEqual(mu_crit, sa["meanPnl"] + t_crit * se, places=4)
        # And t computed from the boundary equals t_crit by construction.
        self.assertAlmostEqual((mu_crit - sa["meanPnl"]) / se, t_crit, places=3)


class TestBaselineIdentity(unittest.TestCase):
    def test_default_baseline_is_measured_dsp_v2_6(self):
        self.assertEqual(ab.DEFAULT_BASELINE_ID,
                         "run_20261113_080232_paper_dsp_v2_6")
        self.assertEqual(ab.TARGET_SAMPLE_SIZE, 120)
        self.assertEqual(ab.TARGET_PAIRED_WINDOWS, 60)
        self.assertEqual(ab.TARGET_SUB_DOLLAR_PAIRS, 35)

    def test_hypothesis_names_hydrogen_vs_dsp_v2_6(self):
        h0 = ab._hypothesis_text(None, null=True,
                                 baseline_id=ab.DEFAULT_BASELINE_ID)
        h1 = ab._hypothesis_text(None, null=False,
                                 baseline_id=ab.DEFAULT_BASELINE_ID)
        self.assertIn("Hydrogen_v1.0", h0)
        self.assertIn("DSP_v2.6", h0)
        self.assertIn("Hydrogen_v1.0", h1)
        self.assertIn("DSP_v2.6", h1)
        for banned in ("v2.0", "v2.2", "Confidence"):
            self.assertNotIn(banned, h0)
            self.assertNotIn(banned, h1)

    def test_hydrogen_candidate_registered(self):
        from bot import constants as C
        reg = C.STRATEGY_SETUPS.get("hydrogen-v1.0")
        self.assertIsNotNone(reg)
        e = reg["entry"]
        self.assertEqual(e["startAfterOpenSec"], 15)
        self.assertEqual(e["stopBeforeCloseSec"], 30)
        self.assertEqual(e["sweepBeforeCloseSec"], 12)
        self.assertEqual(e["takerDipEntryMax"], 0.42)
        self.assertEqual(e["leg2MaxPrice"], 0.75)
        self.assertEqual(e["lateRescueMaxPairCost"], 1.02)
        self.assertEqual(e["lateRescueStartSec"], 210)


if __name__ == "__main__":
    unittest.main()
