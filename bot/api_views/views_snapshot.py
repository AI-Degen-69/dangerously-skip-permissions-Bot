"""Dashboard summary views: snapshot and KPIs."""

import time
from datetime import datetime, timezone

from bot.api.api_core import is_pending


def build_snapshot(cfg, all_runs, st, markets, *, loop_running, kill_switch, utc_now, bankroll_default=1000.0, resolve_mark=None):
    bankroll = float(cfg.get("bankrollUsd", bankroll_default))
    settled = [r for r in all_runs if not is_pending(r)]
    realized = round(sum((r.get("net_usd") or 0.0) for r in settled), 2)
    positions: list[dict] = []
    exposure = 0.0
    now_ms = int(time.time() * 1000)
    if st and st.get("fills"):
        by_side: dict[str, list[dict]] = {}
        for f in st["fills"]:
            by_side.setdefault(f["outcome"], []).append(f)
        end_ms = int(st.get("endMs") or now_ms)
        is_resolving = now_ms >= end_ms
        slug = st.get("slug", "")

        curr_market = next((m for m in markets if m.get("slug") == slug), None)
        market_quotes = (curr_market.get("quotes") or {}) if curr_market else {}
        ws_data = st.get("ws") or {}

        for side, fills in by_side.items():
            shares = sum(f["shares"] for f in fills)
            cost = sum(f["usd"] for f in fills)
            avg = cost / shares if shares else 0
            mark = None
            if not is_resolving:
                px = None

                # 1. Check WebSocket live orderbook in state (0ms latency)
                ws_book = ws_data.get(f"{side.lower()}_book") or {}
                if isinstance(ws_book, dict):
                    ws_bid = ws_book.get("best_bid")
                    if ws_bid is not None and 0.0 < float(ws_bid) <= 1.0:
                        px = float(ws_bid)
                    elif ws_book.get("midpoint") is not None and 0.0 < float(ws_book["midpoint"]) <= 1.0:
                        px = float(ws_book["midpoint"])
                    elif ws_book.get("best_ask") is not None and 0.0 < float(ws_book["best_ask"]) <= 1.0:
                        px = float(ws_book["best_ask"])

                # 2. Check quotes from live_markets
                if px is None:
                    side_q = market_quotes.get(side) or {}
                    q_bid = side_q.get("bid")
                    q_ask = side_q.get("ask")
                    if q_bid is not None and 0.0 < float(q_bid) <= 1.0:
                        px = float(q_bid)
                    elif q_ask is not None and 0.0 < float(q_ask) <= 1.0:
                        px = float(q_ask)

                # 3. Fallback: shell-provided quote resolver (client CLOB).
                if px is None and resolve_mark is not None:
                    try:
                        px = resolve_mark(side, slug)
                    except Exception:
                        px = None

                # While the window is running (not resolving), mark is NEVER None.
                # If a positive price exists, use it; otherwise price is 0.0.
                mark = px if px is not None else 0.0

            mv = round(mark * shares, 2) if mark is not None else None
            exposure += cost
            positions.append({
                "id": f"{st['slug']}-{side}", "slug": st["slug"], "interval": "5m",
                "side": side, "shares": round(shares, 2), "entryPrice": round(avg, 4),
                "costUsd": round(cost, 2), "modelProb": 0.5, "edge": 0,
                "entryAtMs": st.get("startedAtMs", now_ms),
                "endMs": end_ms,
                "bid": mark, "mark": mark, "markValueUsd": mv,
                "unrealizedPnlUsd": round(mv - cost, 2) if mv is not None else None,
                "secondsLeft": max(0, round((end_ms - now_ms) / 1000)),
                "stalledSec": None,
                "resolving": is_resolving,
            })
    equity = round(bankroll + realized + sum(p["unrealizedPnlUsd"] or 0 for p in positions), 2)
    risk_cfg = cfg.get("risk", {})
    day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_start_ts = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())

    def _run_ts(r: dict) -> int:
        slug = str(r.get("event_slug", ""))
        tail = slug.rsplit("-", 1)[-1]
        return int(tail) if tail.isdigit() else 0

    def _is_today(r: dict) -> bool:
        ts = _run_ts(r)
        if ts > 0:
            return ts >= day_start_ts
        return str(r.get("event_slug", "")).endswith(day_key)

    today = [r for r in all_runs if _is_today(r)]
    prior_settled = [r for r in settled if not _is_today(r)]
    day_start_equity = round(bankroll + sum((r.get("net_usd") or 0.0) for r in prior_settled), 2)

    cum_eq = bankroll
    high_water = bankroll
    for r in sorted(settled, key=_run_ts):
        cum_eq = round(cum_eq + (r.get("net_usd") or 0.0), 2)
        if cum_eq > high_water:
            high_water = cum_eq
    high_water = max(high_water, equity)

    consecutive_losses = 0
    for r in reversed(sorted(settled, key=_run_ts)):
        net_val = r.get("net_usd")
        if net_val is not None and net_val < 0:
            consecutive_losses += 1
        elif net_val is not None and net_val >= 0:
            break

    kills = bool(kill_switch)
    try:
        raw_cap = risk_cfg.get("dailyLossCapUsd")
        daily_loss_cap = float(raw_cap) if raw_cap is not None and float(raw_cap) > 0 else 500.0
    except (ValueError, TypeError):
        daily_loss_cap = 500.0
    daily_loss_pct = round((daily_loss_cap / day_start_equity) * 100, 2) if day_start_equity > 0 else 50.0

    def _to_int(val, default: int) -> int:
        try:
            return int(val) if val is not None else default
        except (ValueError, TypeError):
            return default

    def _to_float(val, default: float) -> float:
        try:
            return float(val) if val is not None else default
        except (ValueError, TypeError):
            return default

    settled_equity = round(bankroll + sum((r.get("net_usd") or 0.0) for r in settled), 2)
    daily_loss_usd = round(max(0.0, day_start_equity - settled_equity), 2)

    from bot import constants as C
    strat = cfg.get("strategy", {})
    strat_id = strat.get("id", C.STRATEGY_ID)
    strat_sym = strat.get("symbol", C.STRATEGY_SYMBOL)
    strat_name = strat.get("name", C.STRATEGY_NAME)
    setup_info = C.STRATEGY_SETUPS.get(strat_id, {})
    strat_sig = setup_info.get("signature", C.STRATEGY_SIGNATURE)
    return {
        "version": 1, "mode": "paper", "asset": cfg.get("asset", "BTC"),
        "strategy": {
            "id": strat_id,
            "symbol": strat_sym,
            "name": strat_name,
            "signature": strat_sig,
        },
        "updatedAt": utc_now, "equityUsd": equity, "bankrollUsd": bankroll,
        "exposureUsd": round(exposure, 2), "cashUsd": round(equity - exposure, 2),
        "realizedPnlUsd": realized,
        "risk": {"dayKey": day_key, "tradesToday": len(today),
                 "tradesTodayByInterval": {"5m": len(today), "15m": 0},
                 "consecutiveLosses": consecutive_losses, "realizedPnlUsd": realized,
                 "dailyLossUsd": daily_loss_usd,
                 "dayStartEquityUsd": day_start_equity, "highWaterEquityUsd": high_water,
                 "halted": kills, "haltReason": "kill-switch-file-present" if kills else None,
                 "cooldownUntilMs": 0},
        "limits": {"maxTradesPerDay": _to_int(risk_cfg.get("maxTradesPerDay"), 288),
                   "maxConsecutiveLosses": _to_int(risk_cfg.get("maxConsecutiveLosses"), 99),
                   "dailyLossLimitPct": daily_loss_pct,
                   "dailyLossCapUsd": daily_loss_cap,
                   "maxDrawdownPct": _to_float(risk_cfg.get("maxDrawdownPct"), 90.0),
                   "maxConcurrentPositions": _to_int(risk_cfg.get("maxConcurrentPositions"), 1),
                   "minEdge": 0, "feeRate": 0, "profitTargetCents": 100},
        "killSwitch": kills, "newsBlocked": False,
        "feed": {"price": None, "updatedAtMs": None, "history": []},
        "lean": (st or {}).get("lean"),
        "leanSource": (st or {}).get("leanSource"),
        "markets": markets, "positions": positions,
        # Resting bids from the live window: shown as orders, not as fills.
        "openOrders": (st or {}).get("openOrders") or [],
        "ws": (st or {}).get("ws") or {
            "state": "disconnected" if not loop_running else "connecting",
            "is_connected": False,
            "is_stale": False,
            "age_ms": None,
            "reconnect_count": 0,
            "tick_count": 0,
        },
        "recentTicks": (st or {}).get("recentTicks") or [],
    }

