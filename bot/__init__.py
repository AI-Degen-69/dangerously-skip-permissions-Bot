"""BTC 5m Up/Down paper bot — MSR-v2 Strategy & Microstructure Engine."""

from .constants import (
    CLIP_SHARES_DEFAULT,
    MAX_SHARES,
    MAX_SHARE_LEAD,
    NUM_WINDOWS_24H,
    STRATEGY_ID,
    STRATEGY_NAME,
    STRATEGY_SYMBOL,
)
from .signal import DumbLean

__all__ = [
    "CLIP_SHARES_DEFAULT",
    "MAX_SHARES",
    "MAX_SHARE_LEAD",
    "NUM_WINDOWS_24H",
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "STRATEGY_SYMBOL",
    "DumbLean",
]
