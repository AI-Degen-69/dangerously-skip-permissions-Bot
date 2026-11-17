"""End-to-End Pipeline Integration Test for Microstructure Inventory Risk Engine.

Validates the full lifecycle:
1. Market feed updates book and external spot ticker.
2. Math engine estimates kappa, reservation center, optimal spread, and quotes sub-$1.00 pair.
3. Risk manager gates sizing and 3:1 ratio compliance.
4. Execution router signs and rests post-only dual bids on CLOB.
5. Paired fills arrive, triggering atomic token merge and realized sub-$1.00 arbitrage profit.
"""

import pytest
from bot.microstructure_engine import (
    MicrostructureMathEngine,
    UnifiedMarketFeed,
    PolymarketFeedClient,
    BinanceSpotFeedClient,
    RiskAndSizeManager,
    ExecutionRouter,
    SettlementManager,
    FillEvent,
    HysteresisAction,
)


def test_full_engine_pipeline_e2e():
    # 1. Initialize components
    math_engine = MicrostructureMathEngine(
        tick_size=0.01,
        gamma=0.05,
        target_sub_dollar_ceiling=0.985,
    )
    feed = UnifiedMarketFeed()
    risk_manager = RiskAndSizeManager(
        max_inventory_per_side=200.0,
        unwind_seconds_before_close=90.0,
        cutoff_seconds_before_close=60.0,
    )
    router = ExecutionRouter()
    settlement = SettlementManager(min_merge_batch_shares=20.0)

    # 2. Simulate incoming Polymarket L2 book
    snap_yes = feed.polymarket.handle_book_message({
        "asset_id": "token_yes_btc",
        "bids": [{"price": "0.48", "size": "150"}, {"price": "0.46", "size": "300"}],
        "asks": [{"price": "0.52", "size": "100"}, {"price": "0.54", "size": "250"}],
    })
    assert snap_yes.mid_price == 0.50

    # 3. Simulate spot ticker (no shock)
    ticker = feed.binance.handle_ticker_message({"c": "92500.0", "timestamp": 100.0})
    assert not feed.is_toxicity_shock()

    # 4. Generate Target Quotes via Math Engine
    # Time remaining: 200 seconds in a 300s window (Normal Phase)
    quote_res = math_engine.calculate_quotes(
        mid_price_yes=snap_yes.mid_price,
        inventory_yes=risk_manager.inventory.shares_yes,
        inventory_no=risk_manager.inventory.shares_no,
        time_remaining_seconds=200.0,
        available_budget_usd=1000.0,
        spot_shock_flag=feed.is_toxicity_shock(),
    )

    # Invariant: Sub-$1.00 pair cost guaranteed
    assert quote_res.target_quotes.is_sub_one_dollar
    assert quote_res.target_quotes.combined_cost <= 0.985
    p_bid_y = quote_res.target_quotes.bid_yes
    p_bid_n = quote_res.target_quotes.bid_no
    assert p_bid_y + p_bid_n <= 0.985

    # 5. Evaluate Risk & Sizing Controls
    risk_state = risk_manager.evaluate_risk(
        time_remaining_seconds=200.0,
        proposed_size_yes=quote_res.size_yes,
        proposed_size_no=quote_res.size_no,
        available_usdc=1000.0,
        price_yes=p_bid_y,
        price_no=p_bid_n,
    )
    assert not risk_state.is_hard_cutoff
    assert risk_state.allow_bid_yes
    assert risk_state.allow_bid_no

    # 6. Execution Router: Place Dual Post-Only Bids
    order_y = router.place_maker_bid("YES", "token_yes_btc", p_bid_y, risk_state.size_cap_yes)
    order_n = router.place_maker_bid("NO", "token_no_btc", p_bid_n, risk_state.size_cap_no)

    assert router.get_active_order("YES") is not None
    assert router.get_active_order("NO") is not None
    assert order_y.post_only and order_n.post_only

    # 7. Simulate Fills: 30 shares of YES and 30 shares of NO fill
    fill_y = FillEvent(outcome="YES", shares=30.0, price=p_bid_y)
    fill_n = FillEvent(outcome="NO", shares=30.0, price=p_bid_n)

    risk_manager.update_fill(fill_y.outcome, fill_y.shares, fill_y.price)
    settlement.on_fill(fill_y)

    risk_manager.update_fill(fill_n.outcome, fill_n.shares, fill_n.price)
    merge_receipt = settlement.on_fill(fill_n)

    # 8. Settlement Manager Executes Atomic Merge
    assert merge_receipt is not None
    assert merge_receipt.pairs_merged == 30.0
    assert merge_receipt.collateral_released_usd == 30.0
    # Expected profit: 30.00 - 30 * (p_bid_y + p_bid_n) > 0
    expected_profit = 30.00 - (30.0 * (p_bid_y + p_bid_n))
    assert pytest.approx(merge_receipt.realized_profit_usd, rel=1e-3) == expected_profit
    assert merge_receipt.realized_profit_usd > 0.0

    # 9. Sync Risk Manager with Settlement Release
    risk_manager.deduct_merged_pairs(merge_receipt.pairs_merged)
    assert risk_manager.inventory.shares_yes == 0.0
    assert risk_manager.inventory.shares_no == 0.0
    assert risk_manager.inventory.net_exposure == 0.0
