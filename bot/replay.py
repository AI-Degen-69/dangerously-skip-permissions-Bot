"""Replay the recorded tape to test placement rules offline.

Replays one recorded market window at a time: walks the window's clock, takes
quotes from the recorded ``book.jsonl`` snapshots, applies a placement rule by
calling the REAL ``bot.executor`` helpers, and books fills from the recorded
``prints.jsonl`` via ``bot.fill_model.match_maker_print``.

The replay never reads a window's own fills to drive the simulation -- only
``condition_id``, ``event_slug`` (start epoch) and ``winner`` (for scoring).

Usage:
    python -m bot.replay --run bot/runs/run_20261113_080232_paper_dsp_v2_6 --rule v2.6
    python -m bot.replay --runs all --rule hump --ceiling 0.75 --levels 2 --spacing 0.02
    python -m bot.replay --runs all --rule v2.6 --against-live       # gate mode

v2.7 ablations (one knob at a time against the hump baseline):
    python -m bot.replay --runs all --rule hump --ceiling 0.55 --levels 2 --spacing 0.01
    python -m bot.replay --runs all --rule hump --levels 2 --spacing 0.01 --leg1-max 0.48 --leg2-ceiling 0.75 --unhedged-usd 45
    python -m bot.replay --runs all --rule hump --levels 2 --spacing 0.01 --leg1-max 0.48 --leg2-ceiling 0.75 --unhedged-usd 45 --taker-dip-max 0.45
    python -m bot.replay --runs all --rule hump --levels 2 --spacing 0.01 --leg1-max 0.48 --leg2-ceiling 0.75 --unhedged-usd 45 --taker-dip-max 0.45 --rescue-max-pair 1.02
    (--rule v2.7 replays the canned v2.7 entry: same knobs, hump sized natively.)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from bot import constants as C
from bot import executor as E
from bot.executor import compute_fill_usd, evaluate_microstructure_ladder
from bot.fill_model import match_maker_print
from bot.risk import clip_shares
from bot.runs import tape_segments

WINDOW_S = int(C.WINDOW_S)
STRATEGY_V26 = "dangerously-skip-permissions-v2.6"
STRATEGY_V27 = "dangerously-skip-permissions-v2.7"
STRATEGY_HYDROGEN = "hydrogen-v1.0"
BASELINE_RUN = "run_20261113_080232_paper_dsp_v2_6"
LOOP_LOG = Path("bot/loop.log")

FOUR_RUNS = [
    "run_20261110_183056_paper_dsp_v2_5",
    "run_20261113_080232_paper_dsp_v2_6",
    "run_20261113_061914_paper_dsp_v2_6",
    "run_20261113_073610_paper_dsp_v2_6",
]

# Hump sizing anchors: (price, shares). The wallet sizes fat in the middle
# (~48.7 sh at 40-50c) and thin at the extremes (~30 sh), the inverse of the
# shipped inverse-dip curve (33 sh at 7c -> 8 sh at 45c).
HUMP_ANCHORS = [(0.07, 30.0), (0.10, 30.0), (0.40, 48.7), (0.50, 48.7), (0.70, 30.0)]


def hump_shares(price: float, max_clip: float) -> float:
    """Piecewise-linear hump clip, clamped outside the anchors."""
    try:
        px = float(price)
    except (TypeError, ValueError):
        return 10.0
    pts = HUMP_ANCHORS
    if px <= pts[0][0]:
        sh = pts[0][1]
    elif px >= pts[-1][0]:
        sh = pts[-1][1]
    else:
        sh = pts[-1][1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= px <= x1:
                a = (px - x0) / (x1 - x0) if x1 > x0 else 0.0
                sh = y0 + (y1 - y0) * a
                break
    return min(clip_shares(round(sh, 1), max_clip), max_clip)


def make_hump_sizing(max_clip: float):
    """select_ladder_clip replacement: deficit branch verbatim, dip = hump.

    Same pattern as scratch/sizing_sim.py: the sizing curve is the parameter
    under test, the engine (evaluate_microstructure_ladder) is untouched.
    """

    def sizing(deficit, price, pair_cost=None, fill_idx=0, default_clip=None,
               max_clip=max_clip, whole_ladder=True, current_lead=0.0,
               is_v22=False, atomic_arb=False, is_v23=False,
               target_risk_usd=None, dip_curve=None, **kwargs):
        if deficit > 0:
            return min(clip_shares(deficit, max_clip), max_clip)
        return hump_shares(price, max_clip)

    return sizing


# ---------------------------------------------------------------------------
# Tape slicing (cached per run under scratch/ or %TEMP%)
# ---------------------------------------------------------------------------

def cache_dir() -> Path:
    base = Path("scratch/replay_cache") if Path("scratch").exists() else Path(tempfile.gettempdir()) / "replay_cache"
    base.mkdir(parents=True, exist_ok=True)
    return base


def list_run_windows(run_dir: Path) -> list[dict]:
    """(slot, condition_id, winner, slug) for every window file in a run."""
    out = []
    wdir = run_dir / "windows"
    if not wdir.exists():
        return out
    for p in sorted(wdir.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        slug = d.get("event_slug") or p.stem
        try:
            slot = int(str(slug).rsplit("-", 1)[1])
        except (ValueError, IndexError):
            continue
        out.append({
            "slot": slot,
            "slug": slug,
            "condition_id": d.get("condition_id"),
            "winner": d.get("winner"),
        })
    return out


def load_prints_grouped(tape_dir: Path) -> dict[str, list[dict]]:
    """Prints grouped by market (condition id), oldest first per market."""
    grouped: dict[str, list[dict]] = {}
    # Flat ts-ordered log too: windows without a recorded condition_id (older
    # run format) join prints by time, majority market wins the slice.
    flat: list[dict] = []
    for path in tape_segments(tape_dir, "prints"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue  # tolerated: tape is append-only, last line may be partial
                    mkt = str(rec.get("market") or "")
                    if not mkt:
                        continue
                    try:
                        ts = float(rec.get("ts") or 0.0)
                    except (TypeError, ValueError):
                        continue
                    if ts <= 0:
                        continue
                    grouped.setdefault(mkt, []).append(rec)
                    flat.append(rec)
        except OSError:
            continue
    for recs in grouped.values():
        recs.sort(key=lambda r: float(r.get("ts") or 0.0))
    flat.sort(key=lambda r: float(r.get("ts") or 0.0))
    grouped[""] = flat  # scratch key: time-slice source for the fallback join
    return grouped


def build_slices(run_id: str, runs_root: Path = Path("bot/runs")) -> dict:
    """Per-window (book_events, prints) slices for one run, cached on disk.

    One streaming pass over the book segments: rows are assigned to a window
    by asset_id (each market's two tokens are learned from its prints) and
    clipped to [slot, slot+300]. Book segments are large (100+ MB), so this
    runs once per tape state and is pickled afterwards.
    """
    cdir = cache_dir()
    run_dir = runs_root / run_id
    tape_dir = run_dir / "tape"
    manifest = {"windows": [], "prints": {}, "book": {}}
    windows = list_run_windows(run_dir)
    if not windows or not tape_dir.exists():
        return manifest

    prints_by_market = load_prints_grouped(tape_dir)
    flat = prints_by_market.pop("", [])
    import bisect as _bisect
    flat_ts = [float(r.get("ts") or 0.0) for r in flat]
    voted = 0
    for w in windows:
        if not w.get("condition_id"):
            # Older window format: no condition_id recorded. The window's own
            # recorder is the first to write into its time range, so the
            # majority market in [slot, slot+300] is this window's.
            lo = _bisect.bisect_left(flat_ts, float(w["slot"]))
            hi = _bisect.bisect_right(flat_ts, float(w["slot"]) + WINDOW_S)
            counts: dict[str, int] = {}
            for rec in flat[lo:hi]:
                mkt = str(rec.get("market") or "")
                if mkt:
                    counts[mkt] = counts.get(mkt, 0) + 1
            if counts:
                w["condition_id"] = max(counts, key=lambda m: counts[m])
                voted += 1
    # asset_id -> slot: each market's tokens are unique to it.
    asset_to_slot: dict[str, int] = {}
    for w in windows:
        for rec in prints_by_market.get(str(w["condition_id"] or ""), []):
            aid = str(rec.get("asset_id") or "")
            if aid and aid not in asset_to_slot:
                asset_to_slot[aid] = w["slot"]

    by_slot: dict[int, list] = {w["slot"]: [] for w in windows}
    slot_set = set(by_slot)
    for path in tape_segments(tape_dir, "book"):
        try:
            f = open(path, "r", encoding="utf-8")
        except OSError:
            continue
        with f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue  # partial last line while the live loop is writing
                aid = str(rec.get("asset_id") or "")
                slot = asset_to_slot.get(aid)
                if slot is None or slot not in slot_set:
                    continue
                try:
                    ts = float(rec.get("ts") or 0.0)
                except (TypeError, ValueError):
                    continue
                if ts < slot or ts > slot + WINDOW_S:
                    continue
                bids = rec.get("bids") or []
                asks = rec.get("asks") or []
                try:
                    bids = [[float(p), float(s)] for p, s in bids]
                    asks = [[float(p), float(s)] for p, s in asks]
                except (TypeError, ValueError):
                    continue
                by_slot[slot].append((ts, str(rec.get("outcome") or ""), bids, asks))
    for rows in by_slot.values():
        rows.sort(key=lambda r: r[0])

    manifest["windows"] = windows
    manifest["voted_markets"] = voted
    manifest["prints"] = {
        w["condition_id"]: [
            (float(r.get("ts") or 0.0), str(r.get("slug_outcome") or ""),
             float(r.get("price") or 0.0), float(r.get("size") or 0.0),
             str(r.get("side") or ""), str(r.get("asset_id") or ""))
            for r in prints_by_market.get(str(w["condition_id"] or ""), [])
            if w["slot"] <= float(r.get("ts") or 0.0) <= w["slot"] + WINDOW_S
        ]
        for w in windows
    }
    manifest["book"] = {str(s): rows for s, rows in by_slot.items()}
    # asset -> outcome fallback for prints missing slug_outcome
    outcome_by_asset: dict[str, str] = {}
    for w in windows:
        for rec in prints_by_market.get(str(w["condition_id"] or ""), []):
            aid, oc = str(rec.get("asset_id") or ""), str(rec.get("slug_outcome") or "")
            if aid and oc and aid not in outcome_by_asset:
                outcome_by_asset[aid] = oc
    manifest["asset_outcome"] = outcome_by_asset
    try:
        with open(cdir / f"{run_id}.pkl", "wb") as f:
            pickle.dump(manifest, f, protocol=5)
    except OSError:
        pass
    return manifest


def load_slices(run_id: str, runs_root: Path = Path("bot/runs")) -> dict:
    """Cached slices; rebuilt when the tape grew since the cache was written."""
    cdir = cache_dir()
    run_dir = runs_root / run_id
    tape_dir = run_dir / "tape"
    cache_path = cdir / f"{run_id}.pkl"
    if cache_path.exists() and tape_dir.exists():
        try:
            newest = max(p.stat().st_mtime for p in list(tape_dir.glob("*.jsonl")))
            if cache_path.stat().st_mtime >= newest:
                with open(cache_path, "rb") as f:
                    return pickle.load(f)
        except Exception:
            pass
    return build_slices(run_id, runs_root)


def load_run_entry(run_id: str, runs_root: Path = Path("bot/runs")) -> tuple[str, dict]:
    """(strategy_id, entry) frozen in the run's own config snapshot."""
    try:
        meta = json.loads((runs_root / run_id / "run_meta.json").read_text(encoding="utf-8"))
        snap = meta.get("configSnapshot", {}) or {}
        strat = (snap.get("strategy") or {}).get("id", STRATEGY_V26)
        entry = dict(snap.get("entry") or {})
        if entry:
            return str(strat), entry
    except Exception:
        pass
    reg = C.STRATEGY_SETUPS[STRATEGY_V26]
    return STRATEGY_V26, dict(reg["entry"])


# ---------------------------------------------------------------------------
# Simulation (mirrors bot/live_paper.trade_window)
# ---------------------------------------------------------------------------

def _quotes_from_state(state: dict) -> dict:
    def side(o):
        b = state[o]["bid"]
        a = state[o]["ask"]
        return {"bid": b if b is not None else a, "ask": a}
    return {"Up": side("Up"), "Down": side("Down")}


def simulate_window(slot: int, winner: str | None, book_rows: list, prints: list,
                    strategy_id: str, entry: dict, levels: int = 1,
                    spacing: float = 0.02, queue_mode: str = "exact",
                    eval_floor_s: float = 0.0,
                    unhedged_step_cents: float = 0.0) -> dict:
    """Replay one window. Deterministic: same inputs -> same output."""
    start_after_open = float(entry.get("startAfterOpenSec", 4))
    stop_before = float(entry.get("stopBeforeCloseSec", 75))
    try:
        sweep_before = float(entry.get("sweepBeforeCloseSec", C.HARD_CUTOFF_SBC))
    except (TypeError, ValueError):
        sweep_before = float(C.HARD_CUTOFF_SBC)
    cutoff_sbc = min(stop_before, sweep_before, float(C.HARD_CUTOFF_SBC))
    end = slot + WINDOW_S - stop_before
    sweep_end = slot + WINDOW_S - cutoff_sbc
    min_fill = max(0.01, float(entry.get("minFillPrice", C.PRICE_FLOOR)))
    max_fill = min(0.99, float(entry.get("maxFillPrice", C.PRICE_CEILING)))
    clip_default = float(entry.get("clipSharesDefault", C.CLIP_SHARES_DEFAULT))
    max_shares = float(entry.get("maxShares", C.MAX_SHARES))
    target_pc = float(entry.get("targetPairCost", C.TARGET_PAIR_COST))
    max_pc = float(entry.get("maxPairCost", C.PAIR_COST_MAX))
    max_lead = float(entry.get("maxShareLead", C.MAX_SHARE_LEAD))
    try:
        max_unhedged_usd = float(entry.get("maxUnhedgedUsd", 0.0) or 0.0)
    except (TypeError, ValueError):
        max_unhedged_usd = 0.0
    dip_curve = entry.get("dipCurve") or None
    rescue_ceiling = float(entry.get("rescueCeilingPrice", C.RESCUE_CEILING_PRICE))
    rescue_max = float(entry.get("rescuePairCostMax", C.RESCUE_PAIR_COST_MAX))
    leg1_max = entry.get("leg1MaxPrice", entry.get("maxLeg1Price", None))
    try:
        leg1_max = float(leg1_max) if leg1_max is not None else None
    except (TypeError, ValueError):
        leg1_max = None
    leg2_max = entry.get("leg2MaxPrice", None)
    try:
        leg2_max = float(leg2_max) if leg2_max is not None else None
    except (TypeError, ValueError):
        leg2_max = None
    taker_dip_max = entry.get("takerDipEntryMax", entry.get("takerDipMax", None))
    try:
        taker_dip_max = float(taker_dip_max) if taker_dip_max is not None else None
    except (TypeError, ValueError):
        taker_dip_max = None
    taker_hedge_cap = entry.get("takerHedgeMaxPairCost", entry.get("takerHedgeMaxPair", None))
    try:
        taker_hedge_cap = float(taker_hedge_cap) if taker_hedge_cap is not None else None
    except (TypeError, ValueError):
        taker_hedge_cap = None
    hedge_clip = entry.get("hedgeMaxClip", entry.get("takerHedgeMaxClip", None))
    try:
        hedge_clip = float(hedge_clip) if hedge_clip is not None else None
    except (TypeError, ValueError):
        hedge_clip = None
    try:
        unhedged_step_cents = float(entry.get("unhedgedStepCents", 0.0) or 0.0)
    except (TypeError, ValueError):
        unhedged_step_cents = 0.0
    try:
        unhedged_probe_shares = float(entry.get("unhedgedProbeShares", 0.0) or 0.0)
    except (TypeError, ValueError):
        unhedged_probe_shares = 0.0
    late_start = entry.get("lateRescueStartSec", None)
    try:
        late_start = float(late_start) if late_start is not None else None
    except (TypeError, ValueError):
        late_start = None
    late_max = entry.get("lateRescueMaxPairCost", None)
    try:
        late_max = float(late_max) if late_max is not None else None
    except (TypeError, ValueError):
        late_max = None
    spacing_move = float(entry.get("minSpacingMoveSec", 0.5))
    spacing_static = float(entry.get("minSpacingStaticSec", 2.5))
    include_fee = bool(entry.get("includeTakerFee", True))

    inv = {"Up": {"shares": 0.0, "cost": 0.0}, "Down": {"shares": 0.0, "cost": 0.0}}
    fills: list[dict] = []
    cost = 0.0
    fees = 0.0
    placements = 0
    queue_unknown = 0
    # side -> {"bid","ask","bids","asks"} latest snapshot
    state = {"Up": {"bid": None, "ask": None, "bids": [], "row_ts": 0.0},
             "Down": {"bid": None, "ask": None, "bids": [], "row_ts": 0.0}}
    # SELL flow per outcome, ts-ordered, to net against snapshot queues.
    import bisect as _bisect
    sells: dict[str, list] = {"Up": [], "Down": []}
    for (pts, poc, ppx, psz, psd, _a) in prints:
        if poc in sells and str(psd) == "SELL" and (psz or 0) > 0:
            try:
                sells[poc].append((float(pts), float(ppx), float(psz)))
            except (TypeError, ValueError):
                continue
    for v in sells.values():
        v.sort()
    sell_ts = {k: [t for t, _, _ in v] for k, v in sells.items()}
    # side -> list of resting order dicts (best price first)
    resting: dict[str, list[dict]] = {"Up": [], "Down": []}
    next_eval_ts = float("-inf")
    last_fill_ts = 0.0
    last_fill_px: float | None = None

    def book_fill(outcome, px, shares, role, minute, sub_reason, queue_ahead, deficit, ts):
        nonlocal cost, fees, last_fill_ts, last_fill_px
        usd, fee_usd = compute_fill_usd(shares, px, role=role, include_fee=include_fee)
        inv[outcome]["shares"] += shares
        inv[outcome]["cost"] += usd
        cur_low = inv[outcome].get("lowest_price")
        if cur_low is None or px < cur_low:
            inv[outcome]["lowest_price"] = px
        cost += usd
        fees += fee_usd
        last_fill_ts = ts
        last_fill_px = px
        fills.append({"ts": ts, "minute": minute, "outcome": outcome, "price": px,
                      "shares": shares, "usd": usd, "role": role,
                      "subReason": sub_reason, "feeUsd": fee_usd,
                      "queueAhead": queue_ahead, "deficit": deficit})

    def offer_print(outcome, side, px, size, ts):
        orders = resting.get(outcome) or []
        # Best (highest) bid is hit first, and one print's size is spent
        # across rungs as it is consumed (mirror of fill_audit._spend): the
        # same shares cannot fill every level.
        remaining = size
        for order in list(orders):
            if remaining <= 0:
                break
            hit = match_maker_print(order, {"outcome": outcome, "side": side,
                                            "price": px, "size": remaining})
            if hit is not None:
                if unhedged_step_cents > 0:
                    opp_side = "Down" if outcome == "Up" else "Up"
                    if inv[opp_side]["shares"] == 0 and inv[outcome]["shares"] > 0:
                        held_pxs = [f["price"] for f in fills if f["outcome"] == outcome]
                        min_held = min(held_pxs) if held_pxs else 1.0
                        if order["price"] > min_held - (unhedged_step_cents / 100.0) + 1e-9:
                            continue
                consumed = ((hit["queueAhead"] - float(order.get("queue_ahead") or 0.0))
                            + hit["fills"])
                remaining = max(0.0, remaining - consumed)
                book_fill(outcome, order["price"], hit["fills"], "MAKER",
                          _minute(ts), order["sub_reason"], hit["queueAhead"],
                          order["deficit"], ts)
                if os.environ.get("REPLAY_TRACE"):
                    print(f"TRACE fill {ts:.1f} {outcome} {order['price']} x{hit['fills']:.2f} qpaid={hit['queueAhead']:.1f}", flush=True)
            if order["shares_left"] <= 0:
                try:
                    orders.remove(order)
                except ValueError:
                    pass

    def _minute(ts):
        return int(min(max((ts - slot) // 60, 0), 4))

    def place_levels(outcome, px, shares, minute, reason, sub_reason, deficit, ts):
        """Diff desired level set against resting orders (mirror _place_maker).

        Same price -> keep the order where it is (no re-queue). New levels get
        queue_ahead = resting size AT the limit price (mirror of
        live_paper.live_queue_ahead, which reads book.bids.get(price)), net
        of recorded SELL flow between the snapshot's ts and now: the live
        book at the placement tick already reflects those prints, while the
        snapshot predates them. When the level is outside the visible top-5
        the queue is unknown: place with 0.0 (exactly what the live loop
        stores for None) and count it.
        """
        nonlocal placements, queue_unknown
        bids = state[outcome]["bids"] or []
        desired = [round(px - i * spacing, 4) for i in range(max(1, levels))]
        if unhedged_step_cents > 0:
            opp_side = "Down" if outcome == "Up" else "Up"
            if inv[opp_side]["shares"] == 0 and inv[outcome]["shares"] > 0:
                held_pxs = [f["price"] for f in fills if f["outcome"] == outcome]
                min_held = min(held_pxs) if held_pxs else 1.0
                max_allowed = min_held - (unhedged_step_cents / 100.0) + 1e-9
                desired = [d for d in desired if d <= max_allowed]
        keep = []
        for order in resting[outcome]:
            if any(abs(order["price"] - d) < 1e-9 for d in desired):
                keep.append(order)
        resting[outcome] = keep
        have = {round(o["price"], 4) for o in keep}
        for d in desired:
            if d in have:
                continue
            if d < min_fill or d <= 0:
                continue
            if queue_mode == "cumulative":
                qa = sum(s for p, s in bids if p >= d - 1e-9)
                if not any(abs(p - d) < 1e-9 for p, s in bids):
                    queue_unknown += 1
            else:
                level = next((s for p, s in bids if abs(p - d) < 1e-9), None)
                if level is None:
                    queue_unknown += 1
                    qa = 0.0
                else:
                    qa = float(level)
                    row_ts = float(state[outcome].get("row_ts") or 0.0)
                    if row_ts < ts:
                        flow = sells.get(outcome) or []
                        tss = sell_ts.get(outcome) or []
                        lo = _bisect.bisect_right(tss, row_ts)
                        hi = _bisect.bisect_right(tss, ts, lo=lo)
                        for _, ppx, psz in flow[lo:hi]:
                            if ppx <= d + 1e-9:
                                qa -= psz
                                if qa <= 0:
                                    qa = 0.0
                                    break
            resting[outcome].append({"side": outcome, "price": d,
                                    "shares_left": shares, "queue_ahead": float(qa),
                                    "placed_ts": ts, "reason": reason,
                                    "sub_reason": sub_reason, "minute": minute,
                                    "deficit": deficit})
            placements += 1
            if os.environ.get("REPLAY_TRACE"):
                print(f"TRACE place {ts:.1f} {outcome} {d} x{shares:.1f} qa={qa:.1f} row_age={ts - float(state[outcome].get('row_ts') or ts):.2f}", flush=True)
        resting[outcome].sort(key=lambda o: -o["price"])

    def cancel_orders():
        resting["Up"] = []
        resting["Down"] = []

    events = []
    for (ts, outcome, bids, asks) in book_rows:
        events.append((ts, 1, ("book", outcome, bids, asks)))
    for (ts, outcome, px, size, side, _aid) in prints:
        events.append((ts, 0, ("print", outcome, px, size, side)))
    events.sort(key=lambda e: (e[0], e[1]))

    for ts, _kind, payload in events:
        if ts < slot + start_after_open:
            # Pre-open book warms the quotes; nothing books before the bell.
            if payload[0] == "book":
                _, outcome, bids, asks = payload
                if outcome in state:
                    state[outcome]["bids"] = bids
                    state[outcome]["bid"] = bids[0][0] if bids else None
                    state[outcome]["ask"] = asks[0][0] if asks else None
                    state[outcome]["row_ts"] = ts
            continue
        if payload[0] == "print":
            _, outcome, px, size, side = payload
            if outcome in resting and resting[outcome]:
                offer_print(outcome, side, px, size, ts)
            continue
        _, outcome, bids, asks = payload
        if outcome not in state:
            continue
        state[outcome]["bids"] = bids
        state[outcome]["bid"] = bids[0][0] if bids else None
        state[outcome]["ask"] = asks[0][0] if asks else None
        state[outcome]["row_ts"] = ts

        # The live loop wakes on every streamer tick, but each iteration pays
        # journal + log I/O, so it evaluates at ~10-80/s (measured in the
        # runs' decisions.jsonl), not at the recorded message rate. The
        # eval_floor_s knob caps the evaluation cadence for sensitivity
        # runs (0 = every recorded row); prints are always offered at full
        # resolution. Both settings pass the gate on the clean set.
        if eval_floor_s and ts < next_eval_ts:
            continue
        if eval_floor_s:
            next_eval_ts = ts + eval_floor_s
        imbalance = abs(inv["Up"]["shares"] - inv["Down"]["shares"])
        in_sweep = (ts >= end and ts < sweep_end and imbalance > 0.0)
        if ts >= end and (resting["Up"] or resting["Down"]):
            # The strategy stops opening in the sweep; a bid left resting
            # through it would fill on flow the strategy never saw.
            cancel_orders()
        if ts >= sweep_end or (ts >= end and imbalance <= 0.0):
            break

        quotes = _quotes_from_state(state)
        decision = evaluate_microstructure_ladder(
            quotes=quotes, inv=inv, fill_idx=len(fills), minute=_minute(ts),
            strategy_id=strategy_id, min_fill=min_fill, max_fill=max_fill,
            default_clip=clip_default, max_clip=max_shares,
            whole_ladder=True, target_pair_cost=target_pc,
            max_pair_cost=max_pc, max_share_lead=max_lead,
            max_unhedged_usd=max_unhedged_usd, dip_curve=dip_curve,
            in_sweep_phase=in_sweep, rescue_ceiling=rescue_ceiling,
            rescue_max_pair_cost=rescue_max,
            leg1_max_price=leg1_max, leg2_max_price=leg2_max,
            taker_dip_max=taker_dip_max,
            taker_hedge_max_pair_cost=taker_hedge_cap,
            hedge_max_clip=hedge_clip,
            late_rescue_start_sec=late_start,
            late_rescue_max_pair_cost=late_max,
            elapsed_sec=float(ts - slot),
            unhedged_step_cents=unhedged_step_cents,
            unhedged_probe_shares=unhedged_probe_shares,
        )
        if decision.action == "skip" or decision.outcome is None or decision.price is None:
            continue
        outcome_d = decision.outcome
        px = decision.price
        shares = min(clip_shares(decision.shares, max_shares), max_shares)
        time_since_fill = ts - last_fill_ts
        is_move = last_fill_px is not None and abs(px - last_fill_px) >= 0.001
        required = 0.5 if in_sweep else (spacing_move if is_move else spacing_static)
        if time_since_fill < required:
            continue
        if decision.role == "TAKER":
            if unhedged_step_cents > 0:
                opp_side = "Down" if outcome_d == "Up" else "Up"
                if inv[opp_side]["shares"] == 0 and inv[outcome_d]["shares"] > 0:
                    held_pxs = [f["price"] for f in fills if f["outcome"] == outcome_d]
                    min_held = min(held_pxs) if held_pxs else 1.0
                    if px > min_held - (unhedged_step_cents / 100.0) + 1e-9:
                        continue
            resting[outcome_d] = []
            book_fill(outcome_d, px, shares, "TAKER", _minute(ts),
                      decision.sub_reason, None, decision.share_deficit, ts)
        else:
            place_levels(outcome_d, px, shares, _minute(ts), decision.reason,
                         decision.sub_reason, decision.share_deficit, ts)

    up = sum(f["shares"] for f in fills if f["outcome"] == "Up")
    down = sum(f["shares"] for f in fills if f["outcome"] == "Down")
    wshares = (up if winner == "Up" else down) if winner in ("Up", "Down") else None
    payout = round(wshares, 2) if wshares is not None else None
    net = round(payout - cost, 2) if payout is not None else None
    pair_cost = round(cost / min(up, down), 4) if min(up, down) > 0 else None
    maker = sum(1 for f in fills if f["role"] == "MAKER")
    return {"slot": slot, "winner": winner, "fills": fills, "n_fills": len(fills),
            "n_maker": maker, "n_taker": len(fills) - maker,
            "cost": round(cost, 2), "fees": round(fees, 4),
            "payout": payout, "net": net, "pair_cost": pair_cost,
            "up": round(up, 2), "down": round(down, 2),
            "placements": placements, "queue_unknown": queue_unknown,
            "frag": sum(1 for f in fills if f["shares"] < 1)}


# ---------------------------------------------------------------------------
# Live fixture (recomputed at gate time -- the baseline run is still growing)
# ---------------------------------------------------------------------------

def coverage_ok(slot: int, book_rows: list, prints: list) -> tuple[bool, str]:
    """A window is replayable only if the surviving tape covers its action.

    Rotation/pruning deleted most book history, so windows whose book starts
    mid-window (after the live fills already happened) are excluded rather
    than scored as zero-fill matches.
    """
    if not prints:
        return False, "no-prints"
    if len(book_rows) < 100:
        return False, "thin-book"
    if set(r[1] for r in book_rows) < {"Up", "Down"}:
        return False, "one-sided-book"
    first = min(r[0] for r in book_rows)
    if first > slot + 60:
        return False, "book-starts-mid-window"
    return True, "ok"


def live_fixture(run_id: str = BASELINE_RUN, runs_root: Path = Path("bot/runs"),
                 slugs: list[str] | None = None) -> dict:
    """What the bot actually did: fills stamped with the run's own strategy.

    When `slugs` is given, the fixture is recomputed over exactly that
    subset (the gate compares replay and live on the same windows).
    """
    try:
        meta = json.loads((runs_root / run_id / "run_meta.json").read_text(encoding="utf-8"))
        S = str((meta.get("configSnapshot") or {}).get("strategy", {}).get("id", STRATEGY_V26))
    except Exception:
        S = STRATEGY_V26
    wdir = runs_root / run_id / "windows"
    keep = set(slugs) if slugs is not None else None
    per_window = []
    fills = maker = taker = frag = 0
    cost = payout = fees = 0.0
    pair_costs = []
    traded = 0
    for p in sorted(wdir.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        slug = d.get("event_slug") or p.stem
        if keep is not None and slug not in keep:
            continue
        fs = [f for f in d.get("fills", []) if (f.get("detail") or {}).get("strategy") == S]
        up = sum(f.get("shares", 0.0) for f in fs if f.get("outcome") == "Up")
        dn = sum(f.get("shares", 0.0) for f in fs if f.get("outcome") == "Down")
        wcost = sum(f.get("usd", 0.0) for f in fs)
        live_n = len(fs)
        if live_n:
            traded += 1
        fills += live_n
        for f in fs:
            fees += float((f.get("detail") or {}).get("feeUsd") or 0.0)
            if (f.get("detail") or {}).get("role") == "MAKER":
                maker += 1
            else:
                taker += 1
            if float(f.get("shares") or 0.0) < 1:
                frag += 1
        cost += wcost
        pc = None
        if d.get("winner") in ("Up", "Down") and min(up, dn) > 0:
            wshares = up if d["winner"] == "Up" else dn
            payout += wshares
            pc = round(wcost / min(up, dn), 4)
            pair_costs.append(pc)
        per_window.append({"slug": d.get("event_slug") or p.stem, "fills": live_n, "pair_cost": pc})
    _place = count_live_placements(run_id, slugs=keep)
    placements = sum(_place.values()) if isinstance(_place, dict) else _place
    pair_costs.sort()
    return {"windows": len(per_window), "traded": traded, "fills": fills,
            "maker": maker, "taker": taker, "frag": frag,
            "cost": round(cost, 2), "payout": round(payout, 2),
            "net": round(payout - cost, 2), "fees": round(fees, 2),
            "fill_rate": (fills / placements) if placements else None,
            "placements": placements,
            "median_pair_cost": round(float(sorted(pair_costs)[len(pair_costs) // 2]), 4) if pair_costs else None,
            "n_paired": len(pair_costs), "per_window": per_window}


def count_live_placements(run_id: str, slugs: set[str] | None = None) -> int | dict:
    """Placement lines in bot/loop.log, matched by [slug].

    Slugs are unique across runs (verified: no window slug appears in two run
    folders), so a whole-log scan attributes every placement to exactly one
    window -- no session-marker windowing needed, and restarts of the same run
    cannot misattribute.
    """
    if not LOOP_LOG.exists():
        return {} if slugs is not None else 0
    lines = LOOP_LOG.read_text(encoding="utf-8", errors="ignore").splitlines()
    scope = [line for line in lines if " rest " in line and "behind" in line]
    if slugs is None:
        slugs = set()
    counts = {s: 0 for s in slugs}
    for line in scope:
        for s in slugs:
            if s in line:
                counts[s] += 1
                break
    return counts


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation (average ranks for ties), stdlib only."""
    n = len(xs)
    if n < 3:
        return None

    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------

def resolve_runs(sel: list[str], use_all: bool, runs_root: Path) -> list[str]:
    if use_all:
        found = [d.name for d in sorted(runs_root.iterdir())
                 if d.is_dir() and (d / "windows").exists() and (d / "tape").exists()]
        preferred = [r for r in FOUR_RUNS if r in found]
        extra = [r for r in found if r not in FOUR_RUNS]
        return preferred + extra
    out = []
    for r in sel:
        name = r.replace("\\", "/").rstrip("/").split("/")[-1]
        out.append(name)
    return out


def run_rule(run_ids: list[str], rule: str, ceiling: float | None, levels: int,
             spacing: float, limit: int | None, runs_root: Path,
             frozen_config: bool = False, queue_mode: str = "exact",
             eval_floor_s: float = 0.0, leg1_max: float | None = None,
             leg2_ceiling: float | None = None, unhedged_usd: float | None = None,
             taker_dip_max: float | None = None, rescue_max_pair: float | None = None,
             late_rescue_start: float | None = None, taker_hedge_pair: float | None = None,
             hedge_clip: float | None = None,
             unhedged_step_cents: float = 0.0) -> list[dict]:
    """Replay windows under a rule.

    frozen_config=True (gate mode): each run replays under its own frozen
    configSnapshot, so the replay is checked against what that run did.
    Otherwise every window replays under the canonical entry for the rule,
    so candidates are counterfactuals on equal footing across eras.

    The v2.7 ablation knobs each change one thing at a time against the
    baseline: leg1_max (Leg-1 ceiling), leg2_ceiling (hedge ceiling),
    unhedged_usd (dollar gap cap), taker_dip_max (fresh-leg taker entry),
    rescue_max_pair + late_rescue_start (late-window rescue cap),
    taker_hedge_pair (profit-lock deficit taker hedge) + hedge_clip.
    """
    canon_sid = {"v2.7": STRATEGY_V27, "hydrogen": STRATEGY_HYDROGEN}.get(rule, STRATEGY_V26)
    canon_entry = dict(C.STRATEGY_SETUPS[canon_sid]["entry"])
    results = []
    for run_id in run_ids:
        if frozen_config:
            strategy_id, entry = load_run_entry(run_id, runs_root)
            entry = dict(entry)
        else:
            strategy_id, entry = canon_sid, dict(canon_entry)
        if rule == "hump":
            entry.pop("dipCurve", None)
        if ceiling is not None:
            entry["maxFillPrice"] = float(ceiling)
            if rule == "v2.7" and leg1_max is None:
                entry["leg1MaxPrice"] = float(ceiling)
                entry["maxLeg1Price"] = float(ceiling)
        elif rule == "hump":
            entry["maxFillPrice"] = 0.55
        if leg1_max is not None:
            entry["leg1MaxPrice"] = float(leg1_max)
            entry["maxLeg1Price"] = float(leg1_max)
            entry["maxFillPrice"] = min(float(entry.get("maxFillPrice", 99.0)), float(leg1_max))
        if leg2_ceiling is not None:
            entry["leg2MaxPrice"] = float(leg2_ceiling)
        if unhedged_usd is not None:
            entry["maxUnhedgedUsd"] = float(unhedged_usd)
        if taker_dip_max is not None:
            entry["takerDipEntryMax"] = float(taker_dip_max)
        if rescue_max_pair is not None:
            entry["rescuePairCostMax"] = float(rescue_max_pair)
            entry["lateRescueMaxPairCost"] = float(rescue_max_pair)
        if late_rescue_start is not None:
            entry["lateRescueStartSec"] = float(late_rescue_start)
        if taker_hedge_pair is not None:
            entry["takerHedgeMaxPairCost"] = float(taker_hedge_pair)
        if hedge_clip is not None:
            entry["hedgeMaxClip"] = float(hedge_clip)
        slices = load_slices(run_id, runs_root)
        asset_outcome = slices.get("asset_outcome", {})
        book = slices.get("book", {})
        prints = slices.get("prints", {})
        wins = slices.get("windows", [])
        if limit is not None:
            wins = wins[:limit]
        # "hump" keeps the historical monkeypatch (v2.6 entry + popped curve).
        # "v2.7" exercises the shipped path: dipCurve="hump" is sized natively
        # by executor.select_ladder_clip, so no patch is applied.
        sizing = make_hump_sizing(float(entry.get("maxShares", 45.0))) if rule == "hump" else None
        orig = E.select_ladder_clip
        if sizing is not None:
            E.select_ladder_clip = sizing
        try:
            for w in wins:
                cid = str(w.get("condition_id") or "")
                prows = []
                for (ts, oc, px, size, side, aid) in prints.get(cid, []):
                    if not oc:
                        oc = asset_outcome.get(aid, "")
                    if oc not in ("Up", "Down"):
                        continue
                    prows.append((ts, oc, px, size, side, aid))
                res = simulate_window(w["slot"], w.get("winner"), book.get(str(w["slot"]), []),
                                      prows, strategy_id, entry, levels=levels, spacing=spacing,
                                      queue_mode=queue_mode, eval_floor_s=eval_floor_s,
                                      unhedged_step_cents=unhedged_step_cents)
                res["run"] = run_id
                res["slug"] = w["slug"]
                res["rule"] = rule
                res["ceiling"] = entry.get("maxFillPrice")
                res["leg1Max"] = entry.get("leg1MaxPrice", entry.get("maxLeg1Price"))
                res["leg2Ceiling"] = entry.get("leg2MaxPrice")
                res["unhedgedUsd"] = entry.get("maxUnhedgedUsd")
                res["takerDipMax"] = entry.get("takerDipEntryMax")
                res["rescueMaxPair"] = entry.get("lateRescueMaxPairCost", entry.get("rescuePairCostMax"))
                res["levels"] = levels
                results.append(res)
        finally:
            E.select_ladder_clip = orig
    return results


def summarize(results: list[dict]) -> dict:
    settled = [r for r in results if r["payout"] is not None]
    pcs = sorted(r["pair_cost"] for r in settled if r.get("pair_cost") is not None)
    fills = sum(r["n_fills"] for r in results)
    maker = sum(r["n_maker"] for r in results)
    cost = sum(r["cost"] for r in results)
    payout = sum(r["payout"] for r in settled)
    placements = sum(r["placements"] for r in results)
    traded = sum(1 for r in results if r["n_fills"])
    fees = sum(r.get("fees", 0.0) for r in results)
    # Scorecard: paired-window median pair cost + locked bps, both computed
    # from fee-inclusive cost with NO rebates in the loop (replay never books
    # rebates), so taker slippage via 0.07*p*(1-p) is fully in the numbers.
    edge_bps = round((payout - cost) / cost * 1e4, 1) if cost else None
    return {"windows": len(results), "traded": traded,
            "fills": fills, "fills_per_window": round(fills / len(results), 2) if results else 0,
            "maker": maker, "taker": fills - maker,
            "fill_rate": round(fills / placements, 4) if placements else None,
            "placements": placements,
            "queue_unknown": sum(r["queue_unknown"] for r in results),
            "frag": sum(r["frag"] for r in results),
            "cost": round(cost, 2), "payout": round(payout, 2),
            "net": round(payout - cost, 2),
            "fees": round(fees, 4),
            "gross_bps": edge_bps,
            "locked_bps": edge_bps,
            "median_pair_cost": round(float(pcs[len(pcs) // 2]), 4) if pcs else None,
            "n_paired": len(pcs)}


def gate(results: list[dict], live: dict) -> tuple[bool, dict]:
    """Pass conditions against the recomputed live fixture.

    Only replayable windows (same slugs on both sides) count: windows whose
    book was pruned away are excluded, never scored as zero-fill matches.
    """
    live_slugs = {w["slug"] for w in live["per_window"]}
    results = [r for r in results if r["slug"] in live_slugs]
    rep_maker = sum(r["n_maker"] for r in results)
    rep_place = sum(r["placements"] for r in results)
    rep_rate = (sum(r["n_fills"] for r in results) / rep_place) if rep_place else None
    rep_pcs = sorted(r["pair_cost"] for r in results
                     if r.get("pair_cost") is not None and r["payout"] is not None)
    rep_med = float(rep_pcs[len(rep_pcs) // 2]) if rep_pcs else None
    live_by_slug = {w["slug"]: w["fills"] for w in live["per_window"]}
    xs = [live_by_slug.get(r["slug"], 0) for r in results if r["slug"] in live_by_slug]
    ys = [r["n_fills"] for r in results if r["slug"] in live_by_slug]
    rho = spearman([float(x) for x in xs], [float(y) for y in ys])
    checks = {}
    if live["maker"]:
        lo, hi = live["maker"] * 0.8, live["maker"] * 1.2
        checks["maker_fills"] = {"live": live["maker"], "replay": rep_maker,
                                 "band": [round(lo, 1), round(hi, 1)],
                                 "pass": lo <= rep_maker <= hi}
    if live["fill_rate"] is not None and rep_rate is not None:
        checks["fill_rate"] = {"live": round(live["fill_rate"], 4), "replay": round(rep_rate, 4),
                               "tol_pp": 0.5,
                               "pass": abs(rep_rate - live["fill_rate"]) <= 0.005}
    if live["median_pair_cost"] is not None and rep_med is not None:
        checks["median_pair_cost"] = {"live": live["median_pair_cost"], "replay": round(rep_med, 4),
                                      "tol": 0.02,
                                      "pass": abs(rep_med - live["median_pair_cost"]) <= 0.02}
    checks["spearman"] = {"value": round(rho, 3) if rho is not None else None,
                          "threshold": 0.5,
                          "pass": (rho is not None and rho > 0.5)}
    ok = all(c.get("pass") for c in checks.values())
    return ok, {"checks": checks, "replay_windows": len(results),
                "replay_placements": rep_place,
                "replay_median_pair_n": len(rep_pcs)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Replay recorded tape to test placement rules.")
    ap.add_argument("--run", action="append", default=[], help="run id (repeatable)")
    ap.add_argument("--runs", default=None, help="'all' for the full corpus")
    ap.add_argument("--rule", default="v2.6", choices=["v2.6", "hump", "v2.7", "hydrogen"])
    ap.add_argument("--ceiling", type=float, default=None)
    ap.add_argument("--levels", type=int, default=None)
    ap.add_argument("--spacing", type=float, default=None)
    ap.add_argument("--leg1-max", type=float, default=None,
                    help="v2.7 ablation: Leg-1 ceiling (fresh dips + straddle-open)")
    ap.add_argument("--leg2-ceiling", type=float, default=None,
                    help="v2.7 ablation: deficit-hedge ceiling (late/sweep rescue keeps the full ceiling)")
    ap.add_argument("--unhedged-usd", type=float, default=None,
                    help="v2.7 ablation: dollar-denominated unhedged gap cap")
    ap.add_argument("--taker-dip-max", type=float, default=None,
                    help="v2.7 ablation: cross the ask on a fresh leg if ask <= this (maker-only when absent)")
    ap.add_argument("--rescue-max-pair", type=float, default=None,
                    help="v2.7 ablation: late-window rescue pair-cost cap")
    ap.add_argument("--late-rescue-start", type=float, default=None,
                    help="v2.7 ablation: elapsed seconds when the late rescue cap takes over")
    ap.add_argument("--unhedged-step-cents", type=float, default=0.0,
                    help="Arm S1: min cents below lowest held unhedged fill price before allowing another fill on that side")
    ap.add_argument("--taker-hedge-max-pair", type=float, default=None,
                    help="profit-lock ablation: deficit hedge crosses the ask as TAKER if fee-inclusive pair cost <= this (off when absent)")
    ap.add_argument("--hedge-max-clip", type=float, default=None,
                    help="profit-lock ablation: deficit taker-hedge clip cap in shares (default: maxShares)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--against-live", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--queue-mode", default="exact", choices=["exact", "cumulative"])
    ap.add_argument("--eval-floor-ms", type=float, default=0.0)
    args = ap.parse_args(argv)

    runs_root = Path("bot/runs")
    run_ids = resolve_runs(args.run, (args.runs or "").lower() == "all", runs_root)
    if args.against_live and not args.run:
        # Gate pools the v2.6 runs with surviving book, each replayed under
        # its own frozen config. The baseline run alone keeps a handful of
        # replayable windows after rotation pruning -- too few for a
        # rate/correlation gate. The v2.5 run is excluded: its fills predate
        # queueAhead stamping and its loop.log placements have scrolled, so
        # neither the queue nor the fill-rate denominator survives.
        run_ids = ["run_20261113_061914_paper_dsp_v2_6",
                   "run_20261113_073610_paper_dsp_v2_6",
                   BASELINE_RUN]
    if not run_ids:
        print("no runs resolved", file=sys.stderr)
        return 2

    if args.against_live and args.rule != "v2.6":
        print("gate mode only supports --rule v2.6", file=sys.stderr)
        return 2

    # Ladder shape defaults come from the rule's entry (v2.7 stores
    # levelsPerSide/levelSpacing); explicit flags always win. Pre-v2.7
    # entries carry no ladder keys, so the historical 1 x 0.02 stands.
    canon_for_defaults = C.STRATEGY_SETUPS[STRATEGY_V27 if args.rule == "v2.7" else STRATEGY_V26]["entry"]
    levels = args.levels if args.levels is not None else int(canon_for_defaults.get("levelsPerSide", 1))
    spacing = args.spacing if args.spacing is not None else float(canon_for_defaults.get("levelSpacing", 0.02))
    results = run_rule(run_ids, args.rule, args.ceiling, levels,
                       spacing, args.limit, runs_root,
                       frozen_config=args.against_live,
                       queue_mode=args.queue_mode,
                       eval_floor_s=(args.eval_floor_ms or 0.0) / 1000.0,
                       leg1_max=args.leg1_max,
                       leg2_ceiling=args.leg2_ceiling,
                       unhedged_usd=args.unhedged_usd,
                       taker_dip_max=args.taker_dip_max,
                       rescue_max_pair=args.rescue_max_pair,
                       late_rescue_start=args.late_rescue_start,
                       taker_hedge_pair=args.taker_hedge_max_pair,
                       hedge_clip=args.hedge_max_clip,
                       unhedged_step_cents=args.unhedged_step_cents)
    summary = summarize(results)

    if args.against_live:
        by_run: dict[str, list[str]] = {}
        excluded: dict[str, int] = {}
        for run_id in run_ids:
            slices = load_slices(run_id, runs_root)
            book = slices.get("book", {})
            prints = slices.get("prints", {})
            wins = {w["slug"]: w for w in slices.get("windows", [])}
            ok_here = []
            for r in [x for x in results if x["run"] == run_id]:
                w = wins.get(r["slug"], {})
                good, why = coverage_ok(r["slot"], book.get(str(r["slot"]), []),
                                        prints.get(str(w.get("condition_id") or ""), []))
                if good:
                    ok_here.append(r["slug"])
                else:
                    excluded[f"{run_id}:{why}"] = excluded.get(f"{run_id}:{why}", 0) + 1
            by_run[run_id] = ok_here
        live = None
        pooled = {"windows": 0, "traded": 0, "fills": 0, "maker": 0, "taker": 0,
                  "frag": 0, "cost": 0.0, "payout": 0.0, "net": 0.0, "fees": 0.0,
                  "placements": 0, "pair_costs": [], "per_window": []}
        for run_id, ok_slugs in by_run.items():
            lf = live_fixture(run_id, runs_root, slugs=ok_slugs)
            for k in ("windows", "traded", "fills", "maker", "taker", "frag",
                      "placements"):
                pooled[k] += lf[k]
            for k in ("cost", "payout", "net", "fees"):
                pooled[k] += lf[k]
            pooled["pair_costs"].extend(
                w["pair_cost"] for w in lf["per_window"] if w["pair_cost"] is not None)
            pooled["per_window"].extend(lf["per_window"])
        pooled["pair_costs"].sort()
        n = len(pooled["pair_costs"])
        live = {**pooled,
                "fill_rate": (pooled["fills"] / pooled["placements"]) if pooled["placements"] else None,
                "median_pair_cost": round(float(pooled["pair_costs"][n // 2]), 4) if n else None,
                "n_paired": n}
        ok, detail = gate(results, live)
        detail["excluded_windows"] = excluded
        detail["gate_runs"] = {r: len(v) for r, v in by_run.items()}
        report = {"live": {k: v for k, v in live.items() if k != "per_window"},
                  "replay": summary, "gate": detail, "pass": ok}
        print(json.dumps(report, indent=2))
        print(("GATE PASS" if ok else "GATE FAIL"))
        if args.out:
            Path(args.out).write_text(json.dumps({"results": results, **report}, indent=2))
        return 0 if ok else 1

    print(json.dumps({"summary": summary,
                      "windows": [{k: r.get(k) for k in
                                   ("slug", "run", "rule", "ceiling", "leg1Max", "leg2Ceiling",
                                    "unhedgedUsd", "takerDipMax", "rescueMaxPair", "levels",
                                    "n_fills", "n_maker", "n_taker", "cost", "fees", "payout",
                                    "net", "pair_cost", "placements", "queue_unknown", "frag")
                                   } for r in results]}, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps({"summary": summary, "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
