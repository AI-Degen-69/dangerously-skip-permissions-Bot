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
            "rescuePairCostMax": 1.080,
            "rescueCeilingPrice": 0.985,
            "minSpacingMoveSec": 0.5,
            "minSpacingStaticSec": 2.5,
            "includeTakerFee": True,
            "wholeLadderClips": True,
            "maxDepthShares": 0.0,
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
            "rescuePairCostMax": 1.080,
            "rescueCeilingPrice": 0.985,
            "minSpacingMoveSec": 0.5,
            "minSpacingStaticSec": 2.5,
            "includeTakerFee": True,
            "wholeLadderClips": True,
            "maxDepthShares": 0.0,
        },
    },
    "dangerously-skip-permissions-v2.6": {
        "id": "dangerously-skip-permissions-v2.6",
        "symbol": "⚡ DSP-v2.6",
        "name": "Dangerously Skip Permissions v2.6 (Patient Pair)",
        "entry": {
            # v2.5's numbers with two placement rules replaced. The band now
            # reaches the at-the-money entry the ledger shows (first leg near
            # 50c within ~13s of the open) instead of stopping at 45c, and the
            # hedge is a resting bid that closes in the sweep, not a taker buy
            # on the next tick.
            "startAfterOpenSec": 4,
            "stopBeforeCloseSec": 75,
            "clipSharesDefault": 10.0,
            "maxShares": 45.0,
            "minFillPrice": 0.07,
            "maxFillPrice": 0.55,
            "benchmarkPairCost": 0.965,
            "targetPairCost": 0.965,
            "maxPairCost": 0.985,
            # v2.5's $5.00 vetoed the curve's own mid-band (20 sh at 26c is
            # $5.20, and the curve peaks at $5.37), so those dips never opened.
            # $6.00 is the smallest round cap that covers the curve.
            "maxUnhedgedUsd": 6.0,
            "dipCurve": {"lo": 0.07, "hi": 0.45, "sharesLo": 33.0, "sharesHi": 8.0},
            "rescuePairCostMax": 0.995,
            "rescueCeilingPrice": 0.985,
            "minSpacingMoveSec": 0.5,
            "minSpacingStaticSec": 2.5,
            "includeTakerFee": True,
            "wholeLadderClips": True,
        },
    },
    "dangerously-skip-permissions-v2.7": {
        "id": "dangerously-skip-permissions-v2.7",
        "symbol": "⚡ DSP-v2.7",
        "name": "Dangerously Skip Permissions v2.7 (Hump + Taker Dip + Late Rescue)",
        "entry": {
            # W29-W35 CSV regime: 1st fill median T+21s, p90 last fill T+277s.
            "startAfterOpenSec": 15,
            "stopBeforeCloseSec": 30,
            "sweepBeforeCloseSec": 12,
            "clipSharesDefault": 10.0,
            "maxShares": 25.0,
            "maxClipShares": 25.0,
            "minFillPrice": 0.07,
            # Leg 1 capped at 48c (was 55c); Leg 2 decoupled via leg2MaxPrice.
            "maxFillPrice": 0.48,
            "maxLeg1Price": 0.48,
            "leg1MaxPrice": 0.48,
            "leg2MaxPrice": 0.75,
            "benchmarkPairCost": 0.960,
            "targetPairCost": 0.960,
            "maxPairCost": 0.985,
            "maxUnhedgedShares": 100.0,
            "maxUnhedgedUsd": 45.0,
            # Hump sizing: 30 sh at <=10c -> ~48.7 sh at 40-50c -> 30 sh at >=70c.
            # Stored as a flag; executor.select_ladder_clip + replay share the curve.
            "dipCurve": "hump",
            "wholeLadderClips": True,
            "levelsPerSide": 2,
            "levelSpacing": 0.01,
            "minSpacingMoveSec": 0.5,
            "minSpacingStaticSec": 2.5,
            "includeTakerFee": True,
            # --- 4 new knobs ---
            "takerDipEntryMax": 0.45,
            "lateRescueStartSec": 210,
            "lateRescueMaxPairCost": 1.02,
            "rescuePairCostMax": 1.02,
            "rescueCeilingPrice": 0.985,
            "maxDepthShares": 0.0,
        },
    },
    "hydrogen-v1.0": {
        "id": "hydrogen-v1.0",
        "symbol": "H2 Hydrogen-v1.0",
        "name": "Hydrogen v1.0",
        "entry": {
            "startAfterOpenSec": 15,
            "stopBeforeCloseSec": 30,
            "sweepBeforeCloseSec": 12,
            "clipSharesDefault": 10.0,
            "maxShares": 25.0,
            "maxClipShares": 25.0,
            "minFillPrice": 0.07,
            "maxFillPrice": 0.48,
            "maxLeg1Price": 0.48,
            "leg1MaxPrice": 0.48,
            "leg2MaxPrice": 0.75,
            "benchmarkPairCost": 0.960,
            "targetPairCost": 0.960,
            "maxPairCost": 0.985,
            "maxUnhedgedShares": 100.0,
            "maxUnhedgedUsd": 45.0,
            "dipCurve": "hump",
            "wholeLadderClips": True,
            "levelsPerSide": 2,
            "levelSpacing": 0.01,
            "minSpacingMoveSec": 0.5,
            "minSpacingStaticSec": 2.5,
            "includeTakerFee": True,
            "takerDipEntryMax": 0.42,
            "lateRescueStartSec": 210,
            "lateRescueMaxPairCost": 1.02,
            "rescuePairCostMax": 1.02,
            "rescueCeilingPrice": 0.985,
            "maxDepthShares": 0.0,
        },
    },
    "hydrogen-v1.9": {
        "id": "hydrogen-v1.9",
        "symbol": "H2 Hydrogen-v1.9",
        "name": "Hydrogen v1.9",
        "signature": "Single Probe (5 sh) · Clamped Maker (≤$0.990) + Patient L3 (20s) · Dollar Gap Cap ($2.50) · Max Buy 85¢",
        "description": (
            "Dynamic 3-layer architecture for 5-minute binary markets: Layer 1 probes with exactly 1 single 5-share rung in the 42–49¢ ATM band with T+150s / 40-share cutoff; Layer 2 triggers immediately on any deficit (tol = 0.5 sh) with sub-par clamped maker hedging at ≤$0.990 and strict resting order hygiene; Layer 3 delays taker bailouts by 20.0s (requiring marginal pair ≥$1.07 and ask ≤72¢) with single-window freeze latch to eliminate terminal breakout tax."
        ),
        "configHighlights": {
            "timing": "T+4s open, 5 sh single probe (T+150s / 40 sh cutoff)",
            "sizing": "1-level maker probe, clamped rebalance-maker (≤$0.990), patient 20s taker equalizer",
            "riskGates": "tol = 0.5 sh trigger, sub-par maker clamp, single-window bailout freeze latch",
        },
        "entry": {
            "startAfterOpenSec": 4,
            "stopBeforeCloseSec": 30,
            "sweepBeforeCloseSec": 12,
            "clipSharesDefault": 5.0,
            "maxShares": 5.0,
            "maxClipShares": 5.0,
            "minFillPrice": 0.05,
            "maxFillPrice": 0.85,
            "levelsPerSide": 1,
            "levelSpacing": 0.01,
            "benchmarkPairCost": 0.960,
            "targetPairCost": 0.960,
            "maxPairCost": 0.990,
            "maxUnhedgedShares": 5.0,
            "maxUnhedgedUsd": 2.50,
            "wholeLadderClips": True,
            "minSpacingMoveSec": 0.5,
            "minSpacingStaticSec": 2.5,
            "includeTakerFee": True,
            "maxDepthShares": 0.0,
        },
    },
    "hydrogen-v2.0": {
        "id": "hydrogen-v2.0",
        "symbol": "H2 Hydrogen-v2.0",
        "name": "Hydrogen v2.0",
        "entry": {
            "startAfterOpenSec": 4,
            "stopBeforeCloseSec": 30,
            "sweepBeforeCloseSec": 12,
            "clipSharesDefault": 10.0,
            "maxShares": 45.0,
            "maxClipShares": 45.0,
            "levelsPerSide": 1,
            "levelSpacing": 0.01,
            "minFillPrice": 0.07,
            "maxFillPrice": 0.47,
            "benchmarkPairCost": 0.965,
            "targetPairCost": 0.965,
            "maxPairCost": 0.985,
            "rescuePairCostMax": 0.995,
            "rescueCeilingPrice": 0.985,
            "maxUnhedgedShares": 0.0,
            "maxUnhedgedUsd": 6.0,
            "dipCurve": {"lo": 0.07, "hi": 0.45, "sharesLo": 33.0, "sharesHi": 8.0},
            "minSpacingMoveSec": 0.5,
            "minSpacingStaticSec": 2.5,
            "includeTakerFee": True,
            "wholeLadderClips": True,
            "maxDepthShares": 0.0,
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
    "dangerously-skip-permissions-v2.6": {
        "sizing": "inverse-curve", "preflightGate": False, "patientHedge": True,
        "heavyAtomic": False, "sweep": True, "pairedVolumeCapped": False,
        "blurb": "inverse-dip clip curve entered at the touch near 50c, with the hedge resting on the other side instead of crossing its ask",
    },
    "dangerously-skip-permissions-v2.7": {
        "sizing": "hump", "preflightGate": False, "patientHedge": True, "takerDip": True,
        "heavyAtomic": False, "sweep": True, "pairedVolumeCapped": False,
        "blurb": "hump-sized dips (fat in the middle) with taker dip entry to 45c, leg-2 ceiling 75c, and a late rescue to $1.02 from T+210s",
    },
    "hydrogen-v1.0": {
        "sizing": "hump", "preflightGate": False, "patientHedge": True, "takerDip": True,
        "heavyAtomic": False, "sweep": True, "pairedVolumeCapped": False,
        "blurb": "hump-sized dips (fat in the middle) with taker dip entry to 42c, leg-2 ceiling 75c, and a late rescue to $1.02 from T+210s",
    },
    "hydrogen-v1.9": {
        "sizing": "split-ladder-v19", "preflightGate": False, "patientHedge": False, "takerDip": False,
        "heavyAtomic": False, "sweep": True, "pairedVolumeCapped": False,
        "blurb": "dynamic 3-layer architecture: 1-level 5sh probe in 42–49c ATM band with T+150s cutoff; clamped maker hedge (<= $0.990) on any lead > 0.5sh; patient 20s delayed taker bailout (>= $1.07 marginal pair, <= 72c ask) with single-window freeze latch",
    },
    "hydrogen-v2.0": {
        "sizing": "two-sided-dip-v20", "preflightGate": False, "patientHedge": False, "takerDip": False,
        "heavyAtomic": False, "sweep": True, "pairedVolumeCapped": False,
        "blurb": "two-sided simultaneous resting (42-47c ATM & 7-45c inverse-dip curve, <=$6 unhedged USD) + clamped sub-$0.985 maker / <=$0.965 profit-lock taker",
    },
}


def _setup_tag(setup_id: str) -> str:
    """'dangerously-skip-permissions-v2.6' -> 'v2.6', 'hapcs-v1' -> 'v1'."""
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
    tgt = float(e.get("targetPairCost", e.get("benchmarkPairCost", 0.965)))
    cap = float(e.get("maxPairCost", 0.985))
    rescue = float(e.get("rescuePairCostMax", 0.995))
    cutoff = e.get("stopBeforeCloseSec", 75)
    try:
        depth_cap = float(e.get("maxDepthShares", 0.0) or 0.0)
    except Exception:
        depth_cap = 0.0
    risk = float(f.get("dollarRisk", 4.50))
    sizing = f.get("sizing", "ladder")
    split_v19 = (sizing == "split-ladder-v19")
    two_sided_v20 = (sizing == "two-sided-dip-v20")
    preflight = bool(f.get("preflightGate", False))
    hedge_now = bool(f.get("hedgeNowGate", False))
    patient = bool(f.get("patientHedge", False))
    heavy = bool(f.get("heavyAtomic", False))
    sweep = bool(f.get("sweep", False))
    uncapped = bool(f.get("pairedVolumeCapped", True)) is False

    _sched = e.get("clipSchedule") or []
    _sched_ok = False
    try:
        _s0, _s1 = _sched[0], _sched[-1]
        _sched_ok = bool(isinstance(_sched, (list, tuple)) and len(_sched) >= 2)
    except (TypeError, IndexError):
        _sched_ok = False
    _sched_txt = None
    if sizing == "hump" and _sched_ok:
        try:
            _c0, _t1, _c1 = float(_s0[1]), float(_s1[0]), float(_s1[1])
            _sched_txt = (
                f"scheduled clips ({_c0:g} sh at the open decaying to {_c1:g} sh "
                f"by T+{_t1:g}s, linear in between — the wallet's measured 30→15 shape)",
                f"Scheduled Clips ({_c0:g}→{_c1:g} sh)",
            )
        except (TypeError, ValueError):
            _sched_txt = None
    if split_v19:
        dip_txt = (
            f"1-level single 5 sh probe in the 42–49c ATM band (frozen at T+150s / 40 sh matched) "
            f"with strict resting hygiene and exact deficit sizing"
        )
        sig_size = "Single Probe (5 sh)"
    elif two_sided_v20:
        curve = e.get("dipCurve") or {}
        s_lo = curve.get("sharesLo", 33) if isinstance(curve, dict) else 33
        s_hi = curve.get("sharesHi", 8) if isinstance(curve, dict) else 8
        c_lo = round(float(curve.get("lo", lo_c / 100)) * 100) if isinstance(curve, dict) else lo_c
        c_hi = round(float(curve.get("hi", 0.45)) * 100) if isinstance(curve, dict) else 45
        dip_txt = (
            f"simultaneous two-sided resting orders: {s_lo:g} sh at {c_lo}c scaling down to "
            f"{s_hi:g} sh at {c_hi}c–{hi_c}c (off-touch -1c in ATM balanced band), "
            f"strictly bounded to ${float(e.get('maxUnhedgedUsd', 6.0)):.2f} max unhedged USD"
        )
        sig_size = f"Two-Sided + Curve ({s_lo:g}@{c_lo}c → {s_hi:g}@{hi_c}c)"
    elif _sched_txt is not None:
        dip_txt, sig_size = _sched_txt
    elif sizing == "hump":
        probe = e.get("unhedgedProbeShares")
        if probe and float(probe) > 0:
            if float(probe) == float(mx) == float(clip):
                dip_txt = f"flat {clip:g} sh clips (probe, ladder and cap all bind at {clip:g} sh, so the hump curve never expresses)"
                sig_size = f"Flat {clip:g} sh Clips"
            else:
                dip_txt = f"hump clips ({float(probe):g} sh probe / {mx:g} sh pair)"
                sig_size = f"Hump Curve ({float(probe):g}sh probe / {mx:g}sh pair)"
        else:
            dip_txt = f"hump clips (30 sh at/below 10c, ~48.7 sh at 40-50c, 30 sh at/above 70c, capped at {mx:g} sh)"
            sig_size = f"Hump Curve (30-48.7-30 sh, cap {mx:g})"
    elif sizing == "inverse-curve":
        curve = e.get("dipCurve") or {}
        if not isinstance(curve, dict):
            dip_txt = f"hump clips (capped at {mx:g} sh)"
            sig_size = f"Hump Curve (cap {mx:g})"
            curve = {}
        else:
            s_lo = curve.get("sharesLo", clip)
            s_hi = curve.get("sharesHi", clip)
            c_lo = round(float(curve.get("lo", lo_c / 100)) * 100)
            c_hi = round(float(curve.get("hi", hi_c / 100)) * 100)
            dip_txt = f"{s_lo:g} sh at {c_lo}c falling to {s_hi:g} sh at {c_hi}c"
            sig_size = f"Inverse-Dip Curve ({s_lo:g} sh @{c_lo}c → {s_hi:g} sh @{c_hi}c)"
    elif sizing == "constant-risk":
        dip_txt = (
            f"${risk:.2f} risk per dip ({clip:g}-{mx:g} sh by price, "
            f"dips under {hi_c}c)"
        )
        sig_size = f"Capped ${risk:.2f} Per Dip ({clip:g}-{mx:g} sh)"
    else:
        dip_txt = f"{clip:g} sh (max {mx:g} sh) in the {lo_c}c-{hi_c}c band"
        sig_size = f"Dip Grid [{lo_c}c-{hi_c}c]"

    if split_v19:
        gate_txt = (
            f"a 3-layer breakout defense: Layer 1 quotes only within [42¢, 49¢] under ${cap:.3f} pair cost; "
            f"Layer 2 rebalances with sub-par clamped maker hedging (<= $0.990) on any lead > 0.5 sh; "
            f"Layer 3 executes a patient 20s delayed taker bailout (>= $1.07 marginal pair, <= 72¢ ask) "
            f"with single-window freeze latch"
        )
        sig_gate = "Clamped Maker (≤$0.990) + Patient L3 (20s)"
    elif two_sided_v20:
        sweep_sec = float(e.get("sweepBeforeCloseSec", 12))
        gate_txt = (
            f"mutual two-sided gating under ${tgt:.3f} fresh pair cost; "
            f"any imbalance > 0.5 sh cancels heavy-side orders and hedges via profit-lock taker (<= ${tgt:.3f}) "
            f"or clamped maker (<= ${cap:.3f}), sweeping deficits <= ${rescue:.3f} down to T-{sweep_sec:g}s "
            f"(never >= $1.00, no freeze latch)"
        )
        sig_gate = f"Two-Sided ≤${cap:.3f} (No ≥$1.00 / No Latch)"
    elif preflight:
        gate_txt = f"pre-flight hedge gate plus pair gates (under ${rescue:.3f})"
        sig_gate = f"Pre-Flight Gate (under ${rescue:.3f})"
    elif patient:
        gate_txt = (
            f"a patient pair: legs are bought as dips in the {lo_c}c-{hi_c}c band, cheapest side "
            f"first (a taker leg is crossed immediately up to the dip threshold, otherwise the deficit "
            f"hedge rests on the other side as a maker order and is crossed only in the sweep), "
            f"and the pair cost stays under ${cap:.3f}"
        )
        sig_gate = f"Patient Pair (under ${cap:.3f})"
    elif hedge_now:
        gate_txt = (
            f"a hedge that exists at entry: the leg plus the opposite ask plus its taker fee "
            f"must stay under ${cap:.3f}, so no leg is opened on a second leg that has not arrived"
        )
        sig_gate = f"Hedge-Now Gate (under ${cap:.3f})"
    else:
        gate_txt = f"pair-cost gates (fresh under ${tgt:.3f}, closing a gap under ${cap:.3f}, rescue under ${rescue:.3f})"
        sig_gate = f"Pair Gates (fresh under ${tgt:.3f})"

    dollar_cap = float(e.get("maxUnhedgedUsd", 0.0) or 0.0)
    gap_txt = (
        (f"more than ${dollar_cap:.2f} of unhedged cost on one side" if dollar_cap > 0
         else "unhedged size without limit")
        + (" while total paired-up shares have no cap" if uncapped else "")
    )
    sweep_txt = (
        " Late gaps are swept with resting no-fee orders."
        if sweep else ""
    )
    heavy_txt = " No heavy bulk fills." if not heavy else ""
    depth_txt = f" Maker clips capped to resting depth ({depth_cap:g} sh max)." if depth_cap > 0 else ""

    gap_cap_txt = f"Dollar Gap Cap (${dollar_cap:.2f})" if dollar_cap > 0 else "No Gap Cap"
    signature = f"{sig_size} - {sig_gate} - {gap_cap_txt} - Under-${rescue:.3f} Cap"
    description = (
        f"Buys dips {dip_txt}; entries follow {gate_txt}; "
        f"never {gap_txt}.{sweep_txt}{heavy_txt}{depth_txt}"
    ).strip()
    if split_v19 or two_sided_v20:
        signature = f"{sig_size} - {sig_gate} - {gap_cap_txt} - Max Buy {hi_c}c"
        description = (
            f"Accumulates both sides from the open: {dip_txt}; {gate_txt}; "
            f"never {gap_txt}.{sweep_txt}{heavy_txt}{depth_txt}"
        ).strip()
    highlights = {
        "dipClips": dip_txt,
        "pairGates": f"fresh under ${tgt:.3f} / close under ${cap:.3f} / rescue under ${rescue:.3f}",
        "preflightGate": ("On (entry + opposite ask under $%.3f)" % rescue) if preflight
                         else ("On (first leg at the touch, hedge rests on the other side)"
                               if patient else
                               (f"On (leg + opposite ask + taker fee under ${cap:.3f})" if hedge_now
                                else "Off (pair-cost gates only)")),
        "heavyFills": ("%g sh atomic pairs" % mx) if heavy else "None",
        "netGapCap": (f"never more than ${dollar_cap:.2f} of unhedged cost" if dollar_cap > 0
                      else "unhedged size uncapped") + ("; paired volume uncapped" if uncapped else ""),
        "depthCap": (f"{depth_cap:g} sh" if depth_cap > 0 else "Off"),
        "maxBuy": f"{hi_c}c",
        "cutoff": f"{cutoff:g}s before close",
    }
    if split_v19:
        highlights["pairGates"] = "balanced <= $0.990; clamped maker <= floor(0.990 - heavy_avg); patient taker 20s delay (>= $1.07)"
        highlights["preflightGate"] = "Deficit Trigger (tol = 0.5 sh) + Window Freeze Latch"
    elif two_sided_v20:
        highlights["pairGates"] = (
            f"balanced <= ${tgt:.3f}; clamped maker <= ${cap:.3f}; "
            f"profit-lock taker <= ${tgt:.3f} (sweep <= ${rescue:.3f}), never >= $1.00"
        )
        highlights["preflightGate"] = "Two-Sided Mutual Gate + Sub-$1.00 Deficit Equalizer (No Freeze Latch)"
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
MAX_UNHEDGED_USD = 0.0         # dollar-denominated unhedged-gap veto (0 = off): caps dollars exposed, not shares

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
TAKER_FEE_COEFF = 0.05         # Polymarket parabolic taker fee: 0.05 * p * (1 - p) (BTC 5m/15m; general crypto: 0.01)
MAKER_FEE = 0.0                # 0% maker fee on resting limit orders
MAKER_REBATE_SHARE = 0.15      # Polymarket Tier 4 maker rebate: 15% on taker fees generated

# Paper Rebate Model (modeled after the measured wallet's economics:
# TAKER_REBATE(D) ~= 50% of day D-1 taker fees at Obsidian tier ($10M+), with
# new structure: None (0%), Gold (10%), Platinum (25%), Diamond (40%),
# Obsidian (50%), Onyx (60%). Paper cannot earn rebates, so the simulator
# credits the configured rate on every window's taker-fee total to keep paper
# P&L comparable to live.)
PAPER_REBATE_TAKER_RATE = 0.50  # default modeled refund of taker fees
PAPER_REBATE_TIER_RANGE = (0.25, 0.40, 0.50, 0.60)  # low / mid / top / onyx volume tiers

# Wallet Benchmark (measured 21-day median,
# docs/leaderboard-traders/ledgers/dangerously-skip-permissions/reports/
# strategy_2026-10-18_to_2026-11-08.md). This is a
# REPORTING benchmark for realized pair cost, not a pairing gate: the bot
# strives to pair under it and accepts above it — sub-$1.00 must emerge from
# sizing, risk and position management, not from refusing to pair.
WALLET_MEDIAN_PAIR_COST = 0.977

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
