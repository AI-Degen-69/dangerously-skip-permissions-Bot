"""Replay CLI (argparse entry point for offline counterfactuals)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bot import constants as C
from .replay_analysis import coverage_ok, gate, live_fixture, resolve_runs, run_rule, summarize
from .replay_consts import BASELINE_RUN, STRATEGY_HYDROGEN, STRATEGY_V26, STRATEGY_V27
from .replay_slices import load_slices


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

    from bot.runs import RUNS_DIR
    runs_root = RUNS_DIR
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
    canon_for_defaults = C.STRATEGY_SETUPS[
        {"v2.7": STRATEGY_V27, "hydrogen": STRATEGY_HYDROGEN}.get(args.rule, STRATEGY_V26)
    ]["entry"]
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
