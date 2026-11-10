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

# Multi-Setup Strategy Registry
STRATEGY_SETUPS = {
    "hapcs-v1": {
        "id": "hapcs-v1",
        "symbol": "🎯 HAPCS-v1",
        "name": "Hybrid Arbitrage Pairing & Certainty Sniping v1",
        "signature": (
            "Maker Dip Grid [7¢–50¢] · Dynamic Pairing Equalizer · "
            "M4 Certainty Sniping [up to 97.5¢] · Pair Cost Benchmark $0.965 (cap ≤$0.990)"
        ),
        "description": (
            "Dual-regime setup combining passive dip grid accumulation with Minute 4 "
            "certainty sniping up to 97.5¢ and late 12s cutoff."
        ),
        "entry": {
            "startAfterOpenSec": 4,
            "stopBeforeCloseSec": 12,
            "clipSharesDefault": 30.0,
            "maxShares": 50.0,
            "minFillPrice": 0.07,
            "maxFillPrice": 0.975,
            "benchmarkPairCost": 0.965,
            "targetPairCost": 0.965,
            "maxPairCost": 0.990,
            "maxShareLead": 90.0,
            "freezeLead": 25.0,
            "rescuePairCostMax": 1.080,
            "rescueCeilingPrice": 0.985,
            "minSpacingMoveSec": 0.5,
            "minSpacingStaticSec": 2.5,
            "includeTakerFee": True,
            "wholeLadderClips": True,
        },
    },
    "dangerously-skip-permissions": {
        "id": "dangerously-skip-permissions",
        "symbol": "⚡ DSP-v2.0",
        "name": "Dangerously Skip Permissions v2.0 (Deep Dip Pairing)",
        "signature": (
            "Deep Dip Grid [7¢–45¢] · Tiered Rescue Pairing (Target ≤$0.965, Rescue ≤$1.025) · "
            "Early Exit (SBC 75s) · Strict Lead Cap (45 sh) · Freeze Lead (15 sh)"
        ),
        "description": (
            "Empirically reconstructed from 174,019 on-chain fills of wallet 0xc533…69a9 "
            "($1.42M vol/wk, +$16.8K/wk rebates). Re-anchors into deep dips [7¢–45¢], 75s early cutoff, "
            "strict 15-share lead freeze, and Tiered Rescue Pairing up to $1.025 to ensure 80¢–92¢ "
            "deficit-closing hedges are executed rather than left unhedged."
        ),
        "entry": {
            "startAfterOpenSec": 4,
            "stopBeforeCloseSec": 75,
            "clipSharesDefault": 30.0,
            "maxShares": 50.0,
            "minFillPrice": 0.07,
            "maxFillPrice": 0.880,
            "benchmarkPairCost": 0.965,
            "targetPairCost": 0.965,
            "maxPairCost": 0.985,
            "maxShareLead": 45.0,
            "freezeLead": 15.0,
            "rescuePairCostMax": 1.080,
            "rescueCeilingPrice": 0.985,
            "minSpacingMoveSec": 0.5,
            "minSpacingStaticSec": 2.5,
            "includeTakerFee": True,
            "wholeLadderClips": True,
        },
    },
    "dangerously-skip-permissions-v2.1": {
        "id": "dangerously-skip-permissions-v2.1",
        "symbol": "⚡ DSP-v2.1",
        "name": "Dangerously Skip Permissions v2.1 (Unified Triad)",
        "signature": (
            "De-escalating Dip Clips (30→20→10) · Passive Maker Sweep (T-75s..15s) · "
            "Strict Sub-$1.00 Pair Cap (≤$0.995) · Certainty Rescue (≤98.5¢)"
        ),
        "description": (
            "Unified candidate setup: Prevents runaway deficits via de-escalating dip clips, "
            "executes 0% fee maker equalization between T-75s and T-15s, and hard-caps pair cost at ≤$0.995 "
            "so every merged pair redeems with guaranteed positive return."
        ),
        "entry": {
            "startAfterOpenSec": 4,
            "stopBeforeCloseSec": 75,
            "clipSharesDefault": 30.0,
            "maxShares": 50.0,
            "minFillPrice": 0.07,
            "maxFillPrice": 0.880,
            "benchmarkPairCost": 0.965,
            "targetPairCost": 0.965,
            "maxPairCost": 0.985,
            "maxShareLead": 45.0,
            "freezeLead": 15.0,
            "rescuePairCostMax": 0.995,
            "rescueCeilingPrice": 0.985,
            "minSpacingMoveSec": 0.5,
            "minSpacingStaticSec": 2.5,
            "includeTakerFee": True,
            "wholeLadderClips": True,
        },
    },
    "dangerously-skip-permissions-v2.2": {
        "id": "dangerously-skip-permissions-v2.2",
        "symbol": "⚡ DSP-v2.2",
        "name": "Dangerously Skip Permissions v2.2 (Confidence Sizing)",
        "signature": (
            "Confidence Sizing (60 sh Atomic / 10 sh Micro) · Pre-Flight Arb Gate (≤$0.995) · "
            "Passive Maker Sweep (T-75s..15s) · Strict Sub-$1.00 Pair Cap"
        ),
        "description": (
            "Confidence-based sizing candidate: Maximizes profit by heavy sizing (60 shares) on 100% risk-free "
            "atomic pairings and deficit equalizations, while minimizing risk via 10-share micro clips on speculative "
            "dips and enforcing a pre-flight hedge gate to prevent entering unhedgeable positions."
        ),
        "entry": {
            "startAfterOpenSec": 4,
            "stopBeforeCloseSec": 75,
            "clipSharesDefault": 10.0,
            "maxShares": 60.0,
            "minFillPrice": 0.07,
            "maxFillPrice": 0.880,
            "benchmarkPairCost": 0.965,
            "targetPairCost": 0.965,
            "maxPairCost": 0.985,
            "maxShareLead": 30.0,
            "freezeLead": 15.0,
            "rescuePairCostMax": 0.995,
            "rescueCeilingPrice": 0.985,
            "minSpacingMoveSec": 0.5,
            "minSpacingStaticSec": 2.5,
            "includeTakerFee": True,
            "wholeLadderClips": True,
        },
    },
    "dangerously-skip-permissions-v2.3": {
        "id": "dangerously-skip-permissions-v2.3",
        "symbol": "⚡ DSP-v2.3",
        "name": "Dangerously Skip Permissions v2.3 (Constant-Risk Sizing)",
        "signature": (
            "Constant Dollar-Risk Sizing ($4.50) · Dip Buys ≤45¢ (10–45 sh) · "
            "Net Imbalance Cap (15 sh) · Total Paired Volume Uncapped · Strict Sub-$1.00 Pair Cap"
        ),
        "description": (
            "Constant dollar-risk candidate: Buys dips at 45¢ or cheaper only, sizing each dip as $4.50 / price "
            "(10 sh at 45¢ up to 45 sh at 10¢) so no single dip risks more than $4.50. Net imbalance capped at 15 sh, "
            "total paired volume uncapped: choppy windows re-trigger Dip -> Equalize micro-cycles "
            "(Dip Up -> Equalize Down -> Dip Down -> Equalize Up) to compound hundreds of paired shares. "
            "No pre-flight gate and no heavy 60-share fills — entries are governed by strict sub-$1.00 pair-cost gates "
            "(≤$0.965 fresh, ≤$0.985 closing a deficit, rescue ≤$0.995)."
        ),
        "entry": {
            "startAfterOpenSec": 4,
            "stopBeforeCloseSec": 75,
            "clipSharesDefault": 10.0,
            "maxShares": 45.0,
            "minFillPrice": 0.07,
            "maxFillPrice": 0.45,
            "benchmarkPairCost": 0.965,
            "targetPairCost": 0.965,
            "maxPairCost": 0.985,
            "maxShareLead": 15.0,
            "freezeLead": 15.0,
            "rescuePairCostMax": 0.995,
            "rescueCeilingPrice": 0.985,
            "minSpacingMoveSec": 0.5,
            "minSpacingStaticSec": 2.5,
            "includeTakerFee": True,
            "wholeLadderClips": True,
        },
    },
}

