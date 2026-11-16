"""Hydrogen v1.9: Dynamic 3-layer architecture for 5m binary markets."""
import unittest

from bot import ab_test as ab
from bot import constants as C
from bot import replay
from bot.executor import (
    H19_L1_PRICE_MAX,
    H19_L1_PRICE_MIN,
    H19_L1_PROBE_SHARES,
    H19_L1_CUTOFF_SEC,
    H19_L1_CUTOFF_MATCHED,
    H19_L2_PAIR_CAP,
    H19_L3_PATIENCE_SEC,
    H19_L3_MARGINAL_MIN,
    H19_L3_ASK_MAX,
    H19_LEAD_TOLERANCE,
    evaluate_microstructure_ladder,
)


def _inv(up, up_cost, down, down_cost):
    return {
        "Up": {"shares": float(up), "cost": float(up_cost)},
        "Down": {"shares": float(down), "cost": float(down_cost)},
    }


def _q(up_bid, up_ask, dn_bid, dn_ask):
    return {
        "Up": {"bid": up_bid, "ask": up_ask},
        "Down": {"bid": dn_bid, "ask": dn_ask},
    }


def _dec(quotes, inv, fill_idx=0, strategy_id="hydrogen-v1.9", **over):
    kw = dict(
        inv=inv,
        fill_idx=fill_idx,
        minute=1,
        strategy_id=strategy_id,
        min_fill=0.05,
        max_fill=0.85,
        default_clip=5.0,
        max_clip=5.0,
        max_unhedged_usd=2.50,
        max_unhedged_shares=5.0,
        elapsed_sec=30.0,
    )
    kw.update(over)
    return evaluate_microstructure_ladder(quotes=quotes, **kw)


class TestHydrogenV19RegistryAndWiring(unittest.TestCase):
    def test_registry_entry_and_features(self):
        for sid in ("hydrogen-v1.9",):
            setup = C.STRATEGY_SETUPS[sid]
            entry = setup["entry"]
            self.assertEqual(entry["levelsPerSide"], 1)
            self.assertEqual(entry["clipSharesDefault"], 5.0)
            self.assertEqual(entry["maxShares"], 5.0)
            self.assertEqual(entry["maxPairCost"], 0.990)
            self.assertEqual(entry["maxUnhedgedShares"], 5.0)
            self.assertEqual(entry["maxUnhedgedUsd"], 2.50)
            self.assertEqual(setup["features"].get("sizing"), "split-ladder-v19")
            self.assertIn(setup["features"].get("l3Mode"), ("patient", "immediate", "off"))

    def test_describe_setup_v19(self):
        _sig, desc, highlights = C.describe_setup(C.STRATEGY_SETUPS["hydrogen-v1.9"])
        self.assertIn("0.990", desc)
        self.assertIn("0.990", highlights["pairGates"])
        self.assertIn("tol = 0.5 sh", highlights["preflightGate"])

    def test_replay_and_ab_test_mapping(self):
        self.assertEqual(replay.STRATEGY_HYDROGEN, "hydrogen-v1.9")
        self.assertEqual(ab.DEFAULT_CANDIDATE_ID, "hydrogen-v2.0")
        self.assertEqual(
            ab._run_strategy_id("run_20261116_160000_paper_hydrogen_v1_9"),
            "hydrogen-v1.9",
        )

    def test_arm_run_ids_map_to_own_arm(self):
        self.assertEqual(
            ab._run_strategy_id("run_20261116_160000_paper_hydrogen_v1_9_arm_a"),
            "hydrogen-v1.9-arm-a",
        )
        self.assertEqual(
            ab._run_strategy_id("run_20261116_160000_paper_hydrogen_v1_9_arm_b"),
            "hydrogen-v1.9-arm-b",
        )
        self.assertEqual(
            ab._run_strategy_id("run_20261116_160000_paper_hydrogen_v1_9_arm_e"),
            "hydrogen-v1.9-arm-e",
        )

class TestHydrogenV19Layer1Probe(unittest.TestCase):
    def test_l1_probe_places_single_rung_in_band(self):
        # Flat inventory: both bids in 42–49c band
        # Up bid = 0.46, Down bid = 0.54 -> Up is cheaper (0.46 in [0.42, 0.49])
        d = _dec(_q(0.46, 0.48, 0.54, 0.56), _inv(0, 0, 0, 0))
        self.assertEqual(d.action, "fill")
        self.assertEqual(d.role, "MAKER")
        self.assertEqual(d.outcome, "Up")
        self.assertEqual(d.price, 0.45)  # bid - 0.01
        self.assertEqual(d.shares, 5.0)
        self.assertEqual(d.sub_reason, "balance-maker")

    def test_l1_blocks_bids_above_49c(self):
        # Both bids above 49c: Up bid = 0.51, Down bid = 0.52 -> skipped
        d = _dec(_q(0.51, 0.53, 0.52, 0.54), _inv(0, 0, 0, 0))
        self.assertEqual(d.action, "skip")
        self.assertEqual(d.reason, "off-atm-skip")

    def test_l1_cutoff_at_150s(self):
        # At elapsed_sec = 150.0, Layer 1 maker probe is frozen
        d = _dec(_q(0.46, 0.48, 0.54, 0.56), _inv(0, 0, 0, 0), elapsed_sec=150.0)
        self.assertEqual(d.action, "skip")
        self.assertEqual(d.reason, "window-frozen")
        self.assertEqual(d.sub_reason, "cutoff-reached")

    def test_l1_cutoff_at_40_matched(self):
        # When matched >= 40.0 shares, Layer 1 maker probe is frozen
        d = _dec(_q(0.46, 0.48, 0.54, 0.56), _inv(40, 18.0, 40, 21.0), elapsed_sec=60.0)
        self.assertEqual(d.action, "skip")
        self.assertEqual(d.reason, "window-frozen")
        self.assertEqual(d.sub_reason, "cutoff-reached")

    def test_l1_frozen_when_window_bailout_latched(self):
        # If bailout occurred earlier in the window, Layer 1 probe is permanently frozen
        d = _dec(_q(0.46, 0.48, 0.54, 0.56), _inv(0, 0, 0, 0), window_bailout_latched=True)
        self.assertEqual(d.action, "skip")
        self.assertEqual(d.reason, "window-frozen")
        self.assertEqual(d.sub_reason, "cutoff-reached")


