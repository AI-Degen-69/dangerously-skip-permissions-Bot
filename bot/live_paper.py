"""Live paper trader — mimics dangerously-skip-permissions on real BTC 5m windows.

Reads LIVE `btc-updown-5m` markets (Gamma discovery + CLOB book), simulates
buy-only straddle-plus-lean fills as if real (paper orders, NO keys, NO
funding — PublicClient only), and resolves each window off the market's own
outcome (winner pays $1/share).

State it maintains for the desk UI (served by bot/api.py):
  bot/state.json    live fills + lean while a window is open
  bot/events.jsonl  decision journal (open / hedge / fill / resolve / skip)
  bot/paper_runs/   one JSON per settled window (fills + net)
  bot/kill          pause entries while present (kill-switch)

Usage:
  python bot/live_paper.py --once        # trade the current/next live window, then exit
  python bot/live_paper.py --loop        # trade every window until Ctrl+C
  python bot/api.py                      # desk API on 127.0.0.1:8788 (start/stop from UI)
"""

import argparse
import json
import re
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, ".")

from polymarket import PublicClient

from bot import constants as C
from bot.discovery import WINDOW_S, current_slot, get_window
from bot.executor import m_quotas, pick_side
from bot.risk import RiskState, assert_single_window, check_window, clip_shares, heartbeat
from bot.runs import RunWorkspace, get_active_run_id, make_run_id, set_active_run_id
from bot.signal import LeanSignal
from bot.ws import LiveBookStreamer

RUNS_DIR = Path("bot/paper_runs")
STATE_PATH = Path("bot/state.json")
EVENTS_PATH = Path("bot/events.jsonl")
CONFIG_PATH = Path("bot/config.json")
KILL_PATH = Path("bot/kill")
CURRENT_WORKSPACE: RunWorkspace | None = None
_STATE_LOCK = threading.Lock()


def get_current_workspace() -> RunWorkspace | None:
    global CURRENT_WORKSPACE
    return CURRENT_WORKSPACE


def init_run_session(run_id: str | None = None, label: str = "default") -> RunWorkspace:
    """Initialize a run-scoped directory and update active run pointer."""
    global CURRENT_WORKSPACE
    rid = run_id or make_run_id(mode="paper", label=label)
    ws = RunWorkspace(rid)
    ws.init_workspace(config=load_cfg(), mode="paper", label=label)
    set_active_run_id(ws.run_id)
    CURRENT_WORKSPACE = ws
    return ws


def load_cfg() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception:
        return {}


def cfg_entry(key: str, default):
    return load_cfg().get("entry", {}).get(key, default)


def log_event(kind: str, reason: str, slug: str | None = None, **kw) -> None:
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind,
           "mode": "paper", "reason": reason}
    if slug:
        rec["slug"] = slug
        rec["interval"] = "5m"
    rec.update(kw)
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    ws = get_current_workspace()
    if ws:
        try:
            ws.root.mkdir(parents=True, exist_ok=True)
            with ws.events_file.open("a") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception:
            pass


def microprice_lean(c: PublicClient, up_id: str, down_id: str, streamer: LiveBookStreamer | None = None) -> LeanSignal:
    """Lean from live book microprice. Neutral when the book is unusable."""
    if load_cfg().get("entry", {}).get("leanSource", "microprice") == "dumb":
        return LeanSignal(lean=0.0, confidence=0.0, source="dumb")
    if streamer is not None:
        try:
            return streamer.get_lean(up_id, down_id)
        except Exception:
            pass
    try:
        up_mid = float(c.get_midpoint(token_id=up_id))
        down_mid = float(c.get_midpoint(token_id=down_id))
    except Exception:
        return LeanSignal(lean=0.0, confidence=0.0, source="book-unavailable")
    edge = (up_mid - down_mid) / 2.0  # >0 favors Up
    raw = edge * 4.0
    lean = max(-1.0, min(1.0, raw))
    spread = abs(up_mid + down_mid - 1.0)
    confidence = max(0.0, min(1.0, 1.0 - spread * 5.0))
    return LeanSignal(lean=lean, confidence=confidence, source="book-microprice", raw=round(raw, 3))


