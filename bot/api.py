"""Local desk API for the Up/Down paper bot — stdlib only, no extra deps.

Serves the exact contract in src/app/lib/bot.ts on loopback
http://127.0.0.1:8789 so the dashboard (Dashboard/Live/Config/Strategy)
works against OUR paper engine: live 5m windows, book-implied odds,
paper fills, replay KPIs.

  python bot/api.py            # serve on 127.0.0.1:8789
  python bot/api.py --port 8789

Backed by: bot/config.json, bot/paper_runs/*.json, bot/state.json,
bot/events.jsonl. Live market reads via PublicClient (public, no keys).
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.runs import (
    RunWorkspace,
    get_active_run_id,
    list_all_runs,
    make_run_id,
    resolve_run_workspace,
    set_active_run_id,
)

BOT_DIR = ROOT / "bot"
CONFIG_PATH = BOT_DIR / "config.json"
RUNS_DIR = BOT_DIR / "paper_runs"
STATE_PATH = BOT_DIR / "state.json"
EVENTS_PATH = BOT_DIR / "events.jsonl"
PID_PATH = BOT_DIR / "loop.pid"
KILL_PATH = BOT_DIR / "kill"
LOG_PATH = BOT_DIR / "loop.log"

BANKROLL_DEFAULT = 1000.0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception:
        return {"bankrollUsd": BANKROLL_DEFAULT, "mode": "paper", "asset": "BTC",
                "intervals": ["5m"], "entry": {}, "risk": {}, "news": {"blackoutMinutes": 0, "events": []}}


SELECTED_RUN_ID: str | None = None


def get_selected_run_id() -> str | None:
    global SELECTED_RUN_ID
    return SELECTED_RUN_ID


def set_selected_run_id(run_id: str | None) -> None:
    global SELECTED_RUN_ID
    SELECTED_RUN_ID = run_id


def is_view_only() -> bool:
    """Returns True if user has selected a historical run or explicit view-only mode."""
    sel = get_selected_run_id()
    if not sel:
        return False
    active = get_active_run_id()
    return sel != active


def runs() -> list[dict]:
    sel = get_selected_run_id()
    ws = resolve_run_workspace(sel)
    if ws and ws.windows_dir.exists():
        ws_runs = ws.list_windows()
        if ws_runs:
            return ws_runs
    out = []
    if RUNS_DIR.exists():
        for p in sorted(RUNS_DIR.glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except Exception:
                continue
    return out


def state() -> dict | None:
    if is_view_only():
        return None
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return None


def events(limit: int = 150) -> list[dict]:
    sel = get_selected_run_id()
    ws = resolve_run_workspace(sel)
    target_path = ws.events_file if (ws and ws.events_file.exists()) else EVENTS_PATH
    if not target_path.exists():
        return []
    lines = target_path.read_text().splitlines()[-max(limit, 1):]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def log_event(kind: str, reason: str, **kw) -> None:
    rec = {"ts": utc_now_iso(), "kind": kind, "mode": "paper", "reason": reason, **kw}
    with EVENTS_PATH.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def _win_alive(pid: int) -> bool:
    import ctypes
    try:
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    except Exception:
        return False
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        return code.value == 259  # STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def loop_running() -> int | None:
    try:
        pid = int(PID_PATH.read_text().strip())
    except Exception:
        return None
    try:
        alive = _win_alive(pid) if os.name == "nt" else (os.kill(pid, 0) is None)
    except Exception:
        return None
    return pid if alive else None


# ---------------------------------------------------------------- live reads

_client = None


def client():
    global _client
    if _client is None:
        from polymarket import PublicClient
        _client = PublicClient()
    return _client


NEXT_WINDOW_REVEAL_SEC = 15  # 4:45 into a 5:00 window


def visible_slots(now_ts: int | None = None) -> list[int]:
    """Current window only, until its last 15s — then current + next.

    The Live page used to carry both panels for the whole window, which
    split attention across a market that had not opened yet.
    """
    from bot.discovery import WINDOW_S, current_slot

    now = int(time.time()) if now_ts is None else now_ts
    slot = current_slot(now)
    if now - slot >= WINDOW_S - NEXT_WINDOW_REVEAL_SEC:
        return [slot, slot + WINDOW_S]
    return [slot]


def live_markets(cfg: dict) -> list[dict]:
    """Current 5m window with live CLOB quotes (public reads only).

    The next window joins at 4:45 (its last 15s), so the page shows one
    panel for most of the window and two only at the handover.
    """
    from bot.discovery import WINDOW_S, get_window

    c = client()
    out = []
    for s in visible_slots():
        slug = f"btc-updown-5m-{s}"
        try:
            spec = get_window(c, slug)
        except Exception:
            continue
        quotes: dict[str, dict[str, float | None]] = {}
        for side, tid in (("Up", spec.up_token_id), ("Down", spec.down_token_id)):
            try:
                ask = float(c.get_price(token_id=tid, side="BUY"))
            except Exception:
                ask = None
            try:
                bid = float(c.get_price(token_id=tid, side="SELL"))
            except Exception:
                bid = None
            quotes[side] = {"bid": bid, "ask": ask}
        now_ms = int(time.time() * 1000)
        start_ms, end_ms = s * 1000, (s + WINDOW_S) * 1000
        remaining = max(0, round((end_ms - now_ms) / 1000))
        asks = [q["ask"] for q in quotes.values() if q["ask"] is not None]
        bids = [q["bid"] for q in quotes.values() if q["bid"] is not None]
        spread = (min(asks) - max(bids)) if asks and bids else None
        entry = cfg.get("entry", {})
        stop_before = entry.get("stopBeforeCloseSec", 15)
        if remaining <= stop_before:
            verdict = {"action": "skip", "reason": "too-late-in-window",
                       "detail": {"remainingSec": remaining, "needsSec": stop_before}}
        elif spread is not None and spread > 0.30:
            verdict = {"action": "skip", "reason": "spread-too-wide",
                       "detail": {"spreadCents": round(spread * 100, 1), "maxCents": 30}}
        elif not asks:
            verdict = {"action": "skip", "reason": "no-liquidity", "detail": {"side": "both"}}
        else:
            # straddle-plus-lean always has a side to take; lean comes from the book
            try:
                up_mid = float(c.get_midpoint(token_id=spec.up_token_id))
                down_mid = float(c.get_midpoint(token_id=spec.down_token_id))
                lean_side = "Up" if up_mid >= down_mid else "Down"
            except Exception:
                lean_side = None
            verdict = {"action": "enter", "reason": "straddle-open",
                       "detail": {"leanSide": lean_side or "even"}}
        out.append({
            "slug": slug, "interval": "5m", "startMs": start_ms, "endMs": end_ms,
            "price": None, "anchor": None, "movePct": None, "requiredMovePct": 0,
            "side": None, "quotes": quotes, "modelProb": None, "edge": None,
            "spreadCents": round(spread * 100, 1) if spread is not None else None,
            "secondsRemaining": remaining, "verdict": verdict,
        })
    return out


def snapshot() -> dict:
    cfg = load_config()
    bankroll = float(cfg.get("bankrollUsd", BANKROLL_DEFAULT))
    all_runs = runs()
    realized = round(sum(r.get("net_usd", 0) for r in all_runs), 2)
    st = state()
    positions: list[dict] = []
    exposure = 0.0
    if st and st.get("fills"):
        by_side: dict[str, list[dict]] = {}
        for f in st["fills"]:
            by_side.setdefault(f["outcome"], []).append(f)
        for side, fills in by_side.items():
            shares = sum(f["shares"] for f in fills)
            cost = sum(f["usd"] for f in fills)
            avg = cost / shares if shares else 0
            # live mark = current BUY price of that side's token
            mark = None
            try:
                from bot.discovery import get_window
                spec = get_window(client(), st["slug"])
                tid = spec.up_token_id if side == "Up" else spec.down_token_id
                mark = float(client().get_price(token_id=tid, side="BUY"))
            except Exception:
                mark = None
            mv = round(mark * shares, 2) if mark is not None else None
            exposure += cost
            positions.append({
                "id": f"{st['slug']}-{side}", "slug": st["slug"], "interval": "5m",
                "side": side, "shares": round(shares, 2), "entryPrice": round(avg, 4),
                "costUsd": round(cost, 2), "modelProb": 0.5, "edge": 0,
                "entryAtMs": st.get("startedAtMs", int(time.time() * 1000)),
                "endMs": st.get("endMs", int(time.time() * 1000)),
                "bid": mark, "mark": mark, "markValueUsd": mv,
                "unrealizedPnlUsd": round(mv - cost, 2) if mv is not None else None,
                "secondsLeft": max(0, round(((st.get("endMs") or 0) - int(time.time() * 1000)) / 1000)),
                "stalledSec": None,
            })
    equity = round(bankroll + realized + sum(p["unrealizedPnlUsd"] or 0 for p in positions), 2)
    risk_cfg = cfg.get("risk", {})
    day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today = [r for r in all_runs if r.get("event_slug", "").endswith(str(day_key)) ]  # best-effort
    kills = KILL_PATH.exists()
    try:
        markets = live_markets(cfg)
    except Exception:
        markets = []
    return {
        "version": 1, "mode": "paper", "asset": cfg.get("asset", "BTC"),
        "updatedAt": utc_now_iso(), "equityUsd": equity, "bankrollUsd": bankroll,
        "exposureUsd": round(exposure, 2), "cashUsd": round(equity - exposure, 2),
        "realizedPnlUsd": realized,
        "risk": {"dayKey": day_key, "tradesToday": len(today),
                 "tradesTodayByInterval": {"5m": len(today), "15m": 0},
                 "consecutiveLosses": 0, "realizedPnlUsd": realized,
                 "dayStartEquityUsd": bankroll, "highWaterEquityUsd": max(bankroll, equity),
                 "halted": kills, "haltReason": "kill-switch-file-present" if kills else None,
                 "cooldownUntilMs": 0},
        "limits": {"maxTradesPerDay": 288, "maxConsecutiveLosses": 99,
                   "dailyLossLimitPct": 50,
                   "maxDrawdownPct": 90, "maxConcurrentPositions": 1,
                   "minEdge": 0, "feeRate": 0, "profitTargetCents": 100},
        "killSwitch": kills, "newsBlocked": False,
        "feed": {"price": None, "updatedAtMs": None, "history": []},
        "markets": markets, "positions": positions,
        "ws": (st or {}).get("ws") or {
            "state": "disconnected" if not loop_running() else "connecting",
            "is_connected": False,
            "is_stale": False,
            "age_ms": None,
            "reconnect_count": 0,
            "tick_count": 0,
        },
        "recentTicks": (st or {}).get("recentTicks") or [],
    }


def kpis() -> dict:
    cfg = load_config()
    bankroll = float(cfg.get("bankrollUsd", BANKROLL_DEFAULT))
    all_runs = sorted(runs(), key=lambda r: r.get("event_slug", ""))
    settled = [r for r in all_runs if not r.get("pending")]
    nets = [r.get("net_usd", 0) for r in settled]
    wins = [n for n in nets if n > 0]
    losses = [-n for n in nets if n <= 0]
    cum, series = 0.0, []
    recent = []
    for r in all_runs:
        try:
            ts = int(r["event_slug"].split("-")[-1]) * 1000
        except Exception:
            ts = 0
        if r.get("pending"):
            pnl = None
            reason = "awaiting-resolution"
        else:
            cum = round(cum + r.get("net_usd", 0), 2)
            pnl = r.get("net_usd")
            reason = "paper-resolve"
        series.append({"ts": ts, "equity": round(bankroll + cum, 2)})
        recent.append({"ts": ts,
                       "kind": "settle", "slug": r.get("event_slug"),
                       "interval": "5m", "price": None,
                       "shares": r.get("trades"), "pnlUsd": pnl,
                       "reason": reason, "mode": "paper"})
    st = state()
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


# ------------------------------------------------------- fidelity + performance


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


def _window_row(r: dict) -> dict:
    """One settled/pending window flattened for the dashboard tables."""
    fills = r.get("fills") or []
    cost = _num(r.get("cost_usd"))
    payout = _num(r.get("payout_usd"))
    pending = bool(r.get("pending")) or not r.get("winner")
    try:
        start_ms = int(str(r.get("event_slug", "")).split("-")[-1]) * 1000
    except (TypeError, ValueError):
        start_ms = 0
    sides = {f.get("outcome") for f in fills if f.get("outcome")}
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
        "upFills": sum(1 for f in fills if f.get("outcome") == "Up"),
        "downFills": sum(1 for f in fills if f.get("outcome") == "Down"),
        "zeroPriceFills": sum(1 for f in fills if _num(f.get("price")) <= 0),
        "mShape": _minute_shape(fills),
    }


def _median(values: list[float]) -> float:
    return round(statistics.median(values), 2) if values else 0.0


def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 2) if values else 0.0


def _band_status(value: float, target: float, tight: float, loose: float) -> str:
    delta = abs(value - target)
    if delta <= target * tight:
        return "pass"
    if delta <= target * loose:
        return "warn"
    return "fail"


def perf() -> dict:
    """Fidelity + performance for the straddle-plus-lean paper loop.

    Everything here is computed from bot/paper_runs/*.json (no network), so the
    desk can answer two questions in one read: how much did the paper loop make,
    and how close is its behaviour to the frozen tape (45 fills, 280/288 both
    sides, $316/$447 cost, M0-M4 shape).
    """
    from bot import constants as C

    rows = [_window_row(r) for r in sorted(runs(), key=lambda r: str(r.get("event_slug", "")))]
    settled = [w for w in rows if not w["pending"]]
    pending = [w for w in rows if w["pending"]]

    cost = round(sum(w["costUsd"] for w in settled), 2)
    payout = round(sum(w["payoutUsd"] for w in settled), 2)
    net = round(payout - cost, 2)
    fills = sum(w["trades"] for w in settled)
    profitable = sum(1 for w in settled if (w["netUsd"] or 0) > 0)
    both = sum(1 for w in settled if w["bothSides"])
    zero_fills = sum(w["zeroPriceFills"] for w in settled)
    up_fills = sum(w["upFills"] for w in settled)
    down_fills = sum(w["downFills"] for w in settled)
    nets = [w["netUsd"] or 0.0 for w in settled]

    median_fills = _median([float(w["trades"]) for w in settled])
    mean_fills = _mean([float(w["trades"]) for w in settled])
    median_cost = _median([w["costUsd"] for w in settled])
    mean_cost = _mean([w["costUsd"] for w in settled])

    live_shape = [0, 0, 0, 0, 0]
    for w in settled:
        for i, n in enumerate(w["mShape"]):
            live_shape[i] += n
    live_total = sum(live_shape) or 1
    live_share = [round(n / live_total, 4) for n in live_shape]
    target_shape = [int(n) for n in C.M_BUCKETS]
    target_total = sum(target_shape)
    target_share = [round(n / target_total, 4) for n in target_shape]
    shape_tv = round(0.5 * sum(abs(a - b) for a, b in zip(live_share, target_share)), 4)

    both_rate = round(both / len(settled), 4) if settled else 0.0
    judged = len(settled) >= 48  # below this the metrics are noise, not a verdict

    def mark(status: str) -> str:
        return status if judged else "sample"

    both_status = "pass" if both_rate >= C.BOTH_SIDES_RATE else ("warn" if both_rate >= 0.93 else "fail")
    shape_status = "pass" if shape_tv <= 0.10 else ("warn" if shape_tv <= 0.20 else "fail")

    gate = [
        {"key": "windows", "label": "Windows settled",
         "value": f"{len(settled)} / {C.NUM_WINDOWS_24H}",
         "target": f"{C.NUM_WINDOWS_24H}",
         "status": "pass" if len(settled) >= C.NUM_WINDOWS_24H else "sample",
         "judged": len(settled) >= C.NUM_WINDOWS_24H,
         "detail": "A full 24h slate is the gate; one JSON per settled window."},
        {"key": "medianFills", "label": "Median fills / window",
         "value": f"{median_fills:g}", "target": f"{C.MEDIAN_TRADES_PER_WINDOW:g}",
         "status": mark(_band_status(median_fills, C.MEDIAN_TRADES_PER_WINDOW, 0.2, 0.35)),
         "judged": judged, "detail": "Tape median ticket count per 5m window."},
        {"key": "bothSides", "label": "Both sides covered",
         "value": f"{both}/{len(settled)}" if settled else "0/0",
         "target": f"{round(C.NUM_WINDOWS_24H * C.BOTH_SIDES_RATE)}/{C.NUM_WINDOWS_24H}",
         "status": mark(both_status), "judged": judged,
         "detail": "The straddle must touch both outcomes, not pick a direction."},
        {"key": "medianCost", "label": "Median cost / window",
         "value": f"${median_cost:,.2f}", "target": f"${C.MEDIAN_USD_PER_WINDOW:,.0f}",
         "status": mark(_band_status(median_cost, C.MEDIAN_USD_PER_WINDOW, 0.25, 0.4)),
         "judged": judged, "detail": "Live spreads run wider than the flat 0.476 model, so cost is watched, not tuned."},
        {"key": "meanCost", "label": "Mean cost / window",
         "value": f"${mean_cost:,.2f}", "target": f"${C.MEAN_USD_PER_WINDOW:,.0f}",
         "status": mark(_band_status(mean_cost, C.MEAN_USD_PER_WINDOW, 0.25, 0.4)),
         "judged": judged, "detail": "Sensitive to the few fat windows in the tape."},
        {"key": "shape", "label": "M0-M4 cadence",
         "value": f"{shape_tv * 100:.1f}% TV", "target": "≤10%",
         "status": mark(shape_status), "judged": judged,
         "detail": "Total-variation distance from the tape's minute mix (3,081/3,821/4,289/3,914/1,750)."},
    ]

    redeem_due = [w for w in settled if w["winner"] and not w["redeemed"]]
    redeem_payout = round(sum(w["payoutUsd"] for w in redeem_due), 2)

    pid = loop_running()
    st = state()
    age_ms = None
    if st and st.get("updatedAtMs"):
        age_ms = max(0, int(time.time() * 1000) - int(st["updatedAtMs"]))
    health = {
        "loopRunning": pid is not None,
        "pid": pid,
        "killSwitch": KILL_PATH.exists(),
        "stateSlug": (st or {}).get("slug"),
        "stateFills": len((st or {}).get("fills") or []),
        "snapshotAgeSec": round(age_ms / 1000, 1) if age_ms is not None else None,
        "windowEndsInSec": max(0, round((int((st or {}).get("endMs") or 0) - time.time() * 1000) / 1000)) if st else None,
    }

    notes: list[dict] = []

    def note(tone: str, title: str, body: str) -> None:
        notes.append({"tone": tone, "title": title, "body": body})

    if not health["loopRunning"]:
        note("warning", "Loop is stopped",
             "No new windows are being taken. Start it from the header; the paper loop runs one window at a time.")
    if health["killSwitch"]:
        note("danger", "Kill switch engaged",
             "Entries stay paused between windows while bot/kill exists. Resume from Live, or `rm bot/kill`.")
    age_s = health["snapshotAgeSec"]
    if health["loopRunning"] and age_s is not None and age_s > 120:
        note("warning", f"Heartbeat is {age_s:.0f}s old",
             "The window may have died mid-fill. Restart the loop — do not delete state.json while it owns the window (assert_single_window).")
    if pending:
        note("info", f"{len(pending)} window{'s' if len(pending) != 1 else ''} still settling",
             "Payout is not final until the market resolves; these are excluded from net, cost and the gate.")
    if redeem_due:
        note("warning", f"{len(redeem_due)} winning window{'s' if len(redeem_due) != 1 else ''} unredeemed (${redeem_payout:,.2f})",
             "Hold-to-redeem is the strategy: paper only books the win when claimed. Run python bot/redeem.py --dry-run, then without the flag.")
    if zero_fills:
        note("danger", f"{zero_fills} fills at $0.00",
             "No capital moved, but they still count toward the fill median and skew the M4 bucket. Fix the late dust path before trusting fill fidelity.")
    if settled and shape_tv > 0.20:
        note("warning", "Cadence is M4-heavy",
             f"Live minute mix {'/'.join(f'{s * 100:.0f}%' for s in live_share)} vs the tape's {'/'.join(f'{s * 100:.0f}%' for s in target_share)}. Late dust quotes are inflating the last bucket.")
    if settled and both < len(settled):
        note("warning", f"{len(settled) - both} single-sided window{'s' if len(settled) - both != 1 else ''}",
             "A missed hedge leg breaks the straddle. Both-sides coverage is a hard fidelity target (280/288).")
    if fills and max(up_fills, down_fills) / fills > 0.75:
        lead = "Up" if up_fills >= down_fills else "Down"
        share = max(up_fills, down_fills) / fills
        note("warning", f"Fill mix is {share * 100:.0f}% {lead}",
             f"{up_fills} Up vs {down_fills} Down fills. The tape tilts about 28%, never this hard — the lean/alternation is not flipping sides the way the strategy expects.")
    if settled:
        roi = net / cost if cost else 0.0
        note("success" if net > 0 else "danger",
             f"Paper net {'+' if net >= 0 else '−'}${abs(net):,.2f} on ${cost:,.2f} staked",
             f"{profitable}/{len(settled)} windows profitable ({roi * 100:+.1f}% on cost). Winners pay $1/share at resolution; there are no sells.")
    if len(settled) < C.NUM_WINDOWS_24H:
        note("info", f"Sample is {len(settled)}/{C.NUM_WINDOWS_24H} windows",
             "Median, cost and cadence drift heavily at this size. python bot/run_paper.py (288 deterministic windows) is the gate until a full live slate exists.")

    severity = {"danger": 0, "warning": 1, "info": 2, "success": 3}
    notes.sort(key=lambda n: severity.get(n["tone"], 9))

    return {
        "summary": {
            "settled": len(settled), "pending": len(pending), "fills": fills,
            "costUsd": cost, "payoutUsd": payout, "netUsd": net,
            "roi": round(net / cost, 4) if cost else 0.0,
            "profitable": profitable,
            "hitRate": round(profitable / len(settled), 4) if settled else 0.0,
            "bothSides": both, "bothSidesRate": both_rate,
            "medianFills": median_fills, "meanFills": mean_fills,
            "medianCostUsd": median_cost, "meanCostUsd": mean_cost,
            "bestUsd": round(max(nets), 2) if nets else 0.0,
            "worstUsd": round(min(nets), 2) if nets else 0.0,
            "zeroPriceFills": zero_fills,
            "upFills": up_fills, "downFills": down_fills,
            "upWins": sum(1 for w in settled if w["winner"] == "Up"),
            "downWins": sum(1 for w in settled if w["winner"] == "Down"),
        },
        "targets": {
            "windows": C.NUM_WINDOWS_24H,
            "medianFills": C.MEDIAN_TRADES_PER_WINDOW,
            "meanFills": C.MEAN_TRADES_PER_WINDOW,
            "medianCostUsd": C.MEDIAN_USD_PER_WINDOW,
            "meanCostUsd": C.MEAN_USD_PER_WINDOW,
            "bothSides": round(C.NUM_WINDOWS_24H * C.BOTH_SIDES_RATE),
        },
        "gate": gate,
        "mShape": {"live": live_shape, "target": target_shape,
                   "liveShare": live_share, "targetShare": target_share, "distance": shape_tv},
        "redeem": {"count": len(redeem_due), "payoutUsd": redeem_payout},
        "health": health,
        "notes": notes,
        "windows": rows,
        "generatedAt": utc_now_iso(),
    }


def slot_ms(slug: str) -> int:
    """Window epoch from a `btc-updown-5m-<epoch>` slug, in ms."""
    try:
        return int(str(slug).split("-")[-1]) * 1000
    except (ValueError, IndexError):
        return 0


def trades_view(limit: int) -> list[dict]:
    out: list[dict] = []
    run_slugs: set[str | None] = set()
    for r in sorted(runs(), key=lambda x: x.get("event_slug", ""))[-12:]:
        rts = slot_ms(r.get("event_slug", ""))
        run_slugs.add(r.get("event_slug"))
        for f in r.get("fills", [])[:200]:
            out.append({"ts": int(f.get("ts") or rts), "kind": "entry",
                        "slug": r.get("event_slug"), "interval": "5m",
                        "side": f.get("outcome"), "shares": f.get("shares"),
                        "price": f.get("price"), "usd": f.get("usd"),
                        "reason": "paper-fill", "mode": "paper"})
        out.append({"ts": rts, "kind": "settle",
                    "slug": r.get("event_slug"), "interval": "5m",
                    "pnlUsd": None if r.get("pending") else r.get("net_usd"),
                    "reason": "awaiting-resolution" if r.get("pending") else "paper-resolve",
                    "mode": "paper",
                    "detail": {"winner": r.get("winner"), "fills": r.get("trades")}})

    # Open window: its fills live in state.json until the window closes and a
    # run file appears. Without this the table froze on the previous window's
    # "awaiting-resolution" row for the whole next window.
    st = state() or {}
    live_slug = st.get("slug")
    if live_slug and live_slug not in run_slugs:
        base = slot_ms(live_slug)
        for f in (st.get("fills") or [])[:200]:
            out.append({"ts": int(f.get("ts") or base + int(f.get("minute") or 0) * 60_000),
                        "kind": "entry", "slug": live_slug, "interval": "5m",
                        "side": f.get("outcome"), "shares": f.get("shares"),
                        "price": f.get("price"), "usd": f.get("usd"),
                        "reason": "paper-fill", "mode": "paper"})

    out.sort(key=lambda t: int(t.get("ts") or 0))
    return out[-limit:]


EDITABLE = {
    "bankrollUsd": [100, 100000],
    "entry.clipSharesDefault": [1, 50],
    "entry.clipEveryNth": [1, 10],
    "entry.medianShares": [1, 50],
    "entry.maxShares": [1, 50],
    "entry.medianFillsTarget": [5, 400],
    "entry.openDelaySec": [0, 120],
    "entry.hedgeDelaySec": [0, 120],
    "entry.stopBeforeCloseSec": [0, 120],
    "entry.minFillPrice": [0.01, 0.5],
    "risk.maxUsdPerWindow": [50, 50000],
    "risk.maxFillsPerWindow": [5, 500],
    "risk.dailyLossCapUsd": [10, 100000],
    "risk.maxConcurrentPositions": [1, 2],
}


def read_path(cfg: dict, path: str):
    cur: object = cfg
    for key in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def write_path(cfg: dict, path: str, value) -> None:
    *head, tail = path.split(".")
    cur = cfg
    for key in head:
        cur = cur.setdefault(key, {})
    cur[tail] = value


class Handler(BaseHTTPRequestHandler):
    server_version = "PaperDesk/1"

    def log_message(self, *a):
        pass

    def _cors(self) -> bool:
        origin = self.headers.get("Origin")
        if origin and (origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:")):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        elif not origin:
            self.send_header("Access-Control-Allow-Origin", "http://localhost:5174")
        return True

    def _send(self, code: int, obj: object) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "content-type, accept")
        self.end_headers()

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            n = 0
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode())
        except Exception:
            return {}

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(url.query)
        try:
            if url.path == "/api/bot/snapshot":
                pid = loop_running()
                st = state()
                age = None
                if st and st.get("updatedAtMs"):
                    age = max(0, int(time.time() * 1000) - int(st["updatedAtMs"]))
                # A stopped loop has nothing live to stream (and no reason to hit
                # the CLOB every 2s), so report offline rather than serving stale
                # state.json as if it were current.
                if not pid:
                    self._send(200, {"online": False, "snapshot": None, "ageMs": age})
                else:
                    self._send(200, {"online": True, "snapshot": snapshot(), "ageMs": age})
            elif url.path == "/api/bot/ws-ticks":
                st = state()
                ws_status = (st or {}).get("ws") or {
                    "state": "disconnected" if not loop_running() else "connecting",
                    "is_connected": False,
                    "is_stale": False,
                    "age_ms": None,
                    "reconnect_count": 0,
                    "tick_count": 0,
                }
                ticks = (st or {}).get("recentTicks") or []
                self._send(200, {"status": ws_status, "ticks": ticks})
            elif url.path == "/api/bot/events":
                self._send(200, {"items": events(int(qs.get("limit", ["150"])[0]))})
            elif url.path == "/api/bot/trades":
                self._send(200, {"items": trades_view(int(qs.get("limit", ["80"])[0]))})
            elif url.path == "/api/bot/kpis":
                self._send(200, kpis())
            elif url.path == "/api/bot/perf":
                self._send(200, perf())
            elif url.path == "/api/bot/control":
                pid = loop_running()
                st = state()
                age = None
                if st and st.get("updatedAtMs"):
                    age = max(0, int(time.time() * 1000) - st["updatedAtMs"])
                active_id = get_active_run_id()
                sel_id = get_selected_run_id() or active_id
                view_only = is_view_only()
                self._send(200, {
                    "running": pid is not None and not view_only,
                    "pid": pid if not view_only else None,
                    "snapshotAgeMs": age,
                    "mode": "paper",
                    "logPath": str(LOG_PATH),
                    "activeRunId": active_id,
                    "selectedRunId": sel_id,
                    "isViewOnly": view_only,
                })
            elif url.path == "/api/bot/runs":
                all_r = list_all_runs()
                active_id = get_active_run_id()
                sel_id = get_selected_run_id() or active_id
                self._send(200, {
                    "runs": all_r,
                    "activeRunId": active_id,
                    "selectedRunId": sel_id,
                    "isViewOnly": is_view_only(),
                })
            elif url.path == "/api/bot/config":
                self._send(200, {"config": self._config_view(), "configFile": str(CONFIG_PATH)})
            else:
                self._send(404, {"error": "not found"})
        except Exception as ex:
            self._send(500, {"error": f"{type(ex).__name__}: {ex}"})

    def do_POST(self):
        body = self._body()
        try:
            if self.path == "/api/bot/start":
                if is_view_only():
                    self._send(400, {
                        "error": "Cannot start bot while inspecting a past run in view-only mode. Switch back to live run first.",
                        "isViewOnly": True,
                    })
                    return
                if loop_running():
                    self._send(200, {"running": True, "pid": loop_running(), "reason": "already-running"})
                    return
                LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                logf = LOG_PATH.open("ab")
                proc = subprocess.Popen(
                    [sys.executable, "bot/live_paper.py", "--loop"],
                    cwd=str(ROOT), stdout=logf, stderr=subprocess.STDOUT,
                    start_new_session=True)
                PID_PATH.write_text(str(proc.pid))
                log_event("info", "loop-started", detail={"pid": proc.pid})
                self._send(200, {"running": True, "pid": proc.pid})
            elif self.path == "/api/bot/stop":
                pid = loop_running()
                if pid:
                    try:
                        if os.name == "nt":
                            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                           capture_output=True)
                        else:
                            os.kill(pid, 15)
                    except Exception:
                        pass
                    PID_PATH.unlink(missing_ok=True)
                    log_event("risk", "loop-stopped", detail={"pid": pid})
                active_id = get_active_run_id()
                if active_id:
                    ws = RunWorkspace(active_id)
                    if ws.exists():
                        ws.finalize(status="completed", summary=perf().get("summary", {}))
                self._send(200, {"running": False, "pid": None})
            elif self.path == "/api/bot/select-run":
                target_run_id = body.get("runId")
                if target_run_id:
                    ws = RunWorkspace(target_run_id)
                    if not ws.exists():
                        self._send(404, {"error": f"Run {target_run_id} not found"})
                        return
                    set_selected_run_id(target_run_id)
                else:
                    # Switch back to live
                    set_selected_run_id(None)
                self._send(200, {
                    "selectedRunId": get_selected_run_id() or get_active_run_id(),
                    "activeRunId": get_active_run_id(),
                    "isViewOnly": is_view_only(),
                })
            elif self.path == "/api/bot/reset":
                for p in RUNS_DIR.glob("*.json"):
                    p.unlink()
                for p in (STATE_PATH, EVENTS_PATH):
                    p.unlink(missing_ok=True)
                log_event("risk", "paper-reset", detail={"bankrollUsd": load_config().get("bankrollUsd")})
                self._send(200, {"bankrollUsd": load_config().get("bankrollUsd"), "resetAt": utc_now_iso()})
            elif self.path == "/api/bot/kill-switch":
                if body.get("active"):
                    KILL_PATH.write_text(utc_now_iso())
                    log_event("risk", "kill-switch-file-present")
                else:
                    KILL_PATH.unlink(missing_ok=True)
                self._send(200, {"killSwitch": KILL_PATH.exists()})
            elif self.path == "/api/bot/resume":
                KILL_PATH.unlink(missing_ok=True)
                log_event("info", "entries-resumed")
                self._send(200, {"ok": True, "killSwitch": False})
            else:
                self._send(404, {"error": "not found"})
        except Exception as ex:
            self._send(500, {"error": f"{type(ex).__name__}: {ex}"})

    def do_PUT(self):
        if self.path != "/api/bot/config":
            self._send(404, {"error": "not found"})
            return
        patch = self._body()
        cfg = load_config()
        warnings: list[str] = []
        for path, value in patch.items():
            if path in ("intervals", "news.events"):
                continue
            bounds = EDITABLE.get(path)
            if bounds and isinstance(value, (int, float)):
                lo, hi = bounds
                if not (lo <= value <= hi):
                    warnings.append(f"{path} clamped to [{lo}, {hi}]")
                    value = min(hi, max(lo, value))
            if path == "entry.leanSource" and value not in ("microprice", "dumb"):
                warnings.append("entry.leanSource must be microprice or dumb")
                continue
            write_path(cfg, path, value)
        if isinstance(patch.get("news.events"), list):
            cfg.setdefault("news", {})["events"] = patch["news.events"]
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
        log_event("info", "config-updated", detail={"warnings": warnings})
        self._send(200, {"config": self._config_view(), "warnings": warnings})

    def _config_view(self) -> dict:
        cfg = load_config()
        entry = {"minEdge": 0, "minModelProb": 0.5, "maxModelProb": 1,
                 "maxEntryPriceCents": 1, "minMovePct": 0, "maxMovePct": 100,
                 "minHourlyRangePct": 0, "tightChopRangeUsd": 0, "maxSpreadCents": 30,
                 "noisePct": 0, "nonLiveAnchorExtraMovePct": 0,
                 "kellyCut": 0.25, "maxPositionPct": 0.08, "feeRate": 0,
                 **cfg.get("entry", {})}
        risk = {"maxConcurrentPositions": 1, "maxTradesPerDay": 288,
                "maxConsecutiveLosses": 99, "dailyLossLimitPct": 50,
                "maxDrawdownPct": 90, "cooldownAfterLossSec": 0,
                **cfg.get("risk", {})}
        news = cfg.get("news", {})
        return {"asset": cfg.get("asset", "BTC"), "intervals": ["5m"],
                "mode": "paper", "bankrollUsd": cfg.get("bankrollUsd", BANKROLL_DEFAULT),
                "entry": entry, "exit": {"profitTargetCents": 1},
                "risk": risk,
                "news": {"blackoutMinutes": news.get("blackoutMinutes", 0),
                         "events": news.get("events", [])},
                "intervalParams": {
                    "5m": {"observationSeconds": entry.get("openDelaySec", 13),
                           "minDirectionHoldSeconds": entry.get("hedgeDelaySec", 15),
                           "minRemainingSeconds": entry.get("stopBeforeCloseSec", 15),
                           "stallSeconds": 0},
                    "15m": {"observationSeconds": 300, "minDirectionHoldSeconds": 60,
                            "minRemainingSeconds": 240, "stallSeconds": 180}}}


def main() -> None:
    ap = argparse.ArgumentParser(description="Paper desk API (loopback only)")
    ap.add_argument("--port", type=int, default=8789)
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"paper desk API on http://127.0.0.1:{args.port} (loopback only, no keys)", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
