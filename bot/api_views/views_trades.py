"""Recent-trades view over settled runs plus live state."""

from bot.api.api_core import is_pending
from .views_common import _enrich_fill, slot_ms


def build_trades_view(sorted_runs, live_state, limit: int) -> list[dict]:
    out: list[dict] = []
    run_slugs: set[str | None] = set()
    for r in sorted(sorted_runs, key=lambda x: x.get("event_slug", ""))[-12:]:
        rts = slot_ms(r.get("event_slug", ""))
        run_slugs.add(r.get("event_slug"))
        for idx, f in enumerate(r.get("fills", [])[:200]):
            out.append(_enrich_fill(f, idx, rts, r.get("event_slug")))
        winner = r.get("winner")
        pnl = None if is_pending(r) else r.get("net_usd")
        settle_reason = "awaiting-resolution" if is_pending(r) else ("won" if (pnl or 0) > 0 else "lost" if (pnl or 0) < 0 else "paper-resolve")
        out.append({"ts": rts, "kind": "settle",
                    "slug": r.get("event_slug"), "interval": "5m",
                    "side": winner,
                    "pnlUsd": pnl,
                    "reason": settle_reason,
                    "mode": "paper",
                    "detail": {"winner": winner, "fills": r.get("trades"), "net": pnl}})

    # Open window: its fills live in state.json until the window closes and a
    # run file appears. Without this the table froze on the previous window's
    # "awaiting-resolution" row for the whole next window.
    st = live_state or {}
    live_slug = st.get("slug")
    if live_slug and live_slug not in run_slugs:
        base = slot_ms(live_slug)
        for idx, f in enumerate((st.get("fills") or [])[:200]):
            default_ts = base + int(f.get("minute") or 0) * 60_000
            out.append(_enrich_fill(f, idx, default_ts, live_slug))

    out.sort(key=lambda t: int(t.get("ts") or 0))
    return out[-limit:]