def live_buy_price(c: PublicClient, token_id: str, streamer: LiveBookStreamer | None = None) -> float | None:
    """Best executable BUY price, or None when the book has no usable ask.

    Queries the in-memory WebSocket streamer first. Falls back to REST when
    the streamer is unavailable or has no ask.
    """
    if streamer is not None:
        try:
            px = streamer.get_buy_price(token_id)
            if px is not None and 0.0 < px <= 1.0:
                return px
        except Exception:
            pass
    try:
        px = float(c.get_price(token_id=token_id, side="BUY"))
    except Exception:
        return None
    if not 0.0 < px <= 1.0:
        return None
    return px


def _atomic_write_json(path: Path, data: object) -> None:
    raw = json.dumps(data)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(raw)
    for _ in range(5):
        try:
            tmp.replace(path)
            return
        except OSError:
            time.sleep(0.005)
    try:
        path.write_text(raw)
    except OSError as ex:
        print(f"warning: failed to persist {path}: {ex}", flush=True)


def _settled_net_usd(path: Path, day_start: int) -> float:
    tail = path.stem.rsplit("-", 1)[-1]
    if not tail.isdigit() or int(tail) < day_start:
        return 0.0
    try:
        d = json.loads(path.read_text())
        if not isinstance(d, dict) or d.get("pending"):
            return 0.0
        raw_net = d.get("net_usd")
        return float(raw_net) if raw_net is not None else 0.0
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return 0.0


def _current_daily_pnl(day_start: int) -> float:
    if not RUNS_DIR.exists():
        return 0.0
    return sum(_settled_net_usd(p, day_start) for p in RUNS_DIR.glob("btc-updown-5m-*.json"))


def write_state(
    slug: str,
    end_ms: int,
    started_ms: int,
    fills: list[dict],
    lean: LeanSignal,
    ws_status: dict | None = None,
    recent_ticks: list[dict] | None = None,
) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "slug": slug,
        "endMs": end_ms,
        "startedAtMs": started_ms,
        "updatedAtMs": int(time.time() * 1000),
        "fills": fills,
        "lean": lean.lean,
        "leanSource": lean.source,
    }
    if ws_status is not None:
        payload["ws"] = ws_status
    if recent_ticks is not None:
        payload["recentTicks"] = recent_ticks
    with _STATE_LOCK:
        _atomic_write_json(STATE_PATH, payload)


def _risk_reason_code(raw_reason: str) -> str:
    if "kill-switch" in raw_reason:
        return "kill-switch-engaged"
    if "daily loss cap" in raw_reason:
        return "daily-loss-cap"
    if "cost cap" in raw_reason:
        return "window-cost-cap"
    if "trade cap" in raw_reason:
        return "window-trade-cap"
    return raw_reason


def _risk_detail(raw_reason: str, state: RiskState, cost: float, trades: int) -> dict:
    risk_cfg = load_cfg().get("risk", {})
    default_cap = float(risk_cfg.get("dailyLossCapUsd", 500.0))
    cost_cap = float(risk_cfg.get("maxUsdPerWindow", 4000.0))
    trade_cap = int(risk_cfg.get("maxFillsPerWindow", 500))

    if "daily loss cap" in raw_reason:
        m = re.search(r"daily loss cap \$?([0-9.]+)", raw_reason)
        cap = float(m.group(1)) if m else default_cap
        return {"lossUsd": round(abs(state.daily_loss_usd), 2), "capUsd": cap}
    if "cost cap" in raw_reason:
        m = re.search(r"cost cap \$?([0-9.]+)", raw_reason)
        cap = float(m.group(1)) if m else cost_cap
        return {"costUsd": round(cost, 2), "capUsd": cap}
    if "trade cap" in raw_reason:
        m = re.search(r"trade cap (\d+)", raw_reason)
        cap = int(m.group(1)) if m else trade_cap
        return {"fills": trades, "cap": cap}
    return {}