# ---------------------------------------------------------------------------
# Single source of truth for user-facing copy.
# signature / description / configHighlights are GENERATED from each setup's
# entry numbers + behavior flags below, so changing a threshold automatically
# changes every word the UI shows. Never hand-edit per-setup strings.
# ---------------------------------------------------------------------------
_SETUP_FEATURES = {
    "hapcs-v1": {
        "sizing": "ladder", "preflightGate": False, "heavyAtomic": False,
        "sweep": False, "pairedVolumeCapped": True, "blurb": "ladder dip grid with Minute 4 certainty sniping",
    },
    "dangerously-skip-permissions": {
        "sizing": "ladder", "preflightGate": False, "heavyAtomic": False,
        "sweep": False, "pairedVolumeCapped": True, "blurb": "deep-dip grid with tiered rescue pairing",
    },
    "dangerously-skip-permissions-v2.1": {
        "sizing": "de-escalating", "preflightGate": False, "heavyAtomic": False,
        "sweep": True, "pairedVolumeCapped": True, "blurb": "de-escalating dip clips with passive maker sweep",
    },
    "dangerously-skip-permissions-v2.2": {
        "sizing": "confidence", "preflightGate": True, "heavyAtomic": True,
        "sweep": True, "pairedVolumeCapped": True, "blurb": "heavy clips on risk-free pairs, micro clips on speculative dips, pre-flight hedge gate",
    },
    "dangerously-skip-permissions-v2.3": {
        "sizing": "constant-risk", "dollarRisk": 4.50, "preflightGate": False,
        "heavyAtomic": False, "sweep": True, "pairedVolumeCapped": False,
        "blurb": "every dip sized as $4.50 / price, net gap capped while total paired volume compounds",
    },
}


