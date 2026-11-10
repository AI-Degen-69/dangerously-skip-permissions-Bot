import unittest

from bot.executor import evaluate_microstructure_ladder

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


if __name__ == "__main__":
    unittest.main()
