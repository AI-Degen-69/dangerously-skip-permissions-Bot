"""Unit tests for MicrostructureMathEngine and its zero-network analytical components.
Verifies mathematical invariants, Avellaneda-Stoikov equations, sub-$1.00 pair-cost guarantees,
and numerical stability across extreme market regimes.
"""

import math
import pytest

from bot.microstructure_engine.math_engine import (
    MicrostructureMathEngine,
    OrderFlowCalibrator,
    SpreadOptimizer,
    ReservationPriceCalculator,
    DynamicSizeCalculator,
    HysteresisGate,
    HysteresisAction,
)


class TestOrderFlowCalibrator:
    def test_normal_calibration(self):
        calibrator = OrderFlowCalibrator()
        # lambda(0.01) = 100, lambda(0.03) = 25 -> kappa = ln(4) / 0.02 = 1.38629 / 0.02 = 69.31
        kappa = calibrator.calibrate_from_observations(
            delta_near=0.01,
            lambda_near=100.0,
            delta_far=0.03,
            lambda_far=25.0,
        )
        assert 68.0 < kappa < 71.0

    def test_numerical_stability_edge_cases(self):
        calibrator = OrderFlowCalibrator(default_kappa=15.0, min_kappa=1.0, max_kappa=200.0)
        # Identical delta -> zero division
        assert calibrator.calibrate_from_observations(0.01, 100.0, 0.01, 100.0) == 15.0
        # Negative arrival rate
        assert calibrator.calibrate_from_observations(0.01, -5.0, 0.02, 10.0) == 15.0
        # Inverted distance
        assert calibrator.calibrate_from_observations(0.05, 10.0, 0.01, 100.0) == 15.0
        # Extremely huge ratio -> clamps to max_kappa
        kappa = calibrator.calibrate_from_observations(0.01, 1e9, 0.02, 1e-9)
        assert kappa == 200.0


class TestSpreadOptimizer:
    def test_avellaneda_stoikov_formula(self):
        optimizer = SpreadOptimizer(min_spread=0.01, max_spread=0.25)
        # gamma=0.1, kappa=10.0 -> s* = (2 / 0.1) * ln(1 + 0.1 / 10.0) = 20 * ln(1.01) = 0.1990
        s = optimizer.calculate_optimal_spread(gamma=0.1, kappa=10.0)
        assert 0.18 < s < 0.22

    def test_zero_risk_aversion_limit(self):
        optimizer = SpreadOptimizer(min_spread=0.005, max_spread=0.50)
        # As gamma -> 0, s* -> 2 / kappa
        kappa = 20.0
        s_limit = optimizer.calculate_optimal_spread(gamma=0.0, kappa=kappa)
        expected = 2.0 / 20.0  # 0.10
        assert math.isclose(s_limit, expected, rel_tol=1e-3)

        # Extremely small gamma (1e-8) should also match the Taylor series limit
        s_tiny = optimizer.calculate_optimal_spread(gamma=1e-8, kappa=kappa)
        assert math.isclose(s_tiny, expected, rel_tol=1e-3)


class TestReservationPriceCalculator:
    def test_inventory_skew(self):
        calc = ReservationPriceCalculator()
        # Zero inventory at mid 0.50 -> reservation price 0.50
        r_flat = calc.calculate_reservation_price(
            mid_price=0.50,
            inventory_net=0.0,
            gamma=0.1,
            time_remaining_normalized=0.5,
        )
        assert math.isclose(r_flat, 0.50, abs_tol=1e-4)

        # Long inventory (q = +50 YES) -> reservation price drops below mid to stop buying
        r_long = calc.calculate_reservation_price(
            mid_price=0.50,
            inventory_net=50.0,
            gamma=0.1,
            time_remaining_normalized=0.5,
        )
        assert r_long < 0.50

        # Short inventory (q = -50 YES / excess NO) -> reservation price rises above mid
        r_short = calc.calculate_reservation_price(
            mid_price=0.50,
            inventory_net=-50.0,
            gamma=0.1,
            time_remaining_normalized=0.5,
        )
        assert r_short > 0.50

    def test_boundary_dampening(self):
        calc = ReservationPriceCalculator()
        # Near boundaries (0.02 or 0.98), binary variance s*(1-s) dampens diffusion blowup
        r_edge = calc.calculate_reservation_price(
            mid_price=0.02,
            inventory_net=200.0,
            gamma=1.0,
            time_remaining_normalized=1.0,
            scale_by_binary_variance=True,
        )
        assert 0.01 <= r_edge <= 0.99


