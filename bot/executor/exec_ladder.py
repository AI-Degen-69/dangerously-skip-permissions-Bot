"""Pure main ladder router (deficit hedge + dip grid + snipe)."""

from bot import constants as C
from .exec_hydrogen import _evaluate_hydrogen_v19, _evaluate_hydrogen_v20
from .exec_pricing import MicrostructureDecision, _projected_pair_cost, compute_fill_usd
from .exec_sizing import select_ladder_clip


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
    taker_hedge_max_pair_cost: float | None = None,
    hedge_max_clip: float | None = None,
    late_rescue_start_sec: float | None = None,
    late_rescue_max_pair_cost: float | None = None,
    elapsed_sec: float | None = None,
    unhedged_step_cents: float | None = None,
    unhedged_probe_shares: float | None = None,
    open_orders: dict | None = None,
    clip_schedule: list | None = None,
    _sizing_fn=None,
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
    sizing_fn = _sizing_fn or select_ladder_clip
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
    # DSP family shares the same recovery-engine rules.
    is_dsp = strategy_id.startswith("dangerously-skip-permissions")
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

    if strategy_id == "hydrogen-v1.9":
        try:
            _v19_depth = float(max_depth_shares or 0.0)
        except Exception:
            _v19_depth = 0.0
        return _evaluate_hydrogen_v19(
            quotes=quotes, inv=inv, fill_idx=fill_idx,
            min_fill=min_fill, max_ceiling=max_fill,
            max_unhedged_usd=max_unhedged_usd,
            max_unhedged_shares=max_unhedged_shares,
            in_sweep_phase=in_sweep_phase,
            elapsed_sec=_elapsed or 0.0,
            max_depth_shares=_v19_depth,
            resting_size=resting_size,
            deficit_duration_sec=float(kwargs.get("deficit_duration_sec", 0.0) or 0.0),
            window_bailout_latched=bool(kwargs.get("window_bailout_latched", False)),
            max_pair_cost=max_pair_cost,
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
                shares = sizing_fn(
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

        shares = sizing_fn(
            deficit=deficit,
            price=px,
            pair_cost=None,
            fill_idx=fill_idx,
            default_clip=default_clip,
            max_clip=max_clip,
            whole_ladder=whole_ladder,
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
            h_shares = sizing_fn(
                deficit=deficit,
                price=ask,
                pair_cost=None,
                fill_idx=fill_idx,
                default_clip=default_clip,
                max_clip=h_cap,
                whole_ladder=whole_ladder,
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
        if (deficit <= 0 and _taker_dip is not None and ask is not None
                and ask >= min_fill and ask <= min(max_fill, leg1_cap)
                and ask <= _taker_dip):
            t_clip_cap = min(max_clip, _probe_sh) if (_probe_sh is not None and _probe_sh > 0 and inv[opp]["shares"] <= 0) else max_clip
            t_def_clip = min(default_clip, t_clip_cap)
            t_shares = sizing_fn(
                deficit=0.0,
                price=ask,
                pair_cost=None,
                fill_idx=fill_idx,
                default_clip=t_def_clip,
                max_clip=t_clip_cap,
                whole_ladder=whole_ladder,
                current_lead=lead,
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


            role = "MAKER" if ((bid is not None and px == bid) or bid is None) else "TAKER"
            m_clip_cap = min(max_clip, _probe_sh) if (_probe_sh is not None and _probe_sh > 0 and inv[opp]["shares"] <= 0) else max_clip
            m_def_clip = min(default_clip, m_clip_cap)
            shares = sizing_fn(
                deficit=deficit,
                price=px,
                pair_cost=None,
                fill_idx=fill_idx,
                default_clip=m_def_clip,
                max_clip=m_clip_cap,
                whole_ladder=whole_ladder,
                current_lead=lead,
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
            role = "MAKER" if ((bid is not None and px == bid) or bid is None) else "TAKER"
            s_clip_cap = min(max_clip, _probe_sh) if (_probe_sh is not None and _probe_sh > 0 and inv[opp]["shares"] <= 0) else max_clip
            s_def_clip = min(default_clip, s_clip_cap)
            shares = sizing_fn(
                deficit=0.0,
                price=px,
                pair_cost=None,
                fill_idx=fill_idx,
                default_clip=s_def_clip,
                max_clip=s_clip_cap,
                whole_ladder=whole_ladder,
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
