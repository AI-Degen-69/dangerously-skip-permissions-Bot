"""🎯 Hybrid Arbitrage Pairing & Certainty Sniping v1 (HAPCS-v1).

Microstructure Executor & Order Decision Engine.
Reconstructed and cross-validated against 16,855 fills from wallet
`dangerously-skip-permissions` across 288 consecutive 5-minute Bitcoin markets.

Core Strategy Pillars:
  1. Maker Dip Grid [7¢–50¢] (0% fee, up to 90-share unhedged lead)
  2. Dynamic Arbitrage Pairing (any price that reduces share deficit with pair cost ≤ $0.990)
  3. Resolution Certainty Snipe in Minute 4 [up to 97.5¢]
  4. Phase 0 Pre-Open Resting Orders ($T-310s \to T-300s$)
  5. Settlement Lock ($T-12s \to T-0s$)
"""

from dataclasses import dataclass, field

from . import constants as C
from .risk import RiskState, check_window, clip_shares


def taker_fee_per_share(price: float, coeff: float = C.TAKER_FEE_COEFF) -> float:
    """Polymarket parabolic taker fee: fee_per_share = 0.07 * p * (1 - p)."""
    if price <= 0.0 or price >= 1.0 or coeff <= 0.0:
        return 0.0
    return coeff * price * (1.0 - price)


def compute_fill_usd(
    shares: float,
    price: float,
    role: str = "MAKER",
    include_fee: bool = True,
) -> tuple[float, float]:
    """Return (total_usd, fee_usd) for a fill.

    Maker fills (0% fee): USD_Amount = round(shares * price, 2).
    Taker fills: USD_Amount = round(shares * (price + 0.07 * p * (1 - p)), 2).
    """
    if role == "TAKER" and include_fee:
        fee_ps = taker_fee_per_share(price)
        fee_usd = round(shares * fee_ps, 4)
        total_usd = round(shares * (price + fee_ps), 2)
        return total_usd, fee_usd
    return round(shares * price, 2), 0.0


def dip_curve_shares(curve: dict, price: float, max_clip: float) -> float:
    """Shares for a fresh dip from a linear inverse-dip curve.

    curve = {"lo": 0.07, "hi": 0.45, "sharesLo": 33, "sharesHi": 8}: the fat
    end of the band (low price) gets the big clip, the thin end the small one,
    interpolated linearly in price and clamped outside the band.
    """
    lo = float(curve.get("lo", 0.07))
    hi = float(curve.get("hi", 0.45))
    s_lo = float(curve.get("sharesLo", 10.0))
    s_hi = float(curve.get("sharesHi", 10.0))
    a = min(max((price - lo) / (hi - lo), 0.0), 1.0) if hi > lo else 0.0
    return min(clip_shares(round(s_lo + (s_hi - s_lo) * a), max_clip), max_clip)


