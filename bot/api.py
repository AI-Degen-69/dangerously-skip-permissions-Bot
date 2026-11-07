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
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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


def runs() -> list[dict]:
    out = []
    if RUNS_DIR.exists():
        for p in sorted(RUNS_DIR.glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except Exception:
                continue
    return out


def state() -> dict | None:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return None


def events(limit: int = 150) -> list[dict]:
    if not EVENTS_PATH.exists():
        return []
    lines = EVENTS_PATH.read_text().splitlines()[-max(limit, 1):]
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


def live_markets(cfg: dict) -> list[dict]:
    """Current + next 5m window with live CLOB quotes (public reads only)."""
    from bot.discovery import WINDOW_S, current_slot, get_window

    c = client()
    slot = current_slot()
    out = []
    for s in (slot, slot + WINDOW_S):
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


def trades_view(limit: int) -> list[dict]:
    out: list[dict] = []
    for r in sorted(runs(), key=lambda x: x.get("event_slug", ""))[-12:]:
        try:
            rts = int(str(r.get("event_slug", "")).split("-")[-1]) * 1000
        except (ValueError, IndexError):
            rts = 0
        for f in r.get("fills", [])[:200]:
            out.append({"ts": rts, "kind": "entry",
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
    "entry.minFillPrice": [0, 0.5],
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
                snap = snapshot()
                self._send(200, {"online": True, "snapshot": snap, "ageMs": 0})
            elif url.path == "/api/bot/events":
                self._send(200, {"items": events(int(qs.get("limit", ["150"])[0]))})
            elif url.path == "/api/bot/trades":
                self._send(200, {"items": trades_view(int(qs.get("limit", ["80"])[0]))})
            elif url.path == "/api/bot/kpis":
                self._send(200, kpis())
            elif url.path == "/api/bot/control":
                pid = loop_running()
                st = state()
                age = None
                if st and st.get("updatedAtMs"):
                    age = max(0, int(time.time() * 1000) - st["updatedAtMs"])
                self._send(200, {"running": pid is not None, "pid": pid,
                                 "snapshotAgeMs": age, "mode": "paper",
                                 "logPath": str(LOG_PATH)})
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
                self._send(200, {"running": False, "pid": None})
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
