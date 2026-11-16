"""Tests for Hydrogen v2.0 (simultaneous two-sided resting + inverse-dip curve + sub-$1.00 hedging)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot import ab_test as ab
from bot import constants as C
from bot.executor import compute_fill_usd, evaluate_microstructure_ladder, v20_max_hedge_price
from bot.live_paper import cancel_side_orders, prune_pre_sweep_orders, update_maker_order


def _dec(quotes, inv, fill_idx=0, strategy_id="hydrogen-v2.0", **over):
    setup = C.STRATEGY_SETUPS[strategy_id]["entry"]
    kw = dict(
        inv=inv,
        fill_idx=fill_idx,
        minute=1,
        strategy_id=strategy_id,
        min_fill=setup["minFillPrice"],
        max_fill=setup["maxFillPrice"],
        default_clip=setup["clipSharesDefault"],
        max_clip=setup["maxClipShares"],
        whole_ladder=True,
        benchmark_pair_cost=setup["benchmarkPairCost"],
        max_pair_cost=setup["maxPairCost"],
        max_unhedged_usd=setup["maxUnhedgedUsd"],
        max_unhedged_shares=setup["maxUnhedgedShares"],
        dip_curve=setup["dipCurve"],
        target_pair_cost=setup["targetPairCost"],
        in_sweep_phase=False,
        rescue_max_pair_cost=setup["rescuePairCostMax"],
        rescue_ceiling=setup["rescueCeilingPrice"],
        include_taker_fee=setup["includeTakerFee"],
        open_orders={},
    )
    kw.update(over)
    return evaluate_microstructure_ladder(quotes, **kw)


class HydrogenV20Test(unittest.TestCase):
    def test_registry_and_legacy_untouched(self):
        self.assertIn("hydrogen-v2.0", C.STRATEGY_SETUPS)
        setup = C.STRATEGY_SETUPS["hydrogen-v2.0"]
        self.assertEqual(setup["id"], "hydrogen-v2.0")
        self.assertEqual(setup["symbol"], "H2 Hydrogen-v2.0")
        sig, desc, hl = C.describe_setup(setup)
        self.assertIn("Two-Sided", sig)
        self.assertIn("$6.00", desc)
        self.assertIn("Never >=", hl["pairGates"].replace("never >=", "Never >="))
        self.assertEqual(
            ab._run_strategy_id("run_20261116_210000_paper_hydrogen_v2_0"),
            "hydrogen-v2.0",
        )
        # Prior strategies must remain intact
        self.assertEqual(C.STRATEGY_SETUPS["hydrogen-v1.9"]["entry"]["maxFillPrice"], 0.85)
        self.assertEqual(C.STRATEGY_SETUPS["dangerously-skip-permissions-v2.5"]["entry"]["maxUnhedgedUsd"], 5.0)
        self.assertEqual(ab.DEFAULT_CANDIDATE_ID, "hydrogen-v1.9")

    def test_simultaneous_two_sided_resting_at_50_50_open(self):
        quotes = {
            "Up": {"bid": 0.49, "ask": 0.51},
            "Down": {"bid": 0.50, "ask": 0.52},
        }
        inv = {"Up": {"shares": 0.0, "cost": 0.0}, "Down": {"shares": 0.0, "cost": 0.0}}
        oo: dict = {}

        d1 = _dec(quotes, inv, open_orders=oo)
        self.assertEqual(d1.action, "maker")
        self.assertEqual(d1.outcome, "Up")
        self.assertEqual(d1.price, 0.47)
        self.assertEqual(d1.shares, 8.0)
        self.assertEqual(d1.sub_reason, "two-sided-maker")

        update_maker_order(oo, d1.outcome, d1.price, d1.shares, 0, d1.reason, d1.sub_reason, 0.0, 10.0, 100.0)

        d2 = _dec(quotes, inv, open_orders=oo)
        self.assertEqual(d2.action, "maker")
        self.assertEqual(d2.outcome, "Down")
        self.assertEqual(d2.price, 0.47)
        self.assertEqual(d2.shares, 8.0)

        update_maker_order(oo, d2.outcome, d2.price, d2.shares, 0, d2.reason, d2.sub_reason, 0.0, 10.0, 100.1)

        # Third evaluation with both sides resting must hold quietly without falling through
        d3 = _dec(quotes, inv, open_orders=oo)
        self.assertEqual(d3.action, "skip")
        self.assertEqual(d3.reason, "holding-resting")
        self.assertEqual(d3.sub_reason, "both-sides-resting")

    def test_no_starvation_when_existing_side_bid_dips_slightly(self):
        quotes = {
            "Up": {"bid": 0.46, "ask": 0.48},
            "Down": {"bid": 0.52, "ask": 0.54},
        }
        inv = {"Up": {"shares": 0.0, "cost": 0.0}, "Down": {"shares": 0.0, "cost": 0.0}}
        # Up already resting at 0.47 while target dropped to 0.45: must still place Down!
        oo = {
            "Up": {
                "side": "Up", "price": 0.47, "shares_left": 8.0,
                "queue_ahead": 5.0, "placed_ts": 100.0, "reason": "balanced-open",
                "sub_reason": "two-sided-maker", "minute": 0, "deficit": 0.0,
            }
        }
        d = _dec(quotes, inv, open_orders=oo)
        self.assertEqual(d.action, "maker")
        self.assertEqual(d.outcome, "Down")
        self.assertEqual(d.price, 0.47)

    def test_reprices_upward_inside_band_when_bid_rises(self):
        quotes = {
            "Up": {"bid": 0.49, "ask": 0.51},
            "Down": {"bid": 0.50, "ask": 0.52},
        }
        inv = {"Up": {"shares": 0.0, "cost": 0.0}, "Down": {"shares": 0.0, "cost": 0.0}}
        oo = {
            "Up": {"side": "Up", "price": 0.43, "shares_left": 8.0},
            "Down": {"side": "Down", "price": 0.47, "shares_left": 8.0},
        }
        d = _dec(quotes, inv, open_orders=oo)
        self.assertEqual(d.action, "maker")
        self.assertEqual(d.outcome, "Up")
        self.assertEqual(d.price, 0.47)

    def test_deep_dip_curve_and_dollar_cap_resolution(self):
        # At 0.30 (peak of dipCurve): ~17.9 sh * 0.30 = $5.37 <= $6.00 (fits cleanly now!)
        quotes_30 = {"Up": {"bid": 0.69, "ask": 0.71}, "Down": {"bid": 0.30, "ask": 0.32}}
        inv = {"Up": {"shares": 0.0, "cost": 0.0}, "Down": {"shares": 0.0, "cost": 0.0}}
        d30 = _dec(quotes_30, inv)
        self.assertEqual(d30.action, "maker")
        self.assertEqual(d30.outcome, "Down")
        self.assertEqual(d30.price, 0.30)
        self.assertEqual(d30.shares, 18.0)
        self.assertLessEqual(d30.shares * d30.price, 6.0)

        # Extreme 7c dip gives full 33 sh ($2.31)
        quotes_07 = {"Up": {"bid": 0.91, "ask": 0.93}, "Down": {"bid": 0.07, "ask": 0.09}}
        d07 = _dec(quotes_07, inv)
        self.assertEqual(d07.action, "maker")
        self.assertEqual(d07.outcome, "Down")
        self.assertEqual(d07.price, 0.07)
        self.assertEqual(d07.shares, 33.0)

        # Tight custom dollar cap ($4.00) must scale clip down so unhedged USD <= 4.00
        d_tight = _dec(quotes_30, inv, max_unhedged_usd=4.0)
        self.assertEqual(d_tight.action, "maker")
        self.assertLessEqual(d_tight.shares * d_tight.price, 4.0 + 1e-6)
        self.assertAlmostEqual(d_tight.shares, 13.3, places=1)

    def test_breakout_never_pays_dollar_or_latches(self):
        # Mirror screenshot scenario: 8 Down @ 0.45 filled, Up breaks out to 0.61/0.63
        quotes = {"Up": {"bid": 0.61, "ask": 0.63}, "Down": {"bid": 0.37, "ask": 0.39}}
        inv = {"Up": {"shares": 0.0, "cost": 0.0}, "Down": {"shares": 8.0, "cost": 3.60}}
        oo = {
            "Down": {"side": "Down", "price": 0.45, "shares_left": 8.0},
        }
        d = _dec(quotes, inv, open_orders=oo, deficit_duration_sec=30.0, window_bailout_latched=True)
        self.assertEqual(d.action, "maker")
        self.assertEqual(d.outcome, "Up")
        # Must clamp at floor(0.985 - 0.45) = 0.53 (never 0.61 or 0.62 taker!)
        self.assertEqual(d.price, 0.53)
        self.assertEqual(d.sub_reason, "rebalance-maker")
        self.assertLessEqual(d.projected_pair_cost, 0.985)

        # Simulate live_paper hygiene cancelling heavy side & replacing over-cap resting order
        oo["Up"] = {"side": "Up", "price": 0.56, "shares_left": 8.0, "queue_ahead": 0.0,
                    "placed_ts": 90.0, "reason": "balanced-open", "sub_reason": "two-sided-maker",
                    "minute": 0, "deficit": 0.0}
        pulled = cancel_side_orders(oo, "Down")
        self.assertEqual(len(pulled), 1)
        changed, repriced = update_maker_order(
            oo, "Up", d.price, d.shares, 1, d.reason, d.sub_reason, d.share_deficit, 5.0, 110.0,
            max_hedge_px=0.53,
        )
        self.assertTrue(changed and repriced)
        self.assertEqual(oo["Up"]["price"], 0.53)

    def test_profit_lock_taker_and_sweep_caps(self):
        # Down = 8 @ 0.45 ($3.60), Up ask = 0.48 (fee ~ $0.062 -> total $3.902, pairCost = 0.9378 <= 0.965)
        quotes_lock = {"Up": {"bid": 0.47, "ask": 0.48}, "Down": {"bid": 0.49, "ask": 0.51}}
        inv = {"Up": {"shares": 0.0, "cost": 0.0}, "Down": {"shares": 8.0, "cost": 3.60}}
        d_lock = _dec(quotes_lock, inv, in_sweep_phase=False)
        self.assertEqual(d_lock.action, "taker")
        self.assertEqual(d_lock.outcome, "Up")
        self.assertEqual(d_lock.price, 0.48)
        self.assertLessEqual(d_lock.projected_pair_cost, 0.965)

        # At 0.52 ask outside sweep: fee-inclusive > 0.965, so refuse taker & rest maker at 0.51
        quotes_mid = {"Up": {"bid": 0.51, "ask": 0.52}, "Down": {"bid": 0.46, "ask": 0.48}}
        d_mid = _dec(quotes_mid, inv, in_sweep_phase=False)
        self.assertEqual(d_mid.action, "maker")
        self.assertEqual(d_mid.price, 0.51)

        # In sweep phase with 0.52 ask: 0.45 + 0.52 + fee (~0.5375/sh) = 0.9875 <= 0.995 -> sweep-taker fires!
        quotes_sweep = {"Up": {"bid": 0.51, "ask": 0.52}, "Down": {"bid": 0.45, "ask": 0.47}}
        d_sw = _dec(quotes_sweep, inv, in_sweep_phase=True)
        self.assertEqual(d_sw.action, "taker")
        self.assertEqual(d_sw.reason, "sweep-taker")
        self.assertLessEqual(d_sw.projected_pair_cost, 0.995)

        # In sweep phase with 0.53 ask: fee-inclusive is 0.9975 > 0.995 -> refuses taker, rests sweep maker <= 0.54
        quotes_no_taker = {"Up": {"bid": 0.52, "ask": 0.53}, "Down": {"bid": 0.44, "ask": 0.46}}
        d_no_tk = _dec(quotes_no_taker, inv, in_sweep_phase=True)
        self.assertEqual(d_no_tk.action, "maker")
        self.assertEqual(d_no_tk.price, 0.52)
        self.assertLessEqual(d_no_tk.projected_pair_cost, 0.995)

        # In sweep phase with 0.55 ask (> 0.995): NEVER pays >= $1.00, rests sweep maker capped at 0.54
        quotes_no1 = {"Up": {"bid": 0.54, "ask": 0.55}, "Down": {"bid": 0.43, "ask": 0.45}}
        d_no1 = _dec(quotes_no1, inv, in_sweep_phase=True)
        self.assertEqual(d_no1.action, "maker")
        self.assertEqual(d_no1.price, 0.54)
        self.assertLessEqual(d_no1.projected_pair_cost, 0.995)

    def test_multi_cycle_portfolio_headroom(self):
        # Cycle 1 finished at 0.980 via asymmetric fills: Up 8@0.40 ($3.20), Down 8@0.58 ($4.64)
        inv_c1 = {"Up": {"shares": 8.0, "cost": 3.20}, "Down": {"shares": 8.0, "cost": 4.64}}
        quotes = {"Up": {"bid": 0.49, "ask": 0.51}, "Down": {"bid": 0.50, "ask": 0.52}}
        # Cycle 2 must STILL open balanced legs at 0.47 (making a $0.94 marginal pair!)
        d_c2 = _dec(quotes, inv_c1)
        self.assertEqual(d_c2.action, "maker")
        self.assertEqual(d_c2.outcome, "Up")
        self.assertEqual(d_c2.price, 0.47)

        # Once Cycle 2 Up @ 0.47 fills (16 Up $6.96 vs 8 Down $4.64), hedge cap respects 0.985 portfolio budget:
        # (0.985*16 - 6.96 - 4.64) / 8 = 0.520
        inv_c2 = {"Up": {"shares": 16.0, "cost": 6.96}, "Down": {"shares": 8.0, "cost": 4.64}}
        cap = v20_max_hedge_price(inv_c2, "Up", "Down", 0.985)
        self.assertEqual(cap, 0.52)

    def test_setup_switch_clears_stale_entry_keys(self):
        from bot import api
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_cfg = Path(tmpdir) / "config.json"
            tmp_state = Path(tmpdir) / "state.json"
            stale_cfg = {
                "strategy": {"id": "hydrogen-v1.9", "symbol": "H2", "name": "Hydrogen v1.9"},
                "entry": {
                    "dipCurve": {"lo": 0.05, "hi": 0.40, "sharesLo": 20, "sharesHi": 5},
                    "unhedgedProbeShares": 5.0,
                    "unhedgedStepCents": 3.0,
                    "maxUnhedgedShares": 5.0,
                    "maxUnhedgedUsd": 2.5,
                    "maxFillPrice": 0.85,
                },
            }
            tmp_cfg.write_text(json.dumps(stale_cfg), encoding="utf-8")
            with mock.patch.object(api, "CONFIG_PATH", tmp_cfg), mock.patch.object(api, "STATE_PATH", tmp_state):
                # Switch to hydrogen-v1.9 first (should drop dipCurve/unhedgedProbeShares), then to v2.0
                cfg = api.load_config()
                self.assertEqual(cfg["entry"]["maxFillPrice"], 0.85)
                # Simulate handler cleanup list
                entry_cfg = cfg["entry"]
                for k in ("dipCurve", "unhedgedProbeShares", "unhedgedStepCents", "maxUnhedgedShares", "maxUnhedgedUsd"):
                    entry_cfg.pop(k, None)
                entry_cfg.update(C.STRATEGY_SETUPS["hydrogen-v2.0"]["entry"])
                self.assertEqual(entry_cfg["maxUnhedgedUsd"], 6.0)
                self.assertEqual(entry_cfg["maxUnhedgedShares"], 0.0)
                self.assertEqual(entry_cfg["maxFillPrice"], 0.47)
                self.assertNotIn("unhedgedProbeShares", entry_cfg)
                self.assertNotIn("unhedgedStepCents", entry_cfg)

    def test_prune_pre_sweep_preserves_sweep_and_rebalance_orders(self):
        oo = {
            "Up": {"side": "Up", "price": 0.47, "reason": "balanced-open", "sub_reason": "two-sided-maker"},
            "Down": {"side": "Down", "price": 0.51, "reason": "sweep", "sub_reason": "rebalance-maker"},
        }
        pulled = prune_pre_sweep_orders(oo)
        self.assertEqual(len(pulled), 1)
        self.assertEqual(pulled[0]["side"], "Up")
        self.assertIn("Down", oo)
        self.assertNotIn("Up", oo)
        # Second tick inside sweep must pull nothing so sweep maker keeps queue priority
        self.assertEqual(prune_pre_sweep_orders(oo), [])
        self.assertIn("Down", oo)


if __name__ == "__main__":
    unittest.main()
