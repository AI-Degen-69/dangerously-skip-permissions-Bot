"""A/B Testing & Statistical Hypothesis Validation Module.

Compares Baseline Strategy A (run_20261109_043441_paper_msr_v2: DSP v2.0)
against Candidate Strategy B (DSP v2.1: Unified Triad).

Calculates real-time sample progress, Welch's two-sample t-statistic, p-value,
Cohen's d effect size, 95% confidence intervals, and histogram distributions.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "bot" / "runs"
DEFAULT_BASELINE_ID = "run_20261109_043441_paper_msr_v2"
AB_STATE_PATH = ROOT / "bot" / "ab_test_state.json"

TARGET_SAMPLE_SIZE = 113  # Power 0.80, alpha 0.05, Cohen's d 0.332
T_CRITICAL_95 = 1.658     # df ~ 100-200, one-tailed alpha = 0.05


def _t_cdf(t: float, df: float) -> float:
    """Accurate standard normal approximation for Student t CDF."""
    if df <= 0:
        return 0.5
    z = t * (1.0 - 1.0 / (4.0 * df)) / math.sqrt(1.0 + (t * t) / (2.0 * df))
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _load_run_windows(run_id: str) -> list[dict[str, Any]]:
    """Load all window settled results for a specific run."""
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        return []

    windows_dir = run_dir / "windows"
    events_file = run_dir / "events.jsonl"
    
    settles = {}
    if events_file.exists():
        for line in events_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                if ev.get("kind") == "settle" and ev.get("slug"):
                    settles[ev["slug"]] = ev
            except Exception:
                pass

    records = []
    if windows_dir.exists():
        for wf in sorted(windows_dir.glob("btc-updown-5m-*.json")):
            try:
                data = json.loads(wf.read_text(encoding="utf-8"))
                slug = data.get("slug") or wf.stem
                settle = settles.get(slug)
                fills = data.get("fills", [])
                
                up_sh = sum(f.get("shares", 0.0) for f in fills if f.get("outcome") == "Up")
                down_sh = sum(f.get("shares", 0.0) for f in fills if f.get("outcome") == "Down")
                up_cost = sum(f.get("usd", 0.0) for f in fills if f.get("outcome") == "Up")
                down_cost = sum(f.get("usd", 0.0) for f in fills if f.get("outcome") == "Down")
                total_cost = up_cost + down_cost
                min_sh = min(up_sh, down_sh)
                pair_cost = round(total_cost / min_sh, 4) if min_sh > 0 else None
                imbalance = round(abs(up_sh - down_sh), 1)

                payout = 0.0
                net = None
                winner = None

                if settle:
                    det = settle.get("detail", {})
                    winner = det.get("winner")
                    payout = float(det.get("payout", 0.0))
                    net = round(float(det.get("net", payout - total_cost)), 2)

                if net is not None:
                    records.append({
                        "slug": slug,
                        "epoch": int(slug.split("-")[-1]) if "-" in slug else 0,
                        "net": net,
                        "payout": payout,
                        "cost": round(total_cost, 2),
                        "pairCost": pair_cost,
                        "imbalance": imbalance,
                        "fills": len(fills),
                        "upShares": up_sh,
                        "downShares": down_sh,
                        "winner": winner,
                    })
            except Exception:
                pass

    return records


def _compute_distribution_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    if n == 0:
        return {
            "samples": 0,
            "wins": 0,
            "losses": 0,
            "scratches": 0,
            "winRate": 0.0,
            "lossRate": 0.0,
            "netPnl": 0.0,
            "meanPnl": 0.0,
            "stdPnl": 0.0,
            "variance": 0.0,
            "medianPnl": 0.0,
            "minPnl": 0.0,
            "maxPnl": 0.0,
            "meanPairCost": 0.0,
            "zeroImbalancePct": 0.0,
            "pnlList": [],
            "windows": [],
        }

    pnls = [r["net"] for r in records]
    wins = sum(1 for x in pnls if x > 0.001)
    losses = sum(1 for x in pnls if x < -0.001)
    scratches = sum(1 for x in pnls if abs(x) <= 0.001)

    net_sum = sum(pnls)
    mean_val = net_sum / n
    variance = sum((x - mean_val) ** 2 for x in pnls) / max(1, n - 1)
    std_val = math.sqrt(variance)

    sorted_pnls = sorted(pnls)
    mid = n // 2
    median_val = sorted_pnls[mid] if n % 2 != 0 else (sorted_pnls[mid - 1] + sorted_pnls[mid]) / 2.0

    valid_pcs = [r["pairCost"] for r in records if r.get("pairCost") is not None]
    mean_pc = (sum(valid_pcs) / len(valid_pcs)) if valid_pcs else 0.0

    zero_imbs = sum(1 for r in records if r.get("imbalance", 0.0) == 0.0)
    zero_imb_pct = round((zero_imbs / n) * 100.0, 1)

    return {
        "samples": n,
        "wins": wins,
        "losses": losses,
        "scratches": scratches,
        "winRate": round(wins / n, 4),
        "lossRate": round(losses / n, 4),
        "netPnl": round(net_sum, 2),
        "meanPnl": round(mean_val, 4),
        "stdPnl": round(std_val, 4),
        "variance": round(variance, 4),
        "medianPnl": round(median_val, 2),
        "minPnl": round(sorted_pnls[0], 2),
        "maxPnl": round(sorted_pnls[-1], 2),
        "meanPairCost": round(mean_pc, 4),
        "zeroImbalancePct": zero_imb_pct,
        "pnlList": pnls,
        "windows": records[-30:],  # last 30 for the live table
    }


def _build_histogram(baseline_pnls: list[float], candidate_pnls: list[float]) -> list[dict[str, Any]]:
    """Build standardized comparative histogram bins."""
    bin_edges = [
        (-999.0, -5.0, "< -$5.00"),
        (-5.0, -4.0, "-$5.00..-$4.00"),
        (-4.0, -3.0, "-$4.00..-$3.00"),
        (-3.0, -2.0, "-$3.00..-$2.00"),
        (-2.0, -1.0, "-$2.00..-$1.00"),
        (-1.0, 0.0, "-$1.00..$0.00"),
        (0.0, 1.0, "$0.00..+$1.00"),
        (1.0, 2.0, "+$1.00..+$2.00"),
        (2.0, 3.0, "+$2.00..+$3.00"),
        (3.0, 4.0, "+$3.00..+$4.00"),
        (4.0, 5.0, "+$4.00..+$5.00"),
        (5.0, 999.0, "> +$5.00"),
    ]

    bins = []
    n_a = max(1, len(baseline_pnls))
    n_b = max(1, len(candidate_pnls))

    for low, high, label in bin_edges:
        cnt_a = sum(1 for x in baseline_pnls if low <= x < high)
        cnt_b = sum(1 for x in candidate_pnls if low <= x < high)
        bins.append({
            "label": label,
            "range": [low, high],
            "baselineCount": cnt_a,
            "baselinePct": round((cnt_a / n_a) * 100, 1),
            "candidateCount": cnt_b,
            "candidatePct": round((cnt_b / n_b) * 100, 1) if candidate_pnls else 0.0,
        })

    return bins


def _candidate_strategy_id(candidate_id: str | None) -> str:
    """Read the strategy id recorded in the candidate run's meta, defaulting to v2.2."""
    if candidate_id:
        try:
            meta_p = RUNS_DIR / candidate_id / "run_meta.json"
            if meta_p.exists():
                m = json.loads(meta_p.read_text(encoding="utf-8"))
                strat_id = m.get("configSnapshot", {}).get("strategy", {}).get("id", "")
                if strat_id:
                    return str(strat_id)
        except Exception:
            pass
    return "dangerously-skip-permissions-v2.2"