def _setup_tag(setup_id: str) -> str:
    """'dangerously-skip-permissions-v2.3' -> 'v2.3', 'hapcs-v1' -> 'v1'."""
    tail = str(setup_id).split("-")[-1]
    return tail if tail[:1] == "v" else tail


def describe_setup(setup: dict) -> tuple[str, str, dict[str, str]]:
    """Build signature, description and highlight chips from live entry numbers."""
    e = setup.get("entry", {})
    f = _SETUP_FEATURES.get(setup.get("id", ""), {})
    clip = e.get("clipSharesDefault", 10)
    mx = e.get("maxShares", 45)
    lo_c = round(float(e.get("minFillPrice", 0.07)) * 100)
    hi_c = round(float(e.get("maxFillPrice", 0.45)) * 100)
    lead = e.get("maxShareLead", 15)
    tgt = float(e.get("targetPairCost", e.get("benchmarkPairCost", 0.965)))
    cap = float(e.get("maxPairCost", 0.985))
    rescue = float(e.get("rescuePairCostMax", 0.995))
    cutoff = e.get("stopBeforeCloseSec", 75)
    exposure = float(lead) * float(e.get("maxFillPrice", 0.45))
    risk = float(f.get("dollarRisk", 4.50))
    sizing = f.get("sizing", "ladder")
    preflight = bool(f.get("preflightGate", False))
    heavy = bool(f.get("heavyAtomic", False))
    sweep = bool(f.get("sweep", False))
    uncapped = bool(f.get("pairedVolumeCapped", True)) is False

    if sizing == "constant-risk":
        dip_txt = f"${risk:.2f} risk per dip ({clip:g}-{mx:g} sh by price, dips under {hi_c}c)"
        sig_size = f"Capped ${risk:.2f} Per Dip ({clip:g}-{mx:g} sh)"
    elif sizing == "confidence":
        dip_txt = f"{mx:g} sh on risk-free pairs, {clip:g} sh micro dips"
        sig_size = f"{mx:g} sh Atomic / {clip:g} sh Micro"
    elif sizing == "de-escalating":
        dip_txt = f"shrinking dip clips (max {mx:g} sh)"
        sig_size = f"Shrinking Dip Clips (max {mx:g} sh)"
    else:
        dip_txt = f"{clip:g} sh dips (max {mx:g} sh) in the {lo_c}c-{hi_c}c band"
        sig_size = f"Dip Grid [{lo_c}c-{hi_c}c]"

    if preflight:
        gate_txt = f"pre-flight hedge gate plus pair gates (under ${rescue:.3f})"
        sig_gate = f"Pre-Flight Gate (under ${rescue:.3f})"
    else:
        gate_txt = f"pair-cost gates (fresh under ${tgt:.3f}, closing a gap under ${cap:.3f}, rescue under ${rescue:.3f})"
        sig_gate = f"Pair Gates (fresh under ${tgt:.3f})"

    gap_txt = (
        f"lopsided by at most {lead:g} sh (about ${exposure:.2f} if all bought at the {hi_c}c ceiling)"
        + (" while total paired-up shares have no cap" if uncapped else "")
    )
    sweep_txt = (
        " Late gaps are swept with resting no-fee orders."
        if sweep else ""
    )
    heavy_txt = " No heavy bulk fills." if not heavy else ""

    signature = f"{sig_size} - {sig_gate} - Gap Cap ({lead:g} sh) - Under-${rescue:.3f} Cap"
    description = (
        f"Buys dips {dip_txt}; entries follow {gate_txt}; "
        f"never {gap_txt}.{sweep_txt}{heavy_txt}"
    ).strip()
    highlights = {
        "dipClips": dip_txt,
        "pairGates": f"fresh under ${tgt:.3f} / close under ${cap:.3f} / rescue under ${rescue:.3f}",
        "preflightGate": ("On (entry + opposite ask under $%.3f)" % rescue) if preflight else "Off (pair-cost gates only)",
        "heavyFills": ("%g sh atomic pairs" % mx) if heavy else "None",
        "netGapCap": f"{lead:g} sh (~${exposure:.2f} max)" + ("; paired volume uncapped" if uncapped else ""),
        "maxBuy": f"{hi_c}c",
        "cutoff": f"{cutoff:g}s before close",
    }
    return signature, description, highlights


