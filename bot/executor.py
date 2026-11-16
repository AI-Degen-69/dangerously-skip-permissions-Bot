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

import math
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


# Hump sizing anchors shared with bot/replay.py: fat in the middle
# (~48.7 sh at 40-50c), thin at the extremes (~30 sh). Clamped outside.
HUMP_ANCHORS = [(0.07, 30.0), (0.10, 30.0), (0.40, 48.7), (0.50, 48.7), (0.70, 30.0)]


def hump_shares(price: float, max_clip: float) -> float:
    """Piecewise-linear hump clip, clamped outside the anchors."""
    try:
        px = float(price)
    except (TypeError, ValueError):
        return 10.0
    pts = HUMP_ANCHORS
    if px <= pts[0][0]:
        sh = pts[0][1]
    elif px >= pts[-1][0]:
        sh = pts[-1][1]
    else:
        sh = pts[-1][1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= px <= x1:
                a = (px - x0) / (x1 - x0) if x1 > x0 else 0.0
                sh = y0 + (y1 - y0) * a
                break
    return min(clip_shares(round(sh, 1), max_clip), max_clip)


def is_hump_curve(dip_curve) -> bool:
    """v2.7 hump flag: stored as the string "hump" (or {"type": "hump"})."""
    if dip_curve == "hump":
        return True
    return isinstance(dip_curve, dict) and dip_curve.get("type") == "hump"


def dip_curve_shares(curve: dict, price: float, max_clip: float) -> float | None:
    """Shares for a fresh dip from a linear inverse-dip curve, or None if the curve is unusable.

    curve = {"lo": 0.07, "hi": 0.45, "sharesLo": 33, "sharesHi": 8}: the fat
    end of the band (low price) gets the big clip, the thin end the small one,
    interpolated linearly in price and clamped outside the band.
    """
    try:
        lo = float(curve.get("lo", 0.07))
        hi = float(curve.get("hi", 0.45))
        s_lo = float(curve.get("sharesLo", 10.0))
        s_hi = float(curve.get("sharesHi", 10.0))
    except (AttributeError, TypeError, ValueError):
        # A typo in config.json must not crash the trading loop mid-window.
        return None
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
    if is_hump_curve(dip_curve):
        return hump_shares(price, max_clip)
    if dip_curve:
        curve_clip = dip_curve_shares(dip_curve, price, max_clip)
        if curve_clip is not None:
            return curve_clip
        # Unusable curve values: fall through to the flat ladder clip.
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


# ---------------------------------------------------------------------------
# Hydrogen v1.5: concurrent two-sided accumulation.
#
# Measured wallet grammar (live tape + 486k-trade report): both sides are
# quoted from the first seconds of the window in ~30-share clips (5-share
# probes when the book is uncertain), the lighter side is always bought
# first at whatever the book offers, top-ups close at most half of the
# gap per fill, and size tilts toward the side trading cheaper. There is
# no dip band, no deficit-chase ladder, and no pair-cost gate: pair cost
# is computed for the record and reported against the $0.977 wallet
# benchmark, never enforced. Buy-only, hold-to-settlement, zero sells.
# ---------------------------------------------------------------------------
H15_LEAD_TOLERANCE = 0.25    # measured: share lead stays under ~25% of matched book
H15_MIN_LEAD_SHARES = 5.0   # tiny books: tolerate up to 5 sh before rebalancing
H15_PROBE_SHARES = 5.0      # measured modal minimum: 5-share price-discovery probes
H15_TAKER_SPREAD_MAX = 0.02  # cross the ask when the spread is at most 2c
H15_GAP_CLOSE_FRACTION = 0.5  # rebalance top-ups close at most half the gap per fill

# H16 edge-seeking sizing (no hard pair gate): asks sum ~1.01, so
# taker-taker pairs always lose. Edge only exists at the bids. Expensive
# legs are throttled by SIZE + ROLE (small maker-only), never by refusal,
# so the fill model stays honest and the book still balances. Cheap legs
# are never throttled: buying them is what pulls the average under $1.
H16_LEAD_TOLERANCE = 0.15    # tighter: a 100+ sh gap on a 700 book rebalances
H16_MIN_LEAD_SHARES = 5.0
H16_PROBE_SHARES = 5.0
H16_TAKER_SPREAD_MAX = 0.02
H16_GAP_CLOSE_FRACTION = 0.5
H16_EXPENSIVE = 0.65          # at/above: maker-only, capped clips
H16_VERY_EXPENSIVE = 0.78     # at/above: 5 sh maker-only max
H16_CHEAP = 0.35              # at/below: full clip, taker allowed
H16_MID_PRICE = 0.50          # throttle-by-pair applies only at/above this leg price
H16_BID_SUM_PATIENT = 0.99    # bids summing above: no taker anywhere, makers only
H16_PAIR_SOFT = 1.00          # above: halve expensive-leg size
H16_PAIR_FIRM = 1.02          # above: expensive leg to 5 sh maker-only


def _h15_side_prices(quotes: dict, side: str) -> tuple[float | None, float | None]:
    q = quotes.get(side) or {}
    bid = q.get("bid")
    ask = q.get("ask")
    valid_bid = bid if (bid is not None and 0.0 < bid < 1.0) else None
    valid_ask = ask if (ask is not None and 0.0 < ask < 1.0) else None
    return valid_bid, valid_ask


def _evaluate_concurrent_accumulation(
    quotes: dict[str, dict[str, float | None]],
    inv: dict[str, dict[str, float]],
    fill_idx: int,
    default_clip: float,
    max_clip: float,
    min_fill: float,
    max_ceiling: float,
    max_unhedged_usd: float,
    in_sweep_phase: bool,
    max_depth_shares: float = 0.0,
    resting_size: dict | None = None,
) -> MicrostructureDecision:
    """Hydrogen v1.5 decision: balance first, tilt cheap, never chase.

    Over tolerance the lighter side is bought at the touch (taker when the
    spread is tight, maker otherwise), sized to close at most half the gap.
    Within tolerance the cheaper side is quoted in schedule clips, with
    5-share taker probes when the book is wide. Every price up to the
    ceiling is eligible for the light side; pair cost is recorded, not gated.
    """
    up_sh = float((inv.get("Up") or {}).get("shares", 0.0))
    dn_sh = float((inv.get("Down") or {}).get("shares", 0.0))
    matched = min(up_sh, dn_sh)
    lead = up_sh - dn_sh  # > 0 means Up heavy
    tol = max(H15_MIN_LEAD_SHARES, H15_LEAD_TOLERANCE * matched)
    over = abs(lead) > tol
    light = "Down" if lead > 0 else ("Up" if lead < 0 else None)

    def _unhedged_ok(side: str, shares: float, est_usd: float) -> bool:
        if max_unhedged_usd <= 0:
            return True
        cur = inv.get(side) or {}
        new_sh = float(cur.get("shares", 0.0)) + shares
        new_cost = float(cur.get("cost", 0.0)) + est_usd
        opp = "Down" if side == "Up" else "Up"
        lead_after = new_sh - float((inv.get(opp) or {}).get("shares", 0.0))
        if lead_after > 0 and new_sh > 0:
            if (new_cost / new_sh) * lead_after > max_unhedged_usd:
                return False
        return True

    def _cap_maker(shares: float, role: str, side: str) -> float:
        try:
            dc = float(max_depth_shares or 0.0)
        except Exception:
            dc = 0.0
        if dc <= 0 or role != "MAKER":
            return shares
        avail = None
        if isinstance(resting_size, dict):
            avail = resting_size.get(side)
        try:
            avail = float(avail) if avail is not None else None
        except (TypeError, ValueError):
            avail = None
        if avail is None:
            return shares
        if avail <= 0:
            return 0.0
        return min(float(shares), float(avail))

    def _skip(reason: str, sub: str, preferred: str | None) -> MicrostructureDecision:
        return MicrostructureDecision(action="skip", outcome=preferred,
                                      reason=reason, sub_reason=sub)

    # The sweep stops opening; the book is held to settlement.
    if in_sweep_phase:
        preferred = light if light is not None else "Up"
        return _skip("sweep-balanced", "sweep-balanced", preferred)

    # --- Rebalance mode: the lighter side is bought first, at any price
    # up to the ceiling, closing at most half the gap per fill. ---
    if over and light is not None:
        want = min(float(default_clip), math.ceil(abs(lead) * H15_GAP_CLOSE_FRACTION))
        size = min(clip_shares(round(want, 1), max_clip), max_clip)
        if size <= 0:
            return _skip("no-liquidity", "no-liquidity", light)
        bid, ask = _h15_side_prices(quotes, light)
        spread = (ask - bid) if (ask is not None and bid is not None) else None
        use_taker = ask is not None and (bid is None or (spread is not None and spread <= H15_TAKER_SPREAD_MAX + 1e-9))
        if use_taker:
            px, role = ask, "TAKER"
        elif bid is not None:
            px, role = bid, "MAKER"
        else:
            return _skip("no-liquidity", "no-liquidity", light)
        if px < min_fill:
            return _skip("dust-quote", "below-price-floor", light)
        if px > max_ceiling:
            return _skip("extreme-price-skip", "ceiling-price-skip", light)
        est_usd, _fee = compute_fill_usd(size, px, role=role, include_fee=(role == "TAKER"))
        if not _unhedged_ok(light, size, est_usd):
            return _skip("unhedged-cap-skip", "unhedged-cap", light)
        size = _cap_maker(size, role, light)
        if size <= 0:
            return _skip("no-liquidity", "depth-cap", light)
        proj = _projected_pair_cost(inv, light, size, est_usd)
        opp_sh = float((inv.get("Up" if light == "Down" else "Down") or {}).get("shares", 0.0))
        return MicrostructureDecision(
            action="fill", outcome=light, price=round(px, 4), shares=size,
            role=role, reason="balance-topup",
            sub_reason="rebalance-taker" if role == "TAKER" else "rebalance-maker",
            projected_pair_cost=proj,
            share_deficit=round(max(0.0, opp_sh - float((inv.get(light) or {}).get("shares", 0.0))), 2),
        )

    # --- Balanced mode: tilt toward the cheaper side. ---
    up_bid, up_ask = _h15_side_prices(quotes, "Up")
    dn_bid, dn_ask = _h15_side_prices(quotes, "Down")
    up_ref = up_bid if up_bid is not None else up_ask
    dn_ref = dn_bid if dn_bid is not None else dn_ask
    if up_ref is None and dn_ref is None:
        return _skip("no-liquidity", "no-liquidity", "Up" if fill_idx % 2 == 0 else "Down")
    # Candidate sides: tilt toward the cheaper side first, but ALWAYS also
    # try the other side. A blocked tilt (cap/ceiling/dust) must never freeze
    # the side that actually needs buying.
    if up_ref is None:
        sides = ["Down"]
    elif dn_ref is None:
        sides = ["Up"]
    elif up_ref < dn_ref:
        sides = ["Up", "Down"]
    elif dn_ref < up_ref:
        sides = ["Down", "Up"]
    else:
        sides = ["Up", "Down"] if fill_idx % 2 == 0 else ["Down", "Up"]
    preferred = sides[0]
    saw_dust = saw_ceiling = saw_unhedged = saw_depth = False
    for side in sides:
        bid, ask = _h15_side_prices(quotes, side)
        spread = (ask - bid) if (ask is not None and bid is not None) else None
        attempts: list[tuple[str, float, float]] = []
        if ask is not None and (bid is None or (spread is not None and spread > H15_TAKER_SPREAD_MAX + 1e-9)):
            # Uncertain book: 5-share taker probe at the ask for price discovery.
            attempts.append(("TAKER", ask, min(H15_PROBE_SHARES, max_clip)))
        if bid is not None:
            attempts.append(("MAKER", bid, min(float(default_clip), max_clip)))
        for role, px, want in attempts:
            if px < min_fill:
                saw_dust = True
                continue
            if px > max_ceiling:
                saw_ceiling = True
                continue
            size = min(clip_shares(round(want, 1), max_clip), max_clip)
            if size <= 0:
                continue
            est_usd, _fee = compute_fill_usd(size, px, role=role, include_fee=(role == "TAKER"))
            if not _unhedged_ok(side, size, est_usd):
                saw_unhedged = True
                continue
            size = _cap_maker(size, role, side)
            if size <= 0:
                saw_depth = True
                continue
            proj = _projected_pair_cost(inv, side, size, est_usd)
            return MicrostructureDecision(
                action="fill", outcome=side, price=round(px, 4), shares=size,
                role=role, reason="clip-fill",
                sub_reason="balance-probe" if role == "TAKER" else "balance-maker",
                projected_pair_cost=proj,
                share_deficit=0.0,
            )
        # No fill on this side: fall through and try the other side. Skips
        # are reported once, after every candidate side has been tried.
    if saw_ceiling:
        return _skip("extreme-price-skip", "ceiling-price-skip", preferred)
    if saw_dust:
        return _skip("dust-quote", "below-price-floor", preferred)
    if saw_unhedged:
        return _skip("unhedged-cap-skip", "unhedged-cap", preferred)
    if saw_depth:
        return _skip("no-liquidity", "depth-cap", preferred)
    return _skip("no-liquidity", "no-liquidity", preferred)


def _h16_throttle_size(px: float, want: float, proj: float | None) -> float:
    """Edge-seeking sizing: expensive legs shrink, cheap legs never do.

    No refusal here -- only smaller clips. Buying a cheap leg always pulls
    the matched average down, so throttling applies solely to legs at or
    above mid-price whose projected pair is already over the soft line.
    """
    capped = float(want)
    if px >= H16_VERY_EXPENSIVE:
        capped = min(capped, 5.0)
    elif px >= H16_EXPENSIVE:
        capped = min(capped, 10.0)
    if proj is not None and px >= H16_MID_PRICE:
        if proj > H16_PAIR_FIRM:
            capped = min(capped, 5.0)
        elif proj > H16_PAIR_SOFT:
            capped = min(capped, max(5.0, capped / 2.0))
    return max(0.0, capped)


def _evaluate_edge_accumulation(
    quotes: dict[str, dict[str, float | None]],
    inv: dict[str, dict[str, float]],
    fill_idx: int,
    default_clip: float,
    max_clip: float,
    min_fill: float,
    max_ceiling: float,
    max_unhedged_usd: float,
    in_sweep_phase: bool,
    max_depth_shares: float = 0.0,
    resting_size: dict | None = None,
) -> MicrostructureDecision:
    """Hydrogen v1.6 decision: same concurrent grammar as v1.5, plus edge.

    Tighter lead tolerance (15%) so 100+ sh gaps rebalance instead of
    sitting inside tolerance; expensive legs (>=65c) are maker-only with
    capped clips (5 sh at >=78c); no taker anywhere when the bids sum
    above 99c; projected pairs over $1.00 halve expensive-leg size and
    over $1.02 cut it to 5 sh maker-only. Cheap legs are never throttled.
    Pair cost is still recorded, never a refusal reason.
    """
    up_sh = float((inv.get("Up") or {}).get("shares", 0.0))
    dn_sh = float((inv.get("Down") or {}).get("shares", 0.0))
    matched = min(up_sh, dn_sh)
    lead = up_sh - dn_sh
    tol = max(H16_MIN_LEAD_SHARES, H16_LEAD_TOLERANCE * matched)
    over = abs(lead) > tol
    light = "Down" if lead > 0 else ("Up" if lead < 0 else None)
    up_bid, _up_ask = _h15_side_prices(quotes, "Up")
    dn_bid, _dn_ask = _h15_side_prices(quotes, "Down")
    bid_sum = None
    if up_bid is not None and dn_bid is not None:
        try:
            bid_sum = float(up_bid) + float(dn_bid)
        except (TypeError, ValueError):
            bid_sum = None
    patient = bid_sum is not None and bid_sum > H16_BID_SUM_PATIENT + 1e-9

    def _unhedged_ok(side: str, shares: float, est_usd: float) -> bool:
        if max_unhedged_usd <= 0:
            return True
        cur = inv.get(side) or {}
        new_sh = float(cur.get("shares", 0.0)) + shares
        new_cost = float(cur.get("cost", 0.0)) + est_usd
        opp = "Down" if side == "Up" else "Up"
        lead_after = new_sh - float((inv.get(opp) or {}).get("shares", 0.0))
        if lead_after > 0 and new_sh > 0:
            if (new_cost / new_sh) * lead_after > max_unhedged_usd:
                return False
        return True

    def _cap_maker(shares: float, role: str, side: str) -> float:
        try:
            dc = float(max_depth_shares or 0.0)
        except Exception:
            dc = 0.0
        if dc <= 0 or role != "MAKER":
            return shares
        avail = None
        if isinstance(resting_size, dict):
            avail = resting_size.get(side)
        try:
            avail = float(avail) if avail is not None else None
        except (TypeError, ValueError):
            avail = None
        if avail is None:
            return shares
        if avail <= 0:
            return 0.0
        return min(float(shares), float(avail))

    def _skip(reason: str, sub: str, preferred: str | None) -> MicrostructureDecision:
        return MicrostructureDecision(action="skip", outcome=preferred,
                                      reason=reason, sub_reason=sub)

    if in_sweep_phase:
        preferred = light if light is not None else "Up"
        return _skip("sweep-balanced", "sweep-balanced", preferred)

    # --- Rebalance mode: lighter side first, but expensive light legs go
    # small and maker-only instead of crossing the spread. ---
    if over and light is not None:
        want = min(float(default_clip), math.ceil(abs(lead) * H16_GAP_CLOSE_FRACTION))
        bid, ask = _h15_side_prices(quotes, light)
        spread = (ask - bid) if (ask is not None and bid is not None) else None
        tight = spread is not None and spread <= H16_TAKER_SPREAD_MAX + 1e-9
        # Maker-only when the light leg is expensive or the book shows no bid edge.
        maker_only = patient or (ask is not None and ask >= H16_EXPENSIVE)
        if bid is not None and (ask is None or not tight or maker_only):
            px, role = bid, "MAKER"
        elif ask is not None and not maker_only and tight:
            px, role = ask, "TAKER"
        elif bid is not None:
            px, role = bid, "MAKER"
        else:
            return _skip("no-liquidity", "no-liquidity", light)
        if px < min_fill:
            return _skip("dust-quote", "below-price-floor", light)
        if px > max_ceiling:
            return _skip("extreme-price-skip", "ceiling-price-skip", light)
        est_usd, _fee = compute_fill_usd(5.0, px, role=role,
                                         include_fee=(role == "TAKER"))
        proj_probe = _projected_pair_cost(inv, light, 5.0, est_usd)
        size = _h16_throttle_size(px, want, proj_probe)
        size = min(clip_shares(round(size, 1), max_clip), max_clip)
        if size <= 0:
            return _skip("no-liquidity", "no-liquidity", light)
        est_usd, _fee = compute_fill_usd(size, px, role=role,
                                         include_fee=(role == "TAKER"))
        if not _unhedged_ok(light, size, est_usd):
            return _skip("unhedged-cap-skip", "unhedged-cap", light)
        size = _cap_maker(size, role, light)
        if size <= 0:
            return _skip("no-liquidity", "depth-cap", light)
        proj = _projected_pair_cost(inv, light, size, est_usd)
        opp_sh = float((inv.get("Up" if light == "Down" else "Down") or {}).get("shares", 0.0))
        return MicrostructureDecision(
            action="fill", outcome=light, price=round(px, 4), shares=size,
            role=role, reason="balance-topup",
            sub_reason="rebalance-taker" if role == "TAKER" else "rebalance-maker",
            projected_pair_cost=proj,
            share_deficit=round(max(0.0, opp_sh - float((inv.get(light) or {}).get("shares", 0.0))), 2),
        )

    # --- Balanced mode: tilt cheap, throttle expensive, never gate. ---
    up_bid2, up_ask2 = _h15_side_prices(quotes, "Up")
    dn_bid2, dn_ask2 = _h15_side_prices(quotes, "Down")
    up_ref = up_bid2 if up_bid2 is not None else up_ask2
    dn_ref = dn_bid2 if dn_bid2 is not None else dn_ask2
    if up_ref is None and dn_ref is None:
        return _skip("no-liquidity", "no-liquidity", "Up" if fill_idx % 2 == 0 else "Down")
    if up_ref is None:
        sides = ["Down"]
    elif dn_ref is None:
        sides = ["Up"]
    elif up_ref < dn_ref:
        sides = ["Up", "Down"]
    elif dn_ref < up_ref:
        sides = ["Down", "Up"]
    else:
        sides = ["Up", "Down"] if fill_idx % 2 == 0 else ["Down", "Up"]
    preferred = sides[0]
    saw_dust = saw_ceiling = saw_unhedged = saw_depth = False
    for side in sides:
        bid, ask = _h15_side_prices(quotes, side)
        spread = (ask - bid) if (ask is not None and bid is not None) else None
        wide = spread is not None and spread > H16_TAKER_SPREAD_MAX + 1e-9
        maker_only_side = patient or (ask is not None and ask >= H16_EXPENSIVE) or \
            (bid is not None and bid >= H16_EXPENSIVE)
        attempts: list[tuple[str, float, float]] = []
        if ask is not None and not maker_only_side and (bid is None or wide):
            attempts.append(("TAKER", ask, min(H16_PROBE_SHARES, max_clip)))
        if bid is not None:
            attempts.append(("MAKER", bid, min(float(default_clip), max_clip)))
        for role, px, want in attempts:
            if px < min_fill:
                saw_dust = True
                continue
            if px > max_ceiling:
                saw_ceiling = True
                continue
            if role == "TAKER" and maker_only_side:
                continue
            probe_usd, _f = compute_fill_usd(5.0, px, role=role,
                                             include_fee=(role == "TAKER"))
            probe_proj = _projected_pair_cost(inv, side, 5.0, probe_usd)
            want_adj = _h16_throttle_size(px, want, probe_proj)
            size = min(clip_shares(round(want_adj, 1), max_clip), max_clip)
            if size <= 0:
                continue
            est_usd, _fee = compute_fill_usd(size, px, role=role,
                                             include_fee=(role == "TAKER"))
            if not _unhedged_ok(side, size, est_usd):
                saw_unhedged = True
                continue
            size = _cap_maker(size, role, side)
            if size <= 0:
                saw_depth = True
                continue
            proj = _projected_pair_cost(inv, side, size, est_usd)
            return MicrostructureDecision(
                action="fill", outcome=side, price=round(px, 4), shares=size,
                role=role, reason="clip-fill",
                sub_reason="balance-probe" if role == "TAKER" else "balance-maker",
                projected_pair_cost=proj,
                share_deficit=0.0,
            )
    if saw_ceiling:
        return _skip("extreme-price-skip", "ceiling-price-skip", preferred)
    if saw_dust:
        return _skip("dust-quote", "below-price-floor", preferred)
    if saw_unhedged:
        return _skip("unhedged-cap-skip", "unhedged-cap", preferred)
    if saw_depth:
        return _skip("no-liquidity", "depth-cap", preferred)
    return _skip("no-liquidity", "no-liquidity", preferred)


# ---------------------------------------------------------------------------
# Hydrogen v1.7: 2-level off-touch split ladder + ATM balanced band.
#
# Same two-sided accumulation grammar as v1.6, but the balanced book is only
# quoted when the market is a coin flip (bid inside 0.42..0.58) and it is
# quoted PURE MAKER: two rungs per side, one cent apart, splitting the clip
# (5 sh @ -1c and 5 sh @ -2c off the touch). Nothing crosses the spread in
# balanced mode. Rebalancing still closes the lighter side's gap, and both
# modes enforce a projected-pair ceiling, a share cap and a dollar cap on
# unhedged exposure.
# ---------------------------------------------------------------------------
H17_LEAD_TOLERANCE_MIN = 5.0
H17_LEAD_TOLERANCE_MAX = 12.0
H17_LEAD_FRACTION = 0.15
H17_ATM_MIN = 0.42
H17_ATM_MAX = 0.58
H17_EXPENSIVE = 0.65
H17_BID_SUM_PATIENT = 0.985
H17_PAIR_SOFT = 0.995          # balanced-mode projected-pair ceiling
H17_PAIR_FIRM = 0.990          # rebalance ceiling (stricter, per the setup entry)
H17_LADDER_LEVELS = 2
H17_LADDER_SPACING = 0.01      # -1c and -2c off the touch
H17_TAKER_SPREAD_MAX = 0.02
H17_GAP_CLOSE_FRACTION = 0.5

# Hydrogen v1.8 — 3-layer breakout defense layered onto v1.7 split ladder
H18_HEAVY_FLOOR_DIFF = 10.0     # Layer 1: block heavy balanced rungs when lead >= 10 sh
H18_HEAVY_FLOOR_BID = 0.45      # Layer 1: ...and that side's bid is below 45c
H18_BREAKOUT_MIN_LEAD = 5.0     # Layer 2/3: minimum deficit outside ATM band or for breakout taker
H18_BREAKOUT_ASK_MIN = 0.60     # Layer 3: breakout taker lower ask bound (beats 0.62 on replay)
H18_BREAKOUT_ASK_MAX = 0.68     # Layer 3: breakout taker upper ask bound

# Hydrogen v1.9 — 3-layer breakout defense with immediate deficit trigger (tol = 0.5 sh)
H19_LEAD_TOLERANCE = 0.5        # Layer 2/3 trigger: any lead > 0.5 sh
H19_L1_PROBE_SHARES = 5.0       # Layer 1: single 5-share probe
H19_L1_PRICE_MIN = 0.42         # Layer 1: lower entry price bound
H19_L1_PRICE_MAX = 0.49         # Layer 1: upper entry price bound
H19_L1_CUTOFF_SEC = 150.0       # Layer 1: freeze new leads after T+150s
H19_L1_CUTOFF_MATCHED = 40.0    # Layer 1: freeze new leads once >= 40.0 sh matched
H19_L2_PAIR_CAP = 0.990         # Layer 2: maximum hedge pair cost
H19_L3_PATIENCE_SEC = 20.0      # Layer 3: 20s delayed taker bailout (Arm B)
H19_L3_MARGINAL_MIN = 1.070     # Layer 3: minimum marginal pair cost to fire L3
H19_L3_ASK_MAX = 0.720          # Layer 3: upper ask bound for taker bailout


def _h17_tolerance(matched: float) -> float:
    """Dynamic lead tolerance: 15% of the matched book, clamped to 5..12 sh."""
    return min(H17_LEAD_TOLERANCE_MAX,
               max(H17_LEAD_TOLERANCE_MIN, H17_LEAD_FRACTION * matched))


def _h17_atm(bid: float | None) -> bool:
    """ATM balanced band: only coin-flip prices may be quoted."""
    return (bid is not None
            and H17_ATM_MIN - 1e-9 <= float(bid) <= H17_ATM_MAX + 1e-9)


def _evaluate_split_ladder(
    quotes: dict[str, dict[str, float | None]],
    inv: dict[str, dict[str, float]],
    fill_idx: int,
    default_clip: float,
    max_clip: float,
    min_fill: float,
    max_ceiling: float,
    max_unhedged_usd: float,
    max_unhedged_shares: float,
    in_sweep_phase: bool,
    max_depth_shares: float = 0.0,
    resting_size: dict | None = None,
    three_layer_defense: bool = False,
) -> MicrostructureDecision:
    """Hydrogen v1.7/v1.8 decision: ATM split ladder with optional 3-layer defense.

    When ``three_layer_defense=False`` (Hydrogen v1.7): ATM-only pure-maker
    2-rung split ladder (0.42..0.58), over-tolerance rebalance up to half the
    gap under ``H17_PAIR_FIRM`` (0.990).
    When ``three_layer_defense=True`` (Hydrogen v1.8): adds (L1) Heavy-Side
    Floor Gate (<0.45 when heavy lead >= 10 sh), (L2) unblocked passive
    rebalance-maker up to ``max_ceiling`` (0.85) whenever over tolerance OR
    outside ATM with >= 5 sh deficit, and (L3) emergency breakout taker
    (0.60..0.68 ask) when deficit >= 5 sh.
    """
    up_sh = float((inv.get("Up") or {}).get("shares", 0.0))
    dn_sh = float((inv.get("Down") or {}).get("shares", 0.0))
    matched = min(up_sh, dn_sh)
    lead = up_sh - dn_sh  # > 0 means Up heavy
    tol = _h17_tolerance(matched)
    over = abs(lead) > tol
    light = "Down" if lead > 0 else ("Up" if lead < 0 else None)
    up_bid, _up_ask = _h15_side_prices(quotes, "Up")
    dn_bid, _dn_ask = _h15_side_prices(quotes, "Down")
    bid_sum = None
    if up_bid is not None and dn_bid is not None:
        bid_sum = float(up_bid) + float(dn_bid)
    patient = bid_sum is not None and bid_sum > H17_BID_SUM_PATIENT + 1e-9

    def _unhedged_ok(side: str, shares: float, est_usd: float) -> bool:
        cur = inv.get(side) or {}
        new_sh = float(cur.get("shares", 0.0)) + shares
        opp = "Down" if side == "Up" else "Up"
        lead_after = new_sh - float((inv.get(opp) or {}).get("shares", 0.0))
        if lead_after <= 0 or new_sh <= 0:
            return True
        if max_unhedged_shares > 0 and lead_after > max_unhedged_shares + 1e-9:
            return False
        if max_unhedged_usd > 0:
            new_cost = float(cur.get("cost", 0.0)) + est_usd
            if (new_cost / new_sh) * lead_after > max_unhedged_usd:
                return False
        return True

    def _cap_maker(shares: float, role: str, side: str) -> float:
        try:
            dc = float(max_depth_shares or 0.0)
        except Exception:
            dc = 0.0
        if dc <= 0 or role != "MAKER":
            return shares
        avail = resting_size.get(side) if isinstance(resting_size, dict) else None
        try:
            avail = float(avail) if avail is not None else None
        except (TypeError, ValueError):
            avail = None
        if avail is None:
            return shares
        if avail <= 0:
            return 0.0
        return min(float(shares), float(avail))

    def _skip(reason: str, sub: str, preferred: str | None) -> MicrostructureDecision:
        return MicrostructureDecision(action="skip", outcome=preferred,
                                      reason=reason, sub_reason=sub)

    if in_sweep_phase:
        return _skip("sweep-balanced", "sweep-balanced",
                     light if light is not None else "Up")

    if three_layer_defense and light is not None:
        abs_lead = abs(lead)
        l_bid, l_ask = _h15_side_prices(quotes, light)
        outside_atm = (
            (up_bid is not None and not _h17_atm(up_bid))
            or (dn_bid is not None and not _h17_atm(dn_bid))
        )
        opp_sh = float((inv.get("Up" if light == "Down" else "Down") or {}).get("shares", 0.0))
        deficit = round(max(0.0, opp_sh - float((inv.get(light) or {}).get("shares", 0.0))), 2)

        # Layer 3: Emergency Breakout Equalizer Taker when deficit >= 5 sh and light ask hits 60-68c.
        if (
            abs_lead >= H18_BREAKOUT_MIN_LEAD - 1e-9
            and l_ask is not None
            and H18_BREAKOUT_ASK_MIN - 1e-9 <= l_ask <= H18_BREAKOUT_ASK_MAX + 1e-9
        ):
            if l_ask < min_fill:
                return _skip("dust-quote", "below-price-floor", light)
            if l_ask > max_ceiling:
                return _skip("extreme-price-skip", "ceiling-price-skip", light)
            take_size = min(clip_shares(round(min(float(max_clip), abs_lead), 1), max_clip), max_clip)
            if take_size > 0:
                est_usd, _fee = compute_fill_usd(take_size, l_ask, role="TAKER", include_fee=True)
                if not _unhedged_ok(light, take_size, est_usd):
                    return _skip("unhedged-cap-skip", "unhedged-cap", light)
                proj = _projected_pair_cost(inv, light, take_size, est_usd)
                return MicrostructureDecision(
                    action="fill", outcome=light, price=round(l_ask, 4),
                    shares=take_size, role="TAKER",
                    reason="balance-topup", sub_reason="rebalance-taker",
                    projected_pair_cost=proj, share_deficit=deficit,
                )

        # Layer 2: Unblocked passive rebalance-maker whenever over tolerance or outside ATM with >= 5 sh.
        over_inside = abs_lead >= tol - 1e-9
        rebal_outside = outside_atm and abs_lead >= H18_BREAKOUT_MIN_LEAD - 1e-9
        if over_inside or rebal_outside:
            want = min(float(max_clip), abs_lead)
            size = min(clip_shares(round(want, 1), max_clip), max_clip)
            if size <= 0 or l_bid is None:
                return _skip("no-liquidity", "no-liquidity", light)
            px = float(l_bid)
            if px < min_fill:
                return _skip("dust-quote", "below-price-floor", light)
            if px > max_ceiling:
                return _skip("extreme-price-skip", "ceiling-price-skip", light)
            est_usd, _fee = compute_fill_usd(size, px, role="MAKER", include_fee=False)
            proj = _projected_pair_cost(inv, light, size, est_usd)
            if not _unhedged_ok(light, size, est_usd):
                return _skip("unhedged-cap-skip", "unhedged-cap", light)
            # Split across 2 ladder rungs so total resting size matches min(max_clip, abs_lead).
            out_shares = round(max(1.0, size / H17_LADDER_LEVELS), 2)
            out_shares = _cap_maker(out_shares, "MAKER", light)
            if out_shares <= 0:
                return _skip("no-liquidity", "depth-cap", light)
            return MicrostructureDecision(
                action="fill", outcome=light, price=round(px, 4),
                shares=out_shares, role="MAKER",
                reason="balance-topup", sub_reason="rebalance-maker",
                projected_pair_cost=proj, share_deficit=deficit,
            )

    # --- v1.7 Rebalance mode: close at most half the gap, priced against a
    # stricter pair ceiling than the balanced ladder. ---
    elif over and light is not None:
        want = min(float(default_clip), math.ceil(abs(lead) * H17_GAP_CLOSE_FRACTION))
        size = min(clip_shares(round(want, 1), max_clip), max_clip)
        if size <= 0:
            return _skip("no-liquidity", "no-liquidity", light)
        bid, ask = _h15_side_prices(quotes, light)
        spread = (ask - bid) if (ask is not None and bid is not None) else None
        tight = spread is not None and spread <= H17_TAKER_SPREAD_MAX + 1e-9
        maker_only = patient or (ask is not None and ask >= H17_EXPENSIVE)
        if bid is not None and (ask is None or not tight or maker_only):
            px, role = bid, "MAKER"
        elif ask is not None and not maker_only and tight:
            px, role = ask, "TAKER"
        elif bid is not None:
            px, role = bid, "MAKER"
        else:
            return _skip("no-liquidity", "no-liquidity", light)
        if px < min_fill:
            return _skip("dust-quote", "below-price-floor", light)
        if px > max_ceiling:
            return _skip("extreme-price-skip", "ceiling-price-skip", light)
        est_usd, _fee = compute_fill_usd(size, px, role=role, include_fee=(role == "TAKER"))
        proj = _projected_pair_cost(inv, light, size, est_usd)
        if proj is not None and proj > H17_PAIR_FIRM + 1e-9:
            return _skip("pair-cost-skip", "pair-ceiling", light)
        if not _unhedged_ok(light, size, est_usd):
            return _skip("unhedged-cap-skip", "unhedged-cap", light)
        size = _cap_maker(size, role, light)
        if size <= 0:
            return _skip("no-liquidity", "depth-cap", light)
        opp_sh = float((inv.get("Up" if light == "Down" else "Down") or {}).get("shares", 0.0))
        return MicrostructureDecision(
            action="fill", outcome=light, price=round(px, 4), shares=size,
            role=role, reason="balance-topup",
            sub_reason="rebalance-taker" if role == "TAKER" else "rebalance-maker",
            projected_pair_cost=proj,
            share_deficit=round(max(0.0, opp_sh - float((inv.get(light) or {}).get("shares", 0.0))), 2),
        )

    # --- Balanced mode: pure maker ladder, ATM band only. ---
    up_ref = up_bid if up_bid is not None else _up_ask
    dn_ref = dn_bid if dn_bid is not None else _dn_ask
    if up_ref is None and dn_ref is None:
        return _skip("no-liquidity", "no-liquidity", "Up" if fill_idx % 2 == 0 else "Down")
    if up_ref is None:
        sides = ["Down"]
    elif dn_ref is None:
        sides = ["Up"]
    elif up_ref < dn_ref:
        sides = ["Up", "Down"]
    elif dn_ref < up_ref:
        sides = ["Down", "Up"]
    else:
        sides = ["Up", "Down"] if fill_idx % 2 == 0 else ["Down", "Up"]
    preferred = sides[0]
    saw_band = saw_dust = saw_ceiling = saw_unhedged = saw_depth = saw_pair = saw_heavy = False
    for side in sides:
        bid, _ask = _h15_side_prices(quotes, side)
        if not _h17_atm(bid):
            saw_band = True
            continue
        if three_layer_defense:
            opp = "Down" if side == "Up" else "Up"
            s_sh = float((inv.get(side) or {}).get("shares", 0.0))
            o_sh = float((inv.get(opp) or {}).get("shares", 0.0))
            if (s_sh - o_sh) >= H18_HEAVY_FLOOR_DIFF - 1e-9 and float(bid) < H18_HEAVY_FLOOR_BID - 1e-9:
                saw_heavy = True
                continue
        anchor = round(float(bid) - H17_LADDER_SPACING, 4)
        if anchor < min_fill:
            saw_dust = True
            continue
        if anchor > max_ceiling:
            saw_ceiling = True
            continue
        total = min(clip_shares(round(float(default_clip), 1), max_clip), max_clip)
        if total <= 0:
            continue
        per_level = round(total / H17_LADDER_LEVELS, 2)
        if per_level <= 0:
            continue
        # Cost the whole ladder (both rungs) for the pair gate; the lower rung
        # fills first only when price comes to it, so this is the conservative
        # reading.
        l2 = round(anchor - H17_LADDER_SPACING, 4)
        est_usd, _fee = compute_fill_usd(per_level, anchor, role="MAKER", include_fee=False)
        est_usd_l2, _fee = compute_fill_usd(per_level, l2, role="MAKER", include_fee=False)
        est_usd_total = est_usd + est_usd_l2
        proj = _projected_pair_cost(inv, side, per_level * H17_LADDER_LEVELS, est_usd_total)
        if proj is not None and proj > H17_PAIR_SOFT + 1e-9:
            saw_pair = True
            continue
        if not _unhedged_ok(side, per_level, est_usd):
            saw_unhedged = True
            continue
        size = _cap_maker(per_level, "MAKER", side)
        if size <= 0:
            saw_depth = True
            continue
        return MicrostructureDecision(
            action="fill", outcome=side, price=anchor, shares=size,
            role="MAKER", reason="clip-fill", sub_reason="split-ladder-maker",
            projected_pair_cost=proj, share_deficit=0.0,
        )
    if saw_pair:
        return _skip("pair-cost-skip", "pair-ceiling", preferred)
    if saw_ceiling:
        return _skip("extreme-price-skip", "ceiling-price-skip", preferred)
    if saw_dust:
        return _skip("dust-quote", "below-price-floor", preferred)
    if saw_unhedged:
        return _skip("unhedged-cap-skip", "unhedged-cap", preferred)
    if saw_depth:
        return _skip("no-liquidity", "depth-cap", preferred)
    if saw_heavy:
        return _skip("heavy-floor-skip", "heavy-floor-gate", preferred)
    if saw_band:
        return _skip("off-atm-skip", "atm-band", preferred)
    return _skip("no-liquidity", "no-liquidity", preferred)


def _evaluate_hydrogen_v19(
    quotes: dict[str, dict[str, float | None]],
    inv: dict[str, dict[str, float]],
    fill_idx: int,
    min_fill: float,
    max_ceiling: float,
    max_unhedged_usd: float,
    max_unhedged_shares: float,
    in_sweep_phase: bool,
    elapsed_sec: float,
    max_depth_shares: float = 0.0,
    resting_size: dict | None = None,
    open_orders: dict | None = None,
    deficit_duration_sec: float = 0.0,
    window_bailout_latched: bool = False,
    candidate_arm: str = "B",
    max_pair_cost: float = H19_L2_PAIR_CAP,
) -> MicrostructureDecision:
    """Hydrogen v1.9 microstructure decision engine.

    Layer 1 (Flat, abs(lead) <= 0.5 sh): Single 5-share maker probe in 42-49c ATM band.
        Frozen once elapsed_sec >= 150.0 OR matched >= 40.0 OR window_bailout_latched.
    Layer 2 (Over, abs(lead) > 0.5 sh): Immediate sub-par clamped maker hedge
        at px = min(light_bid, floor(0.990 - heavy_avg)). Heavy resting orders cancelled.
    Layer 3 (Over, abs(lead) > 0.5 sh): Taker bailout.
        Arm A: Immediate on deficit if ask <= 0.72 & marginal >= 1.00.
        Arm B (v1.9 core): 20s delayed after deficit opens, marginal >= 1.07 & ask <= 0.72.
        Arm E: Pure maker (Layer 3 disabled).
    """
    up_sh = float((inv.get("Up") or {}).get("shares", 0.0))
    dn_sh = float((inv.get("Down") or {}).get("shares", 0.0))
    matched = min(up_sh, dn_sh)
    lead = up_sh - dn_sh
    abs_lead = abs(lead)
    over = abs_lead > H19_LEAD_TOLERANCE
    heavy = "Up" if lead > 0 else "Down"
    light = "Down" if lead > 0 else ("Up" if lead < 0 else None)
    deficit = round(abs_lead, 2)

    def _skip(reason: str, sub: str, pref: str | None) -> MicrostructureDecision:
        return MicrostructureDecision(action="skip", outcome=pref, reason=reason, sub_reason=sub)

    def _unhedged_ok(side: str, shares: float, est_usd: float) -> bool:
        cur = inv.get(side) or {}
        new_sh = float(cur.get("shares", 0.0)) + shares
        opp = "Down" if side == "Up" else "Up"
        lead_after = new_sh - float((inv.get(opp) or {}).get("shares", 0.0))
        if lead_after <= 0 or new_sh <= 0:
            return True
        if max_unhedged_shares > 0 and lead_after > max_unhedged_shares + 1e-9:
            return False
        if max_unhedged_usd > 0:
            new_cost = float(cur.get("cost", 0.0)) + est_usd
            if (new_cost / new_sh) * lead_after > max_unhedged_usd:
                return False
        return True

    def _cap_m(shares: float, role: str, side: str) -> float:
        try:
            dc = float(max_depth_shares or 0.0)
        except Exception:
            dc = 0.0
        if dc <= 0 or role != "MAKER":
            return shares
        avail = resting_size.get(side) if isinstance(resting_size, dict) else None
        try:
            avail = float(avail) if avail is not None else None
        except (TypeError, ValueError):
            avail = None
        if avail is None:
            return shares
        if avail <= 0:
            return 0.0
        return min(float(shares), float(avail))

    if in_sweep_phase:
        return _skip("sweep-balanced", "sweep-balanced", light if light is not None else "Up")

    # Check Layer 1 freeze
    l1_frozen = (elapsed_sec >= H19_L1_CUTOFF_SEC) or (matched >= H19_L1_CUTOFF_MATCHED) or window_bailout_latched

    up_bid, up_ask = _h15_side_prices(quotes, "Up")
    dn_bid, dn_ask = _h15_side_prices(quotes, "Down")

    # --- OVER CONDITION: Layer 2 / Layer 3 ---
    if over and light is not None:
        heavy_inv = inv.get(heavy) or {}
        heavy_cost = float(heavy_inv.get("cost", 0.0))
        heavy_shares = float(heavy_inv.get("shares", 0.0))
        heavy_avg = heavy_cost / max(heavy_shares, 1e-6)
        l_bid, l_ask = _h15_side_prices(quotes, light)

        # Layer 3: Taker Equalizer
        taker_fire = False
        if candidate_arm == "A":
            if l_ask is not None and l_ask <= H19_L3_ASK_MAX and (heavy_avg + l_ask >= 1.000):
                taker_fire = True
        elif candidate_arm == "B":
            if (deficit_duration_sec >= H19_L3_PATIENCE_SEC and
                    l_ask is not None and l_ask <= H19_L3_ASK_MAX and
                    (heavy_avg + l_ask >= H19_L3_MARGINAL_MIN)):
                taker_fire = True

        if taker_fire and l_ask is not None:
            if l_ask < min_fill:
                return _skip("dust-quote", "below-price-floor", light)
            if l_ask > max_ceiling:
                return _skip("extreme-price-skip", "ceiling-price-skip", light)
            take_size = min(deficit, 10.0)
            est_usd, _ = compute_fill_usd(take_size, l_ask, role="TAKER", include_fee=True)
            if not _unhedged_ok(light, take_size, est_usd):
                return _skip("unhedged-cap-skip", "unhedged-cap", light)
            proj = _projected_pair_cost(inv, light, take_size, est_usd)
            return MicrostructureDecision(
                action="fill", outcome=light, price=round(l_ask, 4),
                shares=take_size, role="TAKER",
                reason="balance-topup", sub_reason="rebalance-taker",
                projected_pair_cost=proj, share_deficit=deficit,
            )

        # Layer 2: Clamped Maker Rebalance (<= min(configured cap, 0.990))
        max_hedge_px = math.floor((min(H19_L2_PAIR_CAP, max_pair_cost) - heavy_avg + 1e-9) * 100.0) / 100.0
        if l_bid is None:
            return _skip("no-liquidity", "no-liquidity", light)
        px = min(float(l_bid), max_hedge_px)
        if px < min_fill:
            return _skip("dust-quote", "below-price-floor", light)
        if px > max_ceiling:
            return _skip("extreme-price-skip", "ceiling-price-skip", light)
        size = round(deficit, 2)
        size = _cap_m(size, "MAKER", light)
        if size <= 0:
            return _skip("no-liquidity", "depth-cap", light)
        est_usd, _ = compute_fill_usd(size, px, role="MAKER", include_fee=False)
        if not _unhedged_ok(light, size, est_usd):
            return _skip("unhedged-cap-skip", "unhedged-cap", light)
        proj = _projected_pair_cost(inv, light, size, est_usd)
        return MicrostructureDecision(
            action="fill", outcome=light, price=round(px, 4),
            shares=size, role="MAKER",
            reason="hedge-leg", sub_reason="rebalance-maker",
            projected_pair_cost=proj, share_deficit=deficit,
        )

    # --- BALANCED CONDITION: Layer 1 ---
    if l1_frozen:
        return _skip("window-frozen", "cutoff-reached", "Up" if fill_idx % 2 == 0 else "Down")

    if candidate_arm == "E":
        # Two-Sided Simultaneous Resting within [0.42, 0.48].
        # A side rests only when its own bid implies a price inside the band;
        # clamping an out-of-band bid up to 0.42 could cross the ask.
        if up_bid is not None and dn_bid is not None:
            up_in_band = 0.42 <= round(up_bid - 0.01, 2) <= 0.48
            dn_in_band = 0.42 <= round(dn_bid - 0.01, 2) <= 0.48
            up_base = min(max(round(up_bid - 0.01, 2), 0.42), 0.48)
            dn_max = math.floor((0.990 - up_base + 1e-9) * 100.0) / 100.0
            dn_base = min(max(round(dn_bid - 0.01, 2), 0.42), min(0.48, dn_max))
            up_max = math.floor((0.990 - dn_base + 1e-9) * 100.0) / 100.0
            up_base = min(up_base, min(0.48, up_max))

            has_up = bool(open_orders and "Up" in open_orders)
            has_dn = bool(open_orders and "Down" in open_orders)
            if up_in_band and not has_up:
                return MicrostructureDecision(
                    action="fill", outcome="Up", price=up_base, shares=5.0,
                    role="MAKER", reason="straddle-open", sub_reason="balance-maker",
                    projected_pair_cost=None, share_deficit=0.0,
                )
            elif dn_in_band and not has_dn:
                return MicrostructureDecision(
                    action="fill", outcome="Down", price=dn_base, shares=5.0,
                    role="MAKER", reason="straddle-open", sub_reason="balance-maker",
                    projected_pair_cost=None, share_deficit=0.0,
                )

    # Standard single probe: 5 sh within [0.42, 0.49]
    up_px = round(up_bid - 0.01, 2) if up_bid is not None else None
    dn_px = round(dn_bid - 0.01, 2) if dn_bid is not None else None
    up_ok = (up_px is not None) and (H19_L1_PRICE_MIN <= up_px <= H19_L1_PRICE_MAX)
    dn_ok = (dn_px is not None) and (H19_L1_PRICE_MIN <= dn_px <= H19_L1_PRICE_MAX)

    if not up_ok and not dn_ok:
        return _skip("off-atm-skip", "atm-band", "Up" if fill_idx % 2 == 0 else "Down")

    if up_ok and dn_ok:
        if up_px + dn_px <= 0.970:
            pick = "Up" if fill_idx % 2 == 0 else "Down"
        elif up_px <= dn_px:
            pick = "Up"
        else:
            pick = "Down"
    elif up_ok:
        pick = "Up"
    else:
        pick = "Down"

    target_px = up_px if pick == "Up" else dn_px
    size = 5.0
    size = _cap_m(size, "MAKER", pick)
    if size <= 0:
        return _skip("no-liquidity", "depth-cap", pick)
    est_usd, _ = compute_fill_usd(size, target_px, role="MAKER", include_fee=False)
    if not _unhedged_ok(pick, size, est_usd):
        return _skip("unhedged-cap-skip", "unhedged-cap", pick)
    return MicrostructureDecision(
        action="fill", outcome=pick, price=round(target_px, 4),
        shares=size, role="MAKER",
        reason="straddle-open", sub_reason="balance-maker",
        projected_pair_cost=None, share_deficit=0.0,
    )


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


H20_LEAD_TOLERANCE = 0.5
H20_DIP_TOUCH_MAX = 0.45
H20_ATM_MAX_BID = 0.58


def v20_max_hedge_price(
    inv: dict[str, dict[str, float]],
    heavy: str,
    light: str,
    cap: float,
) -> float:
    """Strict maker hedge ceiling keeping both cumulative & marginal pair cost <= cap."""
    heavy_sh = float((inv.get(heavy) or {}).get("shares", 0.0))
    heavy_cost = float((inv.get(heavy) or {}).get("cost", 0.0))
    light_sh = float((inv.get(light) or {}).get("shares", 0.0))
    light_cost = float((inv.get(light) or {}).get("cost", 0.0))
    deficit = heavy_sh - light_sh
    if heavy_sh <= 0.0 or deficit <= 0.0:
        return 0.0
    heavy_avg = heavy_cost / heavy_sh
    portfolio_cap = (cap * heavy_sh - heavy_cost - light_cost) / deficit
    marginal_cap = cap - heavy_avg
    return math.floor((min(portfolio_cap, marginal_cap) + 1e-9) * 100.0) / 100.0


def _evaluate_hydrogen_v20(
    quotes: dict[str, dict[str, float | None]],
    inv: dict[str, dict[str, float]],
    min_fill: float = 0.07,
    max_fill: float = 0.47,
    default_clip: float = 10.0,
    max_clip: float = 45.0,
    dip_curve: dict | None = None,
    target_pair_cost: float = 0.965,
    max_pair_cost: float = 0.985,
    rescue_max_pair_cost: float = 0.995,
    rescue_ceiling: float = 0.985,
    max_unhedged_usd: float = 6.0,
    max_unhedged_shares: float = 0.0,
    include_taker_fee: bool = True,
    in_sweep_phase: bool = False,
    open_orders: dict | None = None,
) -> MicrostructureDecision:
    """Hydrogen v2.0 decision engine.

    Balanced (abs(lead) <= 0.5 sh, outside sweep):
      - Simultaneous two-sided maker resting across Up and Down.
      - Deep dips (bid <= 45c) rest at best bid with inverse-dip curve sizing.
      - Balanced ATM odds (45c < bid <= 58c) rest off-touch at min(bid - 1c, max_fill).
      - Unhedged exposure strictly capped by max_unhedged_usd (default $6.00).
      - Mutual target_pair_cost gate (<= $0.965); clean holding-resting skip when
        both eligible sides are already resting (no single-probe fallthrough).

    Imbalanced (abs(lead) > 0.5 sh):
      - Heavy-side resting orders are cancelled in live_paper/replay.
      - Profit-lock / sweep taker crosses only if fee-inclusive projected pair cost
        stays <= target_pair_cost ($0.965 normally, $0.995 in sweep) and <= rescue_ceiling.
      - Otherwise rests clamped maker hedge at min(light_bid, _v20_max_hedge_price(cap)).
      - Never pays >= $1.00 pair cost and never triggers single-window freeze latch.
    """
    up_sh = float((inv.get("Up") or {}).get("shares", 0.0))
    dn_sh = float((inv.get("Down") or {}).get("shares", 0.0))
    lead = up_sh - dn_sh
    abs_lead = abs(lead)
    oo = open_orders or {}

    if abs_lead > H20_LEAD_TOLERANCE:
        heavy = "Up" if lead > 0 else "Down"
        light = "Down" if lead > 0 else "Up"
        deficit = round(abs_lead, 4)
        light_bid, light_ask = _h15_side_prices(quotes, light)

        taker_cap = float(rescue_max_pair_cost if in_sweep_phase else target_pair_cost)
        if (
            light_ask is not None
            and min_fill - 1e-9 <= float(light_ask) <= float(rescue_ceiling) + 1e-9
        ):
            taker_usd, _ = compute_fill_usd(
                deficit, float(light_ask), role="TAKER", include_fee=include_taker_fee,
            )
            proj_taker = _projected_pair_cost(inv, light, deficit, taker_usd)
            heavy_avg = (inv[heavy]["cost"] / inv[heavy]["shares"]) if inv[heavy]["shares"] > 0 else 0.0
            marginal_taker = heavy_avg + (taker_usd / deficit)
            if (
                proj_taker is not None
                and proj_taker <= taker_cap + 1e-9
                and marginal_taker <= taker_cap + 1e-9
                and proj_taker < 1.0 - 1e-9
            ):
                return MicrostructureDecision(
                    action="taker",
                    outcome=light,
                    price=round(float(light_ask), 4),
                    shares=deficit,
                    role="TAKER",
                    reason="sweep-taker" if in_sweep_phase else "balance-topup",
                    sub_reason="rebalance-taker",
                    projected_pair_cost=proj_taker,
                    share_deficit=deficit,
                )

        maker_cap = float(rescue_max_pair_cost if in_sweep_phase else max_pair_cost)
        max_hedge_px = min(float(rescue_ceiling), v20_max_hedge_price(inv, heavy, light, maker_cap))
        if light_bid is None or float(light_bid) < min_fill - 1e-9 or max_hedge_px < min_fill - 1e-9:
            return MicrostructureDecision(
                action="skip",
                outcome=light,
                price=None,
                shares=0.0,
                role="MAKER",
                reason="sweep-cap" if in_sweep_phase else "pair-cost-cap",
                sub_reason="rebalance-cap",
                projected_pair_cost=None,
                share_deficit=deficit,
            )

        px = round(min(float(light_bid), max_hedge_px), 2)
        if px < min_fill - 1e-9 or px > max_hedge_px + 1e-9:
            return MicrostructureDecision(
                action="skip",
                outcome=light,
                price=None,
                shares=0.0,
                role="MAKER",
                reason="pair-cost-cap",
                sub_reason="rebalance-cap",
                projected_pair_cost=None,
                share_deficit=deficit,
            )
        maker_usd, _ = compute_fill_usd(deficit, px, role="MAKER", include_fee=include_taker_fee)
        return MicrostructureDecision(
            action="maker",
            outcome=light,
            price=px,
            shares=deficit,
            role="MAKER",
            reason="sweep" if in_sweep_phase else "hedge-leg",
            sub_reason="rebalance-maker",
            projected_pair_cost=_projected_pair_cost(inv, light, deficit, maker_usd),
            share_deficit=deficit,
        )

    if in_sweep_phase:
        return MicrostructureDecision(
            action="skip",
            outcome=None,
            price=None,
            shares=0.0,
            role="MAKER",
            reason="sweep-idle",
            sub_reason="balanced",
            projected_pair_cost=None,
            share_deficit=0.0,
        )

    def _raw_target_px(bid: float | None) -> float | None:
        if bid is None or bid < min_fill - 1e-9 or bid > H20_ATM_MAX_BID + 1e-9:
            return None
        if bid <= H20_DIP_TOUCH_MAX + 1e-9:
            px = round(float(bid), 2)
        else:
            px = min(round(float(bid) - 0.01, 2), round(float(max_fill), 2))
        if px < min_fill - 1e-9 or px > max_fill + 1e-9:
            return None
        return px

    raw_px: dict[str, float | None] = {}
    side_bids: dict[str, float | None] = {}
    for side in ("Up", "Down"):
        bid, _ = _h15_side_prices(quotes, side)
        side_bids[side] = bid
        raw_px[side] = _raw_target_px(bid)

    # Ensure two-sided resting quotes sum <= target_pair_cost when both sides quote together
    for side in ("Up", "Down"):
        if raw_px[side] is None:
            continue
        opp = "Down" if side == "Up" else "Up"
        opp_oo = oo.get(opp)
        if opp_oo is not None:
            opp_px = float(opp_oo.get("price", 0.0) or 0.0)
            mutual_cap = math.floor((target_pair_cost - opp_px + 1e-9) * 100.0) / 100.0
            if raw_px[side] > mutual_cap + 1e-9:
                raw_px[side] = mutual_cap if mutual_cap >= min_fill - 1e-9 else None
    if raw_px["Up"] is not None and raw_px["Down"] is not None:
        if raw_px["Up"] + raw_px["Down"] > target_pair_cost + 1e-9:
            half_cap = math.floor((target_pair_cost / 2.0 + 1e-9) * 100.0) / 100.0
            for side in ("Up", "Down"):
                if raw_px[side] is not None and raw_px[side] > half_cap + 1e-9:
                    raw_px[side] = half_cap if half_cap >= min_fill - 1e-9 else None

    candidates: list[dict] = []
    for side in ("Up", "Down"):
        px = raw_px[side]
        if px is None:
            continue
        opp = "Down" if side == "Up" else "Up"
        # When opposite side is >58c (not two-sided ATM), only take genuine dips <=45c
        if raw_px[opp] is None and oo.get(opp) is None and px > H20_DIP_TOUCH_MAX + 1e-9:
            continue

        raw_sh = (
            dip_curve_shares(dip_curve, px, max_clip)
            if isinstance(dip_curve, dict)
            else float(default_clip)
        )
        if raw_sh is None:
            raw_sh = float(default_clip)
        shares = clip_shares(float(raw_sh), max_clip)

        side_sh = float((inv.get(side) or {}).get("shares", 0.0))
        side_cost = float((inv.get(side) or {}).get("cost", 0.0))
        opp_sh = float((inv.get(opp) or {}).get("shares", 0.0))
        opp_cost = float((inv.get(opp) or {}).get("cost", 0.0))

        if max_unhedged_usd > 0.0:
            new_sh = side_sh + shares
            new_cost = side_cost + shares * px
            lead_after = max(0.0, new_sh - opp_sh)
            unhedged_after = (new_cost / new_sh) * lead_after if new_sh > 0 else 0.0
            if unhedged_after > max_unhedged_usd + 1e-9:
                if side_sh <= opp_sh + 1e-9:
                    avail_lead = max(0.0, max_unhedged_usd / max(px, 1e-6))
                    allowed = math.floor((avail_lead + max(0.0, opp_sh - side_sh) + 1e-9) * 10.0) / 10.0
                else:
                    cur_avg = side_cost / side_sh
                    rem_usd = max(0.0, max_unhedged_usd - cur_avg * (side_sh - opp_sh))
                    allowed = math.floor((rem_usd / max(px, 1e-6) + 1e-9) * 10.0) / 10.0
                shares = min(shares, allowed)
                if shares < 1.0 - 1e-9:
                    continue

        if max_unhedged_shares > 0.0:
            new_sh = side_sh + shares
            lead_after = max(0.0, new_sh - opp_sh)
            if lead_after > max_unhedged_shares + 1e-9:
                allowed = math.floor((max_unhedged_shares + opp_sh - side_sh + 1e-9) * 10.0) / 10.0
                shares = min(shares, max(0.0, allowed))
                if shares < 1.0 - 1e-9:
                    continue

        # Verify enough hedge headroom remains under max_pair_cost
        new_sh = side_sh + shares
        new_cost = side_cost + shares * px
        need_opp = max(0.0, new_sh - opp_sh)
        if need_opp > 0.0:
            rem_budget = max_pair_cost * new_sh - new_cost - opp_cost
            if (rem_budget / need_opp) < min_fill - 1e-9:
                continue

        candidates.append({
            "side": side,
            "px": round(px, 2),
            "shares": round(shares, 2),
            "proj": _projected_pair_cost(inv, side, shares, shares * px),
        })

    # Cheaper side first (Up ties first)
    candidates.sort(key=lambda c: (c["px"], 0 if c["side"] == "Up" else 1))

    for cand in candidates:
        side = cand["side"]
        cur = oo.get(side)
        if cur is None:
            return MicrostructureDecision(
                action="maker",
                outcome=side,
                price=cand["px"],
                shares=cand["shares"],
                role="MAKER",
                reason="balanced-open",
                sub_reason="two-sided-maker",
                projected_pair_cost=cand["proj"],
                share_deficit=0.0,
            )
        cur_px = float(cur.get("price", 0.0) or 0.0)
        cur_sh = float(cur.get("shares_left", 0.0) or 0.0)
        # Reprice upward inside band, or resize at exact same price; never starve the other side
        if cand["px"] > cur_px + 1e-9 or (
            abs(cand["px"] - cur_px) < 1e-9 and abs(cand["shares"] - cur_sh) > 0.5
        ):
            return MicrostructureDecision(
                action="maker",
                outcome=side,
                price=cand["px"],
                shares=cand["shares"],
                role="MAKER",
                reason="balanced-open",
                sub_reason="two-sided-maker",
                projected_pair_cost=cand["proj"],
                share_deficit=0.0,
            )

    if any(s in oo for s in ("Up", "Down")):
        return MicrostructureDecision(
            action="skip",
            outcome=None,
            price=None,
            shares=0.0,
            role="MAKER",
            reason="holding-resting",
            sub_reason="both-sides-resting" if ("Up" in oo and "Down" in oo) else "one-side-resting",
            projected_pair_cost=None,
            share_deficit=0.0,
        )

    return MicrostructureDecision(
        action="skip",
        outcome=None,
        price=None,
        shares=0.0,
        role="MAKER",
        reason="price-band-skip",
        sub_reason="balanced-out-of-band",
        projected_pair_cost=None,
        share_deficit=0.0,
    )


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
    max_unhedged_usd: float = 0.0,
    max_unhedged_shares: float = 0.0,
    dip_curve: dict | None = None,
    target_pair_cost: float | None = None,
    in_sweep_phase: bool = False,
    rescue_max_pair_cost: float = C.RESCUE_PAIR_COST_MAX,
    rescue_ceiling: float = C.RESCUE_CEILING_PRICE,
    max_depth_shares: float = 0.0,
    resting_size: float | dict | None = None,
    leg1_max_price: float | None = None,
    leg2_max_price: float | None = None,
    taker_dip_max: float | None = None,
    taker_dip_balanced_only: bool = False,
    taker_hedge_max_pair_cost: float | None = None,
    hedge_max_clip: float | None = None,
    late_rescue_start_sec: float | None = None,
    late_rescue_max_pair_cost: float | None = None,
    elapsed_sec: float | None = None,
    unhedged_step_cents: float | None = None,
    unhedged_probe_shares: float | None = None,
    open_orders: dict | None = None,
    clip_schedule: list | None = None,
    **kwargs,
) -> MicrostructureDecision:
    """Decision Engine for Hybrid Arbitrage Pairing & Certainty Sniping.

    Supports both setups:
    - 'hapcs-v1': Aggressive dual-regime with M4 certainty sniping up to 97.5¢ and 12s cutoff.
    - 'dangerously-skip-permissions': Reconstructed from wallet 0xc533…69a9 ($1.42M vol/wk).
      Focuses on deep dips [7¢–45¢], 75s early cutoff, dollar-capped unhedged
      risk (no share veto), and Tiered Rescue Pairing up to $1.025 so 80¢–92¢ deficit-closing hedges
      are executed rather than left unhedged to face 100% loss at resolution.
    """
    bench_pc = target_pair_cost if target_pair_cost is not None else benchmark_pair_cost
    try:
        _depth_cap = float(max_depth_shares or 0.0)
    except Exception:
        _depth_cap = 0.0
    def _resting_for(side: str) -> float | None:
        rs = resting_size
        if rs is None:
            rs = kwargs.get('resting_sizes')
        if isinstance(rs, dict):
            v = rs.get(side)
            try:
                return float(v) if v is not None else None
            except Exception:
                return None
        try:
            return float(rs) if rs is not None else None
        except Exception:
            return None
    def _cap_for_maker(shares: float, role: str, side: str) -> float:
        if _depth_cap <= 0 or role != 'MAKER':
            return shares
        avail = _resting_for(side)
        if avail is None:
            return shares
        if avail <= 0:
            return 0.0
        return min(float(shares), float(avail))

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
    saw_depth_cap = False
    saw_unhedged_cap = False
    saw_unhedged_step = False

    def _lowest_held_price(side_key: str) -> float | None:
        s = inv.get(side_key) or {}
        if s.get("shares", 0.0) <= 0:
            return None
        for k in ("lowest_price", "min_price", "lowest_fill_price", "min_fill_price"):
            val = s.get(k)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
        sh = s.get("shares", 0.0)
        c = s.get("cost", 0.0)
        if sh > 0 and c > 0:
            return float(c / sh)
        return None
    # DSP family (v2.0, v2.1, v2.2, ...) shares the same recovery-engine rules.
    is_dsp = strategy_id.startswith("dangerously-skip-permissions")
    is_v22 = strategy_id.endswith("v2.2")
    is_v23 = strategy_id.endswith("v2.3")
    is_confidence = is_v22 or is_v23
    # No share-denominated veto: unhedged inventory is NOT capped by share
    # count. The measured wallet holds triple-digit residuals, so a share
    # veto only suppresses fills without buying safety. Unhedged risk is
    # governed by the dollar cap (max_unhedged_usd) instead.

    # --- v2.7 knob resolution (all optional; absent = pre-v2.7 behavior) ---
    def _fnum(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None
    _leg1 = _fnum(leg1_max_price)
    if _leg1 is None:
        _leg1 = _fnum(kwargs.get("maxLeg1Price", kwargs.get("leg1MaxPrice")))
    leg1_cap = _leg1 if _leg1 is not None else max_fill
    _leg2 = _fnum(leg2_max_price)
    if _leg2 is None:
        _leg2 = _fnum(kwargs.get("leg2MaxPrice"))
    _taker_dip = _fnum(taker_dip_max)
    if _taker_dip is None:
        _taker_dip = _fnum(kwargs.get("takerDipEntryMax", kwargs.get("takerDipMax")))
    _td_balanced_only = bool(taker_dip_balanced_only) or bool(
        kwargs.get("takerDipBalancedOnly", kwargs.get("taker_dip_balanced_only", False)))
    _th_cap = _fnum(taker_hedge_max_pair_cost)
    if _th_cap is None:
        _th_cap = _fnum(kwargs.get("takerHedgeMaxPairCost", kwargs.get("takerHedgeMaxPair")))
    _h_clip = _fnum(hedge_max_clip)
    if _h_clip is None:
        _h_clip = _fnum(kwargs.get("hedgeMaxClip", kwargs.get("takerHedgeMaxClip")))
    _late_start = _fnum(late_rescue_start_sec)
    if _late_start is None:
        _late_start = _fnum(kwargs.get("lateRescueStartSec"))
    _late_max = _fnum(late_rescue_max_pair_cost)
    if _late_max is None:
        _late_max = _fnum(kwargs.get("lateRescueMaxPairCost"))
    _elapsed = _fnum(elapsed_sec)
    if _elapsed is None:
        _elapsed = _fnum(kwargs.get("elapsedSec"))
    _step_cents = _fnum(unhedged_step_cents)
    if _step_cents is None:
        _step_cents = _fnum(kwargs.get("unhedgedStepCents", kwargs.get("unhedged_step_cents")))
    _probe_sh = _fnum(unhedged_probe_shares)
    if _probe_sh is None:
        _probe_sh = _fnum(kwargs.get("unhedgedProbeShares", kwargs.get("unhedged_probe_shares")))
    # Wallet-measured clip schedule: the researched account opens windows
    # with ~30-share clips and decays to ~15 after T+120s. A schedule is an
    # explicit [[elapsedSec, clipShares], ...] ladder, linearly interpolated
    # and clamped at both ends; absent/empty means a flat default clip.
    _sched = clip_schedule
    if _sched is None:
        _sched = kwargs.get("clipSchedule", kwargs.get("clip_schedule"))
    if _sched:
        try:
            pts = sorted((float(a), float(b)) for a, b in _sched)
            t = _elapsed if _elapsed is not None else 0.0
            if t <= pts[0][0]:
                default_clip = float(pts[0][1])
            elif t >= pts[-1][0]:
                default_clip = float(pts[-1][1])
            else:
                for (t0, c0), (t1, c1) in zip(pts, pts[1:]):
                    if t0 <= t <= t1:
                        frac = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
                        default_clip = c0 + (c1 - c0) * frac
                        break
        except (TypeError, ValueError):
            pass
    has_late = _late_start is not None
    in_late = bool(has_late and _elapsed is not None and _elapsed >= _late_start)
    late_cap = _late_max if (has_late and _late_max is not None) else rescue_max_pair_cost

    # Hydrogen v1.5: concurrent two-sided accumulation. This path replaces
    # the dip grid, deficit ladder and rescue sections below entirely: no
    # dip band, no deficit chase, no pair-cost gate. The balancing ceiling
    # is max_fill (0.85 in the v1.5 preset); pair cost is computed for the
    # record and reported against the wallet benchmark, never enforced.
    if strategy_id == "hydrogen-v1.5":
        try:
            _v15_depth = float(max_depth_shares or 0.0)
        except Exception:
            _v15_depth = 0.0
        return _evaluate_concurrent_accumulation(
            quotes=quotes, inv=inv, fill_idx=fill_idx,
            default_clip=default_clip, max_clip=max_clip,
            min_fill=min_fill, max_ceiling=max_fill,
            max_unhedged_usd=max_unhedged_usd,
            in_sweep_phase=in_sweep_phase,
            max_depth_shares=_v15_depth,
            resting_size=resting_size,
        )

    if strategy_id == "hydrogen-v1.6":
        try:
            _v16_depth = float(max_depth_shares or 0.0)
        except Exception:
            _v16_depth = 0.0
        return _evaluate_edge_accumulation(
            quotes=quotes, inv=inv, fill_idx=fill_idx,
            default_clip=default_clip, max_clip=max_clip,
            min_fill=min_fill, max_ceiling=max_fill,
            max_unhedged_usd=max_unhedged_usd,
            in_sweep_phase=in_sweep_phase,
            max_depth_shares=_v16_depth,
            resting_size=resting_size,
        )

    if strategy_id == "hydrogen-v2.0":
        return _evaluate_hydrogen_v20(
            quotes=quotes,
            inv=inv,
            min_fill=min_fill,
            max_fill=max_fill,
            default_clip=default_clip,
            max_clip=max_clip,
            dip_curve=dip_curve,
            target_pair_cost=float(target_pair_cost if target_pair_cost is not None else 0.965),
            max_pair_cost=float(max_pair_cost),
            rescue_max_pair_cost=float(rescue_max_pair_cost),
            rescue_ceiling=float(rescue_ceiling),
            max_unhedged_usd=float(max_unhedged_usd),
            max_unhedged_shares=float(max_unhedged_shares),
            include_taker_fee=bool(kwargs.get("include_taker_fee", True)),
            in_sweep_phase=in_sweep_phase,
            open_orders=open_orders,
        )

    if strategy_id in ("hydrogen-v1.9", "hydrogen-v1.9-arm-a", "hydrogen-v1.9-arm-b", "hydrogen-v1.9-arm-e"):
        try:
            _v19_depth = float(max_depth_shares or 0.0)
        except Exception:
            _v19_depth = 0.0
        arm_type = "B"
        if "arm-a" in strategy_id:
            arm_type = "A"
        elif "arm-e" in strategy_id:
            arm_type = "E"
        return _evaluate_hydrogen_v19(
            quotes=quotes, inv=inv, fill_idx=fill_idx,
            min_fill=min_fill, max_ceiling=max_fill,
            max_unhedged_usd=max_unhedged_usd,
            max_unhedged_shares=max_unhedged_shares,
            in_sweep_phase=in_sweep_phase,
            elapsed_sec=_elapsed or 0.0,
            max_depth_shares=_v19_depth,
            resting_size=resting_size,
            open_orders=open_orders,
            deficit_duration_sec=float(kwargs.get("deficit_duration_sec", 0.0) or 0.0),
            window_bailout_latched=bool(kwargs.get("window_bailout_latched", False)),
            candidate_arm=arm_type,
            max_pair_cost=max_pair_cost,
        )

    if strategy_id in ("hydrogen-v1.7", "hydrogen-v1.8"):
        try:
            _v17_depth = float(max_depth_shares or 0.0)
        except Exception:
            _v17_depth = 0.0
        return _evaluate_split_ladder(
            quotes=quotes, inv=inv, fill_idx=fill_idx,
            default_clip=default_clip, max_clip=max_clip,
            min_fill=min_fill, max_ceiling=max_fill,
            max_unhedged_usd=max_unhedged_usd,
            max_unhedged_shares=max_unhedged_shares,
            in_sweep_phase=in_sweep_phase,
            max_depth_shares=_v17_depth,
            resting_size=resting_size,
            three_layer_defense=(strategy_id == "hydrogen-v1.8"),
        )

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
                    shares = _cap_for_maker(shares, role, side)
                    if shares <= 0:
                        saw_depth_cap = True
                        continue
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
        # v2.7: leg2MaxPrice decouples the normal hedge ceiling from the dip band
        # (e.g. 0.75 so $0.30+$0.62 can pair) while the late/sweep rescue keeps
        # the full rescue ceiling.
        if _leg2 is not None and not (in_late or in_sweep_phase):
            effective_ceiling = _leg2
        else:
            effective_ceiling = rescue_ceiling if (is_dsp or in_sweep_phase or in_late) else max_fill
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
        # Profit-lock taker hedge (opt-in; None = off = exact legacy behavior).
        # When closing a deficit projects a fee-inclusive pair cost at/below the
        # cap, the pair is already profitable: cross the ask now instead of
        # resting at the bid and hoping a seller arrives. hedge_max_clip lets
        # the taker hedge snap to the full deficit (up to the given shares)
        # instead of one max_clip rung per fill.
        if (_th_cap is not None and ask is not None
                and ask >= min_fill and ask <= effective_ceiling):
            h_cap = _h_clip if _h_clip is not None else max_clip
            h_shares = select_ladder_clip(
                deficit=deficit,
                price=ask,
                pair_cost=None,
                fill_idx=fill_idx,
                default_clip=default_clip,
                max_clip=h_cap,
                whole_ladder=whole_ladder,
                is_v22=is_v22,
                is_v23=is_v23,
            )
            h_est, _ = compute_fill_usd(h_shares, ask, role="TAKER", include_fee=True)
            h_proj = _projected_pair_cost(inv, side, h_shares, h_est)
            if h_proj is not None and h_proj <= _th_cap:
                return MicrostructureDecision(
                    action="fill",
                    outcome=side,
                    price=round(ask, 4),
                    shares=h_shares,
                    role="TAKER",
                    reason="clip-fill",
                    sub_reason="taker-hedge-lock",
                    projected_pair_cost=h_proj,
                    share_deficit=deficit,
                )
        # Tiered Rescue Hedging:
        # Standard: proj_pc <= max_pair_cost -> sub-$1.00 profitable pairing arbitrage.
        # Rescue: when holding a deficit in DSP or sweep phase, accepting proj_pc up to rescue_max_pair_cost (1.080)
        # locks in capital redemption, preventing a 100% loss ($0.00 redemption) on the naked leg.
        # v2.7: with lateRescueStartSec set, rescue pricing only kicks in in the
        # late window (elapsed >= start) or the sweep; before that the hard cap rules.
        if has_late:
            rescue_allowed = bool(in_late or in_sweep_phase)
            rescue_cap = late_cap
        else:
            rescue_allowed = bool(is_dsp or in_sweep_phase)
            rescue_cap = rescue_max_pair_cost
        # Patient pair, forced close. The hedge rests at the lagging side's bid
        # and books when a seller comes to it. Crossing the ask on the next tick
        # is the one timing the ledger measures as a loss (-0.2c per pair at a
        # 0-5s lag, +2.7c at 61-120s). In the sweep the pair has to close, so
        # there we cross.
        if in_sweep_phase or bid is None:
            role = "TAKER"
            exec_px = px
        else:
            role = "MAKER"
            exec_px = bid
            if open_orders:
                cur_order = open_orders.get(side)
                if isinstance(cur_order, dict):
                    cur_px = _fnum(cur_order.get("price"))
                    if cur_px is not None and cur_px > exec_px + 1e-9 and cur_px <= effective_ceiling:
                        cur_est, _ = compute_fill_usd(shares, cur_px, role="MAKER", include_fee=False)
                        cur_proj = _projected_pair_cost(inv, side, shares, cur_est)
                        if cur_proj is None or cur_proj <= max_pair_cost or (rescue_allowed and cur_proj <= rescue_cap):
                            exec_px = cur_px
        est_usd, _ = compute_fill_usd(shares, exec_px, role=role, include_fee=(role == "TAKER"))
        proj_pc = _projected_pair_cost(inv, side, shares, est_usd)
        is_rescue = (proj_pc is not None and proj_pc > max_pair_cost)
        if proj_pc is None or proj_pc <= max_pair_cost or (rescue_allowed and proj_pc <= rescue_cap and exec_px <= effective_ceiling):
            shares = _cap_for_maker(shares, role, side)
            if shares <= 0:
                saw_depth_cap = True
                continue
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
        if saw_depth_cap:
            return MicrostructureDecision(action="skip", outcome=preferred, reason="no-liquidity", sub_reason="depth-cap")
        if saw_pair_cap:
            return MicrostructureDecision(action="skip", outcome=preferred, reason="extreme-price-skip", sub_reason="pair-cost-cap")
        return MicrostructureDecision(action="skip", outcome=preferred, reason="sweep-balanced", sub_reason="sweep-balanced")

    # Candidate order: the lagging (deficit) side goes first so pairing is
    # preferred, but neither side is ever frozen out. Both sides stay eligible
    # on every evaluation.
    if up_def > 0:
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
        # v2.7 taker-dip entry (fresh legs only): when the knob is set and the
        # ask sits at/below the threshold, cross it as TAKER ahead of the maker
        # path -- a live 5m book almost always has a restable bid, so gating on
        # "no bid" would silently act like maker-only. Priced with the taker
        # fee via compute_fill_usd, so slippage is never understated. Falls
        # through to the maker path when the taker candidate fails its gates.
        # No atomic bypass here: a fresh taker dip is never the v2.2 risk-free
        # atomic pair, and no share veto exists to bind it.
        # hydrogen-v1.2 balanced-or-light-only taker dip: when the book is
        # imbalanced (lead > 0 means this side is heavy, since deficit <= 0
        # here), skip the taker cross and fall through to the maker path.
        # Balanced books and light-side deficit hedges are unaffected (the
        # light side has deficit > 0 and never enters this block).
        if (deficit <= 0 and _taker_dip is not None and ask is not None
                and ask >= min_fill and ask <= min(max_fill, leg1_cap)
                and ask <= _taker_dip
                and not (_td_balanced_only and lead > 0)):
            t_clip_cap = min(max_clip, _probe_sh) if (_probe_sh is not None and _probe_sh > 0 and inv[opp]["shares"] <= 0) else max_clip
            t_def_clip = min(default_clip, t_clip_cap)
            t_shares = select_ladder_clip(
                deficit=0.0,
                price=ask,
                pair_cost=None,
                fill_idx=fill_idx,
                default_clip=t_def_clip,
                max_clip=t_clip_cap,
                whole_ladder=whole_ladder,
                current_lead=lead,
                is_v22=is_v22,
                atomic_arb=False,
                is_v23=is_v23,
                dip_curve=dip_curve,
            )
            t_est, _ = compute_fill_usd(t_shares, ask, role="TAKER", include_fee=True)
            t_proj = _projected_pair_cost(inv, side, t_shares, t_est)
            t_ok = True
            if _step_cents is not None and _step_cents > 0 and inv[opp]["shares"] <= 0 and inv[side]["shares"] > 0:
                low_p = _lowest_held_price(side)
                if low_p is not None and ask > (low_p - (_step_cents / 100.0) + 1e-6):
                    saw_unhedged_step = True
                    t_ok = False
            if t_ok and max_unhedged_usd > 0:
                t_new_sh = inv[side]["shares"] + t_shares
                t_new_cost = inv[side]["cost"] + t_est
                t_lead_after = t_new_sh - inv[opp]["shares"]
                if t_lead_after > 0 and (t_new_cost / t_new_sh) * t_lead_after > max_unhedged_usd:
                    saw_unhedged_cap = True
                    t_ok = False
            elif t_ok and not (t_proj is None or t_proj <= bench_pc):
                saw_pair_cap = True
                t_ok = False
            if t_ok:
                    return MicrostructureDecision(
                        action="fill",
                        outcome=side,
                        price=round(ask, 4),
                        shares=t_shares,
                        role="TAKER",
                        reason="clip-fill",
                        sub_reason="taker-dip-entry",
                        projected_pair_cost=t_proj,
                        share_deficit=deficit,
                    )
        if is_dsp and (bid is None or bid < min_fill):
            # DSP only rests bids. With no bid at or above the floor there is
            # no price to rest at, and the ask fallback would book a taker fill
            # instead: on 2026-11-13 it took 33 sh at 0.07 against a 0.05 bid
            # and paid $0.15 of fee on a $2.46 clip, bypassing the dust skip.
            saw_dust = True
            continue
        if px < min_fill:
            saw_dust = True
            continue
        if px > min(max_fill, leg1_cap):
            if not saw_pair_cap:
                saw_ceiling = True
            continue
        dip_max = 0.45 if is_dsp else C.DIP_LADDER_MAX
        if px <= dip_max:
            if _step_cents is not None and _step_cents > 0 and inv[opp]["shares"] <= 0 and inv[side]["shares"] > 0:
                low_p = _lowest_held_price(side)
                if low_p is not None and px > (low_p - (_step_cents / 100.0) + 1e-6):
                    saw_unhedged_step = True
                    continue

            # High-Confidence Atomic Arb Detection:
            # If both sides can be filled immediately with sum <= 0.990, flag atomic_arb = True!
            is_atomic = bool(is_confidence and opp_ref is not None and (px + opp_ref <= 0.990))

            role = "MAKER" if ((bid is not None and px == bid) or bid is None) else "TAKER"
            m_clip_cap = min(max_clip, _probe_sh) if (_probe_sh is not None and _probe_sh > 0 and inv[opp]["shares"] <= 0) else max_clip
            m_def_clip = min(default_clip, m_clip_cap)
            shares = select_ladder_clip(
                deficit=deficit,
                price=px,
                pair_cost=None,
                fill_idx=fill_idx,
                default_clip=m_def_clip,
                max_clip=m_clip_cap,
                whole_ladder=whole_ladder,
                current_lead=lead,
                is_v22=is_v22,
                atomic_arb=is_atomic,
                is_v23=is_v23,
                dip_curve=dip_curve,
            )
            est_usd, _ = compute_fill_usd(shares, px, role=role, include_fee=(role == "TAKER"))
            proj_pc = _projected_pair_cost(inv, side, shares, est_usd)
            # Dollar-denominated unhedged cap (opt-in; 0 = off). This knob caps
            # the dollars exposed instead of counting shares: average cost of
            # this side's inventory x the net unhedged lead it would leave
            # behind.
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
                shares = _cap_for_maker(shares, role, side)
                if shares <= 0:
                    saw_depth_cap = True
                    continue
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
        elif px <= min(C.STRADDLE_BAND[1], leg1_cap) and inv["Up"]["shares"] == 0 and inv["Down"]["shares"] == 0:
            # Opening Straddle Leg 1 in (0.45, 0.55]. Both sides are flat, so
            # this is the at-the-money entry the ledger shows: the first leg
            # lands near 50c within ~13s of the open. The hedge is not assumed
            # here — it is placed as a resting bid once this leg fills.
            is_atomic = bool(is_confidence and opp_ref is not None and (px + opp_ref <= 0.990))
            role = "MAKER" if ((bid is not None and px == bid) or bid is None) else "TAKER"
            s_clip_cap = min(max_clip, _probe_sh) if (_probe_sh is not None and _probe_sh > 0 and inv[opp]["shares"] <= 0) else max_clip
            s_def_clip = min(default_clip, s_clip_cap)
            shares = select_ladder_clip(
                deficit=0.0,
                price=px,
                pair_cost=None,
                fill_idx=fill_idx,
                default_clip=s_def_clip,
                max_clip=s_clip_cap,
                whole_ladder=whole_ladder,
                is_v22=is_v22,
                atomic_arb=is_atomic,
                is_v23=is_v23,
            )
            shares = _cap_for_maker(shares, role, side)
            if shares <= 0:
                saw_depth_cap = True
                continue
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

    # Ceiling first: the opposite side is out of band on almost every DSP tick,
    # and this ordering is what the journal has always shown.
    if saw_ceiling:
        return MicrostructureDecision(action="skip", outcome=preferred, reason="extreme-price-skip", sub_reason="ceiling-price-skip")
    if saw_dust:
        return MicrostructureDecision(action="skip", outcome=preferred, reason="dust-quote", sub_reason="below-price-floor")
    if saw_unhedged_cap:
        return MicrostructureDecision(action="skip", outcome=preferred, reason="unhedged-cap-skip", sub_reason="unhedged-cap")
    if saw_unhedged_step:
        return MicrostructureDecision(action="skip", outcome=preferred, reason="unhedged-step-skip", sub_reason="unhedged-step-cents")
    if saw_depth_cap:
        return MicrostructureDecision(action="skip", outcome=preferred, reason="no-liquidity", sub_reason="depth-cap")
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
