"""Frozen execution constants measured from dangerously-skip-permissions_24h_trades.csv.

Source: 17,416 rows = 16,855 TRADE (all BUY) + 559 REDEEM, 288 markets.
Verified 2026-11-07 via local CSV analysis. Do not tune without re-measuring.
"""

# Clips / sizing
CLIP_SHARES_DEFAULT = 30.0
CLIP_SHARES_FRACTION = 0.304  # 30.4% of tickets are exactly 30.0 shares
MAX_SHARES = 50.0
MEAN_SHARES = 16.42
MEDIAN_SHARES = 13.86
MEAN_USD_PER_TICKET = 7.64
MEDIAN_USD_PER_TICKET = 4.98

# Window budget
MEAN_TRADES_PER_WINDOW = 58.5
MEDIAN_TRADES_PER_WINDOW = 45
MAX_TRADES_PER_WINDOW = 404
MEAN_USD_PER_WINDOW = 447.0
MEDIAN_USD_PER_WINDOW = 316.0
MAX_USD_PER_WINDOW = 3800.0

# Coverage / structure
NUM_WINDOWS_24H = 288
BOTH_SIDES_RATE = 0.972  # 280/288 windows touched both outcomes
SINGLE_SIDED_WINDOWS = 8

# Timing (seconds after window open)
FIRST_TOUCH_MEDIAN_S = 13.0
FIRST_TOUCH_MEAN_S = 24.0
HEDGE_LEG_MEDIAN_S = 15.0

# Cadence shape M0..M4 (minute buckets within 5-min window)
M_BUCKETS = (3081, 3821, 4289, 3914, 1750)

# Behavior
BUY_ONLY = True
HOLD_TO_REDEEM = True
MEDIAN_ABS_TILT = 0.28
