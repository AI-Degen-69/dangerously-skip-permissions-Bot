"""Live paper trader — MSR-v2 Hybrid Maker/Taker Straddle & Lagging-Leg Equalizer.

Reconstructed from 16,855 fills from wallet `dangerously-skip-permissions` across
288 consecutive 5-minute Bitcoin markets.

Simulates the 4-phase microstructure lifecycle:
  Phase 0 (T-310s..T-300s): Pre-open book discovery & resting order prep
  Phase 1 (T-300s..T-296s): Oracle anchor price registration (0 fills)
  Phase 2 (T-296s..T-60s):  Maker Dip Grid [7¢–50¢] + Lagging-Leg Equalizer [75¢–95¢]
  Phase 3 (T-60s..T-12s):   Minute 4 Resolution Certainty Snipe [92¢–96¢]
  Phase 4 (T-12s..T-0s):    Settlement lock (0 fills)

Usage:
  python bot/live_paper.py --once        # trade current/next live window, then exit
  python bot/live_paper.py --loop        # trade every window continuously
  python bot/api.py                      # desk API on 127.0.0.1:8789
"""

import argparse
import json
import os
import re
import shutil
import sys

# Ensure UTF-8 output encoding across all operating systems / Windows cp1252 consoles
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, ".")

from polymarket import PublicClient

from bot import constants as C
from bot.discovery import WINDOW_S, current_slot, get_window
from bot.executor import (
    compute_fill_usd,
    evaluate_microstructure_ladder,
)
from bot.risk import RiskState, assert_single_window, check_window, clip_shares, heartbeat
from bot.runs import RunWorkspace, find_run_id, get_active_run_id, make_run_id, set_active_run_id
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


def init_run_session(run_id: str | None = None, label: str = "msr_v2") -> RunWorkspace:
    """Initialize a run-scoped directory and update active run pointer."""
    global CURRENT_WORKSPACE
    resolved_id = find_run_id(run_id) if run_id else None
    rid = resolved_id or run_id or make_run_id(mode="paper", label=label)
    ws = RunWorkspace(rid)
    ws.init_workspace(config=load_cfg(), mode="paper", label=label)
    set_active_run_id(ws.run_id)
    ws.sync_to_paper_runs(RUNS_DIR)
    try:
        ws.settle_pending_windows(RUNS_DIR)
    except Exception:
        pass
    if ws.events_file.exists() and ws.events_file.stat().st_size > 0:
        try:
            shutil.copyfile(ws.events_file, EVENTS_PATH)
        except Exception:
            pass
    if STATE_PATH.exists():
        try:
            st = json.loads(STATE_PATH.read_text())
            end_ms = st.get("endMs")
            st_run_id = st.get("runId")
            if (st_run_id and st_run_id != ws.run_id) or (end_ms and int(end_ms) < int(time.time() * 1000)):
                STATE_PATH.unlink(missing_ok=True)
        except Exception:
            STATE_PATH.unlink(missing_ok=True)
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
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "mode": "paper",
        "reason": reason,
    }
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


def build_decision_record(
    slug: str,
    minute: int,
    in_sweep_phase: bool,
    imbalance: float,
    fills: int,
    cost: float,
    quotes: dict,
    decision,
) -> dict:
    up_q = (quotes.get("Up") or {})
    down_q = (quotes.get("Down") or {})
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "slug": slug,
        "minute": minute,
        "inSweepPhase": bool(in_sweep_phase),
        "imbalance": round(float(imbalance), 1),
        "fills": fills,
        "cost": round(float(cost), 2),
        "action": decision.action,
        "outcome": decision.outcome,
        "price": decision.price,
        "shares": decision.shares,
        "role": decision.role,
        "reason": decision.reason,
        "subReason": decision.sub_reason,
        "projectedPairCost": decision.projected_pair_cost,
        "shareDeficit": decision.share_deficit,
        "quotes": {
            "Up": {"bid": up_q.get("bid"), "ask": up_q.get("ask")},
            "Down": {"bid": down_q.get("bid"), "ask": down_q.get("ask")},
        },
    }


