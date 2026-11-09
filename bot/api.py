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
import math
import os
import shutil
import statistics
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.runs import (
    RunWorkspace,
    find_run_id,
    get_active_run_id,
    list_all_runs,
    make_run_id,
    resolve_run_workspace,
    set_active_run_id,
)
from bot import constants as C

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
    if not active:
        return False
    return sel != active


def runs() -> list[dict]:
    sel = get_selected_run_id()
    if sel:
        ws = resolve_run_workspace(sel)
        if ws and ws.windows_dir.exists():
            return ws.list_windows()
        return []
    ws = resolve_run_workspace(None)
    if ws and ws.windows_dir.exists():
        return ws.list_windows()
    out = []
    if RUNS_DIR.exists():
        for p in sorted(RUNS_DIR.glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except Exception:
                continue
    return out


def is_pending(r: dict) -> bool:
    return bool(r.get("pending")) or not r.get("winner")


_LAST_STATE: tuple[str, dict] | None = None


def state() -> dict | None:
    global _LAST_STATE
    if is_view_only():
        return None
    if not STATE_PATH.exists():
        _LAST_STATE = None
        return None
    for _ in range(3):
        try:
            st = json.loads(STATE_PATH.read_text())
            _LAST_STATE = (str(STATE_PATH), st)
            return st
        except Exception:
            time.sleep(0.005)
    if _LAST_STATE and _LAST_STATE[0] == str(STATE_PATH):
        cached = _LAST_STATE[1]
        end_ms = cached.get("endMs")
        if end_ms is None or int(end_ms) > int(time.time() * 1000):
            return cached
        _LAST_STATE = None
    return None


def events(limit: int = 150) -> list[dict]:
    sel = get_selected_run_id()
    if sel:
        ws = resolve_run_workspace(sel)
        target_path = ws.events_file if (ws and ws.events_file.exists()) else None
    else:
        ws = resolve_run_workspace(None)
        target_path = ws.events_file if (ws and ws.events_file.exists()) else EVENTS_PATH
    if not target_path or not target_path.exists():
        return []
    lines = target_path.read_text().splitlines()[-max(limit, 1):]
    out = []
    open_prices: dict[str, float] = {}
    for line in lines:
        try:
            ev = json.loads(line)
            slug = ev.get("slug")
            detail = ev.setdefault("detail", {})
            # Track leg 1 price for pairCost calculation
            if ev.get("reason") == "straddle-open" and slug and "price" in detail:
                try:
                    open_prices[slug] = float(detail["price"])
                except (ValueError, TypeError):
                    pass
            # Normalize legacy reasons if reading past versions
            elif ev.get("reason") == "thesis-intact":
                ev["reason"] = "clip-fill"
                if "bid" in detail:
                    detail["price"] = detail.pop("bid")
            elif ev.get("reason") == "kill-switch-file-present":
                ev["reason"] = "kill-switch-engaged"

            # Normalize kind mappings
            if ev.get("reason") in ("dust-quote", "extreme-price-skip", "no-liquidity", "spread-too-wide"):
                ev["kind"] = "refuse"
            elif ev.get("reason") == "m4-snipe" or (ev.get("kind") in ("entry", "snipe") and ev.get("detail", {}).get("minute") in ("M4", 4)):
                ev["kind"] = "snipe"
                ev["reason"] = "m4-snipe"
            elif ev.get("reason") in ("holding-to-resolution", "too-late-in-window"):
                ev["kind"] = "done"

            # Compute pairCost for hedge-leg if missing
            if ev.get("reason") == "hedge-leg" and "pairCost" not in detail and slug in open_prices and "price" in detail:
                try:
                    detail["pairCost"] = round(open_prices[slug] + float(detail["price"]), 2)
                    detail["leg1Price"] = open_prices[slug]
                except (ValueError, TypeError):
                    pass

            out.append(ev)
        except Exception:
            continue
    return out


def log_event(kind: str, reason: str, **kw) -> None:
    rec = {"ts": utc_now_iso(), "kind": kind, "mode": "paper", "reason": reason, **kw}
    with EVENTS_PATH.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    ws = resolve_run_workspace(None)
    if ws:
        try:
            ws.root.mkdir(parents=True, exist_ok=True)
            with ws.events_file.open("a") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception:
            pass


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


_loop_lock = threading.Lock()


def stop_loop_process(timeout: float = 3.0) -> int | None:
    with _loop_lock:
        pid = loop_running()
        if pid:
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
                else:
                    os.kill(pid, 15)
            except Exception:
                pass
            start_t = time.time()
            while time.time() - start_t < timeout:
                if not loop_running():
                    break
                time.sleep(0.1)
            if os.name != "nt" and loop_running():
                try:
                    os.kill(pid, 9)
                except Exception:
                    pass
            PID_PATH.unlink(missing_ok=True)
            log_event("risk", "loop-stopped", detail={"pid": pid})
        return pid


def start_loop_process(run_id: str | None = None) -> int:
    with _loop_lock:
        existing_pid = loop_running()
        if existing_pid:
            return existing_pid
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        logf = LOG_PATH.open("ab")
        cmd = [sys.executable, "bot/live_paper.py", "--loop"]
        if run_id:
            cmd.extend(["--run-id", run_id])
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT), stdout=logf, stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True)
        PID_PATH.write_text(str(proc.pid))
        if run_id:
            try:
                ws = resolve_run_workspace(run_id)
                if ws:
                    ws.pid_file.write_text(str(proc.pid))
            except Exception:
                pass
        log_event("info", "loop-started", detail={"pid": proc.pid, "runId": run_id})
        return proc.pid


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


