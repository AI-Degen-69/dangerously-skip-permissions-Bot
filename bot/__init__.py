"""BTC 5m Up/Down paper bot — Phase 3 paper executor (no keys, no funding)."""
from .constants import CLIP_SHARES_DEFAULT, NUM_WINDOWS_24H
from .signal import DumbLean

__all__ = ["CLIP_SHARES_DEFAULT", "NUM_WINDOWS_24H", "DumbLean"]
