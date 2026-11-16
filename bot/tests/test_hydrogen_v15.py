"""Hydrogen v1.5: concurrent two-sided accumulation (measured wallet grammar)."""
import unittest
from bot import ab_test as ab
from bot import constants as C
from bot.executor import evaluate_microstructure_ladder


def _inv(up, up_cost, down, down_cost):
    return {
        "Up": {"shares": float(up), "cost": float(up_cost)},
        "Down": {"shares": float(down), "cost": float(down_cost)},
    }


def _q(up_bid, up_ask, dn_bid, dn_ask):
    return {"Up": {"bid": up_bid, "ask": up_ask},
            "Down": {"bid": dn_bid, "ask": dn_ask}}


def _dec(quotes, inv, fill_idx=0, **over):
    kw = dict(inv=inv, fill_idx=fill_idx, minute=1, strategy_id="hydrogen-v1.5",
              min_fill=0.07, max_fill=0.85, default_clip=30.0, max_clip=30.0,
              max_unhedged_usd=45.0)
    kw.update(over)
    return evaluate_microstructure_ladder(quotes=quotes, **kw)


class TestHydrogenV15Registry(unittest.TestCase):
    def test_v15_registered_with_balance_first_entry(self):
        reg = C.STRATEGY_SETUPS.get("hydrogen-v1.5")
        self.assertIsNotNone(reg)
        e = reg["entry"]
        self.assertEqual(e["startAfterOpenSec"], 4)
        self.assertEqual(e["clipSharesDefault"], 30.0)
        self.assertEqual(e["maxShares"], 30.0)
        self.assertEqual(e["clipSchedule"], [[0, 30.0], [120, 15.0]])
        # Balancing ceiling replaces the dip band: the light side may be
        # bought at any price up to 85c.
        self.assertEqual(e["maxFillPrice"], 0.85)
        # No dip/rescue/taker-dip knobs bind the v1.5 path.
        for dead in ("dipCurve", "leg2MaxPrice", "takerDipEntryMax",
                     "takerDipBalancedOnly", "unhedgedStepCents",
                     "unhedgedProbeShares", "lateRescueStartSec",
                     "lateRescueMaxPairCost", "rescuePairCostMax",
                     "rescueCeilingPrice"):
            self.assertNotIn(dead, e)
        # Pair-cost fields stay as reporting benchmarks only.
        self.assertEqual(e["maxPairCost"], 0.985)
        self.assertEqual(e["maxUnhedgedUsd"], 45.0)

    def test_v15_copy_describes_accumulation_not_dips(self):
        reg = C.STRATEGY_SETUPS["hydrogen-v1.5"]
        self.assertIn("Balanced Books", reg["signature"])
        self.assertIn("85", reg["signature"])
        self.assertNotIn("Patient Pair", reg["signature"])
        self.assertIn("lighter side", reg["description"])
        self.assertEqual(reg["configHighlights"]["pairGates"],
                         "reported vs $0.977 wallet benchmark, never gated")

    def test_v15_is_default_candidate(self):
        self.assertEqual(ab.DEFAULT_CANDIDATE_ID, "hydrogen-v1.5")
        self.assertEqual(ab.CANDIDATE_DISPLAY_NAME, "Hydrogen v1.5")
        # v1.4 stays registered as a frozen setup.
        self.assertIsNotNone(C.STRATEGY_SETUPS.get("hydrogen-v1.4"))


class TestConcurrentAccumulation(unittest.TestCase):
    def test_flat_open_buys_cheaper_side(self):
        d = _dec(_q(0.22, 0.24, 0.76, 0.78), _inv(0, 0, 0, 0))
        self.assertEqual((d.action, d.outcome, d.role), ("fill", "Up", "MAKER"))
        self.assertEqual(d.shares, 30.0)

    def test_light_side_bought_first_at_any_price(self):
        # Down light at 70c+ is bought anyway: no dip band, no refusal.
        d = _dec(_q(0.28, 0.30, 0.70, 0.72), _inv(30, 6.9, 0, 0))
        self.assertEqual((d.action, d.outcome), ("fill", "Down"))
        self.assertEqual(d.reason, "balance-topup")

    def test_topup_closes_at_most_half_the_gap(self):
        d = _dec(_q(0.60, 0.62, 0.38, 0.40), _inv(40, 9.2, 0, 0))
        self.assertEqual(d.outcome, "Down")
        self.assertLessEqual(d.shares, 20.0)

    def test_balanced_book_tilts_cheaper_not_rebalance(self):
        d = _dec(_q(0.22, 0.24, 0.76, 0.78), _inv(30, 6.9, 26, 20.0), fill_idx=3)
        self.assertEqual(d.reason, "clip-fill")
        self.assertEqual(d.outcome, "Up")

    def test_ceiling_never_chased(self):
        d = _dec(_q(0.13, 0.15, 0.86, 0.88), _inv(78, 11.7, 0, 0))
        self.assertEqual(d.action, "skip")
        self.assertEqual(d.sub_reason, "ceiling-price-skip")

    def test_wide_book_probe_is_5_share_taker(self):
        d = _dec(_q(0.10, 0.30, 0.70, 0.90 - 0.05), _inv(10, 2.0, 10, 7.0))
        self.assertEqual((d.action, d.role), ("fill", "TAKER"))
        self.assertEqual(d.shares, 5.0)
        self.assertEqual(d.sub_reason, "balance-probe")

    def test_no_pair_cost_gate(self):
        # Projected pair well over $1.00 still fills: reported, not gated.
        d = _dec(_q(0.22, 0.24, 0.76, 0.78), _inv(30, 6.9, 0, 0))
        self.assertEqual(d.action, "fill")
        self.assertIsNotNone(d.projected_pair_cost)

    def test_sweep_stops_opening(self):
        d = _dec(_q(0.22, 0.24, 0.76, 0.78), _inv(30, 6.9, 0, 0),
                 in_sweep_phase=True)
        self.assertEqual((d.action, d.sub_reason), ("skip", "sweep-balanced"))

    def test_strategy_id_mapping_covers_v15(self):
        self.assertEqual(
            ab._run_strategy_id("run_20261116_020000_paper_hydrogen_v1_5"),
            "hydrogen-v1.5",
        )


if __name__ == "__main__":
    unittest.main()
