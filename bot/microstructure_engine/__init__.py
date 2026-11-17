"""Microstructure-Calibrated Inventory Risk Engine for Polymarket Binary Options.

Core Components:
- math_engine: Zero-network analytical math classes (kappa, s*, r_i, target quotes, sizing, hysteresis).
- market_feed: Async WebSocket clients for Polymarket L2 books and external spot tickers (Binance BTC).
- risk_and_size_manager: Capital allocation, hard inventory caps, 3:1 reward ratio, and time decay cutoffs.
- execution_router: Dual-sided 'Everything is a Bid' order lifecycle, EIP-712 signing, and post-only quoting.
- settlement_manager: Automated paired fill listener and atomic CTF token merging (YES + NO -> $1.00 USDC).
"""

from .math_engine import (
    MicrostructureMathEngine,
    OrderFlowCalibrator,
    SpreadOptimizer,
    ReservationPriceCalculator,
    DynamicSizeCalculator,
    HysteresisGate,
    HysteresisAction,
    QuoteResult,
    TargetQuotes,
)
from .market_feed import (
    OrderBookSnapshot,
    TradePrint,
    ExternalSpotTicker,
    PolymarketFeedClient,
    BinanceSpotFeedClient,
    UnifiedMarketFeed,
)
from .risk_and_size_manager import (
    RiskAndSizeManager,
    InventoryPosition,
    RiskState,
    TimePhase,
)
from .execution_router import (
    ExecutionRouter,
    OrderSide,
    OrderStatus,
    RestingOrder,
    EIP712OrderSigner,
)
from .settlement_manager import (
    SettlementManager,
    MergeReceipt,
    FillEvent,
)

__all__ = [
    "MicrostructureMathEngine",
    "OrderFlowCalibrator",
    "SpreadOptimizer",
    "ReservationPriceCalculator",
    "DynamicSizeCalculator",
    "HysteresisGate",
    "HysteresisAction",
    "QuoteResult",
    "TargetQuotes",
    "OrderBookSnapshot",
    "TradePrint",
    "ExternalSpotTicker",
    "PolymarketFeedClient",
    "BinanceSpotFeedClient",
    "UnifiedMarketFeed",
    "RiskAndSizeManager",
    "InventoryPosition",
    "RiskState",
    "TimePhase",
    "ExecutionRouter",
    "OrderSide",
    "OrderStatus",
    "RestingOrder",
    "EIP712OrderSigner",
    "SettlementManager",
    "MergeReceipt",
    "FillEvent",
]