def select_ladder_clip(
    deficit: float,
    price: float,
    pair_cost: float | None = None,
    fill_idx: int = 0,
    default_clip: float = C.CLIP_SHARES_DEFAULT,
    max_clip: float = C.MAX_SHARES,
    whole_ladder: bool = True,
    current_lead: float = 0.0,
    is_v22: bool = False,
    atomic_arb: bool = False,
    is_v23: bool = False,
    target_risk_usd: float | None = None,
    dip_curve: dict | None = None,
    **kwargs,  # absorbs legacy unused kwargs
) -> float:
    """Select clip size. In v2.2, employs Confidence Sizing (Heavy on atomic/deficit, Micro on dips).

    In v2.3, employs Constant Dollar-Risk Sizing: Shares = $4.50 / entry price,
    floored to 5-share increments and bounded to [10, max_clip] so unhedged
    downside (shares * entry price) strictly never exceeds $4.50.

    dip_curve (optional): linear inverse-dip curve that overrides the fresh-dip
    clip. Deficit-closing fills are unaffected (they snap to the deficit).
    """
    if deficit > 0:
        # Snap directly to the deficit capped at max_clip so we don't overshoot
        # or leave residual unhedged dust!
        return min(clip_shares(deficit, max_clip), max_clip)
    if dip_curve:
        return dip_curve_shares(dip_curve, price, max_clip)
    # DSP v2.2 Confidence-Based Sizing:
    # 1. Atomic Arb (High Confidence, Risk-Free): Size heavy (up to max_clip = 60 sh)
    # v2.3 intentionally does NOT take the heavy path here: fresh dips always
    # use constant-risk sizing so one fill never creates a 60-share lead that
    # blocks the next micro-cycle.
    if is_v22 and atomic_arb:
        return min(clip_shares(max_clip, max_clip), max_clip)
    # 2a. DSP-v2.3 Speculative Dip Intake (Constant Dollar-Risk Parity):
    if is_v23:
        target = target_risk_usd if target_risk_usd is not None else C.TARGET_DOLLAR_RISK_USD
        raw_shares = target / max(0.01, price)
        snapped = (int(raw_shares // 5.0)) * 5.0
        snapped = max(10.0, min(max_clip, snapped))
        return min(clip_shares(snapped, max_clip), max_clip)
    # 2b. DSP-v2.2 Speculative Dip Intake (Low Confidence, Directional Risk): Size micro (10 sh)
    if is_v22:
        return min(clip_shares(10.0, max_clip), max_clip)
    # Tweak 2: De-escalating clip sizes when leading side accumulates dips
    # Prevents huge runaway deficits from forming during early trending moves
    if current_lead >= 10.0:
        return min(clip_shares(10.0, max_clip), max_clip)
    if current_lead >= 5.0:
        return min(clip_shares(20.0, max_clip), max_clip)
    # Standard 30-share ladder clip on opening, deep dips (<=35c), or alternate fills
    if fill_idx % 2 == 0 or price <= 0.35:
        return min(clip_shares(default_clip, max_clip), max_clip)
    rungs = [r for r in (25.0, 20.0, 15.0, 10.0) if r <= max_clip]
    chosen = rungs[fill_idx % len(rungs)] if rungs else default_clip
    return min(clip_shares(chosen, max_clip), max_clip)


@dataclass
class MicrostructureDecision:
    action: str  # "fill" | "skip"
    outcome: str | None = None
    price: float | None = None
    shares: float = 0.0
    role: str = "MAKER"  # "MAKER" | "TAKER"
    reason: str = "clip-fill"
    sub_reason: str = "maker-dip-ladder"
    projected_pair_cost: float | None = None
    share_deficit: float = 0.0


def _avg_cost(shares: float, cost: float) -> float | None:
    return (cost / shares) if shares > 0 else None


def _projected_pair_cost(
    inv: dict[str, dict[str, float]],
    side: str,
    add_shares: float,
    add_cost: float,
) -> float | None:
    opp = "Down" if side == "Up" else "Up"
    opp_avg = _avg_cost(inv[opp]["shares"], inv[opp]["cost"])
    new_side_avg = _avg_cost(inv[side]["shares"] + add_shares, inv[side]["cost"] + add_cost)
    if opp_avg is None or new_side_avg is None:
        return None
    return round(new_side_avg + opp_avg, 4)


def evaluate_microstructure_ladder(
    quotes: dict[str, dict[str, float | None]],
    inv: dict[str, dict[str, float]],
    fill_idx: int,
    minute: int,
    strategy_id: str = C.STRATEGY_ID,
    min_fill: float = C.PRICE_FLOOR,
    max_fill: float = C.PRICE_CEILING,
    default_clip: float = C.CLIP_SHARES_DEFAULT,
    max_clip: float = C.MAX_SHARES,
    whole_ladder: bool = True,
    benchmark_pair_cost: float = C.BENCHMARK_PAIR_COST,
    max_pair_cost: float = C.PAIR_COST_MAX,
    max_share_lead: float = C.MAX_SHARE_LEAD,
    max_unhedged_usd: float = 0.0,
    dip_curve: dict | None = None,
    target_pair_cost: float | None = None,  # backward compat
    in_sweep_phase: bool = False,
    rescue_max_pair_cost: float = C.RESCUE_PAIR_COST_MAX,
    rescue_ceiling: float = C.RESCUE_CEILING_PRICE,
    **kwargs,  # absorbs legacy kwargs
) -> MicrostructureDecision:
    """Decision Engine for Hybrid Arbitrage Pairing & Certainty Sniping.

    Supports both setups:
    - 'hapcs-v1': Aggressive dual-regime with M4 certainty sniping up to 97.5¢ and 12s cutoff.
    - 'dangerously-skip-permissions': Reconstructed from wallet 0xc533…69a9 ($1.42M vol/wk).
      Focuses on deep dips [7¢–45¢], 75s early cutoff, strict unhedged-gap veto,
      and Tiered Rescue Pairing up to $1.025 so 80¢–92¢ deficit-closing hedges
      are executed rather than left unhedged to face 100% loss at resolution.
    """
    bench_pc = target_pair_cost if target_pair_cost is not None else benchmark_pair_cost

    def _side_prices(s: str) -> tuple[float | None, float | None]:
        q = quotes.get(s) or {}
        bid = q.get("bid")
        ask = q.get("ask")
        valid_bid = bid if (bid is not None and 0.0 < bid < 1.0) else None
        valid_ask = ask if (ask is not None and 0.0 < ask < 1.0) else None
        return valid_bid, valid_ask

    saw_ceiling = False
    saw_dust = False
    saw_pair_cap = False
    saw_unhedged_cap = False
    # DSP family (v2.0, v2.1, v2.2, ...) shares the same recovery-engine rules.
    is_dsp = strategy_id.startswith("dangerously-skip-permissions")
    is_v22 = strategy_id.endswith("v2.2")
    is_v23 = strategy_id.endswith("v2.3")
    is_confidence = is_v22 or is_v23
    # SINGLE unhedged-gap knob: max_share_lead is a strict veto, identical for
    # every strategy version. A fill that would leave this side's lead AT OR
    # ABOVE max_share_lead is skipped, so unhedged inventory strictly never
    # reaches the knob value (knob 20 -> at most 19 sh held, 20 unreachable).
    # This caps the NET difference only, NOT total paired volume, so choppy
    # windows can re-trigger Dip -> Equalize micro-cycles indefinitely
    # while unhedged risk at any second stays strictly below the knob.
    # (There used to be a hidden +5.0 overshoot allowance here that let the
    # gap land on lead_cap+5; it is gone. What the dashboard shows is what
    # the engine enforces.)
    lead_cap = max_share_lead
    rescue_cap = rescue_max_pair_cost if (is_dsp or in_sweep_phase) else max_pair_cost

    # 1. Phase 3: Resolution Certainty Snipe in Minute 4 [0.90, 0.975]
    # Enabled exclusively for 'hapcs-v1'. Disabled for 'dangerously-skip-permissions'
    # to avoid 95¢–99¢ reversal wipeouts, and disabled in sweep phase.
    if minute == 4 and strategy_id == "hapcs-v1" and not in_sweep_phase:
        for side in ("Up", "Down"):
            opp = "Down" if side == "Up" else "Up"
            deficit = round(inv[opp]["shares"] - inv[side]["shares"], 2)
            bid, ask = _side_prices(side)
            px = ask if ask is not None else bid
            if px is not None and C.RESOLUTION_SNIPE_BAND[0] <= px <= max_fill:
                clip = default_clip if deficit <= 0 else min(deficit, max_clip)
                shares = select_ladder_clip(
                    deficit=max(0.0, deficit),
                    price=px,
                    pair_cost=None,
                    fill_idx=fill_idx,
                    default_clip=clip,
                    max_clip=max_clip,
                    whole_ladder=whole_ladder,
                )
                role = "MAKER" if (bid is not None and ask is not None and (ask - bid) <= 0.01) else "TAKER"
                exec_px = bid if role == "MAKER" and bid is not None else px
                est_usd, _ = compute_fill_usd(shares, exec_px, role=role, include_fee=(role == "TAKER"))
                proj_pc = _projected_pair_cost(inv, side, shares, est_usd)
                if proj_pc is None or proj_pc <= max_pair_cost:
                    return MicrostructureDecision(
                        action="fill",
                        outcome=side,
                        price=round(exec_px, 4),
                        shares=shares,
                        role=role,
                        reason="m4-snipe",
                        sub_reason="resolution-certainty-snipe" if deficit <= 0 else "hedge-equalizer",
                        projected_pair_cost=proj_pc,
                        share_deficit=deficit,
                    )

    # 2. Dynamic Arbitrage Pairing (Equalizer & Rescue Deficit Hedging)
    # Check any side with a share deficit!
    for side in ("Up", "Down"):
        opp = "Down" if side == "Up" else "Up"
        deficit = round(inv[opp]["shares"] - inv[side]["shares"], 2)
        if deficit <= 0:
            continue
        bid, ask = _side_prices(side)
        px = ask if ask is not None else bid
        if px is None:
            continue
        if px < min_fill:
            saw_dust = True
            continue
        # In rescue/hedging mode (deficit > 0), allow up to rescue_ceiling (0.985)
        # to ensure open deficit-closing hedges are executed rather than facing 100% loss at resolution.
        effective_ceiling = rescue_ceiling if (is_dsp or in_sweep_phase) else max_fill
        if px > effective_ceiling:
            saw_ceiling = True
            continue

        shares = select_ladder_clip(
            deficit=deficit,
            price=px,
            pair_cost=None,
            fill_idx=fill_idx,
            default_clip=default_clip,
            max_clip=max_clip,
            whole_ladder=whole_ladder,
            is_v22=is_v22,
            is_v23=is_v23,
        )
        # Tweak 3: Prioritize 0% maker fills during sweep equalization to eliminate adverse fee drag
        if in_sweep_phase and bid is not None:
            role = "MAKER"
            exec_px = bid
        else:
            role = "MAKER" if (bid is not None and ask is not None and round(ask - bid, 4) <= 0.01) else "TAKER"
            exec_px = bid if role == "MAKER" and bid is not None else px
        est_usd, _ = compute_fill_usd(shares, exec_px, role=role, include_fee=(role == "TAKER"))
        proj_pc = _projected_pair_cost(inv, side, shares, est_usd)

        # Tiered Rescue Hedging:
        # Standard: proj_pc <= max_pair_cost -> sub-$1.00 profitable pairing arbitrage.
        # Rescue: when holding a deficit in DSP or sweep phase, accepting proj_pc up to rescue_max_pair_cost (1.080)
        # locks in capital redemption, preventing a 100% loss ($0.00 redemption) on the naked leg.
        rescue_cap = rescue_max_pair_cost if (is_dsp or in_sweep_phase) else max_pair_cost
        is_rescue = (proj_pc is not None and proj_pc > max_pair_cost)
        if proj_pc is None or proj_pc <= max_pair_cost or (proj_pc <= rescue_cap and exec_px <= effective_ceiling):
            return MicrostructureDecision(
                action="fill",
                outcome=side,
                price=round(exec_px, 4),
                shares=shares,
                role=role,
                reason="rescue-hedge" if is_rescue else ("m4-snipe" if minute == 4 else "clip-fill"),
                sub_reason="rescue-equalizer" if is_rescue else "hedge-equalizer",
                projected_pair_cost=proj_pc,
                share_deficit=deficit,
            )
        saw_pair_cap = True

    # 3. Passive Maker Dip Grid in [min_fill, 0.50]
    up_def = round(inv["Down"]["shares"] - inv["Up"]["shares"], 2)
    down_def = round(inv["Up"]["shares"] - inv["Down"]["shares"], 2)

    # If in sweep phase, do NOT take any speculative dip fills!
    if in_sweep_phase:
        preferred = "Up" if up_def > 0 else "Down"
        if saw_ceiling:
            return MicrostructureDecision(action="skip", outcome=preferred, reason="extreme-price-skip", sub_reason="ceiling-price-skip")
        if saw_pair_cap:
            return MicrostructureDecision(action="skip", outcome=preferred, reason="extreme-price-skip", sub_reason="pair-cost-cap")
        return MicrostructureDecision(action="skip", outcome=preferred, reason="sweep-balanced", sub_reason="sweep-balanced")

    # Anti-Runaway Deficit Lock & Strict Leading-Side Freeze:
    # If one side leads by >= the single gap knob (max_share_lead), STRICTLY
    # FREEZE buying the leading side! Candidates must ONLY be the lagging
    # side until balance is restored. (The old separate freezeLead setting was
    # merged into max_share_lead: one setting does all of this.)
    fl = max_share_lead
    if up_def >= fl:
        candidates = ("Up",)   # Down leads -> ONLY Up allowed!
    elif down_def >= fl:
        candidates = ("Down",) # Up leads -> ONLY Down allowed!
    elif up_def > 0:
        candidates = ("Up", "Down")
    elif down_def > 0:
        candidates = ("Down", "Up")
    else:
        up_bid, _ = _side_prices("Up")
        down_bid, _ = _side_prices("Down")
        up_p = up_bid or 0.50
        down_p = down_bid or 0.50
        if up_p < down_p:
            candidates = ("Up", "Down")
        elif down_p < up_p:
            candidates = ("Down", "Up")
        else:
            candidates = ("Up", "Down") if (fill_idx % 2 == 0) else ("Down", "Up")

    preferred = candidates[0]

    for side in candidates:
        opp = "Down" if side == "Up" else "Up"
        deficit = max(0.0, round(inv[opp]["shares"] - inv[side]["shares"], 2))
        lead = max(0.0, round(inv[side]["shares"] - inv[opp]["shares"], 2))
        bid, ask = _side_prices(side)
        opp_bid, opp_ask = _side_prices(opp)
        opp_ref = opp_ask if opp_ask is not None else opp_bid
        px = bid if (bid is not None and bid >= min_fill) else ask
        if px is None:
            continue
        if px < min_fill:
            saw_dust = True
            continue
        if px > max_fill:
            saw_ceiling = True
            continue
        dip_max = 0.45 if is_dsp else C.DIP_LADDER_MAX
        if px <= dip_max:
            # Pre-Flight Hedge Gate (v2.2 only):
            # Before taking an unhedged speculative dip fill, verify that the opposite side
            # allows a hedge under rescue_cap (0.995). If the opposite side is already too expensive,
            # refuse immediately so we NEVER enter a position where a sub-$1.00 hedge is impossible!
            # v2.3 drops this gate and relies on the strict sub-$1.00 pair-cost gates below,
            # so dips keep filling (constant $4.50 risk) and equalize on the next swing.
            if is_v22 and deficit <= 0 and opp_ref is not None:
                if px + opp_ref > rescue_cap:
                    saw_pair_cap = True
                    continue

            # High-Confidence Atomic Arb Detection:
            # If both sides can be filled immediately with sum <= 0.990, flag atomic_arb = True!
            is_atomic = bool(is_confidence and opp_ref is not None and (px + opp_ref <= 0.990))

            role = "MAKER" if ((bid is not None and px == bid) or bid is None) else "TAKER"
            shares = select_ladder_clip(
                deficit=deficit,
                price=px,
                pair_cost=None,
                fill_idx=fill_idx,
                default_clip=default_clip,
                max_clip=max_clip,
                whole_ladder=whole_ladder,
                current_lead=lead,
                is_v22=is_v22,
                atomic_arb=is_atomic,
                is_v23=is_v23,
                dip_curve=dip_curve,
            )
            est_usd, _ = compute_fill_usd(shares, px, role=role, include_fee=(role == "TAKER"))
            proj_pc = _projected_pair_cost(inv, side, shares, est_usd)
            # Strict hard ceiling on one-sided lead: a fill that would leave
            # this side's lead at or above the knob is vetoed, so the knob
            # value itself is unreachable (set 20 -> 20 never held).
            # v2.2 atomic pairs bypass this (one-shot 60/60 then hold).
            atomic_bypass = bool(is_atomic and is_v22)
            if not atomic_bypass and (lead + shares >= lead_cap):
                saw_unhedged_cap = True
                continue
            # Dollar-denominated unhedged cap (opt-in; 0 = off). max_share_lead
            # counts SHARES, so it vetoes a big cheap clip ("33 >= 11") while
            # saying nothing about dollars at risk. This knob caps the dollars
            # exposed instead: average cost of this side's inventory x the net
            # unhedged lead it would leave behind.
            if max_unhedged_usd > 0:
                new_sh = inv[side]["shares"] + shares
                new_cost = inv[side]["cost"] + est_usd
                lead_after = new_sh - inv[opp]["shares"]
                if lead_after > 0 and (new_cost / new_sh) * lead_after > max_unhedged_usd:
                    saw_unhedged_cap = True
                    continue
            # Sub-$1.00 pair-cost gate: <= max_pair_cost when closing deficit, <= bench_pc otherwise
            allowed_pc = max_pair_cost if deficit > 0 else bench_pc
            if proj_pc is None or proj_pc <= allowed_pc:
                return MicrostructureDecision(
                    action="fill",
                    outcome=side,
                    price=round(px, 4),
                    shares=shares,
                    role=role,
                    reason="m4-snipe" if (minute == 4 and px <= 0.15) else "clip-fill",
                    sub_reason="maker-dip-ladder",
                    projected_pair_cost=proj_pc,
                    share_deficit=deficit,
                )
            saw_pair_cap = True
        elif px <= C.STRADDLE_BAND[1] and inv["Up"]["shares"] == 0 and inv["Down"]["shares"] == 0:
            # Opening Straddle Leg 1 in (0.50, 0.55]
            # v2.2 pre-flight gate only; v2.3 opens on pair-cost math alone.
            if is_v22 and opp_ref is not None:
                if px + opp_ref > rescue_cap:
                    saw_pair_cap = True
                    continue

            is_atomic = bool(is_confidence and opp_ref is not None and (px + opp_ref <= 0.990))
            role = "MAKER" if ((bid is not None and px == bid) or bid is None) else "TAKER"
            shares = select_ladder_clip(
                deficit=0.0,
                price=px,
                pair_cost=None,
                fill_idx=fill_idx,
                default_clip=default_clip,
                max_clip=max_clip,
                whole_ladder=whole_ladder,
                is_v22=is_v22,
                atomic_arb=is_atomic,
                is_v23=is_v23,
            )
            return MicrostructureDecision(
                action="fill",
                outcome=side,
                price=round(px, 4),
                shares=shares,
                role=role,
                reason="straddle-open",
                sub_reason="maker-dip-ladder",
                projected_pair_cost=None,
                share_deficit=0.0,
            )

    if saw_ceiling:
        return MicrostructureDecision(action="skip", outcome=preferred, reason="extreme-price-skip", sub_reason="ceiling-price-skip")
    if saw_dust:
        return MicrostructureDecision(action="skip", outcome=preferred, reason="dust-quote", sub_reason="below-price-floor")
    if saw_unhedged_cap:
        return MicrostructureDecision(action="skip", outcome=preferred, reason="unhedged-cap-skip", sub_reason="unhedged-cap")
    if saw_pair_cap:
        return MicrostructureDecision(action="skip", outcome=preferred, reason="extreme-price-skip", sub_reason="pair-cost-cap")
    return MicrostructureDecision(action="skip", outcome=preferred, reason="no-liquidity", sub_reason="no-liquidity")


# ---------------------------------------------------------------------------
# Lightweight Simulation Fixture (for historical fidelity benchmarks)
# ---------------------------------------------------------------------------

@dataclass
class PaperFill:
    minute: int
    outcome: str
    price: float
    shares: float
    usd: float


@dataclass
class WindowPlan:
    event_slug: str
    fills: list[PaperFill] = field(default_factory=list)

    @property
    def cost(self) -> float:
        return sum(f.usd for f in self.fills)


def m_quotas(target: int = int(C.MEDIAN_TRADES_PER_WINDOW)) -> list[int]:
    total = sum(C.M_BUCKETS)
    return [max(1, round(target * b / total)) for b in C.M_BUCKETS]


def pick_side(i: int, minute: int, lean=None) -> str:
    up_side = (i + minute) % 2 == 0
    if lean is not None and getattr(lean, "confidence", 0) > 0:
        l_val = getattr(lean, "lean", 0.0)
        up_p = 0.5 + l_val * 0.25 * (0.5 + 0.5 * getattr(lean, "confidence", 0.0))
        if up_p > 0.6 and i % 3 != 0:
            up_side = True
        elif up_p < 0.4 and i % 3 != 0:
            up_side = False
    return "Up" if up_side else "Down"


def plan_window(event_slug: str, lean=None, state: RiskState | None = None) -> WindowPlan:
    """Deterministic paper simulation plan matching benchmark CSV moments."""
    counts = m_quotas(int(C.MEDIAN_TRADES_PER_WINDOW))
    plan = WindowPlan(event_slug=event_slug)
    cost = 0.0
    st = state or RiskState()
    for minute, n in enumerate(counts):
        for i in range(n):
            blocked = check_window(len(plan.fills), st)
            if blocked:
                return plan
            outcome = pick_side(i, minute, lean)
            if minute < 4:
                price = 0.476
            else:
                price = 0.85 if (i % 5 == 0) else (0.15 if i % 7 == 0 else 0.476)
            shares = clip_shares(C.CLIP_SHARES_DEFAULT if i % 3 == 0 else 14.0)
            usd = round(price * shares, 2)
            plan.fills.append(PaperFill(minute=minute, outcome=outcome, price=price, shares=shares, usd=usd))
            cost += usd
    return plan
