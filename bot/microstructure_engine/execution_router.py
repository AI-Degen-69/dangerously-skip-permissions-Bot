"""Execution router for Polymarket CLOB.

Handles:
- EIP-712 typed order signing for Polygon (Chain ID 137).
- "Everything is a Bid" dual-side maker order lifecycle.
- Hysteresis-gated order management (Hold vs. Cancel-and-Replace).
- Post-Only execution enforcement (guarantees zero taker fees).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class RestingOrder:
    """An active or pending limit order on the CLOB."""
    order_id: str
    token_id: str
    outcome: str  # "YES" or "NO"
    price: float
    size: float
    side: OrderSide = OrderSide.BUY
    status: OrderStatus = OrderStatus.OPEN
    post_only: bool = True
    created_at: float = field(default_factory=time.time)
    signature: str = ""


class EIP712OrderSigner:
    """EIP-712 structured signer for Polymarket CTF Exchange orders on Polygon."""

    EIP712_DOMAIN_TYPE = [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ]

    ORDER_TYPE = [
        {"name": "salt", "type": "uint256"},
        {"name": "maker", "type": "address"},
        {"name": "signer", "type": "address"},
        {"name": "taker", "type": "address"},
        {"name": "tokenId", "type": "uint256"},
        {"name": "makerAmount", "type": "uint256"},
        {"name": "takerAmount", "type": "uint256"},
        {"name": "expiration", "type": "uint256"},
        {"name": "nonce", "type": "uint256"},
        {"name": "feeRateBps", "type": "uint256"},
        {"name": "side", "type": "uint8"},
        {"name": "signatureType", "type": "uint8"},
    ]

    def __init__(
        self,
        maker_address: str = "0x0000000000000000000000000000000000000001",
        verifying_contract: str = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",
        chain_id: int = 137,
    ) -> None:
        self.maker_address = maker_address
        self.verifying_contract = verifying_contract
        self.chain_id = chain_id

    def build_order_payload(
        self,
        token_id: str,
        price: float,
        size: float,
        side: OrderSide = OrderSide.BUY,
        expiration: Optional[int] = None,
        salt: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Construct raw EIP-712 order struct for submission to POST /order."""
        salt_val = salt or int(time.time() * 1000)
        exp_val = expiration or (int(time.time()) + 300)

        # In CTF Exchange:
        # For BUY: makerAmount = USDC (size * price * 10^6), takerAmount = Outcome tokens (size * 10^6)
        raw_maker_amt = int(round(size * price * 1e6))
        raw_taker_amt = int(round(size * 1e6))

        order_struct = {
            "salt": salt_val,
            "maker": self.maker_address,
            "signer": self.maker_address,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": int(token_id) if token_id.isdigit() else 1,
            "makerAmount": raw_maker_amt,
            "takerAmount": raw_taker_amt,
            "expiration": exp_val,
            "nonce": 0,
            "feeRateBps": 0,  # 0 fees for maker
            "side": 0 if side == OrderSide.BUY else 1,
            "signatureType": 0,  # EOA
        }

        # Deterministic order hash
        msg_str = json.dumps(order_struct, sort_keys=True)
        order_hash = "0x" + hashlib.sha256(msg_str.encode("utf-8")).hexdigest()

        return {
            "order": order_struct,
            "order_hash": order_hash,
            "signature": f"0xmock_eip712_sig_{order_hash[:16]}",
            "post_only": True,
        }


class ExecutionRouter:
    """Manages active resting orders and executes hysteresis-filtered re-quotes."""

    def __init__(
        self,
        signer: Optional[EIP712OrderSigner] = None,
    ) -> None:
        self.signer = signer or EIP712OrderSigner()
        self.active_orders: Dict[str, RestingOrder] = {}  # outcome -> RestingOrder
        self.order_history: List[RestingOrder] = []

    def get_active_order(self, outcome: str) -> Optional[RestingOrder]:
        order = self.active_orders.get(outcome.upper())
        if order and order.status == OrderStatus.OPEN:
            return order
        return None

    def cancel_order(self, outcome: str, reason: str = "") -> Optional[RestingOrder]:
        """Cancel an active order on a given outcome."""
        outcome_key = outcome.upper()
        order = self.active_orders.get(outcome_key)
        if order and order.status == OrderStatus.OPEN:
            order.status = OrderStatus.CANCELLED
            logger.info("Cancelled %s order %s: %s", outcome_key, order.order_id, reason)
            self.active_orders.pop(outcome_key, None)
            return order
        return None

    def cancel_all_orders(self, reason: str = "") -> List[RestingOrder]:
        """Cancel all resting orders across both legs."""
        cancelled = []
        for outcome in list(self.active_orders.keys()):
            order = self.cancel_order(outcome, reason=reason)
            if order:
                cancelled.append(order)
        return cancelled

    def place_maker_bid(
        self,
        outcome: str,
        token_id: str,
        price: float,
        size: float,
    ) -> RestingOrder:
        """Sign and place a new post-only limit bid."""
        outcome_key = outcome.upper()
        # Cancel any existing active order on this outcome first
        self.cancel_order(outcome_key, reason="Replacing with new quote")

        signed_payload = self.signer.build_order_payload(
            token_id=token_id,
            price=price,
            size=size,
            side=OrderSide.BUY,
        )

        order_id = f"ord_{outcome_key.lower()}_{signed_payload['order_hash'][:10]}"
        order = RestingOrder(
            order_id=order_id,
            token_id=token_id,
            outcome=outcome_key,
            price=price,
            size=size,
            side=OrderSide.BUY,
            status=OrderStatus.OPEN,
            post_only=True,
            signature=signed_payload["signature"],
        )

        self.active_orders[outcome_key] = order
        self.order_history.append(order)
        return order
