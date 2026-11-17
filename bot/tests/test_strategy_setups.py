import unittest
from bot import constants as C
from bot.executor import evaluate_microstructure_ladder, MicrostructureDecision

class TestStrategySetups(unittest.TestCase):
    def test_registry_contents(self):
        self.assertIn("hapcs-v1", C.STRATEGY_SETUPS)
        self.assertIn("dangerously-skip-permissions", C.STRATEGY_SETUPS)
        
        hapcs = C.STRATEGY_SETUPS["hapcs-v1"]
        dsp = C.STRATEGY_SETUPS["dangerously-skip-permissions"]
        
        self.assertEqual(hapcs["entry"]["maxFillPrice"], 0.975)
        self.assertEqual(hapcs["entry"]["stopBeforeCloseSec"], 12)
        self.assertNotIn("maxShareLead", hapcs["entry"])

        self.assertEqual(dsp["entry"]["maxFillPrice"], 0.880)
        self.assertEqual(dsp["entry"]["stopBeforeCloseSec"], 75)
        self.assertNotIn("maxShareLead", dsp["entry"])
        self.assertEqual(dsp["entry"]["targetPairCost"], 0.965)
        self.assertEqual(dsp["entry"]["maxPairCost"], 0.985)

    def test_dsp_rescue_pairing_accepts_sub_985(self):
        """Verify that when a deficit exists, DSP accepts a rescue pair cost up to 0.985."""
        inv = {
            "Up": {"shares": 0.0, "cost": 0.0},
            "Down": {"shares": 30.0, "cost": 7.50},  # avg 0.25
        }
        # Up ask is 0.72 with taker fee ~0.014 -> 0.734 + 0.25 = 0.984 <= 0.985
        quotes = {
            "Up": {"bid": 0.71, "ask": 0.72},
            "Down": {"bid": 0.24, "ask": 0.25},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv,
            fill_idx=5,
            minute=2,
            strategy_id="dangerously-skip-permissions",
            min_fill=0.07,
            max_fill=0.88,
            default_clip=30.0,
            max_clip=50.0,
            benchmark_pair_cost=0.965,
            max_pair_cost=0.985,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Up")
        self.assertEqual(dec.sub_reason, "hedge-equalizer")
        self.assertLessEqual(dec.projected_pair_cost, 0.985)

    def test_dsp_minute_4_certainty_sniping_disabled(self):
        """Verify that DSP does NOT execute speculative M4 certainty snipes at 0.93, while HAPCS does."""
        # Balanced inventory, so no deficit exists
        inv = {
            "Up": {"shares": 30.0, "cost": 10.0},
            "Down": {"shares": 30.0, "cost": 10.0},
        }
        # Up is at 0.93 (above DSP max_fill=0.88), Down is at 0.49 (above DSP dip_max=0.45)
        quotes = {
            "Up": {"bid": 0.92, "ask": 0.93},
            "Down": {"bid": 0.48, "ask": 0.49},
        }
        # DSP skips because Up is above max_fill=0.88 and certainty sniping is disabled
        dec_dsp = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv,
            fill_idx=10,
            minute=4,
            strategy_id="dangerously-skip-permissions",
            min_fill=0.07,
            max_fill=0.88,
            max_pair_cost=0.985,
        )
        self.assertEqual(dec_dsp.action, "skip")

        # HAPCS allows M4 certainty sniping up to max_fill=0.975
        dec_hapcs = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv,
            fill_idx=10,
            minute=4,
            strategy_id="hapcs-v1",
            min_fill=0.07,
            max_fill=0.975,
            max_pair_cost=0.990,
        )
        self.assertEqual(dec_hapcs.action, "fill")
        self.assertEqual(dec_hapcs.outcome, "Up")
        self.assertEqual(dec_hapcs.reason, "m4-snipe")

    def test_dsp_deficit_side_goes_first_without_freeze(self):
        """No share veto, no freeze: the lagging side is simply evaluated first."""
        inv = {
            "Up": {"shares": 60.0, "cost": 20.0},
            "Down": {"shares": 15.0, "cost": 5.0},
        }
        # Up leads by 45 shares. Down is at 0.40, Up is at 0.40
        quotes = {
            "Up": {"bid": 0.40, "ask": 0.41},
            "Down": {"bid": 0.40, "ask": 0.41},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv,
            fill_idx=10,
            minute=1,
            strategy_id="dangerously-skip-permissions",
            min_fill=0.07,
            max_fill=0.88,
        )
        # Down has the deficit, so it is evaluated first and fills.
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Down")

    def test_no_gap_veto_at_the_open(self):
        """The share veto is gone: pair-gated fills happen at any lead."""
        def decide(up_sh, down_sh):
            inv = {
                "Up": {"shares": float(up_sh), "cost": round(up_sh * 0.44, 2)},
                "Down": {"shares": float(down_sh), "cost": round(down_sh * 0.50, 2)},
            }
            quotes = {"Up": {"bid": 0.44, "ask": 0.45}, "Down": {"bid": 0.44, "ask": 0.45}}
            return evaluate_microstructure_ladder(
                quotes=quotes,
                inv=inv,
                fill_idx=2,
                minute=1,
                strategy_id="dangerously-skip-permissions",
                min_fill=0.07,
                max_fill=0.45,
                default_clip=10.0,
                max_clip=45.0,
                benchmark_pair_cost=0.965,
                max_pair_cost=0.985,
            )
        # A flat book fills the opening dip with no veto.
        dec_ok = decide(0, 0)
        self.assertEqual(dec_ok.action, "fill")
        self.assertEqual(dec_ok.outcome, "Up")
        # A real gap is closed first: 20/10 buys the lagging Down instead.
        dec_gap = decide(20, 10)
        self.assertEqual(dec_gap.outcome, "Down")

    def test_no_gap_veto_on_a_fresh_clip(self):
        """A fresh 10 sh clip fills; a 10 sh gap is hedged, not widened."""
        def decide(up_sh, down_sh):
            inv = {
                "Up": {"shares": float(up_sh), "cost": round(up_sh * 0.44, 2)},
                "Down": {"shares": float(down_sh), "cost": round(down_sh * 0.50, 2)},
            }
            quotes = {"Up": {"bid": 0.44, "ask": 0.45}, "Down": {"bid": 0.44, "ask": 0.45}}
            return evaluate_microstructure_ladder(
                quotes=quotes,
                inv=inv,
                fill_idx=2,
                minute=1,
                strategy_id="dangerously-skip-permissions",
                min_fill=0.07,
                max_fill=0.45,
                default_clip=10.0,
                max_clip=45.0,
                benchmark_pair_cost=0.965,
                max_pair_cost=0.985,
            )
        dec_open = decide(0, 0)
        self.assertEqual(dec_open.action, "fill")
        self.assertEqual(dec_open.outcome, "Up")
        dec_max = decide(10, 0)
        self.assertEqual(dec_max.outcome, "Down")

    def test_exact_deficit_clipping(self):
        """Verify that deficit hedging clips the exact deficit rather than coarse ladder snaps."""
        from bot.executor import select_ladder_clip
        self.assertEqual(select_ladder_clip(deficit=15.0, price=0.60), 15.0)
        self.assertEqual(select_ladder_clip(deficit=35.0, price=0.60), 35.0)
        self.assertEqual(select_ladder_clip(deficit=70.0, price=0.60, max_clip=50.0), 50.0)

    def test_no_freeze_deficit_hedge_goes_first(self):
        """Without the veto there is no freeze: the deficit hedge is simply evaluated first."""
        inv = {
            "Up": {"shares": 50.0, "cost": 17.50},  # Up leads by 20 shares
            "Down": {"shares": 30.0, "cost": 12.00},
        }
        # Up quote is in the dip (0.35); Down hedge at 0.54 pairs at 0.81.
        quotes = {
            "Up": {"bid": 0.35, "ask": 0.36},
            "Down": {"bid": 0.54, "ask": 0.55},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv,
            fill_idx=10,
            minute=1,
            strategy_id="dangerously-skip-permissions",
        )
        # Down has the deficit so it is evaluated first, and the 0.81 pair
        # clears the gates — the hedge fills instead of widening the lead.
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Down")

    def test_rescue_equalizer_on_high_price_deficit(self):
        """Verify that when holding a deficit, higher rescue prices (up to 0.92, pc up to 1.025) are accepted."""
        inv = {
            "Up": {"shares": 70.0, "cost": 24.50},  # avg 0.35
            "Down": {"shares": 30.0, "cost": 16.50}, # avg 0.55, deficit = 40 Down needed
        }
        # Down ask is 0.82.
        # Buying 40 Down @ 0.82 costs $32.80.
        # Total Down: 70 sh for $49.30 (avg 0.7043).
        # Proj pair cost: 0.35 + 0.7043 = 1.054 (or with slightly lower ask, e.g. 0.76 -> avg 0.67 -> pc 1.02)
        quotes = {
            "Up": {"bid": 0.20, "ask": 0.21},
            "Down": {"bid": 0.75, "ask": 0.76},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv,
            fill_idx=10,
            minute=2,
            strategy_id="dangerously-skip-permissions",
            max_pair_cost=0.985,
            rescue_max_pair_cost=1.025,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Down")
        self.assertEqual(dec.shares, 40.0)  # exact deficit match!
        self.assertEqual(dec.sub_reason, "rescue-equalizer")

    def test_balancing_sweep_phase(self):
        """Verify that sweep phase blocks speculative dip buys and only executes deficit hedges."""
        # Case A: Balanced inventory in sweep phase -> returns sweep-balanced skip
        inv_bal = {
            "Up": {"shares": 50.0, "cost": 20.0},
            "Down": {"shares": 50.0, "cost": 20.0},
        }
        quotes = {
            "Up": {"bid": 0.35, "ask": 0.36},
            "Down": {"bid": 0.54, "ask": 0.55},
        }
        dec_bal = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv_bal,
            fill_idx=10,
            minute=3,
            in_sweep_phase=True,
        )
        self.assertEqual(dec_bal.action, "skip")
        self.assertEqual(dec_bal.reason, "sweep-balanced")

        # Case B: Deficit exists in sweep phase -> fills deficit hedge
        inv_def = {
            "Up": {"shares": 60.0, "cost": 21.0},
            "Down": {"shares": 40.0, "cost": 18.0},
        }
        quotes_hedge = {
            "Up": {"bid": 0.35, "ask": 0.36},
            "Down": {"bid": 0.60, "ask": 0.61},
        }
        dec_def = evaluate_microstructure_ladder(
            quotes=quotes_hedge,
            inv=inv_def,
            fill_idx=11,
            minute=3,
            in_sweep_phase=True,
        )
        self.assertEqual(dec_def.action, "fill")
        self.assertEqual(dec_def.outcome, "Down")
        self.assertEqual(dec_def.shares, 20.0)  # exact 20 share deficit!

    def test_switch_strategy_config(self):
        """Verify switching between strategy setups updates config correctly."""
        import json
        from bot.api import CONFIG_PATH, load_config
        
        orig_content = CONFIG_PATH.read_text(encoding="utf-8")
        try:
            # 1. Switch to dangerously-skip-permissions
            dsp_setup = C.STRATEGY_SETUPS["dangerously-skip-permissions"]
            cfg = load_config()
            cfg["strategy"] = {
                "id": dsp_setup["id"],
                "symbol": dsp_setup["symbol"],
                "name": dsp_setup["name"],
            }
            cfg.setdefault("entry", {}).update(dsp_setup["entry"])
            CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            
            reloaded = load_config()
            self.assertEqual(reloaded["strategy"]["id"], "dangerously-skip-permissions")
            self.assertEqual(reloaded["entry"]["maxFillPrice"], 0.880)
            self.assertEqual(reloaded["entry"]["stopBeforeCloseSec"], 75)
            self.assertEqual(reloaded["entry"]["maxPairCost"], 0.985)
            self.assertNotIn("maxShareLead", reloaded["entry"])

            # 2. Switch back to hapcs-v1
            hapcs_setup = C.STRATEGY_SETUPS["hapcs-v1"]
            cfg["strategy"] = {
                "id": hapcs_setup["id"],
                "symbol": hapcs_setup["symbol"],
                "name": hapcs_setup["name"],
            }
            cfg.setdefault("entry", {}).update(hapcs_setup["entry"])
            CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            
            reloaded_hapcs = load_config()
            self.assertEqual(reloaded_hapcs["strategy"]["id"], "hapcs-v1")
            self.assertEqual(reloaded_hapcs["entry"]["maxFillPrice"], 0.975)
            self.assertEqual(reloaded_hapcs["entry"]["stopBeforeCloseSec"], 12)
            self.assertEqual(reloaded_hapcs["entry"]["maxPairCost"], 0.990)
            self.assertNotIn("maxShareLead", reloaded_hapcs["entry"])
        finally:
            CONFIG_PATH.write_text(orig_content, encoding="utf-8")

    def test_deficit_rescue_allows_up_to_985_odds(self):
        """A deficit hedge may quote up to the 98.5c rescue ceiling — as a resting bid."""
        inv = {
            "Up": {"shares": 50.0, "cost": 4.00},   # avg 0.08
            "Down": {"shares": 20.0, "cost": 10.00}, # avg 0.50, deficit = 30 Down needed
        }
        quotes = {
            "Up": {"bid": 0.01, "ask": 0.02},
            "Down": {"bid": 0.95, "ask": 0.98},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv,
            fill_idx=5,
            minute=3,
            strategy_id="dangerously-skip-permissions",
            max_fill=0.880,  # Standard max fill is 0.880
            rescue_ceiling=0.985,  # Rescue ceiling allows up to 0.985
            rescue_max_pair_cost=1.080,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Down")
        self.assertEqual(dec.shares, 30.0)
        self.assertEqual(dec.price, 0.95)
        self.assertEqual(dec.role, "MAKER")

    def test_balanced_inventory_strictly_rejects_98_odds(self):
        """Verify that when inventory is balanced (deficit=0), 98¢ certainty quotes are strictly skipped."""
        inv = {
            "Up": {"shares": 50.0, "cost": 20.00},
            "Down": {"shares": 50.0, "cost": 20.00},
        }
        quotes = {
            "Up": {"bid": 0.01, "ask": 0.02},
            "Down": {"bid": 0.97, "ask": 0.98},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv,
            fill_idx=5,
            minute=4,
            strategy_id="dangerously-skip-permissions",
            max_fill=0.880,
            rescue_ceiling=0.985,
        )
        self.assertEqual(dec.action, "skip")
        self.assertEqual(dec.reason, "extreme-price-skip")
        self.assertEqual(dec.sub_reason, "ceiling-price-skip")

if __name__ == '__main__':
    unittest.main()
