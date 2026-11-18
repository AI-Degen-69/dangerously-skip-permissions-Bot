"""Shared view helpers: number coercion, fill enrichment, window rows."""

import statistics

from bot.api.api_core import is_pending
from bot.fill_audit import role_of


def _num(value, default: float = 0.0) -> float:
    """Paper-run JSON is hand-editable, so never let one bad field 500 the desk."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default





def _minute_shape(fills: list[dict]) -> list[int]:
    shape = [0, 0, 0, 0, 0]
    for f in fills:
        try:
            m = int(f.get("minute", 0))
        except (TypeError, ValueError):
            m = 0
        if 0 <= m <= 4:
            shape[m] += 1
    return shape





def _median(values: list[float]) -> float:
    return round(statistics.median(values), 2) if values else 0.0





def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 2) if values else 0.0





def slot_ms(slug: str) -> int:
    """Window epoch from a `btc-updown-5m-<epoch>` slug, in ms."""
    try:
        return int(str(slug).split("-")[-1]) * 1000
    except (ValueError, IndexError):
        return 0





def _enrich_fill(f: dict, idx: int, default_ts: int, slug: str | None) -> dict:
    reason = f.get("reason")
    detail = dict(f.get("detail") or {})
    minute = f.get("minute")
    if not reason or reason == "paper-fill":
        if idx == 0 or (minute == 0 and idx == 0):
            reason = "straddle-open"
        elif idx == 1:
            reason = "hedge-leg"
        elif minute is not None:
            # No minute-4 snipe default: reason-less late fills are ordinary
            # balance clips (mislabeling them as snipes also mistreats fees).

            reason = "straddle-balance"
        else:
            reason = "paper-fill"
    if minute is not None and "minute" not in detail:
        detail["minute"] = minute
    return {
        "ts": int(f.get("ts") or default_ts),
        "kind": "snipe" if reason == "m4-snipe" else "entry",
        "slug": slug,
        "interval": "5m",
        "side": f.get("outcome"),
        "shares": f.get("shares"),
        "price": f.get("price"),
        "usd": f.get("usd"),
        "reason": reason,
        "detail": detail,
        "mode": "paper",
    }





def _window_row(r: dict) -> dict:
    """One settled/pending window flattened for the dashboard tables."""
    from bot import constants as C

    fills = r.get("fills") or []
    cost = _num(r.get("cost_usd"))
    payout = _num(r.get("payout_usd"))
    pending = is_pending(r)
    try:
        start_ms = int(str(r.get("event_slug", "")).split("-")[-1]) * 1000
    except (TypeError, ValueError):
        start_ms = 0
    sides = {f.get("outcome") for f in fills if f.get("outcome")}

    # Fees are already charged inside cost_usd, so a rebate is only ever added on
    # top. The taker side scales with the account tier and the maker side is a
    # fixed share of the fees its fills were matched against, so both ship as raw
    # bases and the dashboard applies whichever tier is selected.
    maker_fee_base = 0.0
    computed_taker = 0.0
    for f in fills:
        price = _num(f.get("price"))
        shares = _num(f.get("shares"))
        if price <= 0 or shares <= 0:
            continue
        detail = f.get("detail") or {}
        role = str(detail.get("role") or "").upper()
        raw_fee = detail.get("feeUsd")
        has_fee = isinstance(raw_fee, (int, float)) and not isinstance(raw_fee, bool)
        fee = _num(raw_fee)
        base = shares * C.TAKER_FEE_COEFF * price * (1 - price)
        # Same precedence as classifyFill() in src/app/lib/rebates.ts: a recorded
        # role, then a recorded fee, then the legacy reason text, then maker. The
        # orders table classifies with the same rule, so the totals it shows and
        # the per-fill rows can never disagree.
        reason = str(f.get("reason") or "").lower()
        if role in ("MAKER", "TAKER"):
            is_taker = role == "TAKER"
        elif has_fee:
            is_taker = fee > 0
        elif "equalizer" in reason or "snipe" in reason:
            is_taker = True
        else:
            is_taker = False
        if is_taker:
            computed_taker += fee if fee > 0 else base
        else:
            maker_fee_base += base
    recorded_fees = r.get("fees_usd")
    taker_fees = _num(recorded_fees) if recorded_fees is not None else round(computed_taker, 4)

    # Verified-only view: the same window recomputed from the fills the tape
    # verifier confirmed. A maker fill is verified when real prints at its limit
    # price covered the whole clip; taker fills never are, and fills from before
    # the verifier existed carry no status at all, so both drop out here.
    verified_fills = [
        f for f in fills
        if str((f.get("detail") or {}).get("tapeStatus") or "") == "verified"
    ]
    v_cost = 0.0
    v_up = 0
    v_down = 0
    v_zero = 0
    v_maker_base = 0.0
    v_fees = 0.0
    for f in verified_fills:
        price = _num(f.get("price"))
        shares = _num(f.get("shares"))
        v_cost += _num(f.get("usd"))
        outcome = f.get("outcome")
        if outcome == "Up":
            v_up += 1
        elif outcome == "Down":
            v_down += 1
        if price <= 0:
            v_zero += 1
        # A verified fill is always a maker fill, so its fee base is the taker
        # fee the counterparty paid on the same price and size.
        if price > 0 and shares > 0:
            v_maker_base += shares * C.TAKER_FEE_COEFF * price * (1 - price)
        v_fees += _num((f.get("detail") or {}).get("feeUsd"))
    winner = r.get("winner")
    # Same settlement rule as settle_pending_windows: the winning side's shares
    # pay $1 each, everything else is what the window cost.
    v_win_shares = sum(
        _num(f.get("shares")) for f in verified_fills if winner and f.get("outcome") == winner
    )
    v_payout = round(v_win_shares * 1.0, 2) if winner else 0.0

    # Lock-in cost of a window that took both legs: avg Up price + avg Down price.
    up_shares = sum(_num(f.get("shares")) for f in fills if f.get("outcome") == "Up" and _num(f.get("price")) > 0)
    down_shares = sum(_num(f.get("shares")) for f in fills if f.get("outcome") == "Down" and _num(f.get("price")) > 0)
    up_usd = sum(_num(f.get("usd")) for f in fills if f.get("outcome") == "Up" and _num(f.get("price")) > 0)
    down_usd = sum(_num(f.get("usd")) for f in fills if f.get("outcome") == "Down" and _num(f.get("price")) > 0)
    pair_cost = round(up_usd / up_shares + down_usd / down_shares, 4) if up_shares > 0 and down_shares > 0 else None
    # Shares actually held on each side (a $0.00 fill holds nothing) and the
    # part of the window that never got a partner.
    up_held = sum(_num(f.get("shares")) for f in fills if f.get("outcome") == "Up" and _num(f.get("price")) > 0)
    down_held = sum(_num(f.get("shares")) for f in fills if f.get("outcome") == "Down" and _num(f.get("price")) > 0)
    single_side = (up_held > 0) != (down_held > 0)

    # Per-minute queue verdicts for the cadence matrix. Only audited maker fills
    # carry a verdict (a taker fill takes the ask, so the queue cannot block it).
    m_attainable = [0, 0, 0, 0, 0]
    m_phantom = [0, 0, 0, 0, 0]
    for f in fills:
        ok = (f.get("detail") or {}).get("attainable")
        if ok is None or role_of(f) == "TAKER":
            continue
        try:
            m = int(f.get("minute", 0))
        except (TypeError, ValueError):
            m = 0
        if 0 <= m <= 4:
            (m_attainable if ok else m_phantom)[m] += 1

    return {
        "slug": r.get("event_slug"),
        "market": r.get("market"),
        "startMs": start_ms,
        "trades": len(fills) if fills else int(r.get("trades") or 0),
        "costUsd": round(cost, 2),
        "payoutUsd": round(payout, 2),
        "netUsd": None if pending else round(payout - cost, 2),
        "winner": r.get("winner"),
        "pending": pending,
        "redeemed": bool(r.get("redeemedAt")),
        "bothSides": len(sides) > 1,
        "pairCost": pair_cost,
        "upFills": sum(1 for f in fills if f.get("outcome") == "Up"),
        "downFills": sum(1 for f in fills if f.get("outcome") == "Down"),
        "upShares": round(up_held, 2),
        "downShares": round(down_held, 2),
        # Shares that ended up on both sides, and the lone leg when they did not.
        "pairedShares": round(min(up_held, down_held), 2),
        "singleSide": single_side,
        "singleShares": round(max(up_held, down_held), 2) if single_side else 0.0,
        # Resting orders the loop posted and pulled, when the loop counted them.
        "ordersPosted": r.get("orders_posted"),
        "ordersCancelled": r.get("orders_cancelled"),
        # Maker fills are the ones the tape can corroborate; taker fills cannot
        # be checked at all in paper mode, so the desk reports the split.
        "makerFills": int(r.get("maker_fills") or 0),
        "takerFills": int(r.get("taker_fills") or 0),
        "zeroPriceFills": sum(1 for f in fills if _num(f.get("price")) <= 0),
        "mShape": _minute_shape(fills),
        "mAttainable": m_attainable,
        "mPhantom": m_phantom,
        "feesUsd": round(taker_fees, 4),
        "makerFeeBaseUsd": round(maker_fee_base, 4),
        "verified": {
            "trades": len(verified_fills),
            "costUsd": round(v_cost, 2),
            "payoutUsd": v_payout,
            "netUsd": None if pending else round(v_payout - v_cost, 2),
            "feesUsd": round(v_fees, 4),
            "makerFeeBaseUsd": round(v_maker_base, 4),
            "upFills": v_up,
            "downFills": v_down,
            "zeroPriceFills": v_zero,
        },
        # What the auditor found once the window resolved: None when the tape
        # held no print for it, so the desk can tell "not judged" from "zero".
        "fidelity": r.get("fidelity"),
    }