def _candidate_entry(candidate_id: str | None) -> dict[str, Any]:
    """Live entry numbers recorded in the candidate run's snapshot (single source of truth)."""
    strat_id = _candidate_strategy_id(candidate_id)
    if candidate_id:
        try:
            meta_p = RUNS_DIR / candidate_id / "run_meta.json"
            if meta_p.exists():
                m = json.loads(meta_p.read_text(encoding="utf-8"))
                entry = m.get("configSnapshot", {}).get("entry", {})
                if isinstance(entry, dict) and entry:
                    return dict(entry)
        except Exception:
            pass
    try:
        from bot import constants as C
        reg = C.STRATEGY_SETUPS.get(strat_id, {})
        if isinstance(reg.get("entry"), dict):
            return dict(reg["entry"])
    except Exception:
        pass
    return {}


def _version_tag(strategy_id: str) -> str:
    tail = str(strategy_id).split("-")[-1]
    return tail if tail[:1] == "v" else tail


def _hypothesis_text(candidate_id: str | None, *, null: bool) -> str:
    """Hypothesis copy derived from whichever candidate actually ran."""
    strat_id = _candidate_strategy_id(candidate_id)
    tag = _version_tag(strat_id)
    try:
        from bot import constants as C
        reg = C.STRATEGY_SETUPS.get(strat_id, {})
        blurb = reg.get("features", {}).get("blurb", "candidate sizing")
    except Exception:
        blurb = "candidate sizing"
    if null:
        return f"H₀: μ_{tag} ≤ μ_v2.0 (or μ_{tag} ≤ 0) — {blurb} does not produce a statistically significant positive expected return."
    return f"H₁: μ_{tag} > 0 and μ_{tag} > μ_v2.0 — {blurb} generates a statistically significant positive mean window return at α = 0.05."


