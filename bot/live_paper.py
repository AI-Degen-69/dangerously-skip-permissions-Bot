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
import math
import os
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

import collections
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
    v20_max_hedge_price,
)
from bot.fill_audit import audit_window
from bot.fill_model import match_maker_book_cross, match_maker_print
from bot.risk import RiskState, assert_single_window, check_window, clip_shares
from bot.runs import (
    CONFIG_PATH,
    EVENTS_PATH,
    KILL_PATH,
    STATE_PATH as FALLBACK_STATE_PATH,
    WINDOWS_MIRROR_DIR,
    RunWorkspace,
    ensure_data_dir,
    find_run_id,
    make_run_id,
    migrate_windows_mirror,
    set_active_run_id,
)
from bot.live_orders import (
    cancel_side_orders_pure,
    ladder_keys_pure,
    prune_pre_sweep_orders_pure,
    update_maker_order_pure,
)
from bot.live_quotes import (
    live_bid_price_pure,
    live_buy_price_pure,
    live_queue_ahead_pure,
    live_quote_pair_pure,
    microprice_lean_pure,
)
from bot.live_phases import (
    build_close_result,
    build_close_snap,
    classify_trade,
    compute_imp_up,
    desired_ladder_prices,
    is_sweep_phase,
    live_pair_cost as live_pair_cost_pure,
    minute_of,
    next_odds_history,
    open_order_rows as open_order_rows_pure,
    parse_window_params,
    required_spacing as pacing_spacing,
    should_close,
    unhedged_blocked,
)
from bot.live_records import (
    atomic_write_json_pure,
    build_decision_record_pure,
    compute_settlement_pure,
    current_daily_pnl_pure,
    risk_detail_pure,
    risk_reason_code_pure,
    settled_net_usd_pure,
    stamp_attainable_pure,
)
from bot.signal import LeanSignal
from bot.tape_verifier import load_book_for_window, load_prints_for_window, verify_fills
from bot.ws import LiveBookStreamer

# Legacy module aliases kept patchable for existing tests; new code uses the
# per-run workspace paths (ws.state_path / ws.events_file) with the data/
# fallbacks imported above.
STATE_PATH = FALLBACK_STATE_PATH
CURRENT_WORKSPACE: RunWorkspace | None = None
_STATE_LOCK = threading.Lock()


def get_current_workspace() -> RunWorkspace | None:
    global CURRENT_WORKSPACE
    return CURRENT_WORKSPACE


def _state_target(ws: RunWorkspace | None):
    """Per-run state file, or the data/ fallback when no run is active."""
    return ws.state_path if ws is not None else STATE_PATH


def init_run_session(run_id: str | None = None, label: str = "msr_v2") -> RunWorkspace:
    """Initialize a run-scoped directory and update active run pointer."""
    global CURRENT_WORKSPACE
    resolved_id = find_run_id(run_id) if run_id else None
    rid = resolved_id or run_id or make_run_id(mode="paper", label=label)
    ws = RunWorkspace(rid)
    ws.init_workspace(config=load_cfg(), mode="paper", label=label)
    set_active_run_id(ws.run_id)
    ws.sync_windows_mirror(WINDOWS_MIRROR_DIR)
    try:
        ws.settle_pending_windows(WINDOWS_MIRROR_DIR)
    except Exception:
        pass
    # Keep this run's own state file; drop it only when it belongs to a
    # different run or an expired window, so a fresh run never inherits it.
    try:
        if ws.state_path.exists():
            st = json.loads(ws.state_path.read_text())
            end_ms = st.get("endMs")
            st_run_id = st.get("runId")
            if (st_run_id and st_run_id != ws.run_id) or (end_ms and int(end_ms) < int(time.time() * 1000)):
                ws.state_path.unlink(missing_ok=True)
    except Exception:
        try:
            ws.state_path.unlink(missing_ok=True)
        except Exception:
            pass
    CURRENT_WORKSPACE = ws
    return ws


def load_cfg() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception:
        return {}


def cfg_entry(key: str, default):
    return load_cfg().get("entry", {}).get(key, default)


def paper_rebate_rate() -> float:
    """Configured paper taker-rebate rate (0 = off), clamped to [0, 1]."""
    try:
        raw = load_cfg().get("rebate", {}).get("takerRate", C.PAPER_REBATE_TAKER_RATE)
        rate = float(raw)
    except (TypeError, ValueError, AttributeError):
        return C.PAPER_REBATE_TAKER_RATE
    if rate != rate:  # NaN guard
        return C.PAPER_REBATE_TAKER_RATE
    return min(1.0, max(0.0, rate))


def run_tape_dir():
    """The run's tape dir, always recorded: the desk audits every fill against it,
    so a run without a tape produces numbers nobody can check. Raises OSError when
    the dir cannot be made, and the loop refuses to start."""
    ws = get_current_workspace()
    if ws is None:
        return None
    ws.tape_dir.mkdir(parents=True, exist_ok=True)
    return ws.tape_dir


def _stamp_attainable(fills: list[dict], prints: list[dict], condition_id: str | None, final: bool = False) -> int:
    """Shell seam: delegates to pure `live_records.stamp_attainable_pure`."""
    return stamp_attainable_pure(fills, prints, condition_id, final=final)


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
    ws = get_current_workspace()
    if ws is not None:
        # Each run keeps its own journal; write once to the relevant run.
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
    """Shell seam: delegates to pure `live_records.build_decision_record_pure`."""
    return build_decision_record_pure(slug, minute, in_sweep_phase, imbalance, fills, cost, quotes, decision)


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
    """Shell seam: reads cfg then delegates to pure `live_quotes.microprice_lean_pure`."""
    try:
        lean_source = load_cfg().get("entry", {}).get("leanSource", "microprice")
    except Exception:
        lean_source = "microprice"
    return microprice_lean_pure(c, up_id, down_id, streamer=streamer, lean_source=lean_source)


def live_buy_price(c: PublicClient, token_id: str, streamer: LiveBookStreamer | None = None) -> float | None:
    """Shell seam: delegates to pure `live_quotes.live_buy_price_pure`."""
    return live_buy_price_pure(c, token_id, streamer=streamer)


def live_bid_price(c: PublicClient, token_id: str, streamer: LiveBookStreamer | None = None) -> float | None:
    """Shell seam: delegates to pure `live_quotes.live_bid_price_pure`."""
    return live_bid_price_pure(c, token_id, streamer=streamer)


