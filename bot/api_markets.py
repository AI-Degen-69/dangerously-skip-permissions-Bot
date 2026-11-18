"""Pure market-math helpers for the desk API.

No imports from bot.api. The shell in bot/api.py owns the network
client, the spec/odds caches, and the background sampler thread, and
passes explicit values into these builders.
"""
import time

NEXT_WINDOW_REVEAL_SEC = 15  # 4:45 into a 5:00 window
STATE_HIST_MAX_AGE_MS = 3_000  # 2x the 1.5 s sampler interval


def visible_slots(now_ts: int | None = None) -> list[int]:
    """Current window only, until its last 15s -- then current + next."""
    from bot.discovery import WINDOW_S, current_slot

    now = int(time.time()) if now_ts is None else now_ts
    slot = current_slot(now)
    if now - slot >= WINDOW_S - NEXT_WINDOW_REVEAL_SEC:
        return [slot, slot + WINDOW_S]
    return [slot]


def decide_verdict(*, remaining: int, elapsed_sec: float, start_buffer, stop_before,
                   spread, has_quotes: bool, fills_count: int, strategy_id: str) -> dict:
    if remaining <= stop_before:
        return {"action": "done", "reason": "holding-to-resolution",
                "detail": {"remainingSec": remaining, "needsSec": stop_before, "fills": fills_count}}
    if not fills_count and elapsed_sec < start_buffer:
        return {"action": "skip", "reason": "opening-buffer",
                "detail": {"elapsedSec": round(elapsed_sec), "needsSec": start_buffer}}
    if spread is not None and spread > 0.30:
        return {"action": "refuse", "reason": "spread-too-wide",
                "detail": {"spreadCents": round(spread * 100, 1), "maxCents": 30}}
    if not has_quotes:
        return {"action": "refuse", "reason": "no-liquidity", "detail": {"side": "both"}}
    minute_num = min(4, max(0, int(elapsed_sec // 60)))
    if fills_count == 0:
        return {"action": "enter", "reason": "straddle-open",
                "detail": {"minute": f"M{minute_num}", "remainingSec": remaining}}
    if fills_count == 1:
        return {"action": "enter", "reason": "hedge-pending",
                "detail": {"fills": fills_count, "minute": f"M{minute_num}", "remainingSec": remaining}}
    if elapsed_sec >= 240 or remaining <= 60:
        snipes = "hydrogen-v2.0" not in str(strategy_id or "")
        action, reason = ("snipe", "m4-snipe") if snipes else ("enter", "working-fills")
        return {"action": action, "reason": reason,
                "detail": {"fills": fills_count, "minute": "M4", "remainingSec": remaining}}
    return {"action": "enter", "reason": "working-fills",
            "detail": {"fills": fills_count, "minute": f"M{minute_num}", "remainingSec": remaining}}


def compute_imp_up(up_val, down_val):
    if up_val is not None and down_val is not None and (up_val + down_val) > 0:
        return round(up_val / (up_val + down_val), 4)
    if up_val is not None:
        return round(up_val, 4)
    if down_val is not None:
        return round(1.0 - down_val, 4)
    return None


def next_odds_history(prior: list[dict], state_hist: list[dict] | None,
                      now_ms: int, imp_up) -> list[dict]:
    hist = list(prior)
    if state_hist and (now_ms - state_hist[-1]["t"]) < STATE_HIST_MAX_AGE_MS:
        return list(state_hist)
    if state_hist:
        hist = list(state_hist)
    if imp_up is not None and (not hist or now_ms - hist[-1]["t"] >= 1500):
        hist.append({"t": now_ms, "v": imp_up})
        if len(hist) > 500:
            hist.pop(0)
    return hist
