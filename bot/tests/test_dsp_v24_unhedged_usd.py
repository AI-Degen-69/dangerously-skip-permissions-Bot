import unittest

from bot.executor import dip_curve_shares, evaluate_microstructure_ladder

INV = {"Up": {"shares": 30.0, "cost": 3.0}, "Down": {"shares": 0.0, "cost": 0.0}}
# Down is un-hedgeable (0.99 > rescue ceiling 0.985), so Up is the speculative dip.
QUOTES = {"Up": {"bid": 0.10, "ask": 0.11}, "Down": {"bid": 0.99, "ask": 1.00}}


def _decide(max_unhedged_usd=0.0):
    return evaluate_microstructure_ladder(
        quotes=QUOTES,
        inv=INV,
        fill_idx=0,
        minute=1,
        strategy_id="dangerously-skip-permissions-v2.4",
        min_fill=0.07,
        max_fill=0.45,
        default_clip=10.0,
        max_clip=45.0,
        whole_ladder=True,
        target_pair_cost=0.965,
        max_pair_cost=0.985,
        max_share_lead=46.0,
        max_unhedged_usd=max_unhedged_usd,
        in_sweep_phase=False,
        rescue_ceiling=0.985,
        rescue_max_pair_cost=0.995,
    )


class TestUnhedgedUsdCap(unittest.TestCase):
    """The share knob (maxShareLead) counts shares; this knob counts dollars."""

    def test_off_by_default_is_unchanged(self):
        dec = _decide()
        self.assertEqual((dec.action, dec.outcome), ("fill", "Up"))

    def test_allows_fill_under_the_dollar_cap(self):
        # 10 sh @ 10c on top of 30 sh @ 10c avg -> $4.00 exposed, cap $5.
        dec = _decide(max_unhedged_usd=5.0)
        self.assertEqual((dec.action, dec.outcome), ("fill", "Up"))

    def test_vetoes_fill_above_the_dollar_cap(self):
        dec = _decide(max_unhedged_usd=2.0)
        self.assertNotEqual((dec.action, dec.outcome), ("fill", "Up"))


class TestDipCurveSizing(unittest.TestCase):
    """DSP-v2.5 sizes a fresh dip from the inverse curve, not from a flat clip."""

    CURVE = {"lo": 0.07, "hi": 0.45, "sharesLo": 33.0, "sharesHi": 8.0}

    def test_curve_endpoints_and_midpoint(self):
        self.assertEqual(dip_curve_shares(self.CURVE, 0.07, 45.0), 33.0)
        self.assertEqual(dip_curve_shares(self.CURVE, 0.45, 45.0), 8.0)
        self.assertEqual(dip_curve_shares(self.CURVE, 0.26, 45.0), 20.0)

    def test_curve_clamps_outside_the_band(self):
        self.assertEqual(dip_curve_shares(self.CURVE, 0.05, 45.0), 33.0)
        self.assertEqual(dip_curve_shares(self.CURVE, 0.60, 45.0), 8.0)

    def test_curve_respects_max_clip(self):
        self.assertEqual(dip_curve_shares(self.CURVE, 0.07, 10.0), 10.0)

    def test_v25_dip_uses_the_curve(self):
        # 7c bid: the fat end of the curve, 33 sh instead of the flat 10-share default.
        dec = evaluate_microstructure_ladder(
            quotes={"Up": {"bid": 0.07, "ask": 0.08}, "Down": {"bid": 0.97, "ask": 0.98}},
            inv={"Up": {"shares": 0.0, "cost": 0.0}, "Down": {"shares": 0.0, "cost": 0.0}},
            fill_idx=0,
            minute=1,
            strategy_id="dangerously-skip-permissions-v2.5",
            min_fill=0.07,
            max_fill=0.45,
            default_clip=10.0,
            max_clip=45.0,
            whole_ladder=True,
            target_pair_cost=0.965,
            max_pair_cost=0.985,
            max_share_lead=46.0,
            dip_curve=self.CURVE,
            in_sweep_phase=False,
            rescue_ceiling=0.985,
            rescue_max_pair_cost=0.995,
        )
        self.assertEqual((dec.action, dec.outcome, dec.shares), ("fill", "Up", 33.0))

    def test_opening_straddle_ignores_the_curve(self):
        # 0.52 is above the dip band, so this is straddle-open, sized by clipSharesDefault (10).
        # A stale dipCurve must not thin it (max_fill 0.975 as in the hapcs config).
        dec = evaluate_microstructure_ladder(
            quotes={"Up": {"bid": 0.52, "ask": 0.53}, "Down": {"bid": 0.46, "ask": 0.47}},
            inv={"Up": {"shares": 0.0, "cost": 0.0}, "Down": {"shares": 0.0, "cost": 0.0}},
            fill_idx=0,
            minute=1,
            strategy_id="dangerously-skip-permissions-v2.5",
            min_fill=0.07,
            max_fill=0.975,
            default_clip=10.0,
            max_clip=45.0,
            whole_ladder=True,
            target_pair_cost=0.965,
            max_pair_cost=0.985,
            max_share_lead=46.0,
            dip_curve=self.CURVE,
            in_sweep_phase=False,
            rescue_ceiling=0.985,
            rescue_max_pair_cost=0.995,
        )
        self.assertEqual((dec.action, dec.reason, dec.shares), ("fill", "straddle-open", 10.0))


if __name__ == "__main__":
    unittest.main()