def live_queue_ahead(streamer: LiveBookStreamer | None, token_id: str, price: float) -> float | None:
    """Shell seam: delegates to pure `live_quotes.live_queue_ahead_pure`."""
    return live_queue_ahead_pure(streamer, token_id, price)


def live_quote_pair(
    c: PublicClient,
    up_id: str,
    down_id: str,
    streamer: LiveBookStreamer | None = None,
) -> dict[str, dict[str, float | None]]:
    """Shell seam: delegates to pure `live_quotes.live_quote_pair_pure`."""
    return live_quote_pair_pure(c, up_id, down_id, streamer=streamer)


def _atomic_write_json(path: Path, data: object) -> None:
    """Shell seam: delegates to pure `live_records.atomic_write_json_pure`."""
    return atomic_write_json_pure(path, data)


def _settled_net_usd(path: Path, day_start: int) -> float:
    """Shell seam: delegates to pure `live_records.settled_net_usd_pure`."""
    return settled_net_usd_pure(path, day_start)


def _current_daily_pnl(day_start: int) -> float:
    """Shell seam: passes mirror dir explicitly to pure helper."""
    return current_daily_pnl_pure(WINDOWS_MIRROR_DIR, day_start)


def write_state(
    slug: str,
    end_ms: int,
    started_ms: int,
    fills: list[dict],
    lean: LeanSignal | None = None,
    ws_status: dict | None = None,
    recent_ticks: list[dict] | None = None,
    odds_history: list[dict] | None = None,
    closed: bool = False,
    open_orders: list[dict] | None = None,
    orders_posted: int | None = None,
    orders_cancelled: int | None = None,
) -> None:
    ws = get_current_workspace()
    target = _state_target(ws)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    cfg = load_cfg()
    strat = cfg.get("strategy", {})
    payload = {
        "runId": CURRENT_WORKSPACE.run_id if CURRENT_WORKSPACE else None,
        "slug": slug,
        "endMs": end_ms,
        "startedAtMs": started_ms,
        "updatedAtMs": int(time.time() * 1000),
        "fills": fills,
        # Resting bids, not fills: the desk has to show the order the strategy
        # placed and is still waiting on.
        "openOrders": open_orders or [],
        "strategy": strat.get("id", C.STRATEGY_ID),
        "strategySymbol": strat.get("symbol", C.STRATEGY_SYMBOL),
        "strategyName": strat.get("name", C.STRATEGY_NAME),
    }
    if orders_posted is not None:
        payload["ordersPosted"] = orders_posted
    if orders_cancelled is not None:
        payload["ordersCancelled"] = orders_cancelled
    if closed:
        # Past the cutoff the window is holding, not trading: the flag lets the
        # next window claim the state while this snapshot stays readable.
        payload["closed"] = True
    if ws_status is not None:
        payload["ws"] = ws_status
    if recent_ticks is not None:
        payload["recentTicks"] = recent_ticks
    if odds_history is not None:
        payload["oddsHistory"] = odds_history
    else:
        # Hold _STATE_LOCK across both the history read and the atomic write so
        # a concurrent sync-thread sample cannot be lost between the two
        # critical sections (the race reported in CodeRabbit review thread 2).
        try:
            with _STATE_LOCK:
                if target.exists():
                    raw = json.loads(target.read_text())
                    if raw.get("slug") == slug and raw.get("oddsHistory"):
                        payload["oddsHistory"] = raw["oddsHistory"]
                _atomic_write_json(target, payload)
            return
        except Exception:
            pass
    with _STATE_LOCK:
        _atomic_write_json(target, payload)


def _risk_reason_code(raw_reason: str) -> str:
    """Shell seam: delegates to pure `live_records.risk_reason_code_pure`."""
    return risk_reason_code_pure(raw_reason)


def _risk_detail(raw_reason: str, state: RiskState, trades: int) -> dict:
    """Shell seam: reads risk cfg then delegates to pure helper."""
    try:
        risk_cfg = load_cfg().get("risk", {})
    except Exception:
        risk_cfg = {}
    return risk_detail_pure(raw_reason, state.daily_loss_usd, trades, risk_cfg)


def update_maker_order(
    open_orders: dict[str, dict],
    outcome: str,
    px: float,
    shares: float,
    minute: int,
    reason: str,
    sub_reason: str,
    deficit: float,
    ahead: float | None,
    now_ts: float,
    inv: dict[str, dict[str, float]] | None = None,
    unhedged_step_cents: float | None = None,
    order_key: str | None = None,
    max_hedge_px: float | None = None,
) -> tuple[bool, bool]:
    """Shell seam: delegates to pure `live_orders.update_maker_order_pure`."""
    return update_maker_order_pure(open_orders, outcome, px, shares, minute, reason, sub_reason, deficit, ahead, now_ts, inv=inv, unhedged_step_cents=unhedged_step_cents, order_key=order_key, max_hedge_px=max_hedge_px)


def ladder_keys(open_orders: dict[str, dict], outcome: str) -> list[str]:
    """Shell seam: delegates to pure `live_orders.ladder_keys_pure`."""
    return ladder_keys_pure(open_orders, outcome)


def cancel_side_orders(open_orders: dict[str, dict], outcome: str) -> list[dict]:
    """Shell seam: delegates to pure `live_orders.cancel_side_orders_pure`."""
    return cancel_side_orders_pure(open_orders, outcome)


def prune_pre_sweep_orders(open_orders: dict[str, dict]) -> list[dict]:
    """Shell seam: delegates to pure `live_orders.prune_pre_sweep_orders_pure`."""
    return prune_pre_sweep_orders_pure(open_orders)


