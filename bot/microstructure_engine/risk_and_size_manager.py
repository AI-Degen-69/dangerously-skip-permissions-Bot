"""Risk and Size Manager for Polymarket Binary Options Market Making.

Enforces:
1. Hard inventory caps (q >= Q_max -> halt accumulation on heavy side).
2. Polymarket 3:1 Liquidity Rewards spread ratio & stub qualification.
3. Market time decay phases:
   - Normal Quoting: t < T - 90s
   - Unwind Mode: T - 90s <= t < T - 60s
   - Hard Kill-Switch Cutoff: t >= T - 60s (pull bids before oracle expiration)
4. Collateral margin sufficiency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class TimePhase(str, Enum):
    NORMAL = "Normal Quoting"
    UNWIND = "Inventory Unwind"
    HARD_CUTOFF = "Hard Cutoff (Orders Pulled)"


@dataclass
class InventoryPosition:
    """Current inventory state across complementary outcomes."""
    shares_yes: float = 0.0
    shares_no: float = 0.0
    cost_basis_yes: float = 0.0
    cost_basis_no: float = 0.0
    unmerged_pairs: float = 0.0

    @property
    def net_exposure(self) -> float:
        """Net directional unhedged shares: positive = long YES, negative = long NO."""
        return self.shares_yes - self.shares_no

    @property
    def completed_pairs(self) -> float:
        """Completed matched pairs available for atomic merging."""
        return min(self.shares_yes, self.shares_no)

    @property
    def total_shares(self) -> float:
        return self.shares_yes + self.shares_no


@dataclass
class RiskState:
    """Snapshot of current risk controls and permissions."""
    time_phase: TimePhase
    allow_bid_yes: bool
    allow_bid_no: bool
    size_cap_yes: float
    size_cap_no: float
    is_hard_cutoff: bool
    reward_ratio_compliant: bool
    reason: str = ""


class RiskAndSizeManager:
    """Dynamic capital and risk controller enforcing microstructural constraints."""

    def __init__(
        self,
        max_inventory_per_side: float = 200.0,
        max_unhedged_shares: float = 80.0,
        unwind_seconds_before_close: float = 90.0,
        cutoff_seconds_before_close: float = 60.0,
        min_reward_stub_size: float = 5.0,
        reward_spread_ratio_max: float = 3.0,
    ) -> None:
        self.max_inventory_per_side = float(max_inventory_per_side)
        self.max_unhedged_shares = float(max_unhedged_shares)
        self.unwind_seconds = float(unwind_seconds_before_close)
        self.cutoff_seconds = float(cutoff_seconds_before_close)
        self.min_reward_stub_size = float(min_reward_stub_size)
        self.reward_spread_ratio_max = float(reward_spread_ratio_max)

        self.inventory = InventoryPosition()

    def update_fill(self, outcome: str, shares: float, price: float) -> None:
        """Update inventory position on trade fill."""
        outcome = outcome.upper()
        amt = float(shares)
        cost = amt * float(price)

        if outcome == "YES":
            self.inventory.shares_yes += amt
            self.inventory.cost_basis_yes += cost
        elif outcome == "NO":
            self.inventory.shares_no += amt
            self.inventory.cost_basis_no += cost

    def deduct_merged_pairs(self, pairs_merged: float) -> None:
        """Deduct merged YES and NO shares when atomic merge executes."""
        m = float(pairs_merged)
        self.inventory.shares_yes = max(0.0, self.inventory.shares_yes - m)
        self.inventory.shares_no = max(0.0, self.inventory.shares_no - m)

    def determine_time_phase(self, time_remaining_seconds: float) -> TimePhase:
        """Classify current time into Normal, Unwind, or Hard Cutoff phase."""
        t_rem = float(time_remaining_seconds)
        if t_rem <= self.cutoff_seconds:
            return TimePhase.HARD_CUTOFF
        elif t_rem <= self.unwind_seconds:
            return TimePhase.UNWIND
        else:
            return TimePhase.NORMAL

    def evaluate_risk(
        self,
        time_remaining_seconds: float,
        proposed_size_yes: float,
        proposed_size_no: float,
        available_usdc: float,
        price_yes: float,
        price_no: float,
    ) -> RiskState:
        """Evaluate inventory limits, 3:1 reward rules, and time cutoffs."""
        phase = self.determine_time_phase(time_remaining_seconds)

        # 1. Hard Cutoff: Pull all bids in final 60 seconds
        if phase == TimePhase.HARD_CUTOFF:
            return RiskState(
                time_phase=phase,
                allow_bid_yes=False,
                allow_bid_no=False,
                size_cap_yes=0.0,
                size_cap_no=0.0,
                is_hard_cutoff=True,
                reward_ratio_compliant=False,
                reason="Hard cutoff reached (<= 60s to resolution). All maker bids pulled to prevent terminal toxic fills.",
            )

        allow_y = True
        allow_n = True
        cap_y = float(proposed_size_yes)
        cap_n = float(proposed_size_no)

        # 2. Unwind Phase (90s to 60s): Cease accumulation, quote closing leg only
        if phase == TimePhase.UNWIND:
            net = self.inventory.net_exposure
            if net > 0:
                # Excess YES: stop buying YES, only buy NO to close
                allow_y = False
                cap_y = 0.0
                cap_n = min(cap_n, abs(net))
            elif net < 0:
                # Excess NO: stop buying NO, only buy YES to close
                allow_n = False
                cap_n = 0.0
                cap_y = min(cap_y, abs(net))
            else:
                # Perfectly hedged: cease new quoting
                allow_y = False
                allow_n = False
                cap_y = 0.0
                cap_n = 0.0

            return RiskState(
                time_phase=phase,
                allow_bid_yes=allow_y,
                allow_bid_no=allow_n,
                size_cap_yes=cap_y,
                size_cap_no=cap_n,
                is_hard_cutoff=False,
                reward_ratio_compliant=True,
                reason=f"Unwind mode (net={net:+.1f} sh): pulling heavy side, quoting closing leg only.",
            )

        # 3. Normal Phase: Enforce inventory caps (q >= Q_max)
        if self.inventory.shares_yes >= self.max_inventory_per_side:
            allow_y = False
            cap_y = self.min_reward_stub_size  # reward stub only
        elif (self.inventory.shares_yes + cap_y) > self.max_inventory_per_side:
            cap_y = max(0.0, self.max_inventory_per_side - self.inventory.shares_yes)

        if self.inventory.shares_no >= self.max_inventory_per_side:
            allow_n = False
            cap_n = self.min_reward_stub_size  # reward stub only
        elif (self.inventory.shares_no + cap_n) > self.max_inventory_per_side:
            cap_n = max(0.0, self.max_inventory_per_side - self.inventory.shares_no)

        # 4. Enforce max unhedged shares cap
        curr_net = self.inventory.net_exposure
        if curr_net >= self.max_unhedged_shares:
            allow_y = False
            cap_y = self.min_reward_stub_size
        elif curr_net <= -self.max_unhedged_shares:
            allow_n = False
            cap_n = self.min_reward_stub_size

        # 5. Enforce 3:1 Reward Ratio compliance between active quotes
        # Reward formula: max(min(q1, q2), max(q1, q2) / 3)
        reward_compliant = True
        if allow_y and allow_n and cap_y > 0 and cap_n > 0:
            ratio = max(cap_y, cap_n) / min(cap_y, cap_n)
            if ratio > self.reward_spread_ratio_max:
                reward_compliant = False
                # Adjust smaller side up to min 1:3 ratio if budget permits
                min_req = max(cap_y, cap_n) / self.reward_spread_ratio_max
                if cap_y < cap_n:
                    cap_y = max(cap_y, min_req)
                else:
                    cap_n = max(cap_n, min_req)

        # 6. Available USDC margin check
        req_usdc = (cap_y * price_yes) + (cap_n * price_no)
        if req_usdc > available_usdc and req_usdc > 0:
            scale = available_usdc / req_usdc
            cap_y = int(cap_y * scale)
            cap_n = int(cap_n * scale)

        return RiskState(
            time_phase=phase,
            allow_bid_yes=allow_y and (cap_y > 0),
            allow_bid_no=allow_n and (cap_n > 0),
            size_cap_yes=float(cap_y),
            size_cap_no=float(cap_n),
            is_hard_cutoff=False,
            reward_ratio_compliant=reward_compliant,
            reason="Normal risk checks passed.",
        )