def build_kpis(cfg, all_runs, st, bankroll_default=1000.0):
    bankroll = float(cfg.get("bankrollUsd", bankroll_default))
    all_runs = sorted(runs(), key=lambda r: r.get("event_slug", ""))
    settled = [r for r in all_runs if not is_pending(r)]
    nets = [r.get("net_usd", 0) for r in settled if r.get("net_usd") is not None]
    wins = [n for n in nets if n > 0]
    losses = [-n for n in nets if n <= 0]
    cum, series = 0.0, []
    recent = []
    for r in all_runs:
        try:
            ts = int(r["event_slug"].split("-")[-1]) * 1000
        except Exception:
            ts = 0
        if is_pending(r):
            pnl = None
            reason = "awaiting-resolution"
        else:
            cum = round(cum + (r.get("net_usd") or 0.0), 2)
            pnl = r.get("net_usd")
            reason = "paper-resolve"
        series.append({"ts": ts, "equity": round(bankroll + cum, 2)})
        recent.append({"ts": ts,
                       "kind": "settle", "slug": r.get("event_slug"),
                       "interval": "5m", "price": None,
                       "shares": r.get("trades"), "pnlUsd": pnl,
                       "reason": reason, "mode": "paper"})
    open_n = len({f["outcome"] for f in (st.get("fills", []) if st else [])})
    gross_w = sum(wins)
    gross_l = sum(losses)
    return {"kpis": {
        "bankrollUsd": bankroll, "equityUsd": round(bankroll + cum, 2), "netPnlUsd": round(cum, 2),
        "closedTrades": len(settled), "wins": len(wins), "losses": len(losses),
        "winRate": round(len(wins) / len(settled), 4) if settled else 0,
        "profitFactor": round(gross_w / gross_l, 2) if gross_l else (float("inf") if gross_w else 0),
        "avgWinUsd": round(gross_w / len(wins), 2) if wins else 0,
        "avgLossUsd": round(gross_l / len(losses), 2) if losses else 0,
        "largestWinUsd": round(max(wins), 2) if wins else 0,
        "largestLossUsd": round(max(losses), 2) if losses else 0,
        "openPositions": open_n,
        "byInterval": [{"interval": "5m", "trades": len(settled),
                        "wins": len(wins), "pnlUsd": round(cum, 2)}],
        "equitySeries": series, "recentClosed": recent[-12:]}}
