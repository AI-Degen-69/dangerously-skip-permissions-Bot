import unittest
from bot.executor import evaluate_microstructure_ladder
from bot import constants as C


V12_KNOBS = dict(
    strategy_id="hydrogen-v1.2",
    min_fill=0.07,
    max_fill=0.48,
    default_clip=10.0,
    max_clip=10.0,
    dip_curve="hump",
    max_share_lead=11.0,
    max_unhedged_usd=45.0,
    taker_dip_max=0.36,
    taker_dip_balanced_only=True,
    unhedged_step_cents=8.0,
    unhedged_probe_shares=10.0,
    leg1_max_price=0.48,
    leg2_max_price=0.75,
    benchmark_pair_cost=0.96,
    max_pair_cost=0.985,
)


def _inv(up, up_cost, down, down_cost, up_low=None, down_low=None):
    out = {
        "Up": {"shares": float(up), "cost": float(up_cost)},
        "Down": {"shares": float(down), "cost": float(down_cost)},
    }
    if up_low is not None:
        out["Up"]["lowest_price"] = up_low
    if down_low is not None:
        out["Down"]["lowest_price"] = down_low
    return out


class TestHydrogenV12Registry(unittest.TestCase):
    def test_v12_registered_with_bound_lead(self):
        reg = C.STRATEGY_SETUPS.get("hydrogen-v1.2")
        self.assertIsNotNone(reg)
        e = reg["entry"]
        # v1.1 working base is preserved ...
        self.assertEqual(e["takerDipEntryMax"], 0.36)
        self.assertEqual(e["unhedgedStepCents"], 8.0)
        self.assertEqual(e["unhedgedProbeShares"], 10.0)
        self.assertEqual(e["leg1MaxPrice"], 0.48)
        self.assertEqual(e["leg2MaxPrice"], 0.75)
        self.assertEqual(e["targetPairCost"], 0.960)
        self.assertEqual(e["maxPairCost"], 0.985)
        self.assertEqual(e["lateRescueStartSec"], 210)
        self.assertEqual(e["lateRescueMaxPairCost"], 1.02)
        self.assertEqual(e["maxUnhedgedUsd"], 45.0)
        # ... but the 25-share ratchet is gone: every leg is 10sh and the
        # strict veto (lead + shares >= 11) caps directional lead at 10.
        self.assertEqual(e["clipSharesDefault"], 10.0)
        self.assertEqual(e["maxShares"], 10.0)
        self.assertEqual(e["maxClipShares"], 10.0)
        self.assertEqual(e["maxShareLead"], 11.0)
        self.assertTrue(e["takerDipBalancedOnly"])

    def test_v11_frozen_setup_untouched(self):
        reg = C.STRATEGY_SETUPS.get("hydrogen-v1.1")
        self.assertIsNotNone(reg)
        self.assertEqual(reg["entry"]["maxShares"], 25.0)
        self.assertEqual(reg["entry"]["maxShareLead"], 100.0)
        self.assertNotIn("takerDipBalancedOnly", reg["entry"])