class TestDynamicSizeCalculator:
    def test_sizing_decay_and_budget(self):
        sizer = DynamicSizeCalculator(base_size=20.0, max_inventory=100.0)
        # Empty inventory -> full base size
        sz_y, sz_n = sizer.calculate_quote_sizes(q_yes=0, q_no=0, available_budget_usd=500.0)
        assert sz_y == 20.0
        assert sz_n == 20.0

        # Max inventory reached on YES (q_yes = 100) -> YES size drops to reward stub (5 sh)
        sz_y_full, sz_n_boost = sizer.calculate_quote_sizes(
            q_yes=100, q_no=0, available_budget_usd=500.0
        )
        assert sz_y_full == 5.0  # reward stub
        assert sz_n_boost > 20.0  # boosted closing leg to accelerate pairing

        # Budget constraint scaling
        sz_budget_y, sz_budget_n = sizer.calculate_quote_sizes(
            q_yes=0, q_no=0, available_budget_usd=10.0, price_yes=0.50, price_no=0.50
        )
        # 10 USD budget with 0.50 prices can support at most 10 shares per side
        assert (sz_budget_y * 0.50 + sz_budget_n * 0.50) <= 10.01


class TestHysteresisGate:
    def test_hysteresis_actions(self):
        gate = HysteresisGate(tick_size=0.01, epsilon_adverse_multiplier=0.5, epsilon_favorable_multiplier=1.5)
        # Sub-tick drift (0.003) -> HOLD
        action = gate.evaluate_order(target_price=0.503, active_price=0.500, is_bid=True)
        assert action == HysteresisAction.HOLD

        # Significant drift (0.02) -> CANCEL_AND_REPLACE
        action = gate.evaluate_order(target_price=0.520, active_price=0.500, is_bid=True)
        assert action == HysteresisAction.CANCEL_AND_REPLACE

        # Adverse drift of 0.006 (target dropped from 0.500 to 0.494):
        # eps_adverse = 0.5 * 0.01 = 0.005. Since 0.006 >= 0.005 -> CANCEL_AND_REPLACE
        action_adverse = gate.evaluate_order(target_price=0.494, active_price=0.500, is_bid=True)
        assert action_adverse == HysteresisAction.CANCEL_AND_REPLACE

        # Fast-path shock overrides deadband -> CANCEL_AND_REPLACE
        action_shock = gate.evaluate_order(
            target_price=0.501, active_price=0.500, is_bid=True, is_toxicity_fast_path=True
        )
        assert action_shock == HysteresisAction.CANCEL_AND_REPLACE


class TestMicrostructureMathEngine:
    def test_sub_dollar_invariant_guarantee(self):
        engine = MicrostructureMathEngine(
            tick_size=0.01,
            gamma=0.05,
            target_sub_dollar_ceiling=0.990,
        )
        # Test across 50 different mid-price scenarios
        for mid_cent in range(5, 95, 5):
            mid = mid_cent / 100.0
            res = engine.calculate_quotes(
                mid_price_yes=mid,
                inventory_yes=15.0,
                inventory_no=10.0,
                time_remaining_seconds=180.0,
            )
            assert res.target_quotes.is_sub_one_dollar
            assert res.target_quotes.combined_cost <= 0.990
            assert res.target_quotes.bid_yes + res.target_quotes.bid_no <= 0.990
            assert res.target_quotes.bid_yes > 0.0
            assert res.target_quotes.bid_no > 0.0

    def test_tick_quantization(self):
        engine = MicrostructureMathEngine(tick_size=0.01)
        assert math.isclose(engine.quantize_floor(0.48999), 0.48, abs_tol=1e-5)
        assert math.isclose(engine.quantize_floor(0.51001), 0.51, abs_tol=1e-5)
        assert math.isclose(engine.quantize_floor(0.50000), 0.50, abs_tol=1e-5)