def log_decision(
    slug: str,
    minute: int,
    in_sweep_phase: bool,
    imbalance: float,
    fills: int,
    cost: float,
    quotes: dict,
    decision,
) -> None:
    ws = get_current_workspace()
    if ws is None:
        return
    rec = build_decision_record(slug, minute, in_sweep_phase, imbalance, fills, cost, quotes, decision)
    try:
        ws.root.mkdir(parents=True, exist_ok=True)
        with ws.decisions_file.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def microprice_lean(c: PublicClient, up_id: str, down_id: str, streamer: LiveBookStreamer | None = None) -> LeanSignal:
    """Optional lean probe from live book microprice. Kept neutral by default."""
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
    edge = (up_mid - down_mid) / 2.0
    raw = edge * 4.0
    lean = max(-1.0, min(1.0, raw))
    spread = abs(up_mid + down_mid - 1.0)
    confidence = max(0.0, min(1.0, 1.0 - spread * 5.0))
    return LeanSignal(lean=lean, confidence=confidence, source="book-microprice", raw=round(raw, 3))


def live_buy_price(c: PublicClient, token_id: str, streamer: LiveBookStreamer | None = None) -> float | None:
    """Best executable BUY price, or None when the book has no usable ask."""
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


def live_bid_price(c: PublicClient, token_id: str, streamer: LiveBookStreamer | None = None) -> float | None:
    """Best resting bid price (for passive Maker ladder fills) from WS memory."""
    if streamer is not None:
        try:
            with streamer._lock:
                book = streamer.books.get(str(token_id))
                if book and book.best_bid is not None and 0.0 < book.best_bid < 1.0:
                    return book.best_bid
        except Exception:
            pass
    return None