def _candidate_info(candidate_id: str | None) -> dict[str, Any]:
    """Name/description/highlights/entry generated from the candidate run's live numbers."""
    from bot import constants as C
    strat_id = _candidate_strategy_id(candidate_id)
    entry = _candidate_entry(candidate_id)
    reg = C.STRATEGY_SETUPS.get(strat_id, {})
    name = reg.get("name", strat_id)
    _sig, desc, hl = C.describe_setup({"id": strat_id, "entry": entry or reg.get("entry", {})})
    return {
        "name": name,
        "description": desc,
        "signature": _sig,
        "configHighlights": hl,
        "entry": entry or reg.get("entry", {}),
        "features": reg.get("features", {}),
    }


def get_ab_test_data() -> dict[str, Any]:
    """Return full state for the A/B Test Dashboard."""
    # Read persistent A/B state if present
    state = {}
    if AB_STATE_PATH.exists():
        try:
            state = json.loads(AB_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    baseline_id = state.get("baselineRunId", DEFAULT_BASELINE_ID)
    candidate_id = state.get("candidateRunId")

    # If candidateRunId is not set, check active_run.json
    active_meta_path = RUNS_DIR / "active_run.json"
    if not candidate_id and active_meta_path.exists():
        try:
            ar = json.loads(active_meta_path.read_text(encoding="utf-8"))
            act_id = ar.get("activeRunId")
            if act_id and act_id != baseline_id:
                meta_p = RUNS_DIR / act_id / "run_meta.json"
                if meta_p.exists():
                    m = json.loads(meta_p.read_text(encoding="utf-8"))
                    strat_id = m.get("configSnapshot", {}).get("strategy", {}).get("id", "")
                    if "v2.2" in strat_id or "v2.3" in strat_id:
                        candidate_id = act_id
        except Exception:
            pass

    baseline_recs = _load_run_windows(baseline_id)
    baseline_stats = _compute_distribution_stats(baseline_recs)

    candidate_recs = _load_run_windows(candidate_id) if candidate_id else []
    candidate_stats = _compute_distribution_stats(candidate_recs)

    # Statistical Comparison (Welch's Two-Sample t-test)
    n_a = baseline_stats["samples"]
    n_b = candidate_stats["samples"]
    mu_a = baseline_stats["meanPnl"]
    mu_b = candidate_stats["meanPnl"]
    var_a = baseline_stats["variance"]
    var_b = candidate_stats["variance"]

    t_stat = 0.0
    p_value = 1.0
    df = 0.0
    mean_diff = 0.0
    cohen_d = 0.0
    ci_lower = 0.0
    ci_upper = 0.0
    significant = False

    if n_a > 1 and n_b > 1:
        mean_diff = round(mu_b - mu_a, 4)
        se_diff = math.sqrt((var_a / n_a) + (var_b / n_b))
        
        # Welch-Satterthwaite degrees of freedom
        num = ((var_a / n_a) + (var_b / n_b)) ** 2
        denom = (((var_a / n_a) ** 2) / (n_a - 1)) + (((var_b / n_b) ** 2) / (n_b - 1))
        df = round(num / max(denom, 1e-9), 1)

        t_stat = round(mean_diff / max(se_diff, 1e-9), 4) if se_diff > 0 else 0.0
        # One-tailed p-value (testing mu_b > mu_a)
        p_value = round(max(0.0, 1.0 - _t_cdf(t_stat, df)), 4)

        # Pooled SD for Cohen's d
        s_pooled = math.sqrt(((n_a - 1) * var_a + (n_b - 1) * var_b) / max(1, n_a + n_b - 2))
        cohen_d = round(mean_diff / max(s_pooled, 1e-9), 3) if s_pooled > 0 else 0.0

        # 95% Confidence Interval for (mu_b - mu_a)
        margin = 1.96 * se_diff
        ci_lower = round(mean_diff - margin, 4)
        ci_upper = round(mean_diff + margin, 4)

        significant = bool(t_stat >= T_CRITICAL_95 and p_value <= 0.05)

    # Status verdict string
    if n_b < 5:
        verdict = "Awaiting Sample Data"
        verdict_tone = "neutral"
    elif n_b < 30:
        verdict = f"Data Gathering ({n_b}/{TARGET_SAMPLE_SIZE})"
        verdict_tone = "info"
    elif significant and n_b >= TARGET_SAMPLE_SIZE:
        verdict = f"Statistically Significant Alpha (Reject H0, p={p_value:.3f})"
        verdict_tone = "success"
    elif mu_b > mu_a:
        verdict = f"Trending Favorable (p={p_value:.3f}, need N={TARGET_SAMPLE_SIZE})"
        verdict_tone = "accent"
    else:
        verdict = f"No Edge Detected (Fail to Reject H0, p={p_value:.3f})"
        verdict_tone = "danger"

    histogram = _build_histogram(baseline_stats["pnlList"], candidate_stats["pnlList"])

    return {
        "status": "ready",
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline": {
            "runId": baseline_id,
            "name": "dangerously-skip-permissions v2.0 (Baseline)",
            "description": "Standard reconstructed profile with SBC 75s, 15-share lead freeze, and permissive rescue pairing (rescuePairCostMax: 1.080).",
            "configHighlights": {
                "rescuePairCostMax": "$1.080 (permits >$1.00 pairs)",
                "dipClips": "Constant 30 sh",
                "sweepEqualization": "None (halts at T-75s)",
                "maxFillPrice": "88¢ (dip) / 98.5¢ (deficit)",
            },
            **baseline_stats,
        },
        "candidate": {
            "runId": candidate_id,
            **_candidate_info(candidate_id),
            "targetSamples": TARGET_SAMPLE_SIZE,
            "progressPct": round(min(100.0, (n_b / TARGET_SAMPLE_SIZE) * 100.0), 1),
            **candidate_stats,
        },
        "statistics": {
            "targetSampleSize": TARGET_SAMPLE_SIZE,
            "alpha": 0.05,
            "confidenceLevel": "95%",
            "power": "80%",
            "tStatistic": t_stat,
            "tCritical": T_CRITICAL_95,
            "pValue": p_value,
            "degreesOfFreedom": df,
            "cohenD": cohen_d,
            "meanDiff": mean_diff,
            "ci95": [ci_lower, ci_upper],
            "significant": significant,
            "verdict": verdict,
            "verdictTone": verdict_tone,
        },
        "hypotheses": {
            "nullHypothesis": _hypothesis_text(candidate_id, null=True),
            "altHypothesis": _hypothesis_text(candidate_id, null=False),
            "decisionRule": f"Reject H₀ if t > {T_CRITICAL_95} (p < 0.05) once candidate sample size reaches N = {TARGET_SAMPLE_SIZE} windows.",
        },
        "histogram": histogram,
    }


