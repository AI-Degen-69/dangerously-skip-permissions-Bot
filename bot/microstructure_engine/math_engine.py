"""Microstructure Math Engine (Zero-Network Mathematical Core)

Implements the 5-step execution pipeline from:
'The-Math-for-Microstructure-Calibrated-Inventory-Risk-Engine.md'
augmented with binary option boundary scaling, sub-$1.00 pair-cost guarantees,
LIIC dynamic inventory sizing, and asymmetric queue-preserving hysteresis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple


class HysteresisAction(str, Enum):
    HOLD = "Hold"
    CANCEL_AND_REPLACE = "Cancel & Replace"


@dataclass(frozen=True)
class TargetQuotes:
    """Pair of target bid prices for binary complementary outcomes."""
    bid_yes: float
    bid_no: float
    reservation_yes: float
    reservation_no: float
    optimal_spread: float
    is_sub_one_dollar: bool
    combined_cost: float


@dataclass(frozen=True)
class QuoteResult:
    """Complete quote output containing target prices, sizing, and hysteresis actions."""
    target_quotes: TargetQuotes
    size_yes: float
    size_no: float
    action_yes: HysteresisAction
    action_no: HysteresisAction
    kappa: float
    notes: str = ""


class OrderFlowCalibrator:
    """Step 1: Calibrate order flow intensity kappa = - d(ln lambda)/d(delta).
    
    Models arrival intensity lambda(delta) = A * exp(-kappa * delta).
    Under exponential decay:
        kappa = ln(lambda(delta_1) / lambda(delta_2)) / (delta_2 - delta_1)
    """

    def __init__(
        self,
        default_kappa: float = 12.0,
        min_kappa: float = 0.5,
        max_kappa: float = 250.0,
    ) -> None:
        self.default_kappa = float(default_kappa)
        self.min_kappa = float(min_kappa)
        self.max_kappa = float(max_kappa)

    def calibrate_from_observations(
        self,
        delta_near: float,
        lambda_near: float,
        delta_far: float,
        lambda_far: float,
    ) -> float:
        """Calibrate kappa from two observed arrival rates at different mid-distances."""
        if delta_far <= delta_near or lambda_near <= 0.0 or lambda_far <= 0.0:
            return self.default_kappa

        denom = delta_far - delta_near
        if abs(denom) < 1e-7:
            return self.default_kappa

        try:
            ratio = lambda_near / lambda_far
            if ratio <= 0.0 or math.isinf(ratio) or math.isnan(ratio):
                return self.default_kappa
            raw_kappa = math.log(ratio) / denom
        except (ValueError, OverflowError, ZeroDivisionError):
            return self.default_kappa

        if math.isnan(raw_kappa) or math.isinf(raw_kappa):
            return self.default_kappa

        return max(self.min_kappa, min(self.max_kappa, raw_kappa))

    def calibrate_from_book_depth(
        self,
        bids: List[Tuple[float, float]],
        mid_price: float,
    ) -> float:
        """Estimate kappa from cumulative book depth decay across price levels.
        
        Args:
            bids: List of (price, size) sorted descending by price.
            mid_price: Current orderbook mid-price.
        """
        if len(bids) < 2 or mid_price <= 0.0:
            return self.default_kappa

        # Pick near level and far level
        p_near, sz_near = bids[0]
        p_far, sz_far = bids[-1]

        delta_near = max(0.001, mid_price - p_near)
        delta_far = max(delta_near + 0.001, mid_price - p_far)

        # Arrival rate is proportional to resting liquidity density
        lambda_near = max(1.0, sz_near)
        lambda_far = max(0.1, sz_far)

        return self.calibrate_from_observations(
            delta_near, lambda_near, delta_far, lambda_far
        )


class SpreadOptimizer:
    """Step 2: Optimal quote width s* = (2 / gamma) * ln(1 + gamma / kappa).
    
    Guarantees sufficient round-trip edge independent of current inventory.
    Handles gamma -> 0 limit via Taylor series expansion: ln(1 + x) ~ x - x^2/2.
    """

    def __init__(
        self,
        min_spread: float = 0.01,
        max_spread: float = 0.20,
    ) -> None:
        self.min_spread = float(min_spread)
        self.max_spread = float(max_spread)

    def calculate_optimal_spread(
        self,
        gamma: float,
        kappa: float,
    ) -> float:
        """Compute optimal spread s* using Avellaneda-Stoikov logarithmic equation."""
        k = max(0.1, float(kappa))
        g = float(gamma)

        if g <= 1e-6:
            # Taylor expansion limit as gamma -> 0:
            # (2 / g) * ln(1 + g / k) -> (2 / g) * (g / k - (g/k)^2 / 2) = 2 / k
            raw_s = 2.0 / k
        else:
            try:
                ratio = g / k
                raw_s = (2.0 / g) * math.log(1.0 + ratio)
            except (ValueError, OverflowError):
                raw_s = 2.0 / k

        if math.isnan(raw_s) or math.isinf(raw_s):
            raw_s = self.min_spread

        return max(self.min_spread, min(self.max_spread, raw_s))


class ReservationPriceCalculator:
    """Step 3: Quote Center r_i(s, q, t) = s_i - gamma * (T - t) * sum_j(Sigma_ij * q_j).
    
    Includes:
    - Heteroskedasticity dampening: binary variance scaling s_i * (1 - s_i) to prevent
      explosive penalties near the 0.0 and 1.0 probability boundaries.
    - Strict complementary parity coupling: r_NO = 1.00 - r_YES.
    """

    def __init__(
        self,
        min_reservation: float = 0.01,
        max_reservation: float = 0.99,
    ) -> None:
        self.min_reservation = float(min_reservation)
        self.max_reservation = float(max_reservation)

    def calculate_reservation_price(
        self,
        mid_price: float,
        inventory_net: float,
        gamma: float,
        time_remaining_normalized: float,
        variance_or_cov: float = 0.04,
        scale_by_binary_variance: bool = True,
    ) -> float:
        """Compute single-asset reservation price r(s, q, t) with binary boundary dampening.
        
        Args:
            mid_price: Current mid-price s in (0, 1).
            inventory_net: Net inventory q (positive = long, negative = short).
            gamma: Risk aversion coefficient (> 0).
            time_remaining_normalized: (T - t) fraction in [0, 1].
            variance_or_cov: Asset variance or cross-asset covariance.
            scale_by_binary_variance: Multiply diffusion penalty by s * (1 - s).
        """
        s = max(0.001, min(0.999, float(mid_price)))
        q = float(inventory_net)
        g = max(0.0, float(gamma))
        tau = max(0.0, min(1.0, float(time_remaining_normalized)))
        cov = float(variance_or_cov)

        if scale_by_binary_variance:
            # Binary Bernoulli variance dampener
            binary_dampener = 4.0 * s * (1.0 - s)  # normalized so dampener=1.0 at s=0.5
            effective_cov = cov * binary_dampener
        else:
            effective_cov = cov

        # Penalty term: gamma * (T - t) * cov * q
        penalty = g * tau * effective_cov * q

        raw_r = s - penalty

        # Ensure reservation price stays within valid probability bounds
        clamped_r = max(self.min_reservation, min(self.max_reservation, raw_r))
        return clamped_r

    def calculate_cross_asset_reservation(
        self,
        mid_prices: Dict[str, float],
        inventories: Dict[str, float],
        covariance_matrix: Dict[str, Dict[str, float]],
        target_asset: str,
        gamma: float,
        time_remaining_normalized: float,
    ) -> float:
        """Compute multi-asset reservation price with full covariance matrix."""
        s_i = mid_prices.get(target_asset, 0.50)
        s_i = max(0.001, min(0.999, float(s_i)))
        g = max(0.0, float(gamma))
        tau = max(0.0, min(1.0, float(time_remaining_normalized)))

        cov_row = covariance_matrix.get(target_asset, {})
        cov_term = sum(
            cov_row.get(other_asset, 0.0) * inventories.get(other_asset, 0.0)
            for other_asset in inventories
        )

        binary_dampener = 4.0 * s_i * (1.0 - s_i)
        penalty = g * tau * binary_dampener * cov_term
        raw_r = s_i - penalty

        return max(self.min_reservation, min(self.max_reservation, raw_r))


class DynamicSizeCalculator:
    """Dynamic inventory sizing via Linear-in-Inventory with Inventory Constraints (LIIC).
    
    Formula:
        S(q) = base_size * max(0, 1 - (q / Q_max)^alpha)
    
    When q reaches Q_max on one outcome:
        - Quoted size on that side drops to 0.0 (or minimal reward-stub size).
        - Quoted size on the closing/hedging leg can scale up to aggressively rebalance.
    """

    def __init__(
        self,
        base_size: float = 25.0,
        max_inventory: float = 200.0,
        min_reward_stub_size: float = 5.0,
        alpha: float = 1.0,
    ) -> None:
        self.base_size = float(base_size)
        self.max_inventory = float(max_inventory)
        self.min_reward_stub_size = float(min_reward_stub_size)
        self.alpha = float(alpha)

    def calculate_quote_sizes(
        self,
        q_yes: float,
        q_no: float,
        available_budget_usd: float = 1000.0,
        price_yes: float = 0.50,
        price_no: float = 0.50,
        keep_reward_stub: bool = True,
    ) -> Tuple[float, float]:
        """Compute dynamic quote sizes for YES and NO bids.
        
        Args:
            q_yes: Current held inventory of YES shares.
            q_no: Current held inventory of NO shares.
            available_budget_usd: Unencumbered USDC capital available for bidding.
            price_yes: Target bid price for YES.
            price_no: Target bid price for NO.
            keep_reward_stub: If True and size hits 0, retain min_reward_stub_size.
            
        Returns:
            Tuple of (size_yes, size_no) in whole shares.
        """
        q_y = max(0.0, float(q_yes))
        q_n = max(0.0, float(q_no))
        q_max = max(1.0, self.max_inventory)

        # Fraction of inventory consumed
        ratio_y = min(1.0, q_y / q_max)
        ratio_n = min(1.0, q_n / q_max)

        # Decay factor on each side
        decay_y = max(0.0, 1.0 - (ratio_y ** self.alpha))
        decay_n = max(0.0, 1.0 - (ratio_n ** self.alpha))

        # Raw desired size
        raw_sz_y = self.base_size * decay_y
        raw_sz_n = self.base_size * decay_n

        # If unbalanced, boost closing leg to accelerate pairing
        net_imbalance = q_y - q_n
        if net_imbalance > 0:
            # We have excess YES -> boost NO leg
            boost = min(1.5, 1.0 + (net_imbalance / q_max))
            raw_sz_n = min(self.base_size * 2.0, raw_sz_n * boost)
        elif net_imbalance < 0:
            # We have excess NO -> boost YES leg
            boost = min(1.5, 1.0 + (abs(net_imbalance) / q_max))
            raw_sz_y = min(self.base_size * 2.0, raw_sz_y * boost)

        # Apply reward stub if inventory hit cap
        if keep_reward_stub:
            if ratio_y >= 0.99:
                raw_sz_y = self.min_reward_stub_size
            if ratio_n >= 0.99:
                raw_sz_n = self.min_reward_stub_size

        # Budget constraint
        cost_y = raw_sz_y * max(0.01, price_yes)
        cost_n = raw_sz_n * max(0.01, price_no)
        total_req_usd = cost_y + cost_n

        budget = max(0.0, float(available_budget_usd))
        if total_req_usd > budget and total_req_usd > 1e-6:
            budget_scale = budget / total_req_usd
            raw_sz_y *= budget_scale
            raw_sz_n *= budget_scale

        final_sz_y = math.floor(max(0.0, raw_sz_y))
        final_sz_n = math.floor(max(0.0, raw_sz_n))

        return float(final_sz_y), float(final_sz_n)


class HysteresisGate:
    """Step 5: Queue Preserver via Hysteresis Deadband.
    
    Protects FIFO queue priority, avoids rate-limit churn, and maximizes
    liquidity reward uptime by ignoring sub-tick noise.
    
    Uses asymmetric deadbands:
    - Adverse drift (price moving towards quote): tighter threshold to avoid toxic flow.
    - Favorable drift (price moving away): wider threshold to preserve queue priority.
    """

    def __init__(
        self,
        tick_size: float = 0.01,
        epsilon_adverse_multiplier: float = 0.5,
        epsilon_favorable_multiplier: float = 1.5,
    ) -> None:
        self.tick_size = float(tick_size)
        self.eps_adverse = self.tick_size * float(epsilon_adverse_multiplier)
        self.eps_favorable = self.tick_size * float(epsilon_favorable_multiplier)

    def evaluate_order(
        self,
        target_price: float,
        active_price: Optional[float],
        is_bid: bool = True,
        is_toxicity_fast_path: bool = False,
    ) -> HysteresisAction:
        """Determine whether to Hold or Cancel & Replace an active resting order."""
        if active_price is None or active_price <= 0.0:
            return HysteresisAction.CANCEL_AND_REPLACE

        if is_toxicity_fast_path:
            return HysteresisAction.CANCEL_AND_REPLACE

        drift = target_price - active_price

        # For a BID order:
        # If target < active, the market or fair valuation is dropping. Active price is too high!
        # This is ADVERSE drift -> tight deadband to prevent getting picked off.
        # If target > active, fair valuation is rising. Active price is safer/conservative.
        # This is FAVORABLE drift -> wider deadband to preserve queue spot.
        if is_bid:
            is_adverse = (drift < 0.0)
        else:
            is_adverse = (drift > 0.0)

        threshold = self.eps_adverse if is_adverse else self.eps_favorable

        if abs(drift) < threshold:
            return HysteresisAction.HOLD
        else:
            return HysteresisAction.CANCEL_AND_REPLACE


class MicrostructureMathEngine:
    """Comprehensive mathematical orchestrator combining all 5 pipeline steps.
    
    1. Order Flow Calibration (kappa)
    2. Quote Width (s*)
    3. Quote Center (r_i) with complementary parity
    4. Target Quotes (p_bid^YES, p_bid^NO) with sub-$1.00 pair-cost enforcement
    5. Dynamic Sizing & Queue Preserver Hysteresis
    """

    def __init__(
        self,
        tick_size: float = 0.01,
        gamma: float = 0.05,
        max_inventory: float = 200.0,
        base_size: float = 25.0,
        target_sub_dollar_ceiling: float = 0.990,
    ) -> None:
        self.tick_size = float(tick_size)
        self.gamma = float(gamma)
        self.max_inventory = float(max_inventory)
        self.base_size = float(base_size)
        self.target_sub_dollar_ceiling = float(target_sub_dollar_ceiling)

        self.calibrator = OrderFlowCalibrator()
        self.spread_optimizer = SpreadOptimizer(min_spread=self.tick_size)
        self.reservation_calc = ReservationPriceCalculator()
        self.size_calc = DynamicSizeCalculator(
            base_size=base_size,
            max_inventory=max_inventory,
        )
        self.hysteresis_gate = HysteresisGate(tick_size=self.tick_size)

    def quantize_floor(self, price: float) -> float:
        """Apply strict downward tick floor quantization to avoid rounding up across $1.00."""
        ticks = math.floor(round(price, 6) / self.tick_size)
        quantized = ticks * self.tick_size
        return round(quantized, 4)

    def calculate_quotes(
        self,
        mid_price_yes: float,
        inventory_yes: float,
        inventory_no: float,
        time_remaining_seconds: float,
        total_window_seconds: float = 300.0,
        observed_kappa: Optional[float] = None,
        active_bid_yes: Optional[float] = None,
        active_bid_no: Optional[float] = None,
        available_budget_usd: float = 1000.0,
        spot_shock_flag: bool = False,
    ) -> QuoteResult:
        """Run the full 5-step mathematical pipeline to generate quotes and execution decisions."""
        # Step 1: Order Flow Calibration (kappa)
        kappa = observed_kappa if observed_kappa is not None else self.calibrator.default_kappa
        kappa = max(self.calibrator.min_kappa, min(self.calibrator.max_kappa, kappa))

        # Step 2: Quote Width (s*)
        optimal_spread = self.spread_optimizer.calculate_optimal_spread(
            gamma=self.gamma,
            kappa=kappa,
        )

        # Step 3: Quote Center (r_i) with Parity Coupling
        tau = max(0.0, min(1.0, time_remaining_seconds / max(1.0, total_window_seconds)))
        net_imbalance = inventory_yes - inventory_no

        r_yes = self.reservation_calc.calculate_reservation_price(
            mid_price=mid_price_yes,
            inventory_net=net_imbalance,
            gamma=self.gamma,
            time_remaining_normalized=tau,
        )
        # Parity Coupling ensures r_YES + r_NO = 1.00
        r_no = round(1.00 - r_yes, 4)

        # Step 4: Target Quotes & Sub-$1.00 Guarantee
        half_spread = optimal_spread / 2.0
        raw_bid_yes = r_yes - half_spread
        raw_bid_no = r_no - half_spread

        # Quantize down
        p_bid_yes = self.quantize_floor(raw_bid_yes)
        p_bid_no = self.quantize_floor(raw_bid_no)

        # Bounds check
        p_bid_yes = max(self.tick_size, min(1.00 - self.tick_size, p_bid_yes))
        p_bid_no = max(self.tick_size, min(1.00 - self.tick_size, p_bid_no))

        # Enforce strict Sub-$1.00 window cap: p_bid_yes + p_bid_no <= target_ceiling
        combined = p_bid_yes + p_bid_no
        if combined > self.target_sub_dollar_ceiling:
            excess = combined - self.target_sub_dollar_ceiling
            # Deduct from the heavy side or split evenly
            if inventory_yes >= inventory_no:
                p_bid_yes = self.quantize_floor(p_bid_yes - excess)
            else:
                p_bid_no = self.quantize_floor(p_bid_no - excess)

            combined = p_bid_yes + p_bid_no

        is_sub_one = (combined < 1.00)

        target_quotes = TargetQuotes(
            bid_yes=p_bid_yes,
            bid_no=p_bid_no,
            reservation_yes=r_yes,
            reservation_no=r_no,
            optimal_spread=optimal_spread,
            is_sub_one_dollar=is_sub_one,
            combined_cost=round(combined, 4),
        )

        # Dynamic Sizing (LIIC)
        size_yes, size_no = self.size_calc.calculate_quote_sizes(
            q_yes=inventory_yes,
            q_no=inventory_no,
            available_budget_usd=available_budget_usd,
            price_yes=p_bid_yes,
            price_no=p_bid_no,
        )

        # Step 5: Queue Preserver (Hysteresis Gate)
        action_yes = self.hysteresis_gate.evaluate_order(
            target_price=p_bid_yes,
            active_price=active_bid_yes,
            is_bid=True,
            is_toxicity_fast_path=spot_shock_flag,
        )
        action_no = self.hysteresis_gate.evaluate_order(
            target_price=p_bid_no,
            active_price=active_bid_no,
            is_bid=True,
            is_toxicity_fast_path=spot_shock_flag,
        )

        return QuoteResult(
            target_quotes=target_quotes,
            size_yes=size_yes,
            size_no=size_no,
            action_yes=action_yes,
            action_no=action_no,
            kappa=kappa,
            notes="Sub-$1.00 pair-locked maker quote generated successfully.",
        )