class TestHydrogenV19Layer2ClampedMaker(unittest.TestCase):
    def test_lead_triggers_layer2(self):
        # Up = 5.0 sh @ 0.46 ($2.30), Down = 0.0 -> lead = 5.0 > tol (0.5)
        # Heavy avg = 0.46. Max hedge px = floor(0.990 - 0.46) = 0.53.
        # Down bid = 0.53, ask = 0.55 -> px = min(0.53, 0.53) = 0.53
        d = _dec(_q(0.44, 0.46, 0.53, 0.55), _inv(5.0, 2.30, 0, 0))
        self.assertEqual(d.action, "fill")
        self.assertEqual(d.role, "MAKER")
        self.assertEqual(d.outcome, "Down")
        self.assertEqual(d.price, 0.53)
        self.assertEqual(d.shares, 5.0)
        self.assertEqual(d.sub_reason, "rebalance-maker")

    def test_l2_clamps_below_light_bid_if_heavy_avg_expensive(self):
        # Up = 5.0 sh @ 0.48 ($2.40). Heavy avg = 0.48.
        # Max hedge px = floor(0.990 - 0.48) = 0.51.
        # Down bid is 0.53 (expensive) -> px clamped down to 0.51!
        d = _dec(_q(0.44, 0.46, 0.53, 0.55), _inv(5.0, 2.40, 0, 0))
        self.assertEqual(d.action, "fill")
        self.assertEqual(d.role, "MAKER")
        self.assertEqual(d.outcome, "Down")
        self.assertEqual(d.price, 0.51)  # clamped to sub-par target!
        self.assertEqual(d.shares, 5.0)
        self.assertEqual(d.sub_reason, "rebalance-maker")


class TestHydrogenV19Layer3TakerBailout(unittest.TestCase):
    def test_arm_b_delays_l3_for_20_seconds(self):
        # Deficit active for only 10s: Layer 3 taker bailout must NOT fire yet
        # Down ask = 0.65 -> heavy_avg (0.46) + 0.65 = 1.11 >= 1.07
        # Since deficit_duration_sec = 10.0 < 20.0, maker hedge at clamped 0.53 rests instead!
        d = _dec(_q(0.33, 0.35, 0.53, 0.65), _inv(5.0, 2.30, 0, 0),
                 deficit_duration_sec=10.0, strategy_id="hydrogen-v1.9")
        self.assertEqual(d.role, "MAKER")
        self.assertEqual(d.sub_reason, "rebalance-maker")

    def test_arm_b_fires_l3_after_20_seconds_on_breakout(self):
        # Deficit active for 21s: breakout ask = 0.65 (ask <= 0.72 & marginal 1.11 >= 1.07)
        # Layer 3 taker equalizer fires!
        d = _dec(_q(0.33, 0.35, 0.53, 0.65), _inv(5.0, 2.30, 0, 0),
                 deficit_duration_sec=21.0, strategy_id="hydrogen-v1.9")
        self.assertEqual(d.action, "fill")
        self.assertEqual(d.role, "TAKER")
        self.assertEqual(d.outcome, "Down")
        self.assertEqual(d.price, 0.65)
        self.assertEqual(d.shares, 5.0)
        self.assertEqual(d.sub_reason, "rebalance-taker")

    def test_arm_a_fires_l3_immediately(self):
        # Arm A fires immediately (deficit_duration_sec = 0.0) when ask <= 0.72 & marginal >= 1.00
        d = _dec(_q(0.33, 0.35, 0.53, 0.60), _inv(5.0, 2.30, 0, 0),
                 deficit_duration_sec=0.0, strategy_id="hydrogen-v1.9-arm-a")
        self.assertEqual(d.action, "fill")
        self.assertEqual(d.role, "TAKER")
        self.assertEqual(d.price, 0.60)
        self.assertEqual(d.sub_reason, "rebalance-taker")

    def test_arm_e_never_fires_taker(self):
        # Arm E is pure maker, even at 25s elapsed deficit with breakout ask
        d = _dec(_q(0.33, 0.35, 0.53, 0.65), _inv(5.0, 2.30, 0, 0),
                 deficit_duration_sec=25.0, strategy_id="hydrogen-v1.9-arm-e")
        self.assertEqual(d.role, "MAKER")
        self.assertEqual(d.sub_reason, "rebalance-maker")


if __name__ == "__main__":
    unittest.main()