_WINDOW_SPEC_CACHE: dict[str, object] = {}
_LAST_MARKETS: list[dict] = []
_ODDS_HISTORY: dict[str, list[dict]] = {}


def live_markets(cfg: dict) -> list[dict]:
    """Current 5m window with live CLOB quotes (public reads only).

    The next window joins at 4:45 (its last 15s), so the page shows one
    panel for most of the window and two only at the handover.
    """
    global _LAST_MARKETS, _ODDS_HISTORY
    from bot.discovery import WINDOW_S, get_window

    c = client()
    out = []
    for s in visible_slots():
        slug = f"btc-updown-5m-{s}"
        spec = _WINDOW_SPEC_CACHE.get(slug)
        if spec is None:
            try:
                spec = get_window(c, slug)
                _WINDOW_SPEC_CACHE[slug] = spec
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
        elapsed = max(0, round((now_ms - start_ms) / 1000))
        elapsed_sec = max(0.0, (now_ms - start_ms) / 1000.0)
        asks = [q["ask"] for q in quotes.values() if q["ask"] is not None]
        bids = [q["bid"] for q in quotes.values() if q["bid"] is not None]
        spread = (min(asks) - max(bids)) if asks and bids else None
        entry = cfg.get("entry", {})
        stop_before = entry.get("stopBeforeCloseSec", C.HARD_CUTOFF_SBC)
        start_buffer = entry.get("startAfterOpenSec", entry.get("openDelaySec", C.WINDOW_OPEN_BUFFER_S))

        curr_state = state()
        has_fills = bool(curr_state and curr_state.get("slug") == slug and curr_state.get("fills"))
        fills_count = len(curr_state["fills"]) if has_fills else 0

        minute_num = min(4, max(0, int(elapsed_sec // 60)))

        if remaining <= stop_before:
            verdict = {"action": "done", "reason": "holding-to-resolution",
                       "detail": {"remainingSec": remaining, "needsSec": stop_before, "fills": fills_count}}
        elif not has_fills and elapsed_sec < start_buffer:
            verdict = {"action": "skip", "reason": "opening-buffer",
                       "detail": {"elapsedSec": elapsed, "needsSec": start_buffer}}
        elif spread is not None and spread > 0.30:
            verdict = {"action": "refuse", "reason": "spread-too-wide",
                       "detail": {"spreadCents": round(spread * 100, 1), "maxCents": 30}}
        elif not asks:
            verdict = {"action": "refuse", "reason": "no-liquidity", "detail": {"side": "both"}}
        elif fills_count == 0:
            verdict = {"action": "enter", "reason": "straddle-open",
                       "detail": {"minute": f"M{minute_num}", "remainingSec": remaining}}
        elif fills_count == 1:
            verdict = {"action": "enter", "reason": "hedge-pending",
                       "detail": {"fills": fills_count, "minute": f"M{minute_num}", "remainingSec": remaining}}
        elif elapsed_sec >= 240 or remaining <= 60:
            verdict = {"action": "snipe", "reason": "m4-snipe",
                       "detail": {"fills": fills_count, "minute": "M4", "remainingSec": remaining}}
        elif fills_count >= 2:
            verdict = {"action": "enter", "reason": "working-fills",
                       "detail": {"fills": fills_count, "minute": f"M{minute_num}", "remainingSec": remaining}}
        else:
            verdict = {"action": "enter", "reason": "working-fills",
                       "detail": {"fills": fills_count, "minute": f"M{minute_num}", "remainingSec": remaining}}

        up_q = quotes.get("Up", {})
        down_q = quotes.get("Down", {})
        up_val = up_q.get("ask") if up_q.get("ask") is not None else up_q.get("bid")
        down_val = down_q.get("ask") if down_q.get("ask") is not None else down_q.get("bid")
        if up_val is not None and down_val is not None and (up_val + down_val) > 0:
            imp_up: float | None = round(up_val / (up_val + down_val), 4)
        elif up_val is not None:
            imp_up = round(up_val, 4)
        elif down_val is not None:
            imp_up = round(1.0 - down_val, 4)
        else:
            imp_up = None

        hist = _ODDS_HISTORY.setdefault(slug, [])
        if imp_up is not None and (not hist or now_ms - hist[-1]["t"] >= 1500):
            hist.append({"t": now_ms, "v": imp_up})
            if len(hist) > 500:
                hist.pop(0)

        out.append({
            "slug": slug, "interval": "5m", "startMs": start_ms, "endMs": end_ms,
            "price": None, "anchor": None, "movePct": None, "requiredMovePct": 0,
            "side": None, "quotes": quotes, "modelProb": None, "edge": None,
            "spreadCents": round(spread * 100, 1) if spread is not None else None,
            "secondsRemaining": remaining, "verdict": verdict,
            "oddsHistory": list(hist),
            "lean": curr_state.get("lean") if (curr_state and curr_state.get("slug") == slug) else None,
            "leanSource": curr_state.get("leanSource") if (curr_state and curr_state.get("slug") == slug) else None,
        })
    if len(_ODDS_HISTORY) > 10 or len(_WINDOW_SPEC_CACHE) > 10:
        active_slugs = {f"btc-updown-5m-{s}" for s in visible_slots()}
        for cache in (_ODDS_HISTORY, _WINDOW_SPEC_CACHE):
            for old in list(cache.keys()):
                if old not in active_slugs:
                    cache.pop(old, None)
    now_cutoff_ms = int(time.time() * 1000)
    if out:
        _LAST_MARKETS = out
        return out
    _LAST_MARKETS = [m for m in _LAST_MARKETS if int(m.get("endMs") or 0) > now_cutoff_ms]
    return _LAST_MARKETS


def snapshot() -> dict:
    cfg = load_config()
    bankroll = float(cfg.get("bankrollUsd", BANKROLL_DEFAULT))
    all_runs = runs()
    settled = [r for r in all_runs if not is_pending(r)]
    realized = round(sum((r.get("net_usd") or 0.0) for r in settled), 2)
    st = state()
    try:
        markets = live_markets(cfg)
    except Exception:
        markets = []
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

                # 3. Fallback: query client CLOB if not found yet
                if px is None:
                    try:
                        spec = _WINDOW_SPEC_CACHE.get(slug)
                        if spec is None:
                            from bot.discovery import get_window
                            spec = get_window(client(), slug)
                            _WINDOW_SPEC_CACHE[slug] = spec
                        tid = spec.up_token_id if side == "Up" else spec.down_token_id
                        c = client()
                        try:
                            p = float(c.get_price(token_id=tid, side="SELL"))
                            if 0.0 < p <= 1.0:
                                px = p
                        except Exception:
                            pass
                        if px is None:
                            try:
                                p = float(c.get_price(token_id=tid, side="BUY"))
                                if 0.0 < p <= 1.0:
                                    px = p
                            except Exception:
                                pass
                        if px is None:
                            try:
                                mid = float(c.get_midpoint(token_id=tid))
                                if 0.0 < mid <= 1.0:
                                    px = mid
                            except Exception:
                                pass
                    except Exception:
                        pass

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

    kills = KILL_PATH.exists()
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

    try:
        markets = live_markets(cfg)
    except Exception:
        markets = []
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
        "updatedAt": utc_now_iso(), "equityUsd": equity, "bankrollUsd": bankroll,
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
    pending = is_pending(r)
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

    redeem_due = [w for w in settled if w["winner"] and not w["redeemed"] and (w.get("payoutUsd") or 0) > 0]
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
             "Hold-to-redeem is the strategy: paper only books the win when claimed. Redeem via the Dashboard or run python bot/redeem.py.")
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

    cfg_bankroll = None
    sel = get_selected_run_id()
    if sel:
        ws = resolve_run_workspace(sel)
        if ws:
            meta = ws.read_meta()
            if meta and meta.config_snapshot:
                cfg_bankroll = meta.config_snapshot.get("bankrollUsd")
    if cfg_bankroll is None:
        cfg = load_config()
        if isinstance(cfg, dict):
            cfg_bankroll = cfg.get("bankrollUsd")
    bankroll = _num(cfg_bankroll, default=float(BANKROLL_DEFAULT))

    wins = [n for n in nets if n > 0]
    losses = [-n for n in nets if n < 0]
    wins_count = len(wins)
    losses_count = len(losses)
    gross_profit = round(sum(wins), 2)
    gross_loss = round(sum(losses), 2)
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
    avg_win = round(gross_profit / wins_count, 2) if wins_count > 0 else 0.0
    avg_loss = round(gross_loss / losses_count, 2) if losses_count > 0 else 0.0
    payoff_ratio = round(avg_win / avg_loss, 2) if avg_loss > 0 else (99.0 if avg_win > 0 else 0.0)
    win_rate = round(profitable / len(settled), 4) if settled else 0.0
    loss_rate = round(losses_count / len(settled), 4) if settled else 0.0
    expectancy_usd = round(net / len(settled), 2) if settled else 0.0
    expectancy_ratio = round((win_rate * payoff_ratio) - loss_rate, 2) if settled else 0.0
    be_win_rate = round(((wins_count + losses_count) / len(settled)) / (1.0 + payoff_ratio), 4) if (settled and wins_count > 0 and payoff_ratio > 0) else None
    edge_pct = round((win_rate - be_win_rate) * 100, 2) if (settled and be_win_rate is not None) else None

    annual_factor = math.sqrt(288 * 365)
    if len(nets) >= 2:
        mean_net = statistics.mean(nets)
        stdev_net = statistics.stdev(nets)
        sharpe_ratio = round((mean_net / stdev_net) * annual_factor, 2) if stdev_net > 0.0001 else 0.0
        downside = [min(0.0, n) for n in nets]
        downside_variance = sum(d**2 for d in downside) / len(nets)
        downside_std = math.sqrt(downside_variance)
        sortino_ratio = round((mean_net / downside_std) * annual_factor, 2) if downside_std > 0.0001 else (99.0 if mean_net > 0 else 0.0)
    else:
        sharpe_ratio = 0.0
        sortino_ratio = 0.0

    sorted_settled = sorted(settled, key=lambda w: w.get("startMs", 0))
    equity = bankroll
    peak = equity
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    for w in sorted_settled:
        n = w.get("netUsd") or 0.0
        equity += n
        if equity > peak:
            peak = equity
        dd = peak - equity
        dd_pct = dd / peak if peak > 0 else 0.0
        if dd > max_dd_usd:
            max_dd_usd = dd
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
    current_dd_usd = round(max(0.0, peak - equity), 2)
    current_dd_pct = round(current_dd_usd / peak, 4) if peak > 0 else 0.0
    max_dd_usd = round(max_dd_usd, 2)
    max_dd_pct = round(max_dd_pct, 4)

    current_streak = 0
    max_win_streak = 0
    max_loss_streak = 0
    streak = 0
    for w in sorted_settled:
        n = w.get("netUsd") or 0.0
        if n > 0:
            streak = streak + 1 if streak > 0 else 1
            if streak > max_win_streak:
                max_win_streak = streak
        elif n < 0:
            streak = streak - 1 if streak < 0 else -1
            if abs(streak) > max_loss_streak:
                max_loss_streak = abs(streak)
        else:
            streak = 0
    current_streak = streak

    up_windows = [w for w in settled if w.get("winner") == "Up"]
    down_windows = [w for w in settled if w.get("winner") == "Down"]
    up_wins = sum(1 for w in up_windows if (w.get("netUsd") or 0) > 0)
    down_wins = sum(1 for w in down_windows if (w.get("netUsd") or 0) > 0)
    up_net = round(sum(w.get("netUsd") or 0.0 for w in up_windows), 2)
    down_net = round(sum(w.get("netUsd") or 0.0 for w in down_windows), 2)
    up_win_rate = round(up_wins / len(up_windows), 4) if up_windows else 0.0
    down_win_rate = round(down_wins / len(down_windows), 4) if down_windows else 0.0

    strat = cfg.get("strategy", {})
    strat_id = strat.get("id", C.STRATEGY_ID)
    strat_sym = strat.get("symbol", C.STRATEGY_SYMBOL)
    strat_name = strat.get("name", C.STRATEGY_NAME)
    setup_info = C.STRATEGY_SETUPS.get(strat_id, {})
    strat_sig = setup_info.get("signature", C.STRATEGY_SIGNATURE)
    entry_cfg = cfg.get("entry", {})

    return {
        "strategy": {
            "id": strat_id,
            "symbol": strat_sym,
            "name": strat_name,
            "signature": strat_sig,
            "makerShareTarget": C.MAKER_SHARE_TARGET,
            "pairCostTarget": entry_cfg.get("targetPairCost", C.PAIR_COST_TARGET),
            "priceFloor": entry_cfg.get("minFillPrice", C.PRICE_FLOOR),
            "priceCeiling": entry_cfg.get("maxFillPrice", C.PRICE_CEILING),
            "cutoffSec": entry_cfg.get("stopBeforeCloseSec", C.HARD_CUTOFF_SBC),
        },
        "summary": {
            "bankrollUsd": bankroll,
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
            "upWins": up_wins,
            "downWins": down_wins,
            "winRate": win_rate,
            "lossRate": loss_rate,
            "winsCount": wins_count,
            "lossesCount": losses_count,
            "grossProfitUsd": gross_profit,
            "grossLossUsd": gross_loss,
            "profitFactor": profit_factor,
            "avgWinUsd": avg_win,
            "avgLossUsd": avg_loss,
            "payoffRatio": payoff_ratio,
            "expectancyUsd": expectancy_usd,
            "expectancyRatio": expectancy_ratio,
            "breakEvenWinRate": be_win_rate,
            "edgePct": edge_pct,
            "sharpeRatio": sharpe_ratio,
            "sortinoRatio": sortino_ratio,
            "maxDrawdownUsd": max_dd_usd,
            "maxDrawdownPct": max_dd_pct,
            "currentDrawdownUsd": current_dd_usd,
            "currentDrawdownPct": current_dd_pct,
            "currentStreak": current_streak,
            "maxWinStreak": max_win_streak,
            "maxLossStreak": max_loss_streak,
            "upWindows": len(up_windows),
            "downWindows": len(down_windows),
            "upNetUsd": up_net,
            "downNetUsd": down_net,
            "upWinRate": up_win_rate,
            "downWinRate": down_win_rate,
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


def _enrich_fill(f: dict, idx: int, default_ts: int, slug: str | None) -> dict:
    reason = f.get("reason")
    detail = dict(f.get("detail") or {})
    minute = f.get("minute")
    if not reason or reason == "paper-fill":
        if idx == 0 or (minute == 0 and idx == 0):
            reason = "straddle-open"
        elif idx == 1:
            reason = "hedge-leg"
        elif minute == 4:
            reason = "m4-snipe"
        elif minute is not None:
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


def trades_view(limit: int) -> list[dict]:
    out: list[dict] = []
    run_slugs: set[str | None] = set()
    for r in sorted(runs(), key=lambda x: x.get("event_slug", ""))[-12:]:
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
    st = state() or {}
    live_slug = st.get("slug")
    if live_slug and live_slug not in run_slugs:
        base = slot_ms(live_slug)
        for idx, f in enumerate((st.get("fills") or [])[:200]):
            default_ts = base + int(f.get("minute") or 0) * 60_000
            out.append(_enrich_fill(f, idx, default_ts, live_slug))

    out.sort(key=lambda t: int(t.get("ts") or 0))
    return out[-limit:]


EDITABLE = {
    "bankrollUsd": [100, 100000],
    "entry.clipSharesDefault": [1, 50],
    "entry.maxShares": [5, 100],
    "entry.minFillPrice": [0.01, 0.50],
    "entry.maxFillPrice": [0.70, 0.99],
    "entry.benchmarkPairCost": [0.80, 0.99],
    "entry.targetPairCost": [0.80, 0.99],
    "entry.maxPairCost": [0.90, 0.999],
    "entry.maxShareLead": [10, 300],
    "entry.freezeLead": [5, 100],
    "entry.rescuePairCostMax": [0.95, 1.05],
    "entry.rescueCeilingPrice": [0.70, 0.99],
    "entry.startAfterOpenSec": [0, 30],
    "entry.stopBeforeCloseSec": [5, 180],
    "entry.minSpacingMoveSec": [0.1, 5.0],
    "entry.minSpacingStaticSec": [0.5, 10.0],
    "risk.maxUsdPerWindow": [500, 20000],
    "risk.maxFillsPerWindow": [50, 1000],
    "risk.dailyLossCapUsd": [50, 10000],
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
        try:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionError, BrokenPipeError):
            pass

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
                from bot import constants as C
                cfg = load_config()
                strat = cfg.get("strategy", {})
                strat_id = strat.get("id", C.STRATEGY_ID)
                strat_sym = strat.get("symbol", C.STRATEGY_SYMBOL)
                strat_name = strat.get("name", C.STRATEGY_NAME)
                setup_info = C.STRATEGY_SETUPS.get(strat_id, {})
                strat_sig = setup_info.get("signature", C.STRATEGY_SIGNATURE)
                self._send(200, {
                    "running": pid is not None and not view_only,
                    "pid": pid if not view_only else None,
                    "snapshotAgeMs": age,
                    "mode": "paper",
                    "logPath": str(LOG_PATH),
                    "activeRunId": active_id,
                    "selectedRunId": sel_id,
                    "isViewOnly": view_only,
                    "strategy": {
                        "id": strat_id,
                        "symbol": strat_sym,
                        "name": strat_name,
                        "signature": strat_sig,
                    },
                })
            elif url.path == "/api/bot/strategy-setups":
                from bot import constants as C
                cfg = load_config()
                active_id = cfg.get("strategy", {}).get("id", C.STRATEGY_ID)
                setups_list = []
                for sid, sdata in C.STRATEGY_SETUPS.items():
                    item = dict(sdata)
                    item["isActive"] = (sid == active_id)
                    setups_list.append(item)
                self._send(200, {
                    "activeSetupId": active_id,
                    "setups": setups_list,
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
        except (ConnectionError, BrokenPipeError):
            pass
        except Exception as ex:
            try:
                self._send(500, {"error": f"{type(ex).__name__}: {ex}"})
            except Exception:
                pass

    def do_POST(self):
        body = self._body()
        try:
            if self.path == "/api/bot/start":
                req_run_id = body.get("runId")
                resume_requested = body.get("resume", False)
                if req_run_id or resume_requested:
                    if req_run_id:
                        resolved_id = find_run_id(str(req_run_id))
                        if not resolved_id:
                            self._send(404, {"error": f"Run not found: {req_run_id}"})
                            return
                    else:
                        target = get_selected_run_id() or get_active_run_id()
                        resolved_id = find_run_id(str(target)) if target else None

                    if resolved_id:
                        prev_active = get_active_run_id()
                        prev_selected = get_selected_run_id()
                        stop_loop_process()

                        if prev_active and STATE_PATH.exists():
                            try:
                                prev_ws = RunWorkspace(prev_active)
                                if prev_ws.exists():
                                    shutil.copyfile(STATE_PATH, prev_ws.root / "state.json")
                            except Exception:
                                pass

                        try:
                            set_active_run_id(resolved_id)
                            set_selected_run_id(None)
                            ws = RunWorkspace(resolved_id)
                            ws.init_workspace(config=load_config(), mode="paper")
                            ws.sync_to_paper_runs(RUNS_DIR)
                            try:
                                ws.settle_pending_windows(RUNS_DIR, max_windows=15)
                            except Exception:
                                pass
                            if ws.events_file.exists() and ws.events_file.stat().st_size > 0:
                                try:
                                    shutil.copyfile(ws.events_file, EVENTS_PATH)
                                except Exception:
                                    pass
                            else:
                                if EVENTS_PATH.exists():
                                    try:
                                        EVENTS_PATH.unlink()
                                    except Exception:
                                        pass
                            STATE_PATH.unlink(missing_ok=True)
                            KILL_PATH.unlink(missing_ok=True)
                            pid = start_loop_process(run_id=resolved_id)
                        except Exception as err:
                            if prev_active:
                                set_active_run_id(prev_active)
                            if prev_selected:
                                set_selected_run_id(prev_selected)
                            self._send(500, {"error": f"Failed to start run {resolved_id}: {err}"})
                            return

                        self._send(200, {"running": True, "pid": pid, "runId": resolved_id, "activeRunId": resolved_id, "isViewOnly": False})
                        return

                if is_view_only():
                    self._send(400, {
                        "error": "Cannot start bot while inspecting a past run in view-only mode. Use 'Resume run' or switch back to live run first.",
                        "isViewOnly": True,
                    })
                    return
                if loop_running():
                    self._send(200, {"running": True, "pid": loop_running(), "reason": "already-running"})
                    return
                active_id = get_active_run_id()
                pid = start_loop_process(run_id=active_id)
                self._send(200, {"running": True, "pid": pid, "runId": active_id})
            elif self.path == "/api/bot/resume-run":
                target = body.get("runId") or get_selected_run_id() or get_active_run_id()
                if not target:
                    self._send(400, {"error": "No runId specified or selected to resume"})
                    return
                resolved_id = find_run_id(str(target))
                if not resolved_id:
                    self._send(404, {"error": f"Run {target} not found"})
                    return
                ws = RunWorkspace(resolved_id)
                if not ws.exists():
                    self._send(404, {"error": f"Run workspace {resolved_id} does not exist"})
                    return

                prev_active = get_active_run_id()
                prev_selected = get_selected_run_id()
                stop_loop_process()

                if prev_active and STATE_PATH.exists():
                    try:
                        prev_ws = RunWorkspace(prev_active)
                        if prev_ws.exists():
                            shutil.copyfile(STATE_PATH, prev_ws.root / "state.json")
                    except Exception:
                        pass

                try:
                    set_active_run_id(resolved_id)
                    set_selected_run_id(None)
                    ws.init_workspace(config=load_config(), mode="paper")
                    ws.sync_to_paper_runs(RUNS_DIR)
                    try:
                        ws.settle_pending_windows(RUNS_DIR, max_windows=15)
                    except Exception:
                        pass
                    if ws.events_file.exists() and ws.events_file.stat().st_size > 0:
                        try:
                            shutil.copyfile(ws.events_file, EVENTS_PATH)
                        except Exception:
                            pass
                    else:
                        if EVENTS_PATH.exists():
                            try:
                                EVENTS_PATH.unlink()
                            except Exception:
                                pass
                    STATE_PATH.unlink(missing_ok=True)
                    KILL_PATH.unlink(missing_ok=True)

                    pid = start_loop_process(run_id=resolved_id)
                except Exception as err:
                    if prev_active:
                        set_active_run_id(prev_active)
                    if prev_selected:
                        set_selected_run_id(prev_selected)
                    self._send(500, {"error": f"Failed to resume run {resolved_id}: {err}"})
                    return

                self._send(200, {
                    "running": True,
                    "pid": pid,
                    "runId": resolved_id,
                    "activeRunId": resolved_id,
                    "isViewOnly": False,
                })
            elif self.path == "/api/bot/stop":
                if is_view_only():
                    self._send(400, {"error": "Cannot stop bot while in view-only mode", "isViewOnly": True})
                    return
                pid = stop_loop_process()
                active_id = get_active_run_id()
                if active_id:
                    ws = RunWorkspace(active_id)
                    if ws.exists():
                        ws.finalize(status="interrupted", summary=perf().get("summary", {}))
                self._send(200, {"running": False, "pid": None})
            elif self.path == "/api/bot/select-run":
                target_run_id = body.get("runId")
                if target_run_id and isinstance(target_run_id, str) and target_run_id.strip():
                    raw_id = target_run_id.strip()
                    try:
                        ws = RunWorkspace(raw_id)
                    except ValueError:
                        self._send(400, {"error": f"Invalid runId: {raw_id}"})
                        return
                    if not ws.exists():
                        self._send(404, {"error": f"Run {raw_id} not found"})
                        return
                    if ws.run_id == get_active_run_id():
                        set_selected_run_id(None)
                    else:
                        set_selected_run_id(ws.run_id)
                else:
                    # Switch back to live
                    set_selected_run_id(None)
                self._send(200, {
                    "selectedRunId": get_selected_run_id() or get_active_run_id(),
                    "activeRunId": get_active_run_id(),
                    "isViewOnly": is_view_only(),
                })
            elif self.path == "/api/bot/reset":
                if is_view_only():
                    self._send(400, {"error": "Cannot reset while in view-only mode", "isViewOnly": True})
                    return
                for p in RUNS_DIR.glob("*.json"):
                    p.unlink()
                active_ws = resolve_run_workspace(None)
                if active_ws and active_ws.windows_dir.exists():
                    for p in active_ws.windows_dir.glob("*.json"):
                        p.unlink(missing_ok=True)
                for p in (STATE_PATH, EVENTS_PATH):
                    p.unlink(missing_ok=True)
                global _LAST_STATE, _LAST_MARKETS
                _LAST_STATE = None
                _LAST_MARKETS = []
                _ODDS_HISTORY.clear()
                log_event("risk", "paper-reset", detail={"bankrollUsd": load_config().get("bankrollUsd")})
                self._send(200, {"bankrollUsd": load_config().get("bankrollUsd"), "resetAt": utc_now_iso()})
            elif self.path == "/api/bot/kill-switch":
                if is_view_only():
                    self._send(400, {"error": "Cannot toggle kill-switch while in view-only mode", "isViewOnly": True})
                    return
                if body.get("active"):
                    KILL_PATH.write_text(utc_now_iso())
                    log_event("risk", "kill-switch-engaged")
                else:
                    KILL_PATH.unlink(missing_ok=True)
                self._send(200, {"killSwitch": KILL_PATH.exists()})
            elif self.path == "/api/bot/resume":
                if is_view_only():
                    self._send(400, {"error": "Cannot resume while in view-only mode", "isViewOnly": True})
                    return
                KILL_PATH.unlink(missing_ok=True)
                log_event("info", "entries-resumed")
                self._send(200, {"ok": True, "killSwitch": False})
            elif self.path == "/api/bot/redeem":
                if is_view_only():
                    self._send(400, {
                        "error": "Cannot redeem windows while in view-only mode. Switch back to live run first.",
                        "isViewOnly": True,
                    })
                    return
                from bot.redeem import execute_redeem
                sel_run = get_selected_run_id()
                try:
                    res = execute_redeem(run_id=sel_run, dry_run=False)
                    self._send(200, res)
                except ValueError as err:
                    self._send(400, {"error": str(err)})
            elif self.path == "/api/bot/strategy-setup":
                from bot import constants as C
                setup_id = body.get("setupId")
                if setup_id not in C.STRATEGY_SETUPS:
                    self._send(400, {"error": f"Unknown setupId: {setup_id}. Valid setups: {list(C.STRATEGY_SETUPS.keys())}"})
                    return
                setup = C.STRATEGY_SETUPS[setup_id]
                cfg = load_config()
                cfg["strategy"] = {
                    "id": setup["id"],
                    "symbol": setup["symbol"],
                    "name": setup["name"],
                }
                cfg.setdefault("entry", {}).update(setup["entry"])
                tmp_cfg = CONFIG_PATH.with_suffix(".tmp")
                tmp_cfg.write_text(json.dumps(cfg, indent=2))
                tmp_cfg.replace(CONFIG_PATH)

                # Update state.json if present
                if STATE_PATH.exists():
                    try:
                        with open(STATE_PATH, "r", encoding="utf-8") as sf:
                            st_data = json.load(sf)
                        st_data["strategy"] = cfg["strategy"]
                        tmp_st = STATE_PATH.with_suffix(".tmp")
                        tmp_st.write_text(json.dumps(st_data, indent=2))
                        tmp_st.replace(STATE_PATH)
                    except Exception:
                        pass

                log_event("info", "strategy-setup-switched",
                          detail={"setupId": setup_id, "symbol": setup["symbol"], "name": setup["name"]})
                self._send(200, {
                    "ok": True,
                    "activeSetupId": setup_id,
                    "setup": setup,
                    "config": self._config_view(),
                })
            else:
                self._send(404, {"error": "not found"})
        except (ConnectionError, BrokenPipeError):
            pass
        except Exception as ex:
            try:
                self._send(500, {"error": f"{type(ex).__name__}: {ex}"})
            except Exception:
                pass

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
            write_path(cfg, path, value)
        if isinstance(patch.get("news.events"), list):
            cfg.setdefault("news", {})["events"] = patch["news.events"]
        tmp_cfg = CONFIG_PATH.with_suffix(".tmp")
        tmp_cfg.write_text(json.dumps(cfg, indent=2))
        tmp_cfg.replace(CONFIG_PATH)
        log_event("info", "config-updated", detail={"warnings": warnings})
        self._send(200, {"config": self._config_view(), "warnings": warnings})

    def _config_view(self) -> dict:
        cfg = load_config()
        entry = {
            "startAfterOpenSec": 4,
            "stopBeforeCloseSec": 12,
            "clipSharesDefault": 30,
            "maxShares": 50,
            "minFillPrice": 0.07,
            "maxFillPrice": 0.975,
            "benchmarkPairCost": 0.965,
            "targetPairCost": 0.965,
            "maxPairCost": 0.990,
            "maxShareLead": 90,
            "minSpacingMoveSec": 0.5,
            "minSpacingStaticSec": 2.5,
            "includeTakerFee": True,
            "wholeLadderClips": True,
            **cfg.get("entry", {}),
        }
        risk_raw = cfg.get("risk", {})
        try:
            raw_cap = risk_raw.get("dailyLossCapUsd")
            daily_loss_cap = float(raw_cap) if raw_cap is not None and float(raw_cap) > 0 else 500.0
        except (ValueError, TypeError):
            daily_loss_cap = 500.0
        bankroll = float(cfg.get("bankrollUsd", BANKROLL_DEFAULT))
        calc_pct = round((daily_loss_cap / bankroll) * 100, 2) if bankroll > 0 else 50.0
        risk = {
            "maxUsdPerWindow": 4000,
            "maxFillsPerWindow": 500,
            "dailyLossCapUsd": daily_loss_cap,
            "maxConcurrentPositions": 1,
            "maxTradesPerDay": 288,
            "maxConsecutiveLosses": 99,
            "dailyLossLimitPct": calc_pct,
            "maxDrawdownPct": 90,
            "cooldownAfterLossSec": 0,
            **risk_raw,
        }
        news = cfg.get("news", {})
        return {
            "asset": cfg.get("asset", "BTC"),
            "intervals": ["5m"],
            "mode": "paper",
            "bankrollUsd": cfg.get("bankrollUsd", BANKROLL_DEFAULT),
            "entry": entry,
            "risk": risk,
            "news": {"blackoutMinutes": news.get("blackoutMinutes", 0), "events": news.get("events", [])},
            "intervalParams": {
                "5m": {
                    "observationSeconds": entry.get("startAfterOpenSec", 4),
                    "minDirectionHoldSeconds": 0,
                    "minRemainingSeconds": entry.get("stopBeforeCloseSec", 12),
                    "stallSeconds": 0,
                },
            },
        }


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        ex = sys.exc_info()[1]
        if isinstance(ex, (ConnectionError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def main() -> None:
    """Run loopback desk API server."""
    ap = argparse.ArgumentParser(description="Paper desk API (loopback only)")
    ap.add_argument("--port", type=int, default=8789)
    args = ap.parse_args()
    try:
        server = QuietThreadingHTTPServer(("127.0.0.1", args.port), Handler)
        print(f"paper desk API on http://127.0.0.1:{args.port} (loopback only, no keys)", flush=True)
        server.serve_forever()
    except Exception as ex:
        print(f"API server exit: {type(ex).__name__}: {ex}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
