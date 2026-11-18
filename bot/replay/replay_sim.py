"""Deterministic single-window replay engine (mirrors live_paper.trade_window)."""

from __future__ import annotations

import math
import os

from bot import constants as C
from bot.executor import compute_fill_usd, evaluate_microstructure_ladder, v20_max_hedge_price
from bot.fill_audit.fill_model import match_maker_book_cross, match_maker_print
from .replay_consts import WINDOW_S
from bot.risk import clip_shares


def _quotes_from_state(state: dict) -> dict:
    def side(o):
        b = state[o]["bid"]
        a = state[o]["ask"]
        return {"bid": b if b is not None else a, "ask": a}
    return {"Up": side("Up"), "Down": side("Down")}

def simulate_window(slot: int, winner: str | None, book_rows: list, prints: list,
                    strategy_id: str, entry: dict, levels: int = 1,
                    spacing: float = 0.02, queue_mode: str = "exact",
                    eval_floor_s: float = 0.0,
                    unhedged_step_cents: float = 0.0) -> dict:
    """Replay one window. Deterministic: same inputs -> same output."""
    start_after_open = float(entry.get("startAfterOpenSec", 4))
    stop_before = float(entry.get("stopBeforeCloseSec", 75))
    try:
        sweep_before = float(entry.get("sweepBeforeCloseSec", C.HARD_CUTOFF_SBC))
    except (TypeError, ValueError):
        sweep_before = float(C.HARD_CUTOFF_SBC)
    cutoff_sbc = min(stop_before, sweep_before, float(C.HARD_CUTOFF_SBC))
    end = slot + WINDOW_S - stop_before
    sweep_end = slot + WINDOW_S - cutoff_sbc
    min_fill = max(0.01, float(entry.get("minFillPrice", C.PRICE_FLOOR)))
    max_fill = min(0.99, float(entry.get("maxFillPrice", C.PRICE_CEILING)))
    clip_default = float(entry.get("clipSharesDefault", C.CLIP_SHARES_DEFAULT))
    max_shares = float(entry.get("maxShares", C.MAX_SHARES))
    target_pc = float(entry.get("targetPairCost", C.TARGET_PAIR_COST))
    max_pc = float(entry.get("maxPairCost", C.PAIR_COST_MAX))
    try:
        max_unhedged_usd = float(entry.get("maxUnhedgedUsd", 0.0) or 0.0)
    except (TypeError, ValueError):
        max_unhedged_usd = 0.0
    try:
        max_unhedged_shares = float(entry.get("maxUnhedgedShares", 0.0) or 0.0)
    except (TypeError, ValueError):
        max_unhedged_shares = 0.0
    dip_curve = entry.get("dipCurve") or None
    clip_schedule = entry.get("clipSchedule") or None
    rescue_ceiling = float(entry.get("rescueCeilingPrice", C.RESCUE_CEILING_PRICE))
    rescue_max = float(entry.get("rescuePairCostMax", C.RESCUE_PAIR_COST_MAX))
    leg1_max = entry.get("leg1MaxPrice", entry.get("maxLeg1Price", None))
    try:
        leg1_max = float(leg1_max) if leg1_max is not None else None
    except (TypeError, ValueError):
        leg1_max = None
    leg2_max = entry.get("leg2MaxPrice", None)
    try:
        leg2_max = float(leg2_max) if leg2_max is not None else None
    except (TypeError, ValueError):
        leg2_max = None
    taker_dip_max = entry.get("takerDipEntryMax", entry.get("takerDipMax", None))
    try:
        taker_dip_max = float(taker_dip_max) if taker_dip_max is not None else None
    except (TypeError, ValueError):
        taker_dip_max = None
    taker_hedge_cap = entry.get("takerHedgeMaxPairCost", entry.get("takerHedgeMaxPair", None))
    try:
        taker_hedge_cap = float(taker_hedge_cap) if taker_hedge_cap is not None else None
    except (TypeError, ValueError):
        taker_hedge_cap = None
    hedge_clip = entry.get("hedgeMaxClip", entry.get("takerHedgeMaxClip", None))
    try:
        hedge_clip = float(hedge_clip) if hedge_clip is not None else None
    except (TypeError, ValueError):
        hedge_clip = None
    try:
        if "unhedgedStepCents" in entry and entry.get("unhedgedStepCents") is not None:
            entry_step = float(entry.get("unhedgedStepCents") or 0.0)
            # Explicit CLI override wins; otherwise keep the frozen entry setting.
            unhedged_step_cents = float(unhedged_step_cents) if unhedged_step_cents else entry_step
        else:
            unhedged_step_cents = float(unhedged_step_cents or 0.0)
    except (TypeError, ValueError):
        unhedged_step_cents = 0.0
    try:
        unhedged_probe_shares = float(entry.get("unhedgedProbeShares", 0.0) or 0.0)
    except (TypeError, ValueError):
        unhedged_probe_shares = 0.0
    late_start = entry.get("lateRescueStartSec", None)
    try:
        late_start = float(late_start) if late_start is not None else None
    except (TypeError, ValueError):
        late_start = None
    late_max = entry.get("lateRescueMaxPairCost", None)
    try:
        late_max = float(late_max) if late_max is not None else None
    except (TypeError, ValueError):
        late_max = None
    spacing_move = float(entry.get("minSpacingMoveSec", 0.5))
    spacing_static = float(entry.get("minSpacingStaticSec", 2.5))
    include_fee = bool(entry.get("includeTakerFee", True))

    inv = {"Up": {"shares": 0.0, "cost": 0.0}, "Down": {"shares": 0.0, "cost": 0.0}}
    fills: list[dict] = []
    cost = 0.0
    fees = 0.0
    placements = 0
    queue_unknown = 0
    # side -> {"bid","ask","bids","asks"} latest snapshot
    state = {"Up": {"bid": None, "ask": None, "bids": [], "row_ts": 0.0},
             "Down": {"bid": None, "ask": None, "bids": [], "row_ts": 0.0}}
    # SELL flow per outcome, ts-ordered, to net against snapshot queues.
    import bisect as _bisect
    sells: dict[str, list] = {"Up": [], "Down": []}
    for (pts, poc, ppx, psz, psd, _a) in prints:
        if poc in sells and str(psd) == "SELL" and (psz or 0) > 0:
            try:
                sells[poc].append((float(pts), float(ppx), float(psz)))
            except (TypeError, ValueError):
                continue
    for v in sells.values():
        v.sort()
    sell_ts = {k: [t for t, _, _ in v] for k, v in sells.items()}
    # side -> list of resting order dicts (best price first)
    resting: dict[str, list[dict]] = {"Up": [], "Down": []}
    next_eval_ts = float("-inf")
    last_fill_ts = 0.0
    last_fill_px: float | None = None
    deficit_since_ts: float | None = None
    window_bailout_latched: bool = False

    def book_fill(outcome, px, shares, role, minute, sub_reason, queue_ahead, deficit, ts):
        nonlocal cost, fees, last_fill_ts, last_fill_px, window_bailout_latched
        imbalance_before = abs(inv["Up"]["shares"] - inv["Down"]["shares"])
        usd, fee_usd = compute_fill_usd(shares, px, role=role, include_fee=include_fee)
        inv[outcome]["shares"] += shares
        inv[outcome]["cost"] += usd
        cur_low = inv[outcome].get("lowest_price")
        if cur_low is None or px < cur_low:
            inv[outcome]["lowest_price"] = px
        cost += usd
        fees += fee_usd
        last_fill_ts = ts
        last_fill_px = px
        imbalance_after = abs(inv["Up"]["shares"] - inv["Down"]["shares"])
        if strategy_id.startswith("hydrogen-v2") and role == "TAKER" and sub_reason == "rebalance-taker":
            opp_outcome = "Down" if outcome == "Up" else "Up"
            resting[opp_outcome] = []
        if strategy_id.startswith("hydrogen-v1.9") and sub_reason in ("rebalance-taker", "rebalance-maker") and imbalance_after < imbalance_before:
            opp_outcome = "Down" if outcome == "Up" else "Up"
            if inv[opp_outcome]["shares"] > 0:
                heavy_avg_cost = inv[opp_outcome]["cost"] / inv[opp_outcome]["shares"]
                marginal_pair = heavy_avg_cost + px
                if marginal_pair > 1.000:
                    window_bailout_latched = True
        fills.append({"ts": ts, "minute": minute, "outcome": outcome, "price": px,
                      "shares": shares, "usd": usd, "role": role,
                      "subReason": sub_reason, "feeUsd": fee_usd,
                      "queueAhead": queue_ahead, "deficit": deficit})

    def _step_blocked(target_outcome, order_price):
        if unhedged_step_cents <= 0:
            return False
        opp_side = "Down" if target_outcome == "Up" else "Up"
        if inv[opp_side]["shares"] == 0 and inv[target_outcome]["shares"] > 0:
            held_pxs = [f["price"] for f in fills if f["outcome"] == target_outcome]
            min_held = min(held_pxs) if held_pxs else 1.0
            return order_price > min_held - (unhedged_step_cents / 100.0) + 1e-9
        return False

    def offer_print(target_outcome, print_outcome, side, px, size, ts):
        orders = resting.get(target_outcome) or []
        # Best (highest) bid is hit first, and one print's size is spent
        # across rungs as it is consumed (mirror of fill_audit._spend): the
        # same shares cannot fill every level.
        remaining = size
        for order in list(orders):
            if remaining <= 0:
                break
            q_before = max(0.0, float(order.get("queue_ahead") or 0.0))
            hit = match_maker_print(order, {"outcome": print_outcome, "side": side,
                                            "price": px, "size": remaining})
            q_after = max(0.0, float(order.get("queue_ahead") or 0.0))
            q_used = max(0.0, q_before - q_after)
            if hit is not None:
                if _step_blocked(target_outcome, order["price"]):
                    remaining = max(0.0, remaining - q_used)
                    continue
                consumed = q_used + hit["fills"]
                remaining = max(0.0, remaining - consumed)
                book_fill(target_outcome, order["price"], hit["fills"], "MAKER",
                          _minute(ts), order["sub_reason"], hit["queueAhead"],
                          order["deficit"], ts)
                if os.environ.get("REPLAY_TRACE"):
                    print(f"TRACE fill {ts:.1f} {target_outcome} {order['price']} x{hit['fills']:.2f} qpaid={hit['queueAhead']:.1f}", flush=True)
            else:
                remaining = max(0.0, remaining - q_used)
            if order["shares_left"] <= 0:
                try:
                    orders.remove(order)
                except ValueError:
                    pass

    def offer_book(target_outcome, asks, ts):
        orders = resting.get(target_outcome) or []
        best_ask = state[target_outcome]["ask"]
        best_bid = state[target_outcome]["bid"]
        ask_avail: float | None = None
        if asks:
            try:
                ask_avail = float(asks[0][1])
            except (TypeError, ValueError, IndexError):
                ask_avail = None
        for order in list(orders):
            q = {"bid": best_bid, "ask": best_ask, "ts": ts}
            is_touch = (
                best_ask is not None
                and abs(float(best_ask) - float(order["price"])) <= 1e-9
                and (best_bid is None or float(best_bid) >= float(order["price"]) - 1e-9)
            )
            if is_touch and ask_avail is not None:
                if ask_avail <= 0.0:
                    continue
                q["askSize"] = ask_avail
            q_before = max(0.0, float(order.get("queue_ahead") or 0.0))
            hit = match_maker_book_cross(order, q)
            q_after = max(0.0, float(order.get("queue_ahead") or 0.0))
            q_used = max(0.0, q_before - q_after)
            if is_touch and ask_avail is not None:
                spent = q_used + (hit["fills"] if hit is not None else 0.0)
                ask_avail = max(0.0, ask_avail - spent)
            if hit is not None:
                if _step_blocked(target_outcome, order["price"]):
                    continue
                book_fill(target_outcome, order["price"], hit["fills"], "MAKER",
                          _minute(ts), order["sub_reason"], hit["queueAhead"],
                          order["deficit"], ts)
            if order["shares_left"] <= 0:
                try:
                    orders.remove(order)
                except ValueError:
                    pass

    def _minute(ts):
        return int(min(max((ts - slot) // 60, 0), 4))

    def place_levels(outcome, px, shares, minute, reason, sub_reason, deficit, ts):
        """Diff desired level set against resting orders (mirror _place_maker).

        Same price -> keep the order where it is (no re-queue). New levels get
        queue_ahead = resting size AT the limit price (mirror of
        live_paper.live_queue_ahead, which reads book.bids.get(price)), net
        of recorded SELL flow between the snapshot's ts and now: the live
        book at the placement tick already reflects those prints, while the
        snapshot predates them. When the level is outside the visible top-5
        the queue is unknown: place with 0.0 (exactly what the live loop
        stores for None) and count it.
        """
        nonlocal placements, queue_unknown
        opp_side = "Down" if outcome == "Up" else "Up"
        max_hedge_px = None
        # v1.9 / v2.0 resting hygiene (mirrors live_paper): older strategies keep prior behavior.
        if sub_reason == "rebalance-maker":
            if strategy_id.startswith("hydrogen-v2"):
                resting[opp_side] = []
                if inv[opp_side]["shares"] > inv[outcome]["shares"] + 1e-9:
                    cap = min(rescue_max if reason == "sweep" else max_pc, 0.999)
                    max_hedge_px = v20_max_hedge_price(inv, opp_side, outcome, cap)
            elif strategy_id.startswith("hydrogen-v1.9"):
                resting[opp_side] = []
                if inv[opp_side]["shares"] > 0:
                    heavy_avg = inv[opp_side]["cost"] / inv[opp_side]["shares"]
                    max_hedge_px = math.floor((max_pc - heavy_avg + 1e-9) * 100.0) / 100.0
        bids = state[outcome]["bids"] or []
        desired = [round(px - i * spacing, 4) for i in range(max(1, levels))]
        if unhedged_step_cents > 0:
            if inv[opp_side]["shares"] == 0 and inv[outcome]["shares"] > 0:
                held_pxs = [f["price"] for f in fills if f["outcome"] == outcome]
                min_held = min(held_pxs) if held_pxs else 1.0
                max_allowed = min_held - (unhedged_step_cents / 100.0) + 1e-9
                desired = [d for d in desired if d <= max_allowed]
        keep = []
        has_higher_hedge = False
        for order in resting[outcome]:
            is_higher_hedge = (
                (deficit > 0 or float(order.get("deficit") or 0.0) > 0)
                and float(order["price"]) > px + 1e-9
            )
            if is_higher_hedge and max_hedge_px is not None and float(order["price"]) > max_hedge_px + 1e-9:
                is_higher_hedge = False
            if any(abs(order["price"] - d) < 1e-9 for d in desired) or is_higher_hedge:
                keep.append(order)
                if is_higher_hedge:
                    has_higher_hedge = True
        resting[outcome] = keep
        have = {round(o["price"], 4) for o in keep}
        for d in desired:
            if d in have:
                continue
            if has_higher_hedge and d < px + 1e-9:
                continue
            if d < min_fill or d <= 0:
                continue
            if queue_mode == "cumulative":
                qa = sum(s for p, s in bids if p >= d - 1e-9)
                if not any(abs(p - d) < 1e-9 for p, s in bids):
                    queue_unknown += 1
            else:
                level = next((s for p, s in bids if abs(p - d) < 1e-9), None)
                if level is None:
                    queue_unknown += 1
                    qa = 0.0
                else:
                    qa = float(level)
                    row_ts = float(state[outcome].get("row_ts") or 0.0)
                    if row_ts < ts:
                        flow = sells.get(outcome) or []
                        tss = sell_ts.get(outcome) or []
                        lo = _bisect.bisect_right(tss, row_ts)
                        hi = _bisect.bisect_right(tss, ts, lo=lo)
                        for _, ppx, psz in flow[lo:hi]:
                            if ppx <= d + 1e-9:
                                qa -= psz
                                if qa <= 0:
                                    qa = 0.0
                                    break
            resting[outcome].append({"side": outcome, "price": d,
                                    "shares_left": shares, "queue_ahead": float(qa),
                                    "placed_ts": ts, "reason": reason,
                                    "sub_reason": sub_reason, "minute": minute,
                                    "deficit": deficit})
            placements += 1
            if os.environ.get("REPLAY_TRACE"):
                print(f"TRACE place {ts:.1f} {outcome} {d} x{shares:.1f} qa={qa:.1f} row_age={ts - float(state[outcome].get('row_ts') or ts):.2f}", flush=True)
        resting[outcome].sort(key=lambda o: -o["price"])

    def cancel_orders():
        resting["Up"] = []
        resting["Down"] = []

    events = []
    for (ts, outcome, bids, asks) in book_rows:
        events.append((ts, 1, ("book", outcome, bids, asks)))
    for (ts, outcome, px, size, side, _aid) in prints:
        events.append((ts, 0, ("print", outcome, px, size, side)))
    events.sort(key=lambda e: (e[0], e[1]))

    for ts, _kind, payload in events:
        if ts < slot + start_after_open:
            # Pre-open book warms the quotes; nothing books before the bell.
            if payload[0] == "book":
                _, outcome, bids, asks = payload
                if outcome in state:
                    state[outcome]["bids"] = bids
                    state[outcome]["bid"] = bids[0][0] if bids else None
                    state[outcome]["ask"] = asks[0][0] if asks else None
                    state[outcome]["row_ts"] = ts
            continue
        if payload[0] == "print":
            _, outcome, px, size, side = payload
            if outcome in resting and resting[outcome]:
                offer_print(outcome, outcome, side, px, size, ts)
            opp_outcome = "Down" if outcome == "Up" else "Up"
            if opp_outcome in resting and resting[opp_outcome] and str(side).upper() in ("BUY", "BID", "BUYS"):
                offer_print(opp_outcome, outcome, side, px, size, ts)
            continue
        _, outcome, bids, asks = payload
        if outcome not in state:
            continue
        state[outcome]["bids"] = bids
        state[outcome]["bid"] = bids[0][0] if bids else None
        state[outcome]["ask"] = asks[0][0] if asks else None
        state[outcome]["row_ts"] = ts

        if ts >= end:
            if resting["Up"] or resting["Down"]:
                # The strategy stops opening in the sweep; a bid left resting
                # through it would fill on flow the strategy never saw.
                cancel_orders()
        elif resting.get(outcome):
            offer_book(outcome, asks, ts)

        # The live loop wakes on every streamer tick, but each iteration pays
        # journal + log I/O, so it evaluates at ~10-80/s (measured in the
        # runs' decisions.jsonl), not at the recorded message rate. The
        # eval_floor_s knob caps the evaluation cadence for sensitivity
        # runs (0 = every recorded row); prints are always offered at full
        # resolution. Both settings pass the gate on the clean set.
        if eval_floor_s and ts < next_eval_ts:
            continue
        if eval_floor_s:
            next_eval_ts = ts + eval_floor_s
        imbalance = abs(inv["Up"]["shares"] - inv["Down"]["shares"])
        if imbalance > 0.5:
            if deficit_since_ts is None:
                deficit_since_ts = ts
        else:
            deficit_since_ts = None
        deficit_duration_sec = (ts - deficit_since_ts) if deficit_since_ts is not None else 0.0
        in_sweep = (ts >= end and ts < sweep_end and imbalance > 0.0)
        if ts >= sweep_end or (ts >= end and imbalance <= 0.0):
            break

        quotes = _quotes_from_state(state)
        open_orders = {s: resting[s][0] for s in ("Up", "Down") if resting.get(s)}
        decision = evaluate_microstructure_ladder(
            quotes=quotes, inv=inv, fill_idx=len(fills), minute=_minute(ts),
            strategy_id=strategy_id, min_fill=min_fill, max_fill=max_fill,
            default_clip=clip_default, max_clip=max_shares,
            whole_ladder=True, target_pair_cost=target_pc,
            max_pair_cost=max_pc,
            max_unhedged_usd=max_unhedged_usd,
            max_unhedged_shares=max_unhedged_shares,
            dip_curve=dip_curve,
            clip_schedule=clip_schedule,
            in_sweep_phase=in_sweep, rescue_ceiling=rescue_ceiling,
            rescue_max_pair_cost=rescue_max,
            leg1_max_price=leg1_max, leg2_max_price=leg2_max,
            taker_dip_max=taker_dip_max,
            taker_hedge_max_pair_cost=taker_hedge_cap,
            hedge_max_clip=hedge_clip,
            late_rescue_start_sec=late_start,
            late_rescue_max_pair_cost=late_max,
            elapsed_sec=float(ts - slot),
            unhedged_step_cents=unhedged_step_cents,
            unhedged_probe_shares=unhedged_probe_shares,
            open_orders=open_orders,
            deficit_duration_sec=deficit_duration_sec,
            window_bailout_latched=window_bailout_latched,
        )
        if decision.action == "skip" or decision.outcome is None or decision.price is None:
            continue
        outcome_d = decision.outcome
        px = decision.price
        shares = min(clip_shares(decision.shares, max_shares), max_shares)
        time_since_fill = ts - last_fill_ts
        is_move = last_fill_px is not None and abs(px - last_fill_px) >= 0.001
        required = 0.5 if in_sweep else (spacing_move if is_move else spacing_static)
        if time_since_fill < required:
            continue
        if decision.role == "TAKER":
            if unhedged_step_cents > 0:
                opp_side = "Down" if outcome_d == "Up" else "Up"
                if inv[opp_side]["shares"] == 0 and inv[outcome_d]["shares"] > 0:
                    held_pxs = [f["price"] for f in fills if f["outcome"] == outcome_d]
                    min_held = min(held_pxs) if held_pxs else 1.0
                    if px > min_held - (unhedged_step_cents / 100.0) + 1e-9:
                        continue
            resting[outcome_d] = []
            book_fill(outcome_d, px, shares, "TAKER", _minute(ts),
                      decision.sub_reason, None, decision.share_deficit, ts)
        else:
            place_levels(outcome_d, px, shares, _minute(ts), decision.reason,
                         decision.sub_reason, decision.share_deficit, ts)

    up = sum(f["shares"] for f in fills if f["outcome"] == "Up")
    down = sum(f["shares"] for f in fills if f["outcome"] == "Down")
    wshares = (up if winner == "Up" else down) if winner in ("Up", "Down") else None
    payout = round(wshares, 2) if wshares is not None else None
    net = round(payout - cost, 2) if payout is not None else None
    pair_cost = round(cost / min(up, down), 4) if min(up, down) > 0 else None
    maker = sum(1 for f in fills if f["role"] == "MAKER")
    return {"slot": slot, "winner": winner, "fills": fills, "n_fills": len(fills),
            "n_maker": maker, "n_taker": len(fills) - maker,
            "cost": round(cost, 2), "fees": round(fees, 4),
            "payout": payout, "net": net, "pair_cost": pair_cost,
            "up": round(up, 2), "down": round(down, 2),
            "placements": placements, "queue_unknown": queue_unknown,
            "frag": sum(1 for f in fills if f["shares"] < 1)}