def trade_window(c: PublicClient, slot: int, origin: str | None, verbose: bool = True) -> dict:
    slug = f"btc-updown-5m-{slot}"
    assert_single_window(slug)  # refuse if a crashed window still owns state
    spec = get_window(c, slug)
    entry = load_cfg().get("entry", {})
    open_delay = entry.get("openDelaySec", 13)
    hedge_delay = entry.get("hedgeDelaySec", 15)
    stop_before = entry.get("stopBeforeCloseSec", 15)
    # Floor the dust guard: minFillPrice is user-editable from the desk, and 0
    # would let $0.00 "fills" back in through the M1-M4 loop.
    min_fill = max(0.01, float(entry.get("minFillPrice", 0.01)))
    clip_default = entry.get("clipSharesDefault", C.CLIP_SHARES_DEFAULT)
    clip_nth = entry.get("clipEveryNth", 3)
    median_shares = entry.get("medianShares", C.MEDIAN_SHARES)
    max_shares = entry.get("maxShares", C.MAX_SHARES)
    target_total = entry.get("medianFillsTarget", int(C.MEDIAN_TRADES_PER_WINDOW))
    min_spacing_move = float(entry.get("minSpacingMoveSec", 0.5))
    min_spacing_static = float(entry.get("minSpacingStaticSec", 3.0))
    day_start = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    state = RiskState(daily_loss_usd=_current_daily_pnl(day_start))
    fills: list[dict] = []
    cost = 0.0
    end_ms = (slot + WINDOW_S) * 1000
    started_ms = int(time.time() * 1000)

    streamer = LiveBookStreamer(
        up_token_id=spec.up_token_id,
        down_token_id=spec.down_token_id,
        rest_fallback_client=c,
    )
    streamer.start()
    write_state(slug, end_ms, started_ms, fills, LeanSignal(0.0, 0.0, "observing"),
                ws_status=streamer.get_status(), recent_ticks=streamer.get_recent_ticks(30))
    stop_sync = threading.Event()

    def _sync_loop():
        while not stop_sync.is_set():
            try:
                with _STATE_LOCK:
                    if STATE_PATH.exists():
                        raw = STATE_PATH.read_text()
                        if isinstance(raw, str):
                            st = json.loads(raw)
                            st["updatedAtMs"] = int(time.time() * 1000)
                            st["ws"] = streamer.get_status()
                            st["recentTicks"] = streamer.get_recent_ticks(30)
                            _atomic_write_json(STATE_PATH, st)
            except (OSError, json.JSONDecodeError, TypeError):
                pass
            stop_sync.wait(1.0)

    sync_thread = threading.Thread(target=_sync_loop, daemon=True, name="WSS-StateSync")
    sync_thread.start()

    def log(msg: str) -> None:
        if verbose:
            print(f"[{slug}] {msg}", flush=True)

    try:
        # --- open: first touch at ~T+13s (median), hedge leg +15s (median) ---
        now = int(time.time())
        open_at = slot + open_delay
        if now < open_at:
            time.sleep(open_at - now)
        lean = microprice_lean(c, spec.up_token_id, spec.down_token_id, streamer=streamer)
        first_up = lean.lean >= 0
        for outcome, tid in (("Up" if first_up else "Down", spec.up_token_id if first_up else spec.down_token_id),
                             ("Down" if first_up else "Up", spec.down_token_id if first_up else spec.up_token_id)):
            px = live_buy_price(c, tid, streamer=streamer)
            if px is None:
                log_event("refuse", "no-liquidity", slug, side=outcome, detail={"side": outcome})
                continue
            if px < min_fill:
                log_event("refuse", "dust-quote", slug, side=outcome,
                          detail={"side": outcome, "price": px, "minFill": min_fill})
                continue
            if outcome != ("Up" if first_up else "Down"):
                time.sleep(hedge_delay)  # hedge leg
                lean = microprice_lean(c, spec.up_token_id, spec.down_token_id, streamer=streamer)
            state.daily_loss_usd = _current_daily_pnl(day_start)
            if reason := check_window(len(fills), cost, state, KILL_PATH):
                log_event("risk", _risk_reason_code(reason), slug,
                          detail=_risk_detail(reason, state, cost, len(fills)))
                break
            shares = clip_shares(clip_default)
            reason = "straddle-open" if len(fills) == 0 else "hedge-leg"
            fills.append({
                "minute": 0, "ts": int(time.time() * 1000), "outcome": outcome,
                "price": px, "shares": shares, "usd": round(px * shares, 2),
                "reason": reason,
                "detail": {"lean": round(lean.lean, 2), "confidence": round(lean.confidence, 2), "minute": 0},
            })
            cost += px * shares
            raw_lean = round(getattr(lean, "raw", None) if getattr(lean, "raw", None) is not None else lean.lean, 2)
            if len(fills) == 1:
                log_event("entry", "straddle-open", slug,
                          side=outcome, detail={"price": px, "shares": shares, "lean": round(lean.lean, 2),
                                                "rawLean": raw_lean,
                                                "fills": 1, "cost": round(cost, 2)})
            else:
                leg1_px = fills[0]["price"] if len(fills) > 1 else 0.0
                pair_cost = round(leg1_px + px, 2)
                log_event("entry", "hedge-leg", slug,
                          side=outcome, detail={"price": px, "shares": shares, "lean": round(lean.lean, 2),
                                                "leg1Price": leg1_px, "pairCost": pair_cost,
                                                "fills": len(fills), "cost": round(cost, 2)})
            log(f"open {outcome} {shares:.0f} @ {px:.3f}")
            write_state(slug, end_ms, started_ms, fills, lean,
                        ws_status=streamer.get_status(), recent_ticks=streamer.get_recent_ticks(30))

        # --- work M1-M3 + M4 snipe: dynamic event-driven fills on live ticks ---
        end = slot + WINDOW_S - stop_before  # stop before close
        last_fill_ts = 0.0
        last_fill_px: float | None = None
        quotas = m_quotas(target_total)
        last_logged_quota_min: int | None = None
        last_extreme_skip_ts: float = 0.0
        last_dust_skip_ts: float = 0.0

        while True:
            now = int(time.time())
            if now >= end:
                up_sh = sum(f["shares"] for f in fills if f["outcome"] == "Up")
                down_sh = sum(f["shares"] for f in fills if f["outcome"] == "Down")
                log_event("done", "holding-to-resolution", slug,
                          detail={"fills": len(fills), "cost": round(cost, 2),
                                  "upShares": round(up_sh, 1), "downShares": round(down_sh, 1)})
                break
            state.daily_loss_usd = _current_daily_pnl(day_start)
            if reason := check_window(len(fills), cost, state, KILL_PATH):
                log_event("risk", _risk_reason_code(reason), slug,
                          detail=_risk_detail(reason, state, cost, len(fills)))
                break

            minute = min(max((now - slot) // 60, 0), 4)
            if len(fills) >= target_total:
                if last_logged_quota_min != 99:
                    last_logged_quota_min = 99
                    log_event("hold", "target-fills-reached", slug,
                              detail={"fills": len(fills), "cost": round(cost, 2)})
                time.sleep(max(0, end - now))
                continue

            if sum(1 for f in fills if f["minute"] == minute) >= quotas[minute]:
                wait_sec = max(0, min(end, slot + (minute + 1) * 60) - now)
                if last_logged_quota_min != minute and wait_sec > 2:
                    last_logged_quota_min = minute
                    min_fills = sum(1 for f in fills if f["minute"] == minute)
                    log_event("hold", "minute-quota-reached", slug,
                              detail={"minute": f"M{minute}", "fills": min_fills, "quota": quotas[minute], "waitSec": round(wait_sec)})
                time.sleep(wait_sec)
                continue

            lean = microprice_lean(c, spec.up_token_id, spec.down_token_id, streamer=streamer)
            outcome = pick_side(len(fills), minute, lean)
            tid = spec.up_token_id if outcome == "Up" else spec.down_token_id
            px = live_buy_price(c, tid, streamer=streamer)
            if px is None:
                streamer.wait_for_tick(timeout=0.25)
                continue
            if px < min_fill:
                log(f"M{minute} {outcome} dust {px:.3f} — skipped")
                if time.time() - last_dust_skip_ts > 10.0:
                    last_dust_skip_ts = time.time()
                    log_event("refuse", "dust-quote", slug, side=outcome,
                              detail={"minute": f"M{minute}", "price": px, "minFill": min_fill})
                streamer.wait_for_tick(timeout=0.25)
                continue
            # M4 snipe: only take extremes late (matches CSV: extremes only in M4)
            if minute < 4 and (px <= 0.15 or px >= 0.85) and len(fills) % 4 != 0:
                if time.time() - last_extreme_skip_ts > 10.0:
                    last_extreme_skip_ts = time.time()
                    log_event("refuse", "extreme-price-skip", slug, side=outcome,
                              detail={"minute": f"M{minute}", "price": px})
                streamer.wait_for_tick(timeout=0.25)
                continue

            # Dynamic anti-runaway gating:
            # If price changed from last fill, allow quick execution (>=min_spacing_move).
            # If price is identical, require orderbook replenishment spacing (>=min_spacing_static).
            time_since_fill = time.time() - last_fill_ts
            is_price_move = (last_fill_px is not None and abs(px - last_fill_px) >= 0.001)
            required_spacing = min_spacing_move if is_price_move else min_spacing_static
            if time_since_fill < required_spacing:
                streamer.wait_for_tick(timeout=0.25)
                continue

            shares = clip_shares(clip_default if len(fills) % clip_nth == 0 else median_shares)
            shares = min(shares, max_shares)

            up_p = 0.5 + lean.lean * 0.25 * (0.5 + 0.5 * lean.confidence)
            if minute == 4 and (px <= 0.15 or px >= 0.85):
                fill_reason = "m4-snipe"
            elif up_p > 0.6 and len(fills) % 3 != 0:
                fill_reason = "lean-up"
            elif up_p < 0.4 and len(fills) % 3 != 0:
                fill_reason = "lean-down"
            else:
                fill_reason = "straddle-balance"

            fills.append({
                "minute": minute, "ts": int(time.time() * 1000), "outcome": outcome,
                "price": px, "shares": shares, "usd": round(px * shares, 2),
                "reason": fill_reason,
                "detail": {
                    "minute": minute,
                    "lean": round(lean.lean, 2),
                    "confidence": round(lean.confidence, 2),
                    "clip": "full" if len(fills) % clip_nth == 0 else "median",
                },
            })
            cost += px * shares
            last_fill_ts = time.time()
            last_fill_px = px

            fill_reason = "m4-snipe" if minute == 4 else "clip-fill"
            fill_kind = "snipe" if minute == 4 else "entry"
            log_event(fill_kind, fill_reason, slug, side=outcome,
                      detail={"minute": f"M{minute}", "price": px, "shares": shares,
                              "lean": round(lean.lean, 2), "fills": len(fills), "cost": round(cost, 2)})
            log(f"M{minute} {outcome} {shares:.1f} @ {px:.3f} (lean {lean.lean:+.2f})")
            write_state(slug, end_ms, started_ms, fills, lean,
                        ws_status=streamer.get_status(), recent_ticks=streamer.get_recent_ticks(30))
            # Event-driven wait: react instantly to next tick or time out after short cadence
            streamer.wait_for_tick(timeout=0.25)
    finally:
        stop_sync.set()
        sync_thread.join(timeout=1.0)
        streamer.stop()

    # --- close: write a pending run file, settle in background, NEVER block next window ---
    result = {"event_slug": slug, "market": spec.question or slug, "trades": len(fills),
              "cost_usd": round(cost, 2), "payout_usd": None, "net_usd": None,
              "winner": None, "pending": True, "fills": fills}
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / f"{slug}.json").write_text(json.dumps(result, indent=2))
    ws = get_current_workspace()
    if ws:
        try:
            ws.windows_dir.mkdir(parents=True, exist_ok=True)
            (ws.windows_dir / f"{slug}.json").write_text(json.dumps(result, indent=2))
        except Exception as ex:
            log(f"warning: failed to save {slug}.json to workspace {ws.run_id}: {ex}")
    try:
        STATE_PATH.unlink()
    except OSError:
        pass
    log(f"window closed, {len(fills)} paper fills, cost ${cost:.2f} — settling in background…")
    snap = {"slug": slug, "market": spec.question or slug,
            "fills": fills, "cost": round(cost, 2)}
    th = threading.Thread(target=settle_slug, args=(slug, snap, origin),
                          kwargs={"budget_s": 900}, daemon=True)
    th.start()
    return result


def settle_slug(slug: str, snap: dict, origin: str | None, budget_s: int = 900) -> dict | None:
    """Resolve one window off the market's own outcome (background-safe)."""
    c = PublicClient()
    fills = snap.get("fills", [])
    cost = float(snap.get("cost", 0.0))
    winner: str | None = None
    waited = 0
    while waited < budget_s:
        time.sleep(30)
        waited += 30
        try:
            ev = c.get_event(slug=slug).model_dump()
            mk = (ev.get("markets") or [{}])[0]
            outs = mk.get("outcomes") or {}
            for _key, info in outs.items():
                try:
                    if float(info.get("price") or 0) >= 1.0:
                        winner = info.get("label")
                        break
                except (TypeError, ValueError):
                    continue
            if winner:
                break
        except Exception as ex:
            print(f"[{slug}] resolve poll: {type(ex).__name__}", flush=True)
    payout = None
    net = None
    if winner:
        wshares = sum(f["shares"] for f in fills if f["outcome"] == winner)
        payout = round(wshares * 1.0, 2)
        net = round(payout - cost, 2)
    result = {"event_slug": slug, "market": snap.get("market", slug), "trades": len(fills),
              "cost_usd": cost, "payout_usd": payout, "net_usd": net,
              "winner": winner, "resolvedAt": datetime.now(timezone.utc).isoformat(),
              "fills": fills}
    if winner:
        result.pop("pending", None)
    else:
        result["pending"] = True
    try:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (RUNS_DIR / f"{slug}.json").write_text(json.dumps(result, indent=2))
        ws = get_current_workspace()
        if ws:
            ws.windows_dir.mkdir(parents=True, exist_ok=True)
            (ws.windows_dir / f"{slug}.json").write_text(json.dumps(result, indent=2))
    except OSError:
        pass
    log_event("settle", "paper-resolve", slug,
              detail={"winner": winner, "fills": len(fills), "cost": cost,
                      "payout": payout, "net": net})
    print(f"[{slug}] resolved: winner={winner} payout=${payout:.2f} net=${net:.2f}", flush=True)
    if origin:
        try:
            post_result(origin, result)
        except Exception as ex:
            print(f"[{slug}] dashboard import: {type(ex).__name__}", flush=True)
    return result


def post_result(origin: str, result: dict) -> None:
    payload = json.dumps({"windows": [{k: result[k] for k in ("event_slug", "market", "trades", "cost_usd", "payout_usd", "net_usd")}]}).encode()
    req = urllib.request.Request(f"{origin.rstrip('/')}/api/bot/import", data=payload,
                                 headers={"Content-Type": "application/json", "Origin": origin.rstrip('/')})
    body = urllib.request.urlopen(req, timeout=20).read().decode()
    print(f"dashboard import: {body[:200]}", flush=True)


def wait_while_killed(verbose: bool = True) -> None:
    while KILL_PATH.exists():
        if verbose:
            print("kill-switch present — entries paused", flush=True)
        time.sleep(30)


def main() -> None:
    ap = argparse.ArgumentParser(description="Live BTC 5m paper trader (no keys, no funding)")
    ap.add_argument("--once", action="store_true", help="trade one live window then exit")
    ap.add_argument("--loop", action="store_true", help="trade every window until Ctrl+C")
    ap.add_argument("--slot", type=int, default=None, help="explicit window epoch (default: current)")
    ap.add_argument("--origin", default="http://localhost:5174", help="Worker origin for dashboard import ('' to skip)")
    ap.add_argument("--run-id", default=None, help="Explicit run_id session directory")
    ap.add_argument("--label", default="default", help="Label for this run session")
    args = ap.parse_args()
    c = PublicClient()

    ws = init_run_session(run_id=args.run_id, label=args.label)
    print(f"session initialized: {ws.run_id}", flush=True)

    def _sigterm_handler(signum, frame):
        ws.finalize(status="interrupted")
        sys.exit(0)

    try:
        import signal
        signal.signal(signal.SIGTERM, _sigterm_handler)
    except Exception:
        pass

    if args.slot:
        try:
            trade_window(c, args.slot, args.origin or None)
            ws.finalize(status="completed")
        except KeyboardInterrupt:
            ws.finalize(status="interrupted")
            raise
        except Exception:
            ws.finalize(status="failed")
            raise
        return
    if args.once:
        slot = current_slot()
        now = int(datetime.now(timezone.utc).timestamp())
        if now > slot + WINDOW_S - 60:
            slot += WINDOW_S  # too late in this window — take the next one
            wait = slot + 13 - now
            print(f"joining next window in {wait}s…", flush=True)
            time.sleep(max(wait, 0))
        wait_while_killed()
        try:
            trade_window(c, slot, args.origin or None)
            ws.finalize(status="completed")
        except KeyboardInterrupt:
            ws.finalize(status="interrupted")
            raise
        except Exception:
            ws.finalize(status="failed")
            raise
        return
    # --loop (default if nothing passed)
    try:
        last_slot: int | None = None
        while True:
            wait_while_killed()
            slot = current_slot()
            now = int(time.time())
            open_delay = cfg_entry("openDelaySec", 13)
            if slot == last_slot or now > slot + open_delay:
                slot += WINDOW_S
            wait = slot + open_delay - now
            if wait > 0:
                print(f"next window in {wait}s…", flush=True)
                time.sleep(wait)
            try:
                last_slot = slot
                trade_window(c, slot, args.origin or None)
            except KeyboardInterrupt:
                raise
            except Exception as ex:
                print(f"window failed: {type(ex).__name__}: {ex}", flush=True)
                log_event("error", "window-failed", f"btc-updown-5m-{slot}", detail={"error": str(ex)[:200]})
                time.sleep(30)
    except KeyboardInterrupt:
        ws.finalize(status="interrupted")
        raise
    except Exception:
        ws.finalize(status="failed")
        raise


if __name__ == "__main__":
    main()
