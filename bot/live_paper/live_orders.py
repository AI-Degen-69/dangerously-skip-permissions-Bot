"""Pure resting-order ladder helpers — no `bot.live_paper` imports."""


def update_maker_order_pure(
    open_orders: dict[str, dict],
    outcome: str,
    px: float,
    shares: float,
    minute: int,
    reason: str,
    sub_reason: str,
    deficit: float,
    ahead: float | None,
    now_ts: float,
    inv: dict[str, dict[str, float]] | None = None,
    unhedged_step_cents: float | None = None,
    order_key: str | None = None,
    max_hedge_px: float | None = None,
) -> tuple[bool, bool]:
    """Place or update a resting Maker bid without chasing falling prices downward.

    Returns (changed, repriced_or_new).
    """
    key = order_key or outcome
    if inv is not None and unhedged_step_cents is not None and float(unhedged_step_cents) > 0:
        opp_outcome = "Down" if outcome == "Up" else "Up"
        if inv[opp_outcome]["shares"] <= 0 and inv[outcome]["shares"] > 0:
            low_px = inv[outcome].get("lowest_price")
            if low_px is not None:
                max_allowed = low_px - (float(unhedged_step_cents) / 100.0) + 1e-6
                if px > max_allowed:
                    return (False, False)

    cur = open_orders.get(key)
    if cur is not None:
        cur_px = float(cur["price"])
        if abs(cur_px - px) < 1e-9:
            if abs(float(cur["shares_left"]) - shares) > 1e-9:
                cur["shares_left"] = shares
                cur["deficit"] = deficit
                return (True, False)
            return (False, False)
        if px < cur_px - 1e-9:
            if max_hedge_px is not None and cur_px > max_hedge_px + 1e-9:
                pass
            else:
                if shares > float(cur["shares_left"]) + 1e-9:
                    cur["shares_left"] = shares
                    cur["deficit"] = deficit
                    return (True, False)
                return (False, False)

    if cur is not None:
        cur.pop("_last_touch_ask_obs", None)
    q_val = float(ahead) if ahead is not None else 0.0
    open_orders[key] = {
        "side": outcome,
        "price": px,
        "shares_left": shares,
        "queue_ahead": q_val,
        "queue_ahead_at_place": q_val,
        "placed_ts": now_ts,
        "reason": reason,
        "sub_reason": sub_reason,
        "minute": minute,
        "deficit": deficit,
    }
    return (True, True)


def ladder_keys_pure(open_orders: dict[str, dict], outcome: str) -> list[str]:
    """Keys of every resting order on one side, best (highest) price first."""
    keys = [k for k, o in open_orders.items() if o.get("side") == outcome]
    return sorted(keys, key=lambda k: -float(open_orders[k]["price"]))


def cancel_side_orders_pure(open_orders: dict[str, dict], outcome: str) -> list[dict]:
    """Pull every rung on one side; returns the pulled orders."""
    pulled = [open_orders.pop(k) for k in ladder_keys_pure(open_orders, outcome)]
    return pulled


def prune_pre_sweep_orders_pure(open_orders: dict[str, dict]) -> list[dict]:
    """Cancel pre-sweep non-hedge orders during sweep."""
    stale_keys = [
        k for k, o in list(open_orders.items())
        if o.get("reason") != "sweep" and o.get("sub_reason") != "rebalance-maker"
    ]
    return [open_orders.pop(k) for k in stale_keys]