class TestHydrogenV12LeadCap(unittest.TestCase):
    def test_flat_book_opens_exactly_10(self):
        dec = evaluate_microstructure_ladder(
            quotes={"Up": {"bid": 0.33, "ask": 0.34},
                    "Down": {"bid": 0.60, "ask": 0.62}},
            inv=_inv(0, 0, 0, 0),
            fill_idx=0,
            minute=0,
            **V12_KNOBS,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.shares, 10.0)

    def test_lead_cannot_exceed_10_shares(self):
        # Up 10 / Down 0: adding 10 more Up would reach lead 20 >= 11, so the
        # engine must NOT add to Up (hedges Down or skips instead).
        dec = evaluate_microstructure_ladder(
            quotes={"Up": {"bid": 0.33, "ask": 0.34},
                    "Down": {"bid": 0.60, "ask": 0.62}},
            inv=_inv(10, 3.4, 0, 0, up_low=0.34),
            fill_idx=1,
            minute=1,
            **V12_KNOBS,
        )
        self.assertFalse(dec.action == "fill" and dec.outcome == "Up",
                         f"lead cap bypassed: {dec}")

    def test_balanced_book_scales_in_10x10_increments(self):
        # Balanced 10/10 with an Up dip: deficit == 0 and lead == 0, so a
        # fresh 10sh Up leg is allowed (20/10, lead back to 10).
        dec = evaluate_microstructure_ladder(
            quotes={"Up": {"bid": 0.33, "ask": 0.34},
                    "Down": {"bid": 0.60, "ask": 0.62}},
            inv=_inv(10, 3.5, 10, 6.0, up_low=0.35, down_low=0.60),
            fill_idx=2,
            minute=1,
            **V12_KNOBS,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Up")
        self.assertEqual(dec.shares, 10.0)
        # ... but the very next Up dip is frozen: lead 10 + 10 >= 11.
        dec2 = evaluate_microstructure_ladder(
            quotes={"Up": {"bid": 0.30, "ask": 0.31},
                    "Down": {"bid": 0.60, "ask": 0.62}},
            inv=_inv(20, 6.8, 10, 6.0, up_low=0.33, down_low=0.60),
            fill_idx=3,
            minute=1,
            **{**V12_KNOBS, "max_clip": 10.0},
        )
        self.assertFalse(dec2.action == "fill" and dec2.outcome == "Up",
                         f"lead cap bypassed: {dec2}")


class TestHydrogenV12BalancedOnlyTakerDip(unittest.TestCase):
    # Loose caps here so ONLY the balanced-only gate decides (v1.2's own
    # maxShareLead=11 would veto these 25sh hump clips via the share cap).
    LOOSE = dict(V12_KNOBS, max_clip=25.0, max_share_lead=100.0,
                 max_unhedged_usd=0.0)

    def _heavy_quotes(self):
        # Up heavy (20/10); Down hedge priced out so the lagging side skips
        # and the heavy Up leg reaches the taker-dip block.
        return ({"Up": {"bid": 0.33, "ask": 0.34},
                 "Down": {"bid": 0.78, "ask": 0.80}},
                _inv(20, 6.8, 10, 6.0, up_low=0.34, down_low=0.60))

    def test_taker_dip_fires_on_heavy_side_without_flag(self):
        quotes, inv = self._heavy_quotes()
        dec = evaluate_microstructure_ladder(
            quotes=quotes, inv=inv, fill_idx=3, minute=1,
            **{**self.LOOSE, "taker_dip_balanced_only": False},
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Up")
        self.assertEqual(dec.role, "TAKER")
        self.assertEqual(dec.sub_reason, "taker-dip-entry")

    def test_taker_dip_vetoed_on_heavy_side_with_flag(self):
        quotes, inv = self._heavy_quotes()
        dec = evaluate_microstructure_ladder(
            quotes=quotes, inv=inv, fill_idx=3, minute=1,
            **{**self.LOOSE, "taker_dip_balanced_only": True},
        )
        # Falls through to the maker path on the same side: never a TAKER
        # cross onto the heavy side.
        if dec.action == "fill" and dec.outcome == "Up":
            self.assertNotEqual(dec.role, "TAKER")
            self.assertNotEqual(dec.sub_reason, "taker-dip-entry")

    def test_taker_dip_still_fires_when_balanced(self):
        dec = evaluate_microstructure_ladder(
            quotes={"Up": {"bid": 0.33, "ask": 0.34},
                    "Down": {"bid": 0.60, "ask": 0.62}},
            inv=_inv(10, 3.5, 10, 6.0, up_low=0.35, down_low=0.60),
            fill_idx=2,
            minute=1,
            **V12_KNOBS,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Up")
        self.assertEqual(dec.role, "TAKER")
        self.assertEqual(dec.sub_reason, "taker-dip-entry")

    def test_light_side_deficit_hedge_unaffected(self):
        # Up leads 10/0 so only Down is a candidate; its deficit hedge must
        # still fill as MAKER with the flag on.
        dec = evaluate_microstructure_ladder(
            quotes={"Up": {"bid": 0.33, "ask": 0.34},
                    "Down": {"bid": 0.60, "ask": 0.62}},
            inv=_inv(10, 3.4, 0, 0, up_low=0.34),
            fill_idx=1,
            minute=1,
            **V12_KNOBS,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Down")
        self.assertEqual(dec.role, "MAKER")


if __name__ == "__main__":
    unittest.main()
