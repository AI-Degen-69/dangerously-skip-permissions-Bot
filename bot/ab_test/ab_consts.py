"""A/B test identities, targets, and state paths."""

from bot.runs import AB_STATE_PATH as _AB_STATE_PATH
from bot.runs import RUNS_DIR

DEFAULT_BASELINE_ID = "run_20261113_183248_paper_hydrogen_v1_0"
DEFAULT_CANDIDATE_ID = "hydrogen-v2.0"
CANDIDATE_DISPLAY_NAME = "Hydrogen v2.0"
BASELINE_DISPLAY_NAME = "Hydrogen v1.0"
AB_STATE_PATH = _AB_STATE_PATH

TARGET_SAMPLE_SIZE = 120  # Active traded windows (fills > 0) for Welch's t-test (80% power, alpha 0.05)
TARGET_PAIRED_WINDOWS = 60  # Windows with upShares > 0 and downShares > 0
TARGET_SUB_DOLLAR_PAIRS = 35  # Sub-$1.00 pairs (pairCost < 1.00); >54% of paired windows
ALPHA = 0.05  # One-tailed significance level

__all__ = [
    "AB_STATE_PATH",
    "ALPHA",
    "RUNS_DIR",
    "BASELINE_DISPLAY_NAME",
    "CANDIDATE_DISPLAY_NAME",
    "DEFAULT_BASELINE_ID",
    "DEFAULT_CANDIDATE_ID",
    "TARGET_PAIRED_WINDOWS",
    "TARGET_SAMPLE_SIZE",
    "TARGET_SUB_DOLLAR_PAIRS",
]
