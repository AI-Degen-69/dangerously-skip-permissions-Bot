"""Strategy Constants & Microstructure Parameters.

🎯 Hybrid Arbitrage Pairing & Certainty Sniping v1 (HAPCS-v1)
Reconstructed and cross-validated against 16,855 fills from wallet
`dangerously-skip-permissions` across 288 consecutive 5-minute Bitcoin markets.
"""

# Strategy Identity
STRATEGY_ID = "hapcs-v1"
STRATEGY_SYMBOL = "🎯 HAPCS-v1"
STRATEGY_NAME = "Hybrid Arbitrage Pairing & Certainty Sniping v1"
STRATEGY_SIGNATURE = (
    "Maker Dip Grid [7¢–50¢] (0% fee) · Dynamic Pairing Arbitrage · "
    "Resolution Certainty Snipe [up to 97.5¢] · Pair Cost Benchmark $0.965 (cap ≤$0.990)"
)

# Timing Parameters (seconds countdown SBC: seconds before close)
WINDOW_S = 300                 # 5 minutes per market window
PRE_OPEN_PIPELINE_S = 10       # T-310s: Pre-open discovery, book initialization & resting order placement
WINDOW_OPEN_BUFFER_S = 4       # T-296s: Anchor price registration threshold
M4_SNIPE_WINDOW_S = 60         # T-60s: Minute 4 resolution certainty snipe & deficit close
HARD_CUTOFF_SBC = 12           # T-12s: Hard settlement cutoff (0 fills in final 12s)
ACTIVE_WINDOW_SBC = (HARD_CUTOFF_SBC, WINDOW_S + PRE_OPEN_PIPELINE_S)

# Sizing Parameters (shares)
CLIP_SHARES_DEFAULT = 30.0     # 30.0 shares = dominant order signature (31.0% of tape)
MAX_SHARES = 50.0              # 50.0 shares = deficit catch-up cap
MAX_SHARE_LEAD = 90.0          # 90.0 shares = hard ceiling on unhedged lead (3 clips max)

# Microstructure Price Bands ($)
STRADDLE_BAND = (0.34, 0.55)   # Opening straddle band [34¢–55¢] (median 43¢)
STRADDLE_MEDIAN = 0.43         # Opening straddle median price (43¢)
DIP_LADDER_MAX = 0.50          # Upper bound of passive Maker Dip Grid [7¢–50¢]
RESOLUTION_SNIPE_BAND = (0.90, 0.975)  # Minute 4 resolution certainty snipe band (up to 97.5¢)
PRICE_FLOOR = 0.07             # Hard lower cutoff (<7¢ lottery tail strictly skipped)
PRICE_CEILING = 0.975          # Hard upper cutoff (>97.5¢ extreme certainty strictly skipped)

# Mathematical Sub-$1.00 Pair Cost Constraints & Benchmarks
BENCHMARK_PAIR_COST = 0.965    # Measured historical tape benchmark ($0.9654 on tape, +3.5% margin)
PAIR_COST_BENCHMARK = BENCHMARK_PAIR_COST
TARGET_PAIR_COST = BENCHMARK_PAIR_COST  # backward-compat alias
PAIR_COST_TARGET = BENCHMARK_PAIR_COST  # backward-compat alias
PAIR_COST_MAX = 0.990          # Hard sub-$1.00 ceiling (never enters pair ≥ $1.00)
MEAN_PAIR_COST = 0.9462        # Measured mean pair cost on tape

# Exchange Fee Model
TAKER_FEE_COEFF = 0.07         # Polymarket parabolic taker fee: 0.07 * p * (1 - p)
MAKER_FEE = 0.0                # 0% maker fee on resting limit orders

# Risk Guardrails
DAILY_LOSS_CAP_USD = 500.0     # Maximum allowable daily loss
MAX_USD_PER_WINDOW = 4000.0    # Maximum capital committed per 5-minute window
MAX_TRADES_PER_WINDOW = 500    # Hard fill cap per window
HEARTBEAT_STALE_S = 120        # Loop staleness threshold

# ---------------------------------------------------------------------------
# Benchmark 24h Tape Reference (docs/dangerously-skip-permissions)
# Used by perf() & reconcile() to measure fidelity against the 288-window tape
# ---------------------------------------------------------------------------
NUM_WINDOWS_24H = 288
MEDIAN_TRADES_PER_WINDOW = 45.0
MEAN_TRADES_PER_WINDOW = 58.5
MEDIAN_USD_PER_WINDOW = 316.0
MEAN_USD_PER_WINDOW = 447.0
BOTH_SIDES_RATE = 0.972
M_BUCKETS = (3081, 3821, 4289, 3914, 1750)
MAKER_SHARE_TARGET = 0.70
BUY_ONLY = True
HOLD_TO_REDEEM = True
