"""Unit tests for SettlementManager.
Verifies paired fill detection, batch thresholding, and atomic token merging (YES + NO -> $1.00 USDC).
"""

import pytest
from bot.microstructure_engine.settlement_manager import (
    SettlementManager,
    FillEvent,
)


class TestSettlementManager:
    def test_paired_fill_and_merge(self):
        manager = SettlementManager(min_merge_batch_shares=20.0)

        # Ingest 30 YES @ 0.48
        manager.on_fill(FillEvent(outcome="YES", shares=30.0, price=0.48))
        assert manager.shares_yes == 30.0
        assert manager.shares_no == 0.0

        # Ingest 30 NO @ 0.49 -> Total cost: 0.48 + 0.49 = 0.97 per pair
        receipt = manager.on_fill(FillEvent(outcome="NO", shares=30.0, price=0.49))

        assert receipt is not None
        assert receipt.pairs_merged == 30.0
        assert receipt.collateral_released_usd == 30.0  # 30 * $1.00
        # Cost = 30 * 0.48 + 30 * 0.49 = 14.40 + 14.70 = 29.10
        assert receipt.combined_cost_usd == 29.10
        # Profit = 30.00 - 29.10 = 0.90 USD
        assert receipt.realized_profit_usd == 0.90
        assert receipt.status == "CONFIRMED"

        # Inventory is zeroed after merge
        assert manager.shares_yes == 0.0
        assert manager.shares_no == 0.0
        assert manager.total_realized_profit() == 0.90

    def test_batch_threshold_postpones_micro_merges(self):
        manager = SettlementManager(min_merge_batch_shares=50.0)

        # Ingest only 10 pairs -> below batch threshold of 50
        manager.on_fill(FillEvent(outcome="YES", shares=10.0, price=0.48))
        receipt = manager.on_fill(FillEvent(outcome="NO", shares=10.0, price=0.49))

        # Receipt should be None because batch size is below 50
        assert receipt is None
        assert manager.shares_yes == 10.0
        assert manager.shares_no == 10.0

        # Force merge on window close
        forced_receipt = manager.evaluate_and_merge(force=True)
        assert forced_receipt is not None
        assert forced_receipt.pairs_merged == 10.0
        assert manager.shares_yes == 0.0
        assert manager.shares_no == 0.0