def live_quote_pair(
    c: PublicClient,
    up_id: str,
    down_id: str,
    streamer: LiveBookStreamer | None = None,
) -> dict[str, dict[str, float | None]]:
    """Fetch {Up: {bid, ask}, Down: {bid, ask}} without extra REST calls."""
    up_ask = live_buy_price(c, up_id, streamer=streamer)
    down_ask = live_buy_price(c, down_id, streamer=streamer)
    up_bid = live_bid_price(c, up_id, streamer=streamer)
    down_bid = live_bid_price(c, down_id, streamer=streamer)
    return {
        "Up": {"bid": up_bid if up_bid is not None else up_ask, "ask": up_ask},
        "Down": {"bid": down_bid if down_bid is not None else down_ask, "ask": down_ask},
    }


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
    lean: LeanSignal | None = None,
    ws_status: dict | None = None,
    recent_ticks: list[dict] | None = None,
) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg = load_cfg()
    strat = cfg.get("strategy", {})
    payload = {
        "runId": CURRENT_WORKSPACE.run_id if CURRENT_WORKSPACE else None,
        "slug": slug,
        "endMs": end_ms,
        "startedAtMs": started_ms,
        "updatedAtMs": int(time.time() * 1000),
        "fills": fills,
        "strategy": strat.get("id", C.STRATEGY_ID),
        "strategySymbol": strat.get("symbol", C.STRATEGY_SYMBOL),
        "strategyName": strat.get("name", C.STRATEGY_NAME),
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
    if "trade cap" in raw_reason:
        return "window-trade-cap"
    return raw_reason


def _risk_detail(raw_reason: str, state: RiskState, trades: int) -> dict:
    risk_cfg = load_cfg().get("risk", {})
    default_cap = float(risk_cfg.get("dailyLossCapUsd", 500.0))
    trade_cap = int(risk_cfg.get("maxFillsPerWindow", 500))

    if "daily loss cap" in raw_reason:
        m = re.search(r"daily loss cap \$?([0-9.]+(?:[eE][+-]?\d+)?)", raw_reason)
        cap = float(m.group(1)) if m else default_cap
        return {"lossUsd": round(abs(state.daily_loss_usd), 2), "capUsd": cap}
    if "trade cap" in raw_reason:
        m = re.search(r"trade cap (\d+)", raw_reason)
        cap = int(m.group(1)) if m else trade_cap
        return {"fills": trades, "cap": cap}
    return {}


def trade_window(
    c: PublicClient,
    slot: int,
    origin: str | None,
    verbose: bool = True,
    pre_streamer: LiveBookStreamer | None = None,
) -> dict:
    slug = f"btc-updown-5m-{slot}"
    assert_single_window(slug)
    spec = get_window(c, slug)
    cfg = load_cfg()
    entry = cfg.get("entry", {})
    strat = cfg.get("strategy", {})
    strat_id = strat.get("id", C.STRATEGY_ID)
    strat_sym = strat.get("symbol", C.STRATEGY_SYMBOL)
    strat_name = strat.get("name", C.STRATEGY_NAME)

    # Timing parameters
    start_after_open = float(entry.get("startAfterOpenSec", entry.get("openDelaySec", C.WINDOW_OPEN_BUFFER_S)))
    stop_before = float(entry.get("stopBeforeCloseSec", C.HARD_CUTOFF_SBC))
    test_max_fills = entry.get("maxWindowFills") or entry.get("medianFillsTarget")

    # Pricing & Sizing parameters
    min_fill = max(0.01, float(entry.get("minFillPrice", C.PRICE_FLOOR)))
    max_fill = min(0.99, float(entry.get("maxFillPrice", C.PRICE_CEILING)))
    clip_default = float(entry.get("clipSharesDefault", C.CLIP_SHARES_DEFAULT))
    max_shares = float(entry.get("maxShares", C.MAX_SHARES))
    target_pair_cost = float(entry.get("targetPairCost", C.TARGET_PAIR_COST))
    max_pair_cost = float(entry.get("maxPairCost", C.PAIR_COST_MAX))
    max_share_lead = float(entry.get("maxShareLead", C.MAX_SHARE_LEAD))
    max_unhedged_usd = float(entry.get("maxUnhedgedUsd", C.MAX_UNHEDGED_USD))
    dip_curve = entry.get("dipCurve") or None
    rescue_ceiling = float(entry.get("rescueCeilingPrice", C.RESCUE_CEILING_PRICE))
    rescue_max_pair_cost = float(entry.get("rescuePairCostMax", C.RESCUE_PAIR_COST_MAX))

    # Pacing parameters
    min_spacing_move = float(entry.get("minSpacingMoveSec", 0.5))
    min_spacing_static = float(entry.get("minSpacingStaticSec", 2.5))
    include_taker_fee = bool(entry.get("includeTakerFee", True))
    whole_ladder = bool(entry.get("wholeLadderClips", True))

    day_start = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    state = RiskState(daily_loss_usd=_current_daily_pnl(day_start))
    fills: list[dict] = []
    cost = 0.0
    total_fees_usd = 0.0
    inv: dict[str, dict[str, float]] = {
        "Up": {"shares": 0.0, "cost": 0.0},
        "Down": {"shares": 0.0, "cost": 0.0},
    }
    end_ms = (slot + WINDOW_S) * 1000
    started_ms = int(time.time() * 1000)

    # Use pre-pipelined WebSocket streamer if supplied, otherwise spawn a fresh one
    streamer = pre_streamer or LiveBookStreamer(
        up_token_id=spec.up_token_id,
        down_token_id=spec.down_token_id,
        rest_fallback_client=c,
    )
    streamer.start()

    write_state(slug, end_ms, started_ms, fills,
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
                            cfg = load_cfg()
                            strat = cfg.get("strategy", {})
                            st["strategy"] = strat.get("id", C.STRATEGY_ID)
                            st["strategySymbol"] = strat.get("symbol", C.STRATEGY_SYMBOL)
                            st["strategyName"] = strat.get("name", C.STRATEGY_NAME)
                            _atomic_write_json(STATE_PATH, st)
            except (OSError, json.JSONDecodeError, TypeError):
                pass
            stop_sync.wait(1.0)

    sync_thread = threading.Thread(target=_sync_loop, daemon=True, name="WSS-StateSync")
    sync_thread.start()

    def log(msg: str) -> None:
        if verbose:
            print(f"[{slug}] {msg}", flush=True)

    def _live_pair_cost() -> float | None:
        if inv["Up"]["shares"] > 0 and inv["Down"]["shares"] > 0:
            return round((inv["Up"]["cost"] / inv["Up"]["shares"]) + (inv["Down"]["cost"] / inv["Down"]["shares"]), 4)
        return None

    try:
        cutoff_sbc = min(stop_before, C.HARD_CUTOFF_SBC)
        end = int(slot + WINDOW_S - stop_before)  # Strategy early exit countdown (e.g. T-75s)
        sweep_end = int(slot + WINDOW_S - cutoff_sbc)  # Phase 4 hard settlement cutoff (e.g. T-12s)
        last_fill_ts = 0.0
        last_fill_px: float | None = None
        last_extreme_skip_ts: float = 0.0
        last_dust_skip_ts: float = 0.0

        while True:
            now = int(time.time())
            imbalance = abs(inv["Up"]["shares"] - inv["Down"]["shares"])
            in_sweep_phase = (now >= end and now < sweep_end and imbalance > 0.0)

            if now >= sweep_end or (now >= end and imbalance <= 0.0):
                up_sh = sum(f["shares"] for f in fills if f["outcome"] == "Up")
                down_sh = sum(f["shares"] for f in fills if f["outcome"] == "Down")
                log_event("done", "holding-to-resolution", slug,
                          detail={"fills": len(fills), "cost": round(cost, 2),
                                  "upShares": round(up_sh, 1), "downShares": round(down_sh, 1),
                                  "pairCost": _live_pair_cost(), "strategy": strat_sym,
                                  "imbalance": round(imbalance, 1)})
                break
            state.daily_loss_usd = _current_daily_pnl(day_start)
            if reason := check_window(len(fills), state, KILL_PATH):
                log_event("risk", _risk_reason_code(reason), slug,
                          detail=_risk_detail(reason, state, len(fills)))
                break

            if test_max_fills and len(fills) >= test_max_fills:
                time.sleep(max(0, sweep_end - now))
                continue

            minute = min(max((now - slot) // 60, 0), 4)

            quotes = live_quote_pair(c, spec.up_token_id, spec.down_token_id, streamer=streamer)
            decision = evaluate_microstructure_ladder(
                quotes=quotes,
                inv=inv,
                fill_idx=len(fills),
                minute=minute,
                strategy_id=strat_id,
                min_fill=min_fill,
                max_fill=max_fill,
                default_clip=clip_default,
                max_clip=max_shares,
                whole_ladder=whole_ladder,
                target_pair_cost=target_pair_cost,
                max_pair_cost=max_pair_cost,
                max_share_lead=max_share_lead,
                max_unhedged_usd=max_unhedged_usd,
                dip_curve=dip_curve,
                in_sweep_phase=in_sweep_phase,
                rescue_ceiling=rescue_ceiling,
                rescue_max_pair_cost=rescue_max_pair_cost,
            )

            # Uncensored decision journal: every evaluation (fill or skip) with
            # the quotes that produced it. Unlike log_event("refuse") this is
            # NOT throttled, so the true skip rate and binding gate are known.
            try:
                log_decision(slug, minute, in_sweep_phase, imbalance, len(fills), cost, quotes, decision)
            except Exception:
                pass

            if decision.action == "skip" or decision.outcome is None or decision.price is None:
                preferred_side = decision.outcome or ("Up" if len(fills) % 2 == 0 else "Down")
                q_side = quotes.get(preferred_side) or {}
                ref_px = q_side.get("ask") or q_side.get("bid")
                if decision.reason == "dust-quote":
                    if ref_px is not None:
                        log(f"M{minute} {preferred_side} dust {ref_px:.3f} — skipped")
                    if time.time() - last_dust_skip_ts > 10.0:
                        last_dust_skip_ts = time.time()
                        log_event("refuse", "dust-quote", slug, side=preferred_side,
                                  detail={"minute": f"M{minute}", "price": ref_px, "minFill": min_fill})
                elif decision.reason == "extreme-price-skip":
                    if time.time() - last_extreme_skip_ts > 10.0:
                        last_extreme_skip_ts = time.time()
                        log_event("refuse", "extreme-price-skip", slug, side=preferred_side,
                                  detail={"minute": f"M{minute}", "price": ref_px, "subReason": decision.sub_reason})
                streamer.wait_for_tick(timeout=0.25)
                continue

            outcome = decision.outcome
            px = decision.price
            shares = min(clip_shares(decision.shares, max_shares), max_shares)
            role = decision.role

            # Anti-runaway dynamic pacing (relaxed in sweep phase to guarantee deficit close)
            time_since_fill = time.time() - last_fill_ts
            is_price_move = (last_fill_px is not None and abs(px - last_fill_px) >= 0.001)
            required_spacing = 0.5 if in_sweep_phase else (min_spacing_move if is_price_move else min_spacing_static)
            if time_since_fill < required_spacing:
                streamer.wait_for_tick(timeout=0.25)
                continue

            usd, fee_usd = compute_fill_usd(shares, px, role=role, include_fee=include_taker_fee)
            inv[outcome]["shares"] += shares
            inv[outcome]["cost"] += usd
            cost += usd
            total_fees_usd += fee_usd
            last_fill_ts = time.time()
            last_fill_px = px
            # Only stamp a pair cost when this fill REDUCES the imbalance
            # (i.e. it closes/equalizes a pair). Opening/extending dips get
            # None: no pair exists yet, so a blended running average here
            # would read as "this pair cost X" and mislead.
            imbalance_after = abs(inv["Up"]["shares"] - inv["Down"]["shares"])
            pair_cost = _live_pair_cost() if imbalance_after < imbalance else None

            # Semantic trade tagging
            if len(fills) == 0:
                trade_reason = "straddle-open"
                event_reason = "straddle-open"
                fill_kind = "entry"
            elif len(fills) == 1:
                trade_reason = "hedge-leg"
                event_reason = "hedge-leg"
                fill_kind = "entry"
            elif decision.sub_reason == "rescue-equalizer":
                trade_reason = "rescue-hedge"
                event_reason = "clip-fill"
                fill_kind = "hedge"
            elif minute == 4 and decision.reason == "m4-snipe":
                trade_reason = "m4-snipe"
                event_reason = "m4-snipe"
                fill_kind = "snipe"
            elif decision.sub_reason == "hedge-equalizer":
                trade_reason = "hedge-equalizer"
                event_reason = "clip-fill"
                fill_kind = "entry"
            elif decision.sub_reason == "maker-dip-ladder":
                trade_reason = "maker-dip-ladder"
                event_reason = "clip-fill"
                fill_kind = "entry"
            else:
                trade_reason = "straddle-balance"
                event_reason = "clip-fill"
                fill_kind = "entry"

            fills.append({
                "minute": minute,
                "ts": int(time.time() * 1000),
                "outcome": outcome,
                "price": px,
                "shares": shares,
                "usd": usd,
                "reason": trade_reason,
                "detail": {
                    "minute": minute,
                    "role": role,
                    "subReason": decision.sub_reason,
                    "feeUsd": fee_usd,
                    "pairCost": pair_cost,
                    "deficit": decision.share_deficit,
                    "strategy": strat_id,
                },
            })

            log_event(fill_kind, event_reason, slug, side=outcome,
                      detail={"minute": f"M{minute}", "price": px, "shares": shares,
                              "role": role, "subReason": decision.sub_reason,
                              "feeUsd": fee_usd, "pairCost": pair_cost,
                              "upShares": round(inv["Up"]["shares"], 1),
                              "downShares": round(inv["Down"]["shares"], 1),
                              "fills": len(fills), "cost": round(cost, 2),
                              "strategy": strat_sym})
            log(f"M{minute} {outcome} {shares:.1f} @ {px:.3f} [{role} · {trade_reason}] (pair={pair_cost})")
            write_state(slug, end_ms, started_ms, fills,
                        ws_status=streamer.get_status(), recent_ticks=streamer.get_recent_ticks(30))
            streamer.wait_for_tick(timeout=0.25)
    finally:
        stop_sync.set()
        sync_thread.join(timeout=1.0)
        streamer.stop()

    # --- Close window: write run file, trigger async background settlement ---
    maker_count = sum(1 for f in fills if (f.get("detail") or {}).get("role") == "MAKER")
    taker_count = len(fills) - maker_count
    result = {
        "event_slug": slug,
        "market": spec.question or slug,
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
        "taker_fills": taker_count,
        "fees_usd": round(total_fees_usd, 2),
        "pair_cost": _live_pair_cost(),
    }
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
    log(f"window closed, {len(fills)} fills, cost ${cost:.2f} — settling in background…")
    snap = {
        "slug": slug,
        "market": spec.question or slug,
        "fills": fills,
        "cost": round(cost, 2),
        "strategy": C.STRATEGY_ID,
        "strategy_symbol": C.STRATEGY_SYMBOL,
        "maker_fills": maker_count,
        "taker_fills": taker_count,
        "fees_usd": round(total_fees_usd, 2),
        "pair_cost": _live_pair_cost(),
    }
    th = threading.Thread(target=settle_slug, args=(slug, snap, origin), kwargs={"budget_s": 900}, daemon=True)
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
            mk = (ev.get("outcomes") and ev) or (ev.get("markets") or [{}])[0]
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
    result = {
        "event_slug": slug,
        "market": snap.get("market", slug),
        "trades": len(fills),
        "cost_usd": cost,
        "payout_usd": payout,
        "net_usd": net,
        "winner": winner,
        "resolvedAt": datetime.now(timezone.utc).isoformat(),
        "fills": fills,
        "strategy": snap.get("strategy", C.STRATEGY_ID),
        "strategy_symbol": snap.get("strategy_symbol", C.STRATEGY_SYMBOL),
        "maker_fills": snap.get("maker_fills"),
        "taker_fills": snap.get("taker_fills"),
        "fees_usd": snap.get("fees_usd"),
        "pair_cost": snap.get("pair_cost"),
    }
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
    req = urllib.request.Request(
        f"{origin.rstrip('/')}/api/bot/import",
        data=payload,
        headers={"Content-Type": "application/json", "Origin": origin.rstrip('/')},
    )
    body = urllib.request.urlopen(req, timeout=20).read().decode()
    print(f"dashboard import: {body[:200]}", flush=True)


def wait_while_killed(verbose: bool = True) -> None:
    while KILL_PATH.exists():
        if verbose:
            print("kill-switch present — entries paused", flush=True)
        time.sleep(30)


def main() -> None:
    ap = argparse.ArgumentParser(description="MSR-v2 Live BTC 5m paper trader (no keys, no funding)")
    ap.add_argument("--once", action="store_true", help="trade one live window then exit")
    ap.add_argument("--loop", action="store_true", help="trade every window continuously")
    ap.add_argument("--slot", type=int, default=None, help="explicit window epoch (default: current)")
    ap.add_argument("--origin", default="", help="Worker origin for dashboard import ('' to skip)")
    ap.add_argument("--run-id", default=None, help="Explicit run_id session directory")
    ap.add_argument("--label", default="msr_v2", help="Label for this run session")
    args = ap.parse_args()
    c = PublicClient()

    ws = init_run_session(run_id=args.run_id, label=args.label)
    cfg = load_cfg()
    strat = cfg.get("strategy", {})
    strat_sym = strat.get("symbol", C.STRATEGY_SYMBOL)
    strat_name = strat.get("name", C.STRATEGY_NAME)
    print(f"session initialized: {ws.run_id} ({strat_sym} · {strat_name})", flush=True)
    try:
        (Path(__file__).resolve().parent / "loop.pid").write_text(str(os.getpid()))
    except Exception:
        pass

    def _sigterm_handler(signum, frame):
        try:
            (Path(__file__).resolve().parent / "loop.pid").unlink(missing_ok=True)
        except Exception:
            pass
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
            slot += WINDOW_S
            wait = slot - now
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

    # Continuous --loop mode with Phase 0 Pre-Open Pipelining
    try:
        last_slot: int | None = None
        next_streamer: LiveBookStreamer | None = None
        while True:
            wait_while_killed()
            slot = current_slot()
            now = int(time.time())
            start_buffer = cfg_entry("startAfterOpenSec", C.WINDOW_OPEN_BUFFER_S)
            if slot == last_slot or (last_slot is not None and now > slot + start_buffer) or (last_slot is None and now > slot + WINDOW_S - 60):
                slot += WINDOW_S

            # Phase 0: Pre-open pipelining & order placement (T-310s = 10s before countdown)
            pre_open_time = slot - C.PRE_OPEN_PIPELINE_S
            now = int(time.time())
            if now < pre_open_time:
                wait_to_pipeline = pre_open_time - now
                print(f"pre-open pipeline in {wait_to_pipeline}s (slot starts in {slot - now}s)…", flush=True)
                time.sleep(wait_to_pipeline)

            # Pre-warm upcoming market discovery & live book streamer early
            active_streamer = None
            try:
                next_spec = get_window(c, f"btc-updown-5m-{slot}")
                print(f"[btc-updown-5m-{slot}] Phase 0: Pre-open pipeline active — initializing live streamer & order placements at T-310s…", flush=True)
                active_streamer = LiveBookStreamer(
                    up_token_id=next_spec.up_token_id,
                    down_token_id=next_spec.down_token_id,
                    rest_fallback_client=c,
                )
                active_streamer.start()
            except Exception as ex:
                print(f"pre-open pipeline warning: {ex}", flush=True)

            try:
                last_slot = slot
                trade_window(c, slot, args.origin or None, pre_streamer=active_streamer)
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
