"""Unit tests for ExecutionRouter and EIP712OrderSigner.
Verifies post-only limit bids, EIP-712 hashing, cancellation, and active order tracking.
"""

import pytest
from bot.microstructure_engine.execution_router import (
    ExecutionRouter,
    EIP712OrderSigner,
    OrderSide,
    OrderStatus,
)


class TestExecutionRouter:
    def test_eip712_signing_structure(self):
        signer = EIP712OrderSigner(
            maker_address="0x1111111111111111111111111111111111111111",
            chain_id=137,
        )
        payload = signer.build_order_payload(
            token_id="12345",
            price=0.48,
            size=50.0,
            side=OrderSide.BUY,
        )
        order = payload["order"]
        assert order["maker"] == "0x1111111111111111111111111111111111111111"
        assert order["feeRateBps"] == 0
        assert order["side"] == 0  # BUY
        assert payload["post_only"] is True
        assert payload["signature"].startswith("0xmock_eip712_sig_")

    def test_place_and_cancel_order(self):
        router = ExecutionRouter()
        order = router.place_maker_bid(
            outcome="YES",
            token_id="999",
            price=0.48,
            size=25.0,
        )
        assert order.outcome == "YES"
        assert order.status == OrderStatus.OPEN
        assert router.get_active_order("YES") == order

        # Cancel
        cancelled = router.cancel_order("YES", reason="Test cancel")
        assert cancelled is not None
        assert cancelled.status == OrderStatus.CANCELLED
        assert router.get_active_order("YES") is None

    def test_cancel_all_orders(self):
        router = ExecutionRouter()
        router.place_maker_bid("YES", "101", 0.48, 20.0)
        router.place_maker_bid("NO", "102", 0.49, 20.0)

        assert router.get_active_order("YES") is not None
        assert router.get_active_order("NO") is not None

        cancelled = router.cancel_all_orders(reason="Shutdown")
        assert len(cancelled) == 2
        assert router.get_active_order("YES") is None
        assert router.get_active_order("NO") is None
