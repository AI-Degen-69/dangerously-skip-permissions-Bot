"""Fee-base summation for the rebate-adjusted A/B view.

_compute_distribution_stats must sum per-window feesUsd / makerFeeBaseUsd
over active windows only, tolerating missing or None fields (e.g. stats
built before the fee-base change or from a stale cache).
"""
import unittest

from bot import ab_test as ab


def _rec(fills, fees="omit", base="omit"):
    r = {
        "slug": "w",
        "epoch": 0,
        "net": -1.0,
        "payout": 0.0,
        "cost": 0.0,
        "pairCost": 0.0,
        "imbalance": 0.0,
        "fills": fills,
        "upShares": 1,
        "downShares": 0,
        "winner": None,
    }
    if fees != "omit":
        r["feesUsd"] = fees
    if base != "omit":
        r["makerFeeBaseUsd"] = base
    return r


class FeeBasesTest(unittest.TestCase):
    def test_sums_active_windows_only(self):
        recs = [
            _rec(2, fees=1.5, base=0.5),
            _rec(1, fees=2.25, base=1.0),
            _rec(0, fees=100.0, base=100.0),  # inactive: excluded
        ]
        s = ab._compute_distribution_stats(recs)
        self.assertAlmostEqual(s["feesUsd"], 3.75)
        self.assertAlmostEqual(s["makerFeeBaseUsd"], 1.5)

    def test_missing_or_none_fields_default_to_zero(self):
        recs = [_rec(1), _rec(1, fees=None, base=None)]
        s = ab._compute_distribution_stats(recs)
        self.assertEqual(s["feesUsd"], 0.0)
        self.assertEqual(s["makerFeeBaseUsd"], 0.0)


if __name__ == "__main__":
    unittest.main()
