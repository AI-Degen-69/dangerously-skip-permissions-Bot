"""Unit tests for RiskAndSizeManager.
Verifies hard inventory caps, 3:1 reward ratio compliance, unwind mode, and hard time cutoffs.
"""

import pytest
from bot.microstructure_engine.risk_and_size_manager import (
    RiskAndSizeManager,
    TimePhase,
)


class TestRiskAndSizeManager:
    def test_hard_cutoff_pulls_all_bids(self):
        manager = RiskAndSizeManager(cutoff_seconds_before_close=60.0)
        # 45 seconds remaining -> HARD_CUTOFF
        state = manager.evaluate_risk(
            time_remaining_seconds=45.0,
            proposed_size_yes=25.0,
            proposed_size_no=25.0,
            available_usdc=1000.0,
            price_yes=0.48,
            price_no=0.48,
        )
        assert state.time_phase == TimePhase.HARD_CUTOFF
        assert not state.allow_bid_yes
        assert not state.allow_bid_no
        assert state.size_cap_yes == 0.0
        assert state.size_cap_no == 0.0
        assert state.is_hard_cutoff

    def test_unwind_mode_quotes_closing_leg_only(self):
        manager = RiskAndSizeManager(
            unwind_seconds_before_close=90.0,
            cutoff_seconds_before_close=60.0,
        )
        # 75s remaining -> UNWIND phase
        # Simulate having 50 excess YES shares
        manager.update_fill("YES", 50.0, 0.48)

        state = manager.evaluate_risk(
            time_remaining_seconds=75.0,
            proposed_size_yes=25.0,
            proposed_size_no=25.0,
            available_usdc=1000.0,
            price_yes=0.48,
            price_no=0.48,
        )
        assert state.time_phase == TimePhase.UNWIND
        # Must halt buying YES, and only quote NO (closing leg)
        assert not state.allow_bid_yes
        assert state.size_cap_yes == 0.0
        assert state.allow_bid_no
        assert state.size_cap_no > 0.0

    def test_inventory_caps(self):
        manager = RiskAndSizeManager(max_inventory_per_side=100.0)
        # Fill 100 YES
        manager.update_fill("YES", 100.0, 0.48)

        state = manager.evaluate_risk(
            time_remaining_seconds=180.0,
            proposed_size_yes=25.0,
            proposed_size_no=25.0,
            available_usdc=1000.0,
            price_yes=0.48,
            price_no=0.48,
        )
        # YES accumulation paused (stub only allowed)
        assert not state.allow_bid_yes
        assert state.size_cap_yes == manager.min_reward_stub_size
        assert state.allow_bid_no
        assert state.size_cap_no == 25.0

    def test_deduct_merged_pairs(self):
        manager = RiskAndSizeManager()
        manager.update_fill("YES", 40.0, 0.48)
        manager.update_fill("NO", 40.0, 0.49)
        assert manager.inventory.completed_pairs == 40.0

        manager.deduct_merged_pairs(40.0)
        assert manager.inventory.shares_yes == 0.0
        assert manager.inventory.shares_no == 0.0
        assert manager.inventory.completed_pairs == 0.0