for _setup in STRATEGY_SETUPS.values():
    _sig, _desc, _hl = describe_setup(_setup)
    _setup["signature"] = _sig
    _setup["description"] = _desc
    _setup["configHighlights"] = _hl
    _setup["features"] = _SETUP_FEATURES.get(_setup["id"], {})


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
TARGET_DOLLAR_RISK_USD = 4.50  # DSP-v2.3 constant dollar-risk ceiling per unhedged dip clip
MAX_SHARE_LEAD = 90.0          # 90.0 shares = hard ceiling on unhedged lead (3 clips max)
FREEZE_LEAD = 15.0             # 15.0 shares = strict accumulation freeze on leading side

# Microstructure Price Bands ($)
STRADDLE_BAND = (0.34, 0.55)   # Opening straddle band [34¢–55¢] (median 43¢)
STRADDLE_MEDIAN = 0.43         # Opening straddle median price (43¢)
DIP_LADDER_MAX = 0.50          # Upper bound of passive Maker Dip Grid [7¢–50¢]
RESOLUTION_SNIPE_BAND = (0.90, 0.975)  # Minute 4 resolution certainty snipe band (up to 97.5¢)
PRICE_FLOOR = 0.07             # Hard lower cutoff (<7¢ lottery tail strictly skipped)
PRICE_CEILING = 0.975          # Hard upper cutoff (>97.5¢ extreme certainty strictly skipped)
RESCUE_CEILING_PRICE = 0.985   # Hard ceiling for deficit rescue pairing fills (up to 98.5¢ when deficit exists)

# Mathematical Sub-$1.00 Pair Cost Constraints & Benchmarks
BENCHMARK_PAIR_COST = 0.965    # Measured historical tape benchmark ($0.9654 on tape, +3.5% margin)
PAIR_COST_BENCHMARK = BENCHMARK_PAIR_COST
TARGET_PAIR_COST = BENCHMARK_PAIR_COST  # backward-compat alias
PAIR_COST_TARGET = BENCHMARK_PAIR_COST  # backward-compat alias
PAIR_COST_MAX = 0.990          # Hard sub-$1.00 ceiling (never enters pair ≥ $1.00)
RESCUE_PAIR_COST_MAX = 1.080   # Cap for deficit rescue pairing (sacrifices modest spread to prevent 100% loss)
MEAN_PAIR_COST = 0.9462        # Measured mean pair cost on tape

# Exchange Fee Model
TAKER_FEE_COEFF = 0.07         # Polymarket parabolic taker fee: 0.07 * p * (1 - p)
MAKER_FEE = 0.0                # 0% maker fee on resting limit orders

# Risk Guardrails
DAILY_LOSS_CAP_USD = 500.0     # Maximum allowable daily loss
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