def trade_window(
    c: PublicClient,
    slot: int,
    origin: str | None,
    verbose: bool = True,
    pre_streamer: LiveBookStreamer | None = None,
) -> dict:
    slug = f"btc-updown-5m-{slot}"
    _ws_for_guard = get_current_workspace()
    _guard_path = _state_target(_ws_for_guard)
    assert_single_window(slug, _guard_path)
    spec = get_window(c, slug)
    cfg = load_cfg()
    entry = cfg.get("entry", {})
    strat = cfg.get("strategy", {})
    strat_id = strat.get("id", C.STRATEGY_ID)
    strat_sym = strat.get("symbol", C.STRATEGY_SYMBOL)
    strat_name = strat.get("name", C.STRATEGY_NAME)

    # Phase 0 setup (pure): timing/pricing/pacing params live in `live_phases.parse_window_params`.
    _wp = parse_window_params(entry)
    start_after_open = _wp["start_after_open"]
    stop_before = _wp["stop_before"]
    test_max_fills = _wp["test_max_fills"]
    min_fill = _wp["min_fill"]
    max_fill = _wp["max_fill"]
    clip_default = _wp["clip_default"]
    max_shares = _wp["max_shares"]
    target_pair_cost = _wp["target_pair_cost"]
    max_pair_cost = _wp["max_pair_cost"]
    max_unhedged_usd = _wp["max_unhedged_usd"]
    max_unhedged_shares = _wp["max_unhedged_shares"]
    ladder_levels = _wp["ladder_levels"]
    ladder_spacing = _wp["ladder_spacing"]
    dip_curve = _wp["dip_curve"]
    clip_schedule = _wp["clip_schedule"]
    rescue_ceiling = _wp["rescue_ceiling"]
    rescue_max_pair_cost = _wp["rescue_max_pair_cost"]
    sweep_before = _wp["sweep_before"]
    leg1_max = _wp["leg1_max"]
    leg2_max = _wp["leg2_max"]
    taker_dip_max = _wp["taker_dip_max"]
    late_start = _wp["late_start"]
    late_max = _wp["late_max"]
    unhedged_step_cents = _wp["unhedged_step_cents"]
    unhedged_probe_shares = _wp["unhedged_probe_shares"]
    min_spacing_move = _wp["min_spacing_move"]
    min_spacing_static = _wp["min_spacing_static"]
    include_taker_fee = _wp["include_taker_fee"]
    whole_ladder = _wp["whole_ladder"]

    day_start = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    state = RiskState(daily_loss_usd=_current_daily_pnl(day_start))
    fills: list[dict] = []
    cost = 0.0
    total_fees_usd = 0.0
    # Resting orders the loop posted and pulled, so the desk can show the
    # funnel: windows -> orders -> fills -> paired vs single-side.
    orders_posted = 0
    orders_cancelled = 0
    inv: dict[str, dict[str, float]] = {
        "Up": {"shares": 0.0, "cost": 0.0},
        "Down": {"shares": 0.0, "cost": 0.0},
    }
    end_ms = (slot + WINDOW_S) * 1000
    started_ms = int(time.time() * 1000)

    # Use pre-pipelined WebSocket streamer if supplied, otherwise spawn a fresh one.
    # Tape (#35 prints + top-5 book) records into the run workspace.
    _tape_dir = run_tape_dir()
    _tape_on = _tape_dir is not None
    streamer = pre_streamer or LiveBookStreamer(
        up_token_id=spec.up_token_id,
        down_token_id=spec.down_token_id,
        rest_fallback_client=c,
        enable_trade_prints=_tape_on,
        tape_dir=_tape_dir,
    )
    if pre_streamer is not None and _tape_on:
        try:
            streamer.enable_trade_prints = True
            streamer.tape_dir = _tape_dir
        except Exception:
            pass
    streamer.start()

    write_state(slug, end_ms, started_ms, fills,
                ws_status=streamer.get_status(), recent_ticks=streamer.get_recent_ticks(30))
    stop_sync = threading.Event()

    def _sync_loop():
        _sync_ws = get_current_workspace()
        _sync_path = _state_target(_sync_ws)
        while not stop_sync.is_set():
            try:
                with _STATE_LOCK:
                    if _sync_path.exists():
                        raw = _sync_path.read_text()
                        if isinstance(raw, str):
                            st = json.loads(raw)
                            now_ms = int(time.time() * 1000)
                            st["updatedAtMs"] = now_ms
                            ws_stat = streamer.get_status()
                            st["ws"] = ws_stat
                            st["recentTicks"] = streamer.get_recent_ticks(30)
                            cfg = load_cfg()
                            strat = cfg.get("strategy", {})
                            st["strategy"] = strat.get("id", C.STRATEGY_ID)
                            st["strategySymbol"] = strat.get("symbol", C.STRATEGY_SYMBOL)
                            st["strategyName"] = strat.get("name", C.STRATEGY_NAME)

                            # Phase: state-sync odds (pure helpers).
                            up_val_book = ws_stat.get("up_book") or {}
                            down_val_book = ws_stat.get("down_book") or {}
                            imp_up = compute_imp_up(up_val_book, down_val_book)
                            if imp_up is not None:
                                new_hist = next_odds_history(st.get("oddsHistory"), now_ms, slot, imp_up)
                                if new_hist is not None:
                                    st["oddsHistory"] = new_hist

                            _atomic_write_json(_sync_path, st)
            except (OSError, json.JSONDecodeError, TypeError):
                pass
            stop_sync.wait(1.0)

    sync_thread = threading.Thread(target=_sync_loop, daemon=True, name="WSS-StateSync")
    sync_thread.start()

    # --- Tape verification thread (#35) ---
    # Every 5s, check unverified fills against accumulated trade prints.
    def _tape_verify_loop():
        while not stop_sync.is_set():
            stop_sync.wait(5.0)
            if stop_sync.is_set():
                break
            if not _tape_on or not fills:
                continue
            try:
                # The window's own bounds: a later window's prints must not
                # confirm this window's fills.
                prints = load_prints_for_window(_tape_dir, float(slot), float(slot) + C.WINDOW_S)
                changed = verify_fills(
                    fills,
                    _tape_dir,
                    window_start_s=float(slot),
                    window_end_s=float(slot) + C.WINDOW_S,
                    prints=prints,
                )
                # Same prints, same rule as the resolution audit: the desk can
                # show which fills the selling so far could actually have filled.
                changed += _stamp_attainable(fills, prints, spec.condition_id)
                if changed > 0:
                    # Persist the new statuses: the sync loop preserves whatever
                    # fills it last read, so without this write the API keeps
                    # serving stale statuses until the next fill calls write_state().
                    with _STATE_LOCK:
                        _verify_ws = get_current_workspace()
                        _verify_path = _state_target(_verify_ws)
                        if _verify_path.exists():
                            st = json.loads(_verify_path.read_text())
                            if st.get("slug") == slug:
                                st["fills"] = fills
                                _atomic_write_json(_verify_path, st)
                if changed > 0 and verbose:
                    stats = {s: 0 for s in ("verified", "partial", "unverified", "pending")}
                    for f in fills:
                        s = (f.get("detail") or {}).get("tapeStatus", "pending")
                        if s in stats:
                            stats[s] += 1
                    print(f"[{slug}] tape: {stats}", flush=True)
            except Exception:
                pass

    verify_thread = threading.Thread(target=_tape_verify_loop, daemon=True, name="TapeVerifier")
    verify_thread.start()

    def log(msg: str) -> None:
        if verbose:
            print(f"[{slug}] {msg}", flush=True)

    def _live_pair_cost() -> float | None:
        # Phase: fill-engine helper (pure).
        return live_pair_cost_pure(inv)

    # --- Fill engine -------------------------------------------------------
    # A maker order is not a fill. It rests at its price and only becomes a fill
    # when a taker SELL prints at or below that price, behind whatever was
    # already resting there. A taker order still executes at once.
    token_outcome = {str(spec.up_token_id): "Up", str(spec.down_token_id): "Down"}
    open_orders: dict[str, dict] = {}
    pending_prints: collections.deque = collections.deque()
    prints_lock = threading.Lock()

    def _queue_print(pr) -> None:
        with prints_lock:
            pending_prints.append(pr)

    # The pre-open streamer was started before this window and has no callback.
    streamer.on_print = _queue_print

    def _minute_of(ts: float) -> int:
        # Phase: fill-engine helper (pure).
        return minute_of(slot, ts)

    def _open_order_rows() -> list[dict]:
        # Phase: fill-engine view helper (pure).
        return open_order_rows_pure(open_orders, int(time.time() * 1000))

    def _persist() -> None:
        write_state(slug, end_ms, started_ms, fills, open_orders=_open_order_rows(),
                    ws_status=streamer.get_status(), recent_ticks=streamer.get_recent_ticks(30),
                    orders_posted=orders_posted, orders_cancelled=orders_cancelled)

    def _book_fill(outcome: str, px: float, shares: float, role: str, minute: int,
                   reason: str, sub_reason: str, queue_ahead, deficit: float,
                   ts_ms: int | None = None, placed_at_ms: int | None = None,
                   queue_ahead_at_place=None, taker_book: dict | None = None) -> None:
        nonlocal cost, total_fees_usd, last_fill_ts, last_fill_px, window_bailout_latched
        imbalance_before = abs(inv["Up"]["shares"] - inv["Down"]["shares"])
        usd, fee_usd = compute_fill_usd(shares, px, role=role, include_fee=include_taker_fee)
        inv[outcome]["shares"] += shares
        inv[outcome]["cost"] += usd
        cur_low = inv[outcome].get("lowest_price")
        if cur_low is None or px < cur_low:
            inv[outcome]["lowest_price"] = px
        cost += usd
        total_fees_usd += fee_usd
        last_fill_ts = time.time()
        last_fill_px = px
        # Only stamp a pair cost when this fill REDUCES the imbalance
        # (i.e. it closes/equalizes a pair). Opening/extending dips get
        # None: no pair exists yet, so a blended running average here
        # would read as "this pair cost X" and mislead.
        imbalance_after = abs(inv["Up"]["shares"] - inv["Down"]["shares"])
        pair_cost = _live_pair_cost() if imbalance_after < imbalance_before else None

        if strat_id.startswith("hydrogen-v2") and role == "TAKER" and sub_reason == "rebalance-taker":
            opp_outcome = "Down" if outcome == "Up" else "Up"
            cancel_side_orders(open_orders, opp_outcome)
        if strat_id.startswith("hydrogen-v1.9") and sub_reason in ("rebalance-taker", "rebalance-maker") and imbalance_after < imbalance_before:
            opp_outcome = "Down" if outcome == "Up" else "Up"
            if inv[opp_outcome]["shares"] > 0:
                heavy_avg_cost = inv[opp_outcome]["cost"] / inv[opp_outcome]["shares"]
                marginal_pair = heavy_avg_cost + px
                if marginal_pair > 1.000:
                    window_bailout_latched = True
                    log(f"Window bailout latched: marginal_pair={marginal_pair:.4f} > 1.000")

        # Phase: fill-engine tagging (pure).
        trade_reason, event_reason, fill_kind = classify_trade(len(fills), sub_reason, minute, reason)

        fills.append({
            "minute": minute,
            "ts": ts_ms if ts_ms is not None else int(time.time() * 1000),
            "outcome": outcome,
            "price": px,
            "shares": shares,
            "usd": usd,
            "reason": trade_reason,
            "detail": {
                "minute": minute,
                "role": role,
                # The queue this fill actually paid through, not what was
                # resting when the loop happened to look.
                "queueAhead": queue_ahead,
                "subReason": sub_reason,
                "feeUsd": fee_usd,
                "pairCost": pair_cost,
                "deficit": deficit,
                "strategy": strat_id,
                "tapeStatus": "pending" if _tape_on else None,
                "placedAtMs": placed_at_ms,
                "queueAheadAtPlace": queue_ahead_at_place,
                "askSize": (taker_book or {}).get("askSize"),
                "bidSize": (taker_book or {}).get("bidSize"),
                "spreadCents": (taker_book or {}).get("spreadCents"),
            },
        })

        log_event(fill_kind, event_reason, slug, side=outcome,
                  detail={"minute": f"M{minute}", "price": px, "shares": shares,
                          "role": role, "subReason": sub_reason,
                          "feeUsd": fee_usd, "pairCost": pair_cost,
                          "upShares": round(inv["Up"]["shares"], 1),
                          "downShares": round(inv["Down"]["shares"], 1),
                          "fills": len(fills), "cost": round(cost, 2),
                          "strategy": strat_sym})
        log(f"M{minute} {outcome} {shares:.1f} @ {px:.3f} [{role} · {trade_reason}] (pair={pair_cost})")
        _persist()

    def _drain_prints() -> None:
        """Turn the prints that arrived since the last tick into fills."""
        with prints_lock:
            batch = list(pending_prints)
            pending_prints.clear()
        for pr in batch:
            pr_outcome = token_outcome.get(str(getattr(pr, "asset_id", "")))
            if pr_outcome is None:
                continue
            for target_outcome in ("Up", "Down"):
                remaining = float(getattr(pr, "size", 0.0) or 0.0)
                for order_key in ladder_keys(open_orders, target_outcome):
                    if remaining <= 0:
                        break
                    order = open_orders.get(order_key)
                    if order is None:
                        continue
                    q_before = max(0.0, float(order.get("queue_ahead") or 0.0))
                    hit = match_maker_print(order, {
                        "outcome": pr_outcome,
                        "side": getattr(pr, "side", ""),
                        "price": getattr(pr, "price", 0.0),
                        "size": remaining,
                    })
                    q_used = max(0.0, q_before - max(0.0, float(order.get("queue_ahead") or 0.0)))
                    if hit is not None:
                        if unhedged_blocked(inv, target_outcome, order["price"], unhedged_step_cents):  # Phase: unhedged guard (pure)
                                        open_orders.pop(order_key, None)
                                        remaining = max(0.0, remaining - q_used)
                                        continue
                        remaining = max(0.0, remaining - (q_used + hit["fills"]))
                        ts = float(getattr(pr, "ts", 0.0) or 0.0) or time.time()
                        try:
                            _placed_ms = int(float(order.get("placed_ts", 0.0)) * 1000) if order.get("placed_ts") else None
                        except (TypeError, ValueError):
                            _placed_ms = None
                        _book_fill(target_outcome, order["price"], hit["fills"], "MAKER",
                                   _minute_of(ts),
                                   order["reason"], order["sub_reason"], hit["queueAhead"],
                                   order["deficit"], ts_ms=int(ts * 1000),
                                   placed_at_ms=_placed_ms,
                                   queue_ahead_at_place=order.get("queue_ahead_at_place", order.get("queue_ahead")))
                    else:
                        remaining = max(0.0, remaining - q_used)
                    if order["shares_left"] <= 0:
                        open_orders.pop(order_key, None)

    def _drain_book_crosses(quotes_map: dict) -> None:
        """Fill resting Maker bids when live CLOB quotes cross or clear their limit."""
        if not open_orders:
            return
        for order_key, order in list(open_orders.items()):
            outcome = order["side"]
            q = dict(quotes_map.get(outcome) or {})
            if streamer is not None and "askSize" not in q and "ask_size" not in q:
                try:
                    tok = spec.up_token_id if outcome == "Up" else spec.down_token_id
                    top = streamer.depth(str(tok), levels=1)
                    asks = (top or {}).get("asks") or []
                    if asks:
                        q["askSize"] = float(asks[0][1])
                except Exception:
                    pass
            hit = match_maker_book_cross(order, q)
            if hit is not None:
                if unhedged_blocked(inv, outcome, order["price"], unhedged_step_cents):  # Phase: unhedged guard (pure)
                                open_orders.pop(order_key, None)
                                continue
                now_ts = time.time()
                try:
                    _placed_ms = int(float(order.get("placed_ts", 0.0)) * 1000) if order.get("placed_ts") else None
                except (TypeError, ValueError):
                    _placed_ms = None
                _book_fill(outcome, order["price"], hit["fills"], "MAKER",
                           _minute_of(now_ts),
                           order["reason"], order["sub_reason"], hit["queueAhead"],
                           order["deficit"], ts_ms=int(now_ts * 1000),
                           placed_at_ms=_placed_ms,
                           queue_ahead_at_place=order.get("queue_ahead_at_place", order.get("queue_ahead")))
            if order["shares_left"] <= 0:
                open_orders.pop(order_key, None)

    def _apply_rebalance_hygiene(outcome: str, reason: str, sub_reason: str) -> float | None:
        if sub_reason != "rebalance-maker":
            return None
        opp_side = "Down" if outcome == "Up" else "Up"
        if strat_id.startswith("hydrogen-v2"):
            cancel_side_orders(open_orders, opp_side)
            if inv[opp_side]["shares"] > inv[outcome]["shares"] + 1e-9:
                cap = min(rescue_max_pair_cost if reason == "sweep" else max_pair_cost, 0.999)
                return v20_max_hedge_price(inv, opp_side, outcome, cap)
        elif strat_id.startswith("hydrogen-v1.9"):
            cancel_side_orders(open_orders, opp_side)
            if inv[opp_side]["shares"] > 0:
                heavy_avg = inv[opp_side]["cost"] / inv[opp_side]["shares"]
                return math.floor((max_pair_cost - heavy_avg + 1e-9) * 100.0) / 100.0
        return None

    def _place_maker(outcome: str, px: float, shares: float, minute: int,
                     reason: str, sub_reason: str, deficit: float) -> None:
        nonlocal orders_posted
        max_hedge_px = _apply_rebalance_hygiene(outcome, reason, sub_reason)
        cur = open_orders.get(outcome)
        ahead = None
        if cur is None or px > float(cur["price"]) + 1e-9:
            ahead = live_queue_ahead(streamer,
                                     spec.up_token_id if outcome == "Up" else spec.down_token_id, px)
        changed, repriced_or_new = update_maker_order(
            open_orders=open_orders,
            outcome=outcome,
            px=px,
            shares=shares,
            minute=minute,
            reason=reason,
            sub_reason=sub_reason,
            deficit=deficit,
            ahead=ahead,
            now_ts=time.time(),
            inv=inv,
            unhedged_step_cents=unhedged_step_cents,
            max_hedge_px=max_hedge_px,
        )
        if not changed:
            return
        order = open_orders[outcome]
        if repriced_or_new:
            orders_posted += 1
        shown = ahead if ahead is not None else "unknown"
        log(f"M{minute} {outcome} rest {order['shares_left']:.1f} @ {order['price']:.3f} behind {shown} [MAKER · {sub_reason}]")
        log_event("hold", "order-placed", slug, side=outcome,
                  detail={"minute": f"M{minute}",
                          "price": order["price"],
                          "shares": round(order["shares_left"], 2),
                          "role": "MAKER",
                          "subReason": sub_reason,
                          "queueAhead": round(float(order["queue_ahead"]), 1),
                          "deficit": round(float(deficit), 2),
                          "strategy": strat_sym})
        _persist()

    def _place_ladder(outcome: str, px: float, shares: float, minute: int,
                      reason: str, sub_reason: str, deficit: float) -> None:
        """Rest an N-rung maker ladder under one side (mirror of replay.place_levels).

        Rungs live one spacing apart below the decision price, each carrying
        the decision's per-level size. A rung whose price left the desired set
        is pulled: an off-touch ladder has to follow the touch down, unlike a
        single patient bid, which must never chase a falling price.
        """
        nonlocal orders_posted, orders_cancelled
        opp_side = "Down" if outcome == "Up" else "Up"
        max_hedge_px = _apply_rebalance_hygiene(outcome, reason, sub_reason)
        desired = desired_ladder_prices(px, ladder_spacing, ladder_levels)  # Phase: ladder layout (pure)
        for key in ladder_keys(open_orders, outcome):
            order = open_orders[key]
            if not any(abs(float(order["price"]) - d) < 1e-9 for d in desired):
                log(f"cancel {outcome} {order['shares_left']:.1f} @ {order['price']:.3f} (rung moved)")
                open_orders.pop(key, None)
                orders_cancelled += 1
        token = spec.up_token_id if outcome == "Up" else spec.down_token_id
        placed = False
        for i, d in enumerate(desired):
            if d < min_fill or d <= 0.0:
                continue
            key = outcome if i == 0 else f"{outcome}#{i}"
            cur = open_orders.get(key)
            ahead = None
            if cur is None or abs(float(cur["price"]) - d) > 1e-9:
                ahead = live_queue_ahead(streamer, token, d)
            changed, repriced_or_new = update_maker_order(
                open_orders=open_orders,
                outcome=outcome,
                px=d,
                shares=shares,
                minute=minute,
                reason=reason,
                sub_reason=sub_reason,
                deficit=deficit,
                ahead=ahead,
                now_ts=time.time(),
                inv=inv,
                unhedged_step_cents=unhedged_step_cents,
                order_key=key,
                max_hedge_px=max_hedge_px,
            )
            if not changed:
                continue
            order = open_orders[key]
            placed = True
            if repriced_or_new:
                orders_posted += 1
            shown = ahead if ahead is not None else "unknown"
            log(f"M{minute} {outcome} rest {order['shares_left']:.1f} @ {order['price']:.3f} behind {shown} [MAKER · {sub_reason}]")
            log_event("hold", "order-placed", slug, side=outcome,
                      detail={"minute": f"M{minute}",
                              "price": order["price"],
                              "shares": round(order["shares_left"], 2),
                              "role": "MAKER",
                              "subReason": sub_reason,
                              "queueAhead": round(float(order["queue_ahead"]), 1),
                              "deficit": round(float(deficit), 2),
                              "rung": i,
                              "strategy": strat_sym})
        if placed:
            _persist()

    def _cancel_orders(why: str) -> None:
        nonlocal orders_cancelled
        for key, order in list(open_orders.items()):
            log(f"cancel {order['side']} {order['shares_left']:.1f} @ {order['price']:.3f} ({why})")
            log_event("refuse", "order-cancel", slug, side=order["side"],
                      detail={"minute": f"M{order['minute']}", "price": order["price"],
                              "shares": round(order["shares_left"], 2), "why": why,
                              "strategy": strat_sym})
            open_orders.pop(key, None)
            orders_cancelled += 1
        _persist()

    try:
        closed_cleanly = False
        cutoff_sbc = min(stop_before, sweep_before, C.HARD_CUTOFF_SBC)
        end = int(slot + WINDOW_S - stop_before)  # Strategy early exit countdown (e.g. T-75s)
        sweep_end = int(slot + WINDOW_S - cutoff_sbc)  # Phase 4 hard settlement cutoff (e.g. T-12s)
        last_fill_ts = 0.0
        last_fill_px: float | None = None
        last_extreme_skip_ts: float = 0.0
        last_dust_skip_ts: float = 0.0
        deficit_since_ts: float | None = None
        window_bailout_latched: bool = False

        while True:
            now = int(time.time())
            # Phase 0 warms the streamer before the bell; trading starts when the
            # window does. Booking fills against the pre-open book was never a
            # fill anyone could have got.
            if now < slot + start_after_open:
                streamer.wait_for_tick(timeout=0.25)
                continue
            _drain_prints()
            imbalance = abs(inv["Up"]["shares"] - inv["Down"]["shares"])
            if imbalance > 0.5:
                if deficit_since_ts is None:
                    deficit_since_ts = float(now)
            else:
                deficit_since_ts = None
            deficit_duration_sec = (float(now) - deficit_since_ts) if deficit_since_ts is not None else 0.0
            in_sweep_phase = is_sweep_phase(now, end, sweep_end, imbalance)  # Phase: sweep check (pure)
            if should_close(now, end, sweep_end, imbalance):  # Phase: exit check (pure)
                if open_orders:
                    # Exit sweep: cancel any remaining resting bids cleanly before resolution hold.
                    _cancel_orders("sweep phase")
                up_sh = sum(f["shares"] for f in fills if f["outcome"] == "Up")
                down_sh = sum(f["shares"] for f in fills if f["outcome"] == "Down")
                log_event("done", "holding-to-resolution", slug,
                          detail={"fills": len(fills), "cost": round(cost, 2),
                                  "upShares": round(up_sh, 1), "downShares": round(down_sh, 1),
                                  "pairCost": _live_pair_cost(), "strategy": strat_sym,
                                  "imbalance": round(imbalance, 1)})
                break
            if in_sweep_phase and open_orders:
                pulled = prune_pre_sweep_orders(open_orders)
                for order in pulled:
                    orders_cancelled += 1
                    log(f"cancel {order['side']} {order['shares_left']:.1f} @ {order['price']:.3f} (pre-sweep)")
                    log_event("refuse", "order-cancel", slug, side=order["side"],
                              detail={"minute": f"M{order['minute']}", "price": order["price"],
                                      "shares": round(order["shares_left"], 2), "why": "pre-sweep",
                                      "strategy": strat_sym})
                if pulled:
                    _persist()
            state.daily_loss_usd = _current_daily_pnl(day_start)
            if reason := check_window(len(fills), state, KILL_PATH):
                log_event("risk", _risk_reason_code(reason), slug,
                          detail=_risk_detail(reason, state, len(fills)))
                break

            if test_max_fills and len(fills) >= test_max_fills:
                time.sleep(max(0, sweep_end - now))
                continue

            minute = minute_of(slot, now)  # Phase: minute bucket (pure)

            quotes = live_quote_pair(c, spec.up_token_id, spec.down_token_id, streamer=streamer)
            _drain_book_crosses(quotes)
            imbalance = abs(inv["Up"]["shares"] - inv["Down"]["shares"])
            in_sweep_phase = is_sweep_phase(now, end, sweep_end, imbalance)  # Phase: sweep check (pure)
            try:
                _depth_cap = float(entry.get("maxDepthShares", 0.0) or 0.0)
            except Exception:
                _depth_cap = 0.0
            _resting = None
            if _depth_cap > 0 and streamer is not None:
                try:
                    _resting = {}
                    for _side, _tok in (("Up", spec.up_token_id), ("Down", spec.down_token_id)):
                        try:
                            _top = streamer.depth(str(_tok), levels=1)
                            _bids = _top.get("bids") or []
                            _resting[_side] = float(_bids[0][1]) if _bids else None
                        except Exception:
                            _resting[_side] = None
                except Exception:
                    _resting = None
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
                max_unhedged_usd=max_unhedged_usd,
                max_unhedged_shares=max_unhedged_shares,
                dip_curve=dip_curve,
                clip_schedule=clip_schedule,
                in_sweep_phase=in_sweep_phase,
                rescue_ceiling=rescue_ceiling,
                rescue_max_pair_cost=rescue_max_pair_cost,
                leg1_max_price=(float(leg1_max) if leg1_max is not None else None),
                leg2_max_price=(float(leg2_max) if leg2_max is not None else None),
                taker_dip_max=(float(taker_dip_max) if taker_dip_max is not None else None),
                late_rescue_start_sec=(float(late_start) if late_start is not None else None),
                late_rescue_max_pair_cost=(float(late_max) if late_max is not None else None),
                elapsed_sec=float(now - slot),
                unhedged_step_cents=(float(unhedged_step_cents) if unhedged_step_cents is not None else 0.0),
                unhedged_probe_shares=(float(unhedged_probe_shares) if unhedged_probe_shares is not None else 0.0),
                max_depth_shares=_depth_cap,
                resting_size=_resting,
                open_orders=open_orders,
                deficit_duration_sec=deficit_duration_sec,
                window_bailout_latched=window_bailout_latched,
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

            # Phase: pacing (pure helper; relaxed in sweep to guarantee deficit close)
            time_since_fill = time.time() - last_fill_ts
            is_price_move = (last_fill_px is not None and abs(px - last_fill_px) >= 0.001)
            required_spacing = pacing_spacing(in_sweep_phase, is_price_move, min_spacing_move, min_spacing_static)
            if time_since_fill < required_spacing:
                streamer.wait_for_tick(timeout=0.25)
                continue

            # A taker order really does execute at the ask, so it is booked now.
            # A maker order only rests: the fill lands when a print sells into it.
            if role == "TAKER":
                # A taker order really does execute at the ask, so it is booked
                # now. Crossing the spread and leaving a resting bid on the same
                # side would be double exposure the desk never ordered.
                cancel_side_orders(open_orders, outcome)
                _taker_book: dict = {}
                try:
                    _tok = spec.up_token_id if outcome == "Up" else spec.down_token_id
                    _top = streamer.depth(str(_tok), levels=1) if streamer is not None else {}
                    _bids = (_top or {}).get("bids") or []
                    _asks = (_top or {}).get("asks") or []
                    _ask_sz = float(_asks[0][1]) if _asks else None
                    _bid_sz = float(_bids[0][1]) if _bids else None
                    _spread = None
                    try:
                        if _asks and _bids:
                            _spread = round((float(_asks[0][0]) - float(_bids[0][0])) * 100.0, 2)
                    except (TypeError, ValueError, IndexError):
                        _spread = None
                    _taker_book = {"askSize": _ask_sz, "bidSize": _bid_sz, "spreadCents": _spread}
                except Exception:
                    _taker_book = {}
                _book_fill(outcome, px, shares, "TAKER", minute,
                           decision.reason, decision.sub_reason, None,
                           decision.share_deficit, taker_book=_taker_book)
            else:
                if ladder_levels > 1:
                    _place_ladder(outcome, px, shares, minute,
                                  decision.reason, decision.sub_reason, decision.share_deficit)
                else:
                    _place_maker(outcome, px, shares, minute,
                                 decision.reason, decision.sub_reason, decision.share_deficit)
            streamer.wait_for_tick(timeout=0.25)
        closed_cleanly = True
    finally:
        _cancel_orders("window closed")
        stop_sync.set()
        sync_thread.join(timeout=1.0)
        verify_thread.join(timeout=2.0)
        # The audit reads this window's tape to its end. The trading loop exits
        # early (hedged, or at the settlement cutoff), so keep recording until
        # the window closes or a late SELL would read as no flow at all.
        if _tape_on and closed_cleanly:
            left = float(slot) + C.WINDOW_S - time.time()
            if left > 0:
                time.sleep(min(left, float(C.WINDOW_S)))
        streamer.stop()

    # --- Final tape verification pass (definitive, all prints available) ---
    if _tape_on and fills:
        try:
            # The recorder has now run to the window's end, so every print that
            # can fill a resting bid is on disk: both verdicts are final here.
            final_prints = load_prints_for_window(_tape_dir, float(slot), float(slot) + C.WINDOW_S)
            verify_fills(
                fills,
                _tape_dir,
                window_start_s=float(slot),
                window_end_s=float(slot) + C.WINDOW_S,
                force=True,
                prints=final_prints,
            )
            _stamp_attainable(fills, final_prints, spec.condition_id, final=True)
            log(f"tape final: {sum(1 for f in fills if (f.get('detail') or {}).get('tapeStatus') == 'verified')}/{len(fills)} verified")
        except Exception:
            pass

    # --- Close window (pure builders): write run file, trigger async background settlement ---
    result = build_close_result(slug, spec.question or slug, spec.condition_id, fills, cost, strat_id, strat_sym, total_fees_usd, _live_pair_cost(), orders_posted, orders_cancelled)
    maker_count = result["maker_fills"]
    WINDOWS_MIRROR_DIR.mkdir(parents=True, exist_ok=True)
    (WINDOWS_MIRROR_DIR / f"{slug}.json").write_text(json.dumps(result, indent=2))
    ws = get_current_workspace()
    if ws:
        try:
            ws.windows_dir.mkdir(parents=True, exist_ok=True)
            (ws.windows_dir / f"{slug}.json").write_text(json.dumps(result, indent=2))
        except Exception as ex:
            log(f"warning: failed to save {slug}.json to workspace {ws.run_id}: {ex}")
    # Keep this window's state on disk after the cutoff. The market still has to
    # resolve and the desk has to show what is being held into resolution; the
    # old unlink() here blanked the position strip for the last 75s of every
    # window. The next window overwrites it, and settle_slug removes it once the
    # outcome is known.
    try:
        write_state(slug, end_ms, started_ms, fills, closed=True,
                    ws_status=streamer.get_status(), recent_ticks=streamer.get_recent_ticks(30),
                    orders_posted=orders_posted, orders_cancelled=orders_cancelled)
    except Exception as ex:
        log(f"warning: failed to persist the held window state: {type(ex).__name__}")
    log(f"window closed, {len(fills)} fills, cost ${cost:.2f} — settling in background…")
    snap = build_close_snap(slug, spec.question or slug, spec.condition_id, slot, fills, cost, _tape_dir, maker_count, result["taker_fills"], total_fees_usd, _live_pair_cost(), orders_posted, orders_cancelled)
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
    # Paper-modeled taker rebate (see live_records.compute_settlement_pure):
    # shell owns the cfg seam, pure module owns the math.
    taker_fees_usd = round(float(snap.get("fees_usd") or 0.0), 2)
    _settlement = compute_settlement_pure(fills, cost, taker_fees_usd, winner, paper_rebate_rate())
    payout = _settlement["payout"]
    net = _settlement["net"]
    rebate_usd = _settlement["rebate_usd"]
    rebate_rate = _settlement["rebate_rate"]
    net_rebated_usd = _settlement["net_rebated_usd"]

    # The definitive read of the fills: a maker fill only counts when the tape
    # shows enough taker selling behind the queue that was actually resting.
    # Resolution is when the window's tape is complete, so this is the number
    # to trust over the assumed paper one.
    fidelity = None
    if winner and snap.get("tapeDir") and snap.get("slot"):
        try:
            slot_s = float(snap["slot"])
            prints = load_prints_for_window(Path(snap["tapeDir"]), slot_s, slot_s + C.WINDOW_S)
            try:
                _book = load_book_for_window(Path(snap["tapeDir"]), slot_s, slot_s + C.WINDOW_S)
            except (OSError, ValueError):
                _book = None
            # Resolution is the last word on attainability: stamp the rows too,
            # so the fills table and the window total can never disagree.
            _stamp_attainable(fills, prints, snap.get("condition_id"), final=True)
            fidelity = audit_window(fills, prints, slot_s, winner, snap.get("condition_id"), book=_book)
        except (OSError, ValueError):
            fidelity = None

    result = {
        "event_slug": slug,
        "market": snap.get("market", slug),
        "condition_id": snap.get("condition_id"),
        "trades": len(fills),
        "cost_usd": cost,
        "payout_usd": payout,
        "net_usd": net,
        "rebate_usd": rebate_usd,
        "rebate_rate": rebate_rate,
        "net_rebated_usd": net_rebated_usd,
        "winner": winner,
        "resolvedAt": datetime.now(timezone.utc).isoformat(),
        "fills": fills,
        "strategy": snap.get("strategy", C.STRATEGY_ID),
        "strategy_symbol": snap.get("strategy_symbol", C.STRATEGY_SYMBOL),
        "maker_fills": snap.get("maker_fills"),
        "taker_fills": snap.get("taker_fills"),
        "fees_usd": snap.get("fees_usd"),
        "pair_cost": snap.get("pair_cost"),
        "orders_posted": snap.get("orders_posted"),
        "orders_cancelled": snap.get("orders_cancelled"),
        "fidelity": fidelity,
    }
    if winner:
        result.pop("pending", None)
    else:
        result["pending"] = True
    try:
        WINDOWS_MIRROR_DIR.mkdir(parents=True, exist_ok=True)
        (WINDOWS_MIRROR_DIR / f"{slug}.json").write_text(json.dumps(result, indent=2))
        ws = get_current_workspace()
        if ws:
            ws.windows_dir.mkdir(parents=True, exist_ok=True)
            (ws.windows_dir / f"{slug}.json").write_text(json.dumps(result, indent=2))
    except OSError:
        pass
    # The window is resolved, so the held-position snapshot has done its job.
    # Only clear it if it still belongs to this slug — the loop may already have
    # written the next window's state.
    with _STATE_LOCK:
        try:
            _settle_ws = get_current_workspace()
            _settle_path = _state_target(_settle_ws)
            if _settle_path.exists():
                st = json.loads(_settle_path.read_text())
                if st.get("slug") == slug:
                    _settle_path.unlink()
        except (OSError, ValueError):
            pass
    log_event("settle", "paper-resolve", slug,
              detail={"winner": winner, "fills": len(fills), "cost": cost,
                      "payout": payout, "net": net,
                      "rebate": rebate_usd, "netRebated": net_rebated_usd})
    print(f"[{slug}] resolved: winner={winner} payout=${payout:.2f} net=${net:.2f} rebate=${rebate_usd:.2f} netRebated=${net_rebated_usd if net_rebated_usd is not None else float('nan'):.2f}", flush=True)
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
    migrate_windows_mirror()
    c = PublicClient()

    ws = init_run_session(run_id=args.run_id, label=args.label)
    cfg = load_cfg()
    strat = cfg.get("strategy", {})
    strat_sym = strat.get("symbol", C.STRATEGY_SYMBOL)
    strat_name = strat.get("name", C.STRATEGY_NAME)
    print(f"session initialized: {ws.run_id} ({strat_sym} · {strat_name})", flush=True)
    try:
        run_tape_dir()
    except OSError as ex:
        # The tape is what makes the fills auditable, so there is no trading without it.
        print(f"tape recording is required - cannot use {ws.tape_dir}: {ex}", flush=True)
        ws.finalize(status="failed")
        raise SystemExit(1)
    try:
        from bot.runs import PID_PATH as _PID_PATH

        ensure_data_dir()
        _PID_PATH.write_text(str(os.getpid()))
        try:
            ws.pid_file.write_text(str(os.getpid()))
        except Exception:
            pass
    except Exception:
        pass

    def _sigterm_handler(signum, frame):
        try:
            from bot.runs import PID_PATH as _PID_PATH2

            _PID_PATH2.unlink(missing_ok=True)
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
                _pre_tape = run_tape_dir()
                active_streamer = LiveBookStreamer(
                    up_token_id=next_spec.up_token_id,
                    down_token_id=next_spec.down_token_id,
                    rest_fallback_client=c,
                    enable_trade_prints=_pre_tape is not None,
                    tape_dir=_pre_tape,
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
