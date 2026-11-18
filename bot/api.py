"""Local desk API for the Up/Down paper bot -- stdlib only, no extra deps.

Serves the exact contract in src/app/lib/bot.ts on loopback
http://127.0.0.1:8789 so the dashboard (Dashboard/Live/Config/Strategy)
works against OUR paper engine: live 5m windows, book-implied odds,
paper fills, replay KPIs.

  python bot/api.py            # serve on 127.0.0.1:8789
  python bot/api.py --port 8789

Backed by: data/config.json, run windows (data/runs/<run_id>/windows/*.json, read
first) with data/windows_mirror/*.json as fallback, data/runs/<run_id>/state.json,
data/runs/<run_id>/events.jsonl (fallback data/events.jsonl). Live market reads via PublicClient (public, no keys).

Shell + pure-domain split: this file owns every patchable seam (paths,
run workspaces, caches, locks, the network client) and orchestrates IO.
bot/api_core.py, bot/api_loop.py, bot/api_markets.py, bot/api_views.py
are pure -- they take explicit arguments and never import bot.api.
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.runs import (
    CONFIG_PATH,
    EVENTS_PATH,
    KILL_PATH,
    LOG_PATH,
    PID_PATH,
    STATE_PATH as FALLBACK_STATE_PATH,
    WINDOWS_MIRROR_DIR,
    RunWorkspace,
    ensure_data_dir,
    find_run_id,
    get_active_run_id,
    list_all_runs,
    make_run_id,
    migrate_windows_mirror,
    resolve_run_workspace,
    set_active_run_id,
)
from bot import constants as C

from bot.atomic_write import atomic_write_json
from bot import api_core as _core
from bot import api_loop as _loop
from bot import api_markets as _markets
from bot import api_views as _views

BOT_DIR = ROOT / "bot"
# Legacy aliases kept patchable for existing tests.
STATE_PATH = FALLBACK_STATE_PATH

BANKROLL_DEFAULT = 1000.0

SELECTED_RUN_ID: str | None = None

_LAST_STATE: tuple[str, dict] | None = None

_client = None

_WINDOW_SPEC_CACHE: dict[str, object] = {}
_LAST_MARKETS: list[dict] = []
_ODDS_HISTORY: dict[str, list[dict]] = {}
_BACKGROUND_SAMPLER_STOP = threading.Event()
_BACKGROUND_SAMPLER_THREAD: threading.Thread | None = None

_loop_lock = threading.Lock()

# --- pure re-exports (no seams to patch) ---
utc_now_iso = _core.utc_now_iso
session_label = _core.session_label
is_pending = _core.is_pending
_num = _views._num
_minute_shape = _views._minute_shape
_median = _views._median
_mean = _views._mean
slot_ms = _views.slot_ms
_enrich_fill = _views._enrich_fill
_win_alive = _loop._win_alive
NEXT_WINDOW_REVEAL_SEC = _markets.NEXT_WINDOW_REVEAL_SEC


def load_config() -> dict:
    return _core.load_config_from_path(CONFIG_PATH, BANKROLL_DEFAULT)


def get_selected_run_id() -> str | None:
    global SELECTED_RUN_ID
    return SELECTED_RUN_ID


def set_selected_run_id(run_id: str | None) -> None:
    global SELECTED_RUN_ID
    SELECTED_RUN_ID = run_id


def is_view_only() -> bool:
    return _core.is_view_only_selected(get_selected_run_id(), get_active_run_id())


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
    return _core.read_mirror_windows(WINDOWS_MIRROR_DIR)


def state() -> dict | None:
    global _LAST_STATE
    if is_view_only():
        return None
    sel = get_selected_run_id()
    if sel:
        return None
    ws = resolve_run_workspace(None)
    target = ws.state_path if ws is not None else STATE_PATH
    if not target.exists():
        _LAST_STATE = None
        return None
    ok, st = _core.try_read_state(target)
    if ok:
        _LAST_STATE = (str(target), st)
        return st
    if _LAST_STATE and _LAST_STATE[0] == str(target):
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
        if ws is None:
            target_path = EVENTS_PATH
        else:
            target_path = ws.events_file if ws.events_file.exists() else None
    if not target_path or not target_path.exists():
        return []
    lines = target_path.read_text().splitlines()[-max(limit, 1):]
    return _core.normalize_event_lines(lines)


def log_event(kind: str, reason: str, **kw) -> None:
    rec = _core.build_log_record(kind, reason, utc_now_iso(), **kw)
    ws = resolve_run_workspace(None)
    if ws is not None:
        try:
            ws.root.mkdir(parents=True, exist_ok=True)
            with ws.events_file.open("a") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception:
            pass
    else:
        try:
            ensure_data_dir()
            with EVENTS_PATH.open("a") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception:
            pass


def reset_paper_state() -> dict:
    """Clear paper state so post-reset reads cannot restore pre-reset results.

    Always clears the mirrored windows. With an active workspace, also clears
    that workspace's windows dir and state file (runs() reads the workspace
    first). Without a workspace, deletes the fallback STATE_PATH that state()
    would otherwise read back. Per-file guarded; view-only guard stays with
    the HTTP handler.
    """
    cleared = {"mirror": 0, "workspace_windows": 0, "state": False}
    for p in WINDOWS_MIRROR_DIR.glob("*.json"):
        try:
            p.unlink(missing_ok=True)
            cleared["mirror"] += 1
        except Exception:
            pass
    active_ws = resolve_run_workspace(None)
    if active_ws is not None:
        try:
            if active_ws.state_path.exists():
                active_ws.state_path.unlink(missing_ok=True)
                cleared["state"] = True
        except Exception:
            pass
        try:
            wdir = active_ws.windows_dir
            if wdir.exists():
                for p in wdir.glob("*.json"):
                    try:
                        p.unlink(missing_ok=True)
                        cleared["workspace_windows"] += 1
                    except Exception:
                        pass
        except Exception:
            pass
    else:
        try:
            if STATE_PATH.exists():
                STATE_PATH.unlink(missing_ok=True)
                cleared["state"] = True
        except Exception:
            pass
    global _LAST_STATE, _LAST_MARKETS
    _LAST_STATE = None
    _LAST_MARKETS = []
    _ODDS_HISTORY.clear()
    return cleared

def loop_running() -> int | None:
    pid = _loop.parse_pid_file(PID_PATH)
    if pid is None:
        return None
    return pid if _loop.pid_is_alive(pid, _win_alive) else None


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
        ensure_data_dir()
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        logf = LOG_PATH.open("ab")
        proc = subprocess.Popen(
            _loop.build_loop_command(run_id),
            cwd=str(ROOT), stdout=logf, stderr=subprocess.STDOUT,
            env=_loop.loop_env(),
            start_new_session=True)
        ensure_data_dir()
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


def tape_status() -> dict:
    run_id = get_active_run_id()
    stats: dict = {"prints": 0, "books": 0, "printsBytes": 0, "bookBytes": 0, "mb": 0.0, "tapeDir": None}
    if run_id:
        try:
            ws = resolve_run_workspace(run_id)
            if ws:
                stats = ws.tape_stats()
        except Exception:
            pass
    cur = state()
    fills = (cur.get("fills") or []) if cur else []
    return _loop.summarize_tape(run_id, stats, fills)


def client():
    global _client
    if _client is None:
        from polymarket import PublicClient
        _client = PublicClient()
    return _client


def visible_slots(now_ts: int | None = None) -> list[int]:
    return _markets.visible_slots(now_ts)


def _background_odds_sampler() -> None:
    while not _BACKGROUND_SAMPLER_STOP.is_set():
        try:
            st = state()
            if st and st.get("slug") and st.get("oddsHistory"):
                _ODDS_HISTORY[st["slug"]] = list(st["oddsHistory"])
            elif not is_view_only():
                live_markets(load_config())
        except Exception:
            pass
        _BACKGROUND_SAMPLER_STOP.wait(1.5)


def start_background_sampler() -> None:
    global _BACKGROUND_SAMPLER_THREAD
    if _BACKGROUND_SAMPLER_THREAD is None or not _BACKGROUND_SAMPLER_THREAD.is_alive():
        _BACKGROUND_SAMPLER_STOP.clear()
        _BACKGROUND_SAMPLER_THREAD = threading.Thread(
            target=_background_odds_sampler,
            daemon=True,
            name="Api-OddsSampler",
        )
        _BACKGROUND_SAMPLER_THREAD.start()


def _resolve_mark(side: str, slug: str):
    from bot.discovery import get_window
    spec = _WINDOW_SPEC_CACHE.get(slug)
    if spec is None:
        spec = get_window(client(), slug)
        _WINDOW_SPEC_CACHE[slug] = spec
    tid = spec.up_token_id if side == "Up" else spec.down_token_id
    c = client()
    try:
        p = float(c.get_price(token_id=tid, side="SELL"))
        if 0.0 < p <= 1.0:
            return p
    except Exception:
        pass
    try:
        p = float(c.get_price(token_id=tid, side="BUY"))
        if 0.0 < p <= 1.0:
            return p
    except Exception:
        pass
    try:
        mid = float(c.get_midpoint(token_id=tid))
        if 0.0 < mid <= 1.0:
            return mid
    except Exception:
        pass
    return None


def live_markets(cfg: dict) -> list[dict]:
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
        verdict = _markets.decide_verdict(
            remaining=remaining, elapsed_sec=elapsed_sec, start_buffer=start_buffer,
            stop_before=stop_before, spread=spread, has_quotes=bool(asks),
            fills_count=fills_count, strategy_id=(cfg.get("strategy") or {}).get("id", ""))
        up_q = quotes.get("Up", {})
        down_q = quotes.get("Down", {})
        up_val = up_q.get("ask") if up_q.get("ask") is not None else up_q.get("bid")
        down_val = down_q.get("ask") if down_q.get("ask") is not None else down_q.get("bid")
        imp_up = _markets.compute_imp_up(up_val, down_val)
        hist = _markets.next_odds_history(
            _ODDS_HISTORY.setdefault(slug, []),
            curr_state.get("oddsHistory") if (curr_state and curr_state.get("slug") == slug) else None,
            now_ms, imp_up)
        _ODDS_HISTORY[slug] = hist
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
        global _LAST_MARKETS
        _LAST_MARKETS = out
        return out
    _LAST_MARKETS = [m for m in _LAST_MARKETS if int(m.get("endMs") or 0) > now_cutoff_ms]
    return _LAST_MARKETS


def _window_row(r: dict) -> dict:
    return _views.build_window_row(r)


def snapshot() -> dict:
    start_background_sampler()
    cfg = load_config()
    try:
        markets = live_markets(cfg)
    except Exception:
        markets = []
    return _views.build_snapshot(
        cfg, runs(), state(), markets,
        loop_running=loop_running() is not None,
        kill_switch=KILL_PATH.exists(),
        utc_now=utc_now_iso(),
        bankroll_default=BANKROLL_DEFAULT,
        resolve_mark=_resolve_mark,
    )


def kpis() -> dict:
    cfg = load_config()
    return _views.build_kpis(cfg, sorted(runs(), key=lambda r: r.get("event_slug", "")), state(), BANKROLL_DEFAULT)


def perf() -> dict:
    sel = get_selected_run_id()
    config_snapshot = None
    if sel:
        try:
            ws = resolve_run_workspace(sel)
            if ws:
                meta = ws.read_meta()
                if meta and meta.config_snapshot:
                    config_snapshot = meta.config_snapshot
        except Exception:
            pass
    cfg = config_snapshot if isinstance(config_snapshot, dict) else load_config()
    return _views.build_perf(
        sorted(runs(), key=lambda r: str(r.get("event_slug", ""))),
        cfg, sel, config_snapshot, loop_running(), state(),
        KILL_PATH.exists(), BANKROLL_DEFAULT, utc_now_iso(),
    )


def trades_view(limit: int) -> list[dict]:
    return _views.build_trades_view(
        sorted(runs(), key=lambda x: x.get("event_slug", "")), state(), limit)


EDITABLE = {
    "bankrollUsd": [100, 100000],
    "entry.clipSharesDefault": [1, 50],
    "entry.maxShares": [5, 100],
    "entry.minFillPrice": [0.01, 0.50],
    "entry.maxFillPrice": [0.40, 0.99],
    "entry.benchmarkPairCost": [0.80, 0.99],
    "entry.targetPairCost": [0.80, 0.99],
    "entry.maxPairCost": [0.90, 0.999],
    "rebate.takerRate": [0, 0.6],
    "entry.rescuePairCostMax": [0.95, 1.05],
    "entry.rescueCeilingPrice": [0.70, 0.99],
    "entry.startAfterOpenSec": [0, 30],
    "entry.stopBeforeCloseSec": [5, 180],
    "entry.minSpacingMoveSec": [0.1, 5.0],
    "entry.minSpacingStaticSec": [0.5, 10.0],
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
        if origin and origin.startswith(("http://localhost:", "http://127.0.0.1:", "http://[::1]:")):
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
                    "tape": tape_status(),
                })
            elif url.path == "/api/bot/tape":
                self._send(200, tape_status())
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
            elif url.path == "/api/bot/ab-test":
                from bot.ab_test import get_ab_test_data
                self._send(200, get_ab_test_data())
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
                # newSession: open a brand-new run (0 windows) under the active strategy.
                new_session = bool(body.get("newSession", False))
                label = session_label(load_config()) if new_session else "default"
                if req_run_id or resume_requested or new_session:
                    if new_session:
                        resolved_id = make_run_id(mode="paper", label=label)
                    elif req_run_id:
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

                        try:
                            set_active_run_id(resolved_id)
                            set_selected_run_id(None)
                            ws = RunWorkspace(resolved_id)
                            ws.init_workspace(config=load_config(), mode="paper", label=label)
                            ws.sync_windows_mirror(WINDOWS_MIRROR_DIR)
                            try:
                                ws.settle_pending_windows(WINDOWS_MIRROR_DIR, max_windows=15)
                            except Exception:
                                pass
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

                try:
                    set_active_run_id(resolved_id)
                    set_selected_run_id(None)
                    ws.init_workspace(config=load_config(), mode="paper")
                    ws.sync_windows_mirror(WINDOWS_MIRROR_DIR)
                    try:
                        ws.settle_pending_windows(WINDOWS_MIRROR_DIR, max_windows=15)
                    except Exception:
                        pass
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
                reset_paper_state()
                log_event("risk", "paper-reset", detail={"bankrollUsd": load_config().get("bankrollUsd")})
                self._send(200, {"bankrollUsd": load_config().get("bankrollUsd"), "resetAt": utc_now_iso()})
            elif self.path == "/api/bot/kill-switch":
                if is_view_only():
                    self._send(400, {"error": "Cannot toggle kill-switch while in view-only mode", "isViewOnly": True})
                    return
                if body.get("active"):
                    ensure_data_dir()
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
                entry_cfg = cfg.setdefault("entry", {})
                # A leftover curve or dollar cap from the previous setup would keep
                # sizing the new one; unrelated entry keys are preserved.
                for _stale_key in (
                    "dipCurve",
                    "clipSchedule",
                    "maxUnhedgedUsd",
                    "maxUnhedgedShares",
                    "takerDipEntryMax",
                    "leg1MaxPrice",
                    "maxLeg1Price",
                    "leg2MaxPrice",
                    "lateRescueStartSec",
                    "lateRescueMaxPairCost",
                    "unhedgedStepCents",
                    "unhedgedProbeShares",
                    "rescuePairCostMax",
                    "rescueCeilingPrice",
                    "maxDepthShares",
                ):
                    entry_cfg.pop(_stale_key, None)
                entry_cfg.update(setup["entry"])
                atomic_write_json(CONFIG_PATH, cfg)

                # Update the active run snapshot if present
                _ws = resolve_run_workspace(None)
                _sp = _ws.state_path if _ws is not None else None
                if _sp is not None and _sp.exists():
                    try:
                        with open(_sp, "r", encoding="utf-8") as sf:
                            st_data = json.load(sf)
                        st_data["strategy"] = cfg["strategy"]
                        atomic_write_json(_sp, st_data)
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
            elif self.path == "/api/bot/ab-test/start":
                from bot.ab_test import start_candidate_test
                res = start_candidate_test(body.get("candidateId"), body.get("baselineRunId"))
                self._send(200, res)
            elif self.path == "/api/bot/ab-test/stop":
                from bot.ab_test import stop_candidate_test
                res = stop_candidate_test()
                self._send(200, res)
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
        atomic_write_json(CONFIG_PATH, cfg)
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
    migrate_windows_mirror()
    try:
        start_background_sampler()
        server = QuietThreadingHTTPServer(("127.0.0.1", args.port), Handler)
        print(f"paper desk API on http://127.0.0.1:{args.port} (loopback only, no keys)", flush=True)
        server.serve_forever()
    except Exception as ex:
        print(f"API server exit: {type(ex).__name__}: {ex}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
