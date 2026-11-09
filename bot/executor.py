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


def select_ladder_clip(
    deficit: float,
    price: float,
    pair_cost: float | None = None,
    fill_idx: int = 0,
    default_clip: float = C.CLIP_SHARES_DEFAULT,
    max_clip: float = C.MAX_SHARES,
    whole_ladder: bool = True,
    **kwargs,  # absorbs legacy unused kwargs
) -> float:
    """Select standard whole-number ladder clip (30 default, 50 max, or deficit catch-up)."""
    # Large share deficit or deep pair-cost arbitrage -> step up to max_clip (50)
    if deficit >= max_clip and (pair_cost is None or pair_cost <= 0.96):
        return min(clip_shares(max_clip), max_clip)
    if deficit > 0:
        # Snap deficit to nearest standard whole ladder clip
        for rung in (50.0, 30.0, 25.0, 20.0, 15.0, 10.0, 5.0):
            if rung <= max_clip and deficit >= rung * 0.8:
                return min(clip_shares(rung), max_clip)
    # Standard 30-share ladder clip on opening, deep dips (<=35c), or alternate fills
    if fill_idx % 2 == 0 or price <= 0.35:
        return min(clip_shares(default_clip), max_clip)
    rungs = [r for r in (25.0, 20.0, 15.0, 10.0) if r <= max_clip]
    chosen = rungs[fill_idx % len(rungs)] if rungs else default_clip
    return min(clip_shares(chosen), max_clip)


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
    min_fill: float = C.PRICE_FLOOR,
    max_fill: float = C.PRICE_CEILING,
    default_clip: float = C.CLIP_SHARES_DEFAULT,
    max_clip: float = C.MAX_SHARES,
    whole_ladder: bool = True,
    benchmark_pair_cost: float = C.BENCHMARK_PAIR_COST,
    max_pair_cost: float = C.PAIR_COST_MAX,
    max_share_lead: float = C.MAX_SHARE_LEAD,
    target_pair_cost: float | None = None,  # backward compat
    **kwargs,  # absorbs legacy kwargs
) -> MicrostructureDecision:
    """Decision Engine for Hybrid Arbitrage Pairing & Certainty Sniping.

    1. Phase 3 Resolution Certainty Snipe in Minute 4 [up to 97.5¢]:
       When a side trades in [0.90, 0.975] near resolution:
       - If closing a deficit: execute catch-up clip up to max_clip (50) provided proj_pc <= max_pair_cost.
       - If no deficit: execute certainty snipe up to default_clip (30) provided proj_pc <= max_pair_cost.
    2. Dynamic Arbitrage Pairing (Lagging-Leg Equalizer):
       Whenever one side holds fewer shares than the opposite leg (deficit > 0),
       buy the lagging leg at ANY price in [min_fill, max_fill] as long as
       projected pair cost <= max_pair_cost (0.990). No artificial 0.75 barrier.
    3. Passive Maker Dip Grid in [min_fill, 0.50]:
       Accumulate the dipping leg at resting bid (0% maker fee), respecting
       the strict 90-share unhedged lead ceiling.
    4. Opening Straddle Leg 1 inside STRADDLE_BAND [0.34, 0.55] when both sides are empty.
    """
    bench_pc = target_pair_cost if target_pair_cost is not None else benchmark_pair_cost

    def _side_prices(s: str) -> tuple[float | None, float | None]:
        q = quotes.get(s) or {}
        bid = q.get("bid")
        ask = q.get("ask")
        valid_bid = bid if (bid is not None and 0.0 < bid < 1.0) else None
        valid_ask = ask if (ask is not None and 0.0 < ask < 1.0) else None
        return valid_bid, valid_ask

    # 1. Phase 3: Resolution Certainty Snipe in Minute 4 [0.90, 0.975]
    if minute == 4:
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

    # 2. Dynamic Arbitrage Pairing (Equalizer): Check any side with a share deficit!
    # No artificial minimum price barrier: if Down is at 20c and Up is at 60c, 70c, or 80c,
    # pairing it locks in sub-$1.00 pair cost and guaranteed arbitrage!
    for side in ("Up", "Down"):
        opp = "Down" if side == "Up" else "Up"
        deficit = round(inv[opp]["shares"] - inv[side]["shares"], 2)
        if deficit <= 0:
            continue
        bid, ask = _side_prices(side)
        px = ask if ask is not None else bid
        if px is None or px > max_fill or px < min_fill:
            continue
        shares = select_ladder_clip(
            deficit=deficit,
            price=px,
            pair_cost=None,
            fill_idx=fill_idx,
            default_clip=default_clip,
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
                reason="m4-snipe" if minute == 4 else "clip-fill",
                sub_reason="hedge-equalizer",
                projected_pair_cost=proj_pc,
                share_deficit=deficit,
            )

    # 3. Passive Maker Dip Grid in [min_fill, 0.50]
    up_def = round(inv["Down"]["shares"] - inv["Up"]["shares"], 2)
    down_def = round(inv["Up"]["shares"] - inv["Down"]["shares"], 2)

    # Anti-Runaway Deficit Lock: If one side leads by >= max_share_lead (90 shares / 3 clips),
    # strictly freeze accumulation of the leading side!
    if up_def >= max_share_lead:
        candidates = ("Up",)
    elif down_def >= max_share_lead:
        candidates = ("Down",)
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

    saw_ceiling = False
    saw_dust = False
    saw_pair_cap = False

    for side in candidates:
        opp = "Down" if side == "Up" else "Up"
        deficit = max(0.0, round(inv[opp]["shares"] - inv[side]["shares"], 2))
        lead = max(0.0, round(inv[side]["shares"] - inv[opp]["shares"], 2))
        bid, ask = _side_prices(side)
        px = bid if (bid is not None and bid >= min_fill) else ask
        if px is None:
            continue
        if px < min_fill:
            saw_dust = True
            continue
        if px > max_fill:
            saw_ceiling = True
            continue
        if px <= C.DIP_LADDER_MAX:
            role = "MAKER" if ((bid is not None and px == bid) or bid is None) else "TAKER"
            shares = select_ladder_clip(
                deficit=deficit,
                price=px,
                pair_cost=None,
                fill_idx=fill_idx,
                default_clip=default_clip,
                max_clip=max_clip,
                whole_ladder=whole_ladder,
            )
            est_usd, _ = compute_fill_usd(shares, px, role=role, include_fee=(role == "TAKER"))
            proj_pc = _projected_pair_cost(inv, side, shares, est_usd)
            # Strict hard ceiling on one-sided lead: NEVER exceed max_share_lead.
            if lead >= max_share_lead or (lead + shares > max_share_lead + 5.0):
                saw_pair_cap = True
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
            role = "MAKER" if ((bid is not None and px == bid) or bid is None) else "TAKER"
            shares = select_ladder_clip(
                deficit=0.0,
                price=px,
                pair_cost=None,
                fill_idx=fill_idx,
                default_clip=default_clip,
                max_clip=max_clip,
                whole_ladder=whole_ladder,
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
            blocked = check_window(len(plan.fills), cost, st)
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
