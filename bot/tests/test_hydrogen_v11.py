import unittest
from bot.executor import evaluate_microstructure_ladder
from bot import constants as C


class TestHydrogenV11Knobs(unittest.TestCase):
    def setUp(self):
        self.quotes_dip = {
            "Up": {"bid": 0.34, "ask": 0.35},
            "Down": {"bid": 0.63, "ask": 0.64},
        }

    def test_unhedged_probe_shares_caps_leg1_clip(self):
        inv_flat = {
            "Up": {"shares": 0.0, "cost": 0.0},
            "Down": {"shares": 0.0, "cost": 0.0},
        }
        dec = evaluate_microstructure_ladder(
            quotes=self.quotes_dip,
            inv=inv_flat,
            fill_idx=0,
            minute=0,
            strategy_id="hydrogen-v1.1",
            max_clip=25.0,
            dip_curve="hump",
            taker_dip_max=0.36,
            unhedged_probe_shares=10.0,
            unhedged_step_cents=8.0,
            min_fill=0.07,
            max_fill=0.48,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Up")
        # Probe knob caps fresh Leg-1 clip size at 10 shares
        self.assertEqual(dec.shares, 10.0)

    def test_unhedged_probe_shares_unlocks_when_opposite_shares_exist(self):
        # Once opposite shares > 0, paired clips unlock to full maxClipShares (25.0)
        inv_paired = {
            "Up": {"shares": 10.0, "cost": 3.5, "lowest_price": 0.35},
            "Down": {"shares": 10.0, "cost": 6.0, "lowest_price": 0.60},
        }
        dec = evaluate_microstructure_ladder(
            quotes=self.quotes_dip,
            inv=inv_paired,
            fill_idx=2,
            minute=1,
            strategy_id="hydrogen-v1.1",
            max_clip=25.0,
            dip_curve="hump",
            taker_dip_max=0.36,
            unhedged_probe_shares=10.0,
            unhedged_step_cents=8.0,
            min_fill=0.07,
            max_fill=0.48,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Up")
        # Unlocked to full max_clip (25.0 shares)
        self.assertEqual(dec.shares, 25.0)

    def test_unhedged_step_cents_allows_first_fill(self):
        inv_flat = {
            "Up": {"shares": 0.0, "cost": 0.0},
            "Down": {"shares": 0.0, "cost": 0.0},
        }
        dec = evaluate_microstructure_ladder(
            quotes=self.quotes_dip,
            inv=inv_flat,
            fill_idx=0,
            minute=0,
            strategy_id="hydrogen-v1.1",
            unhedged_step_cents=8.0,
            unhedged_probe_shares=10.0,
            taker_dip_max=0.36,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Up")

    def test_unhedged_step_cents_forbids_additional_unhedged_fill_above_step(self):
        # Up holds 10 shares at 0.35, Down holds 0 shares.
        # With 8.0c step, next unhedged Up fill must be <= 0.35 - 0.08 = 0.27.
        inv_unhedged = {
            "Up": {"shares": 10.0, "cost": 3.5, "lowest_price": 0.35},
            "Down": {"shares": 0.0, "cost": 0.0},
        }
        quotes_too_high = {
            "Up": {"bid": 0.31, "ask": 0.32},
            "Down": {"bid": 0.66, "ask": 0.67},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes_too_high,
            inv=inv_unhedged,
            fill_idx=1,
            minute=1,
            strategy_id="hydrogen-v1.1",
            unhedged_step_cents=8.0,
            unhedged_probe_shares=10.0,
            taker_dip_max=0.36,
        )
        # Should be forbidden by step gate
        self.assertEqual(dec.action, "skip")
        self.assertEqual(dec.reason, "unhedged-step-skip")
        self.assertEqual(dec.sub_reason, "unhedged-step-cents")

    def test_unhedged_step_cents_allows_additional_unhedged_fill_below_step(self):
        # Up holds 10 shares at 0.35, Down holds 0.
        # Price drops to 0.26 (<= 0.27) -> allowed!
        inv_unhedged = {
            "Up": {"shares": 10.0, "cost": 3.5, "lowest_price": 0.35},
            "Down": {"shares": 0.0, "cost": 0.0},
        }
        quotes_deep_dip = {
            "Up": {"bid": 0.25, "ask": 0.26},
            "Down": {"bid": 0.72, "ask": 0.73},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes_deep_dip,
            inv=inv_unhedged,
            fill_idx=1,
            minute=1,
            strategy_id="hydrogen-v1.1",
            unhedged_step_cents=8.0,
            unhedged_probe_shares=10.0,
            taker_dip_max=0.36,
            max_clip=25.0,
            dip_curve="hump",
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Up")
        self.assertEqual(dec.price, 0.26)
        # Still unhedged on opposite side, so probe cap applies
        self.assertEqual(dec.shares, 10.0)

    def test_unhedged_step_cents_inactive_when_opposite_shares_exist(self):
        # Opposite shares > 0: step gate does NOT apply
        inv_both = {
            "Up": {"shares": 10.0, "cost": 3.5, "lowest_price": 0.35},
            "Down": {"shares": 10.0, "cost": 6.0, "lowest_price": 0.60},
        }
        quotes_moderate = {
            "Up": {"bid": 0.33, "ask": 0.34},
            "Down": {"bid": 0.64, "ask": 0.65},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes_moderate,
            inv=inv_both,
            fill_idx=2,
            minute=1,
            strategy_id="hydrogen-v1.1",
            unhedged_step_cents=8.0,
            unhedged_probe_shares=10.0,
            taker_dip_max=0.36,
            max_clip=25.0,
            dip_curve="hump",
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Up")

    def test_default_off_preserves_legacy_behavior(self):
        inv_flat = {
            "Up": {"shares": 0.0, "cost": 0.0},
            "Down": {"shares": 0.0, "cost": 0.0},
        }
        # hydrogen-v1.0 with no probe knob: uses full hump sizing up to max_clip (25.0)
        dec = evaluate_microstructure_ladder(
            quotes=self.quotes_dip,
            inv=inv_flat,
            fill_idx=0,
            minute=0,
            strategy_id="hydrogen-v1.0",
            max_clip=25.0,
            dip_curve="hump",
            taker_dip_max=0.42,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.shares, 25.0)

    def test_taker_dip_entry_max_threshold_v11(self):
        # v1.1 takerDipEntryMax is 0.36 (v1.0 was 0.42)
        inv_flat = {
            "Up": {"shares": 0.0, "cost": 0.0},
            "Down": {"shares": 0.0, "cost": 0.0},
        }
        # Ask at 0.38 > 0.36 -> does NOT trigger taker dip entry
        quotes_38 = {
            "Up": {"bid": 0.36, "ask": 0.38},
            "Down": {"bid": 0.60, "ask": 0.62},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes_38,
            inv=inv_flat,
            fill_idx=0,
            minute=0,
            strategy_id="hydrogen-v1.1",
            taker_dip_max=0.36,
            unhedged_probe_shares=10.0,
            unhedged_step_cents=8.0,
        )
        self.assertNotEqual(dec.role, "TAKER")


if __name__ == "__main__":
    unittest.main()