def start_candidate_test() -> dict[str, Any]:
    from bot import api
    
    # 1. Update config to the registry's Candidate parameters (single source of truth).
    from bot import constants as C
    _reg = C.STRATEGY_SETUPS["dangerously-skip-permissions-v2.2"]
    cfg = api.load_config()
    cfg["strategy"] = {
        "id": _reg["id"],
        "symbol": _reg["symbol"],
        "name": _reg["name"],
    }
    entry = cfg.setdefault("entry", {})
    entry.update(_reg["entry"])
    
    tmp = api.CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    tmp.replace(api.CONFIG_PATH)

    # 2. Stop any existing loop
    api.stop_loop_process()
    time.sleep(0.5)

    # 3. Generate run ID and register candidate
    run_id = f"run_{time.strftime('%Y%m%d_%H%M%S')}_paper_dsp_v2_2"
    ab_state = {
        "baselineRunId": DEFAULT_BASELINE_ID,
        "candidateRunId": run_id,
        "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    AB_STATE_PATH.write_text(json.dumps(ab_state, indent=2), encoding="utf-8")

    # 4. Start loop process with candidate run_id
    pid = api.start_loop_process(run_id=run_id)
    return {
        "ok": True,
        "pid": pid,
        "candidateRunId": run_id,
        "baselineRunId": DEFAULT_BASELINE_ID,
        "data": get_ab_test_data(),
    }


def stop_candidate_test() -> dict[str, Any]:
    from bot import api
    pid = api.stop_loop_process()
    return {
        "ok": True,
        "pid": pid,
        "data": get_ab_test_data(),
    }

