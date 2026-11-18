"""Pure hydrogen v19/v20 decision engines (no bot.executor coupling)."""

import math

from bot.risk import clip_shares
from .exec_pricing import MicrostructureDecision, _projected_pair_cost, compute_fill_usd
from .exec_sizing import dip_curve_shares


def _h15_side_prices(quotes: dict, side: str) -> tuple[float | None, float | None]:
    q = quotes.get(side) or {}
    bid = q.get("bid")
    ask = q.get("ask")
    valid_bid = bid if (bid is not None and 0.0 < bid < 1.0) else None
    valid_ask = ask if (ask is not None and 0.0 < ask < 1.0) else None
    return valid_bid, valid_ask


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
    deficit_duration_sec: float = 0.0,
    window_bailout_latched: bool = False,
    max_pair_cost: float = H19_L2_PAIR_CAP,
) -> MicrostructureDecision:
    """Hydrogen v1.9 microstructure decision engine.

    Layer 1 (Flat, abs(lead) <= 0.5 sh): Single 5-share maker probe in 42-49c ATM band.
        Frozen once elapsed_sec >= 150.0 OR matched >= 40.0 OR window_bailout_latched.
    Layer 2 (Over, abs(lead) > 0.5 sh): Immediate sub-par clamped maker hedge
        at px = min(light_bid, floor(0.990 - heavy_avg)). Heavy resting orders cancelled.
    Layer 3 (Over, abs(lead) > 0.5 sh): 20s delayed taker bailout once the
        deficit opens, marginal pair >= 1.07 and ask <= 0.72.
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
        taker_fire = (
            deficit_duration_sec >= H19_L3_PATIENCE_SEC
            and l_ask is not None
            and l_ask <= H19_L3_ASK_MAX
            and (heavy_avg + l_ask >= H19_L3_MARGINAL_MIN)
        )

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
            _heavy_pos = inv.get(heavy) or {}
            heavy_avg = (float(_heavy_pos.get("cost", 0.0)) / float(_heavy_pos.get("shares", 0.0))) if float(_heavy_pos.get("shares", 0.0)) > 0 else 0.0
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

        # Never complete a pair at >= $1.00 on the maker path (the taker path
        # enforces this explicitly): clamp custom rescue configs to $0.999.
        # Default configs (sweep 0.995) are unchanged.
        maker_cap = min(float(rescue_max_pair_cost if in_sweep_phase else max_pair_cost), 0.999)
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
                # Exact max addable shares from the same average-cost formula:
                # (side_cost + n*px) * (side_sh + n - opp_sh) <= M * (side_sh + n).
                # Shares resting up to opp_sh carry no unhedged cost; the root
                # accounts for them. Floored to 0.1 sh like the old branches.
                _a = px
                _b = side_cost + px * (side_sh - opp_sh) - max_unhedged_usd
                _c = side_cost * (side_sh - opp_sh) - max_unhedged_usd * side_sh
                _disc = _b * _b - 4.0 * _a * _c
                if _disc < 0.0 or _a <= 1e-12:
                    allowed = 0.0
                else:
                    allowed = max(0.0, (-_b + math.sqrt(_disc)) / (2.0 * _a))
                allowed = math.floor((allowed + 1e-9) * 10.0) / 10.0
                shares = min(shares, allowed)
                if shares < 1.0 - 1e-9:
                    continue
                # Recheck the reduced size against the limit before accepting.
                new_sh = side_sh + shares
                new_cost = side_cost + shares * px
                lead_after = max(0.0, new_sh - opp_sh)
                unhedged_after = (new_cost / new_sh) * lead_after if new_sh > 0 else 0.0
                if unhedged_after > max_unhedged_usd + 1e-9:
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
