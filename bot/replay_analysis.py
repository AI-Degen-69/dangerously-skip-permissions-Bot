"""Replay runners and analysis (rules, summary, live gate)."""

from __future__ import annotations

import json
import math
from pathlib import Path

from . import constants as C
from . import executor as E
from .replay_consts import BASELINE_RUN, FOUR_RUNS, LOOP_LOG, STRATEGY_HYDROGEN, STRATEGY_V26, STRATEGY_V27, _DEFAULT_RUNS_DIR
from .replay_sim import simulate_window
from .replay_sizing import make_hump_sizing
from .replay_slices import load_run_entry, load_slices


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

def live_fixture(run_id: str = BASELINE_RUN, runs_root: Path | None = None,
                 slugs: list[str] | None = None) -> dict:
    """What the bot actually did: fills stamped with the run's own strategy.

    When `slugs` is given, the fixture is recomputed over exactly that
    subset (the gate compares replay and live on the same windows).
    """
    if runs_root is None:
        runs_root = _DEFAULT_RUNS_DIR
    try:
        meta = json.loads((runs_root / run_id / "run_meta.json").read_text(encoding="utf-8"))
        S = str((meta.get("configSnapshot") or {}).get("strategy", {}).get("id", STRATEGY_V26))
    except Exception:
        S = STRATEGY_V26
    if runs_root is None:
        runs_root = _DEFAULT_RUNS_DIR
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
    """Placement lines in data/loop.log, matched by [slug].

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
