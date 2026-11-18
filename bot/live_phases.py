"""Pure phase helpers for `trade_window` — no `bot.live_paper` imports.

The shell (`bot/live_paper.py`) owns workspaces, threads, streamer,
filesystem and clock seams and passes explicit args in here. Everything
below is deterministic given its inputs so the window lifecycle phases
(setup → fill engine → sweep/exit → close) stay unit-testable.
"""

from bot import constants as C


def parse_window_params(entry: dict) -> dict:
    """Timing/pricing/pacing params with the same defaults as `trade_window`."""
    def _f(key, default, alt=None):
        try:
            if alt is not None:
                return float(entry.get(key, entry.get(alt, default)))
            return float(entry.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    def _i(key, default):
        try:
            return max(1, int(entry.get(key, default) or default))
        except (TypeError, ValueError):
            return int(default)

    try:
        max_unhedged_usd = float(entry.get("maxUnhedgedUsd", C.MAX_UNHEDGED_USD))
    except (TypeError, ValueError):
        max_unhedged_usd = C.MAX_UNHEDGED_USD
    try:
        max_unhedged_shares = float(entry.get("maxUnhedgedShares", 0.0) or 0.0)
    except (TypeError, ValueError):
        max_unhedged_shares = 0.0
    ladder_spacing = _f("levelSpacing", 0.02, alt=None) if entry.get("levelSpacing") not in (None, "") else 0.02
    try:
        ladder_spacing = float(entry.get("levelSpacing", 0.02) or 0.02)
    except (TypeError, ValueError):
        ladder_spacing = 0.02

    return {
        "start_after_open": _f("startAfterOpenSec", C.WINDOW_OPEN_BUFFER_S, alt="openDelaySec"),
        "stop_before": _f("stopBeforeCloseSec", C.HARD_CUTOFF_SBC),
        "test_max_fills": entry.get("maxWindowFills") or entry.get("medianFillsTarget"),
        "min_fill": max(0.01, _f("minFillPrice", C.PRICE_FLOOR)),
        "max_fill": min(0.99, _f("maxFillPrice", C.PRICE_CEILING)),
        "clip_default": _f("clipSharesDefault", C.CLIP_SHARES_DEFAULT),
        "max_shares": _f("maxShares", C.MAX_SHARES),
        "target_pair_cost": _f("targetPairCost", C.TARGET_PAIR_COST),
        "max_pair_cost": _f("maxPairCost", C.PAIR_COST_MAX),
        "max_unhedged_usd": max_unhedged_usd,
        "max_unhedged_shares": max_unhedged_shares,
        "ladder_levels": _i("levelsPerSide", 1),
        "ladder_spacing": ladder_spacing,
        "dip_curve": entry.get("dipCurve") or None,
        "clip_schedule": entry.get("clipSchedule") or None,
        "rescue_ceiling": _f("rescueCeilingPrice", C.RESCUE_CEILING_PRICE),
        "rescue_max_pair_cost": _f("rescuePairCostMax", C.RESCUE_PAIR_COST_MAX),
        "sweep_before": _f("sweepBeforeCloseSec", C.HARD_CUTOFF_SBC),
        "leg1_max": entry.get("leg1MaxPrice", entry.get("maxLeg1Price", entry.get("maxFillPrice", C.PRICE_CEILING))),
        "leg2_max": entry.get("leg2MaxPrice", None),
        "taker_dip_max": entry.get("takerDipEntryMax", None),
        "late_start": entry.get("lateRescueStartSec", None),
        "late_max": entry.get("lateRescueMaxPairCost", None),
        "unhedged_step_cents": entry.get("unhedgedStepCents", None),
        "unhedged_probe_shares": entry.get("unhedgedProbeShares", None),
        "min_spacing_move": _f("minSpacingMoveSec", 0.5),
        "min_spacing_static": _f("minSpacingStaticSec", 2.5),
        "include_taker_fee": bool(entry.get("includeTakerFee", True)),
        "whole_ladder": bool(entry.get("wholeLadderClips", True)),
    }


def minute_of(slot: int, ts: float) -> int:
    return int(min(max((ts - slot) // 60, 0), 4))


def live_pair_cost(inv: dict) -> float | None:
    if inv["Up"]["shares"] > 0 and inv["Down"]["shares"] > 0:
        return round((inv["Up"]["cost"] / inv["Up"]["shares"]) + (inv["Down"]["cost"] / inv["Down"]["shares"]), 4)
    return None


def open_order_rows(open_orders: dict, now_ms: int) -> list[dict]:
    return [
        {
            "side": o["side"],
            "price": round(float(o["price"]), 4),
            "shares": round(float(o["shares_left"]), 2),
            "queueAhead": round(float(o["queue_ahead"]), 1),
            "placedAtMs": int(float(o["placed_ts"]) * 1000),
            "ageMs": max(0, now_ms - int(float(o["placed_ts"]) * 1000)),
            "minute": o["minute"],
            "subReason": o["sub_reason"],
        }
        for o in open_orders.values()
    ]


def compute_imp_up(up_book: dict, down_book: dict) -> float | None:
    up_val = up_book.get("best_ask") if up_book.get("best_ask") is not None else up_book.get("best_bid")
    down_val = down_book.get("best_ask") if down_book.get("best_ask") is not None else down_book.get("best_bid")
    if up_val is not None and down_val is not None and (up_val + down_val) > 0:
        return round(up_val / (up_val + down_val), 4)
    elif up_val is not None:
        return round(up_val, 4)
    elif down_val is not None:
        return round(1.0 - down_val, 4)
    return None


def next_odds_history(hist: list | None, now_ms: int, slot: int, imp_up: float | None) -> list | None:
    """Pure odds-history append used by the sync thread (1500ms throttle)."""
    if imp_up is None:
        return hist
    hist = list(hist or [])
    if not hist or (now_ms - hist[-1]["t"]) >= 1500:
        slot_start_ms = slot * 1000
        if not hist and abs(now_ms - slot_start_ms) < 15_000:
            hist.append({"t": slot_start_ms, "v": 0.5})
        hist.append({"t": now_ms, "v": imp_up})
        if len(hist) > 500:
            hist.pop(0)
        return hist
    return hist


def classify_trade(n_fills: int, sub_reason: str | None, minute: int, reason: str | None) -> tuple[str, str, str]:
    if n_fills == 0:
        return ("straddle-open", "straddle-open", "entry")
    if n_fills == 1:
        return ("hedge-leg", "hedge-leg", "entry")
    if sub_reason == "rescue-equalizer":
        return ("rescue-hedge", "clip-fill", "hedge")
    if minute == 4 and reason == "m4-snipe":
        return ("m4-snipe", "m4-snipe", "snipe")
    if sub_reason == "hedge-equalizer":
        return ("hedge-equalizer", "clip-fill", "entry")
    if sub_reason == "maker-dip-ladder":
        return ("maker-dip-ladder", "clip-fill", "entry")
    if sub_reason in ("rebalance-taker", "rebalance-maker"):
        return ("balance-topup", "clip-fill", "hedge")
    if sub_reason in ("balance-maker", "balance-probe", "split-ladder-maker", "two-sided-maker"):
        return ("balance-build", "clip-fill", "entry")
    return ("straddle-balance", "clip-fill", "entry")


def desired_ladder_prices(px: float, spacing: float, levels: int) -> list[float]:
    return [round(px - i * spacing, 4) for i in range(levels)]


def unhedged_blocked(inv: dict, outcome: str, price: float, step_cents) -> bool:
    if step_cents is None:
        return False
    try:
        if float(step_cents) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    opp = "Down" if outcome == "Up" else "Up"
    try:
        if inv[opp]["shares"] <= 0 and inv[outcome]["shares"] > 0:
            low_px = inv[outcome].get("lowest_price")
            if low_px is not None:
                max_allowed = low_px - (float(step_cents) / 100.0) + 1e-6
                return price > max_allowed
    except (TypeError, ValueError, KeyError):
        return False
    return False


def is_sweep_phase(now: int, end: int, sweep_end: int, imbalance: float) -> bool:
    return bool(now >= end and now < sweep_end and imbalance > 0.0)


def should_close(now: int, end: int, sweep_end: int, imbalance: float) -> bool:
    return bool(now >= sweep_end or (now >= end and imbalance <= 0.0))


def required_spacing(in_sweep: bool, is_price_move: bool, min_move: float, min_static: float) -> float:
    if in_sweep:
        return 0.5
    return min_move if is_price_move else min_static


def build_close_result(slug: str, market: str, condition_id, fills: list, cost: float,
                       strat_id: str, strat_sym: str, total_fees: float,
                       pair_cost, posted: int, cancelled: int) -> dict:
    maker_count = sum(1 for f in fills if (f.get("detail") or {}).get("role") == "MAKER")
    return {
        "event_slug": slug,
        "market": market,
        "condition_id": condition_id,
        "trades": len(fills),
        "cost_usd": round(cost, 2),
        "payout_usd": None,
        "net_usd": None,
        "winner": None,
        "pending": True,
        "fills": fills,
        "strategy": strat_id,
        "strategy_symbol": strat_sym,
        "maker_fills": maker_count,
        "taker_fills": len(fills) - maker_count,
        "fees_usd": round(total_fees, 2),
        "pair_cost": pair_cost,
        "orders_posted": posted,
        "orders_cancelled": cancelled,
    }


def build_close_snap(slug: str, market: str, condition_id, slot: int, fills: list, cost: float,
                     tape_dir, maker: int, taker: int, fees: float, pair_cost,
                     posted: int, cancelled: int) -> dict:
    return {
        "slug": slug,
        "market": market,
        "condition_id": condition_id,
        "tapeDir": str(tape_dir) if tape_dir else None,
        "slot": slot,
        "fills": fills,
        "cost": round(cost, 2),
        "strategy": C.STRATEGY_ID,
        "strategy_symbol": C.STRATEGY_SYMBOL,
        "maker_fills": maker,
        "taker_fills": taker,
        "fees_usd": round(fees, 2),
        "pair_cost": pair_cost,
        "orders_posted": posted,
        "orders_cancelled": cancelled,
    }
