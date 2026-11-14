"""A/B Testing & Statistical Hypothesis Validation Module.

Compares the frozen, measured Hydrogen v1.0 baseline run
(DEFAULT_BASELINE_ID, `run_20261113_183248_paper_hydrogen_v1_0`) against the
Hydrogen v1.1 candidate (`hydrogen-v1.1`).

The statistical sample is ACTIVE traded windows only (`fills > 0`): zero-fill
windows never inflate N or dilute variance. Welch's one-tailed two-sample
t-test (alpha = 0.05, 80% power) with Welch-Satterthwaite df, a dynamic
`t_crit(df)`, and the exact rejection boundary
`mu_crit = mean_A + t_crit * SE`.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "bot" / "runs"
DEFAULT_BASELINE_ID = "run_20261113_183248_paper_hydrogen_v1_0"
DEFAULT_CANDIDATE_ID = "hydrogen-v1.1"
CANDIDATE_DISPLAY_NAME = "Hydrogen v1.1"
BASELINE_DISPLAY_NAME = "Hydrogen v1.0"
AB_STATE_PATH = ROOT / "bot" / "ab_test_state.json"

TARGET_SAMPLE_SIZE = 120  # Active traded windows (fills > 0) for Welch's t-test (80% power, alpha 0.05)
TARGET_PAIRED_WINDOWS = 60  # Windows with upShares > 0 and downShares > 0
TARGET_SUB_DOLLAR_PAIRS = 35  # Sub-$1.00 pairs (pairCost < 1.00); >54% of paired windows
ALPHA = 0.05  # One-tailed significance level


def _t_cdf(t: float, df: float) -> float:
    """Accurate standard normal approximation for Student t CDF."""
    if df <= 0:
        return 0.5
    z = t * (1.0 - 1.0 / (4.0 * df)) / math.sqrt(1.0 + (t * t) / (2.0 * df))
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _t_critical(df: float, alpha: float = ALPHA) -> float:
    """One-tailed critical value t_crit with P(T <= t_crit) = 1 - alpha.

    Inverted from _t_cdf by bisection so the rejection threshold tracks the
    actual Welch-Satterthwaite degrees of freedom instead of a hardcoded
    placeholder (df ~ 100-200 -> ~1.658).
    """
    if df <= 0:
        return float("nan")
    target = 1.0 - alpha
    # The normal 95th percentile (1.6449) bounds t_crit from below; Student-t
    # with small df needs a larger cutoff, capped generously at 10.
    lo, hi = 0.0, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if _t_cdf(mid, df) < target:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2.0, 4)


def _pair_cost(up_shares: float, down_shares: float, up_cost: float, down_cost: float) -> float | None:
    """Mean pair cost as the sum of per-side average fill prices.

    Defined on paired windows only (`up_shares > 0 and down_shares > 0`);
    returns None for unpaired windows. Unlike `total_cost / min(shares)`,
    an imbalanced fill split cannot blow the quote up (e.g. a 1-share
    stub on one side no longer prices the whole window at ~$4.76).
    """
    if up_shares > 0 and down_shares > 0:
        return round((up_cost / up_shares) + (down_cost / down_shares), 4)
    return None


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
                pair_cost = _pair_cost(up_sh, down_sh, up_cost, down_cost)
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


def _count_observed_windows(run_id: str | None) -> int:
    """Total 5m windows observed with the loop on (informational only).

    Counts every recorded window file, including unsettled/pending and
    zero-fill windows. Never used as N in Welch's test.
    """
    if not run_id:
        return 0
    windows_dir = RUNS_DIR / run_id / "windows"
    if not windows_dir.exists():
        return 0
    try:
        return sum(1 for _ in windows_dir.glob("btc-updown-5m-*.json"))
    except Exception:
        return 0


def _quantile(sorted_vals: list[float], q: float) -> float:
    """Empirical quantile with linear interpolation (N >= 1)."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return float(sorted_vals[0])
    pos = (n - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_vals[lo])
    frac = pos - lo
    return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


def _empty_stats(observed: int = 0) -> dict[str, Any]:
    return {
        "samples": 0,
        "observedWindows": observed,
        "activeWindows": 0,
        "pairedWindows": 0,
        "subDollarPairs": 0,
        "pairCostUnder096": 0,
        "pairCost096to100": 0,
        "pairCostOver100": 0,
        "totalLockedShares": 0.0,
        "pairsMerged": 0.0,
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
        "q25Pnl": None,
        "q75Pnl": None,
        "meanMinusStd": None,
        "meanPlusStd": None,
        "minPnl": 0.0,
        "maxPnl": 0.0,
        "meanPairCost": 0.0,
        "zeroImbalancePct": 0.0,
        "pnlList": [],
        "windows": [],
    }


def _compute_distribution_stats(records: list[dict[str, Any]],
                                observed_windows: int | None = None) -> dict[str, Any]:
    """Distribution stats over ACTIVE traded windows only (`fills > 0`).

    Zero-fill windows never inflate N or dilute variance: N, mean, variance,
    win rate, pair-cost buckets, and locked-share totals are all computed on
    the active subset. `observedWindows` is the informational loop-on total.
    """
    if observed_windows is None:
        observed_windows = len(records)
    active = [r for r in records if (r.get("fills", 0) or 0) > 0]
    n = len(active)
    if n == 0:
        return _empty_stats(observed_windows)

    pnls = [r["net"] for r in active]
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

    valid_pcs = [r["pairCost"] for r in active if r.get("pairCost") is not None]
    mean_pc = (sum(valid_pcs) / len(valid_pcs)) if valid_pcs else 0.0

    zero_imbs = sum(1 for r in active if r.get("imbalance", 0.0) == 0.0)
    zero_imb_pct = round((zero_imbs / n) * 100.0, 1)

    paired = [r for r in active
              if (r.get("upShares", 0.0) or 0.0) > 0 and (r.get("downShares", 0.0) or 0.0) > 0]
    paired_windows = len(paired)
    under096 = sum(1 for r in paired
                   if r.get("pairCost") is not None and r["pairCost"] < 0.96)
    range096_100 = sum(1 for r in paired
                       if r.get("pairCost") is not None and 0.96 <= r["pairCost"] < 1.00)
    over100 = sum(1 for r in paired
                  if r.get("pairCost") is not None and r["pairCost"] >= 1.00)
    sub_dollar = under096 + range096_100
    pairs_merged = round(sum(min(r.get("upShares", 0.0) or 0.0,
                                r.get("downShares", 0.0) or 0.0) for r in paired), 1)
    locked_shares = round(pairs_merged * 2.0, 1)

    return {
        "samples": n,
        "observedWindows": observed_windows,
        "activeWindows": n,
        "pairedWindows": paired_windows,
        "subDollarPairs": sub_dollar,
        "pairCostUnder096": under096,
        "pairCost096to100": range096_100,
        "pairCostOver100": over100,
        "totalLockedShares": locked_shares,
        "pairsMerged": pairs_merged,
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
        "q25Pnl": round(_quantile(sorted_pnls, 0.25), 4) if n >= 3 else None,
        "q75Pnl": round(_quantile(sorted_pnls, 0.75), 4) if n >= 3 else None,
        "meanMinusStd": round(mean_val - std_val, 4) if n >= 3 else None,
        "meanPlusStd": round(mean_val + std_val, 4) if n >= 3 else None,
        "minPnl": round(sorted_pnls[0], 2),
        "maxPnl": round(sorted_pnls[-1], 2),
        "meanPairCost": round(mean_pc, 4),
        "zeroImbalancePct": zero_imb_pct,
        "pnlList": pnls,
        "windows": active[-30:],  # last 30 active windows for the live table
    }


def _build_histogram(baseline_pnls: list[float], candidate_pnls: list[float],
                     mu_crit: float | None = None) -> list[dict[str, Any]]:
    """Build $1.00 integer histogram bins cropped to the observed range.

    Plot range is only [min - $0.50, max + $0.50] over Baseline A, Candidate B,
    and `mu_crit` (so `mu_crit` is never clipped; $0 is drawn only when it
    falls inside that domain). $1 bins overlapping the domain are kept:
    Binning rule (floor on the linear dollar axis):
      - x >= 0: bin [k, k + 1) where k = floor(x), labelled "$k.00 to $k.99".
      - x < 0:  bin [k, k + 1) where k = floor(x), labelled
        "-$|k|.00 to -$|k+1|.01" (e.g. [-1, 0) -> "-$1.00 to -$0.01").
    Every $1 step is contiguous on the linear dollar x-axis.
    """
    values: list[float] = [float(x) for x in list(baseline_pnls) + list(candidate_pnls)]
    if mu_crit is not None:
        try:
            mc = float(mu_crit)
            if math.isfinite(mc):
                values.append(mc)
        except (TypeError, ValueError):
            pass

    if not values:
        lo_k, hi_k = 0, 0
    else:
        # Tight tail spacing: half a dollar beyond the extremes, snapped
        # outward to $1 bin edges so no stick is ever clipped.
        domain_lo = min(values) - 0.50
        domain_hi = max(values) + 0.50
        lo_k = math.floor(domain_lo)
        hi_k = math.ceil(domain_hi) - 1

    n_a = max(1, len(baseline_pnls))
    n_b = max(1, len(candidate_pnls))

    bins: list[dict[str, Any]] = []
    for k in range(lo_k, hi_k + 1):
        low = float(k)
        high = float(k + 1)
        if k >= 0:
            label = f"${k:.2f} to ${k + 0.99:.2f}"
        else:
            label = f"-${abs(k):.2f} to -${abs(k + 1) + 0.01:.2f}"
        cnt_a = sum(1 for x in baseline_pnls if low <= float(x) < high)
        cnt_b = sum(1 for x in candidate_pnls if low <= float(x) < high)
        bins.append({
            "label": label,
            "range": [low, high],
            "baselineCount": cnt_a,
            "baselinePct": round((cnt_a / n_a) * 100, 1),
            "candidateCount": cnt_b,
            "candidatePct": round((cnt_b / n_b) * 100, 1) if candidate_pnls else 0.0,
        })

    return bins


def _run_strategy_id(run_id: str | None) -> str:
    """Read the strategy id recorded in a run's meta, defaulting to the baseline."""
    if run_id:
        try:
            meta_p = RUNS_DIR / run_id / "run_meta.json"
            if meta_p.exists():
                m = json.loads(meta_p.read_text(encoding="utf-8"))
                strat_id = m.get("configSnapshot", {}).get("strategy", {}).get("id", "")
                if strat_id:
                    return str(strat_id)
        except Exception:
            pass
    if run_id is None:
        return DEFAULT_CANDIDATE_ID
    if "hydrogen_v1_0" in str(run_id).lower() or "hydrogen-v1.0" in str(run_id).lower():
        return "hydrogen-v1.0"
    if "hydrogen_v1_1" in str(run_id).lower() or "hydrogen-v1.1" in str(run_id).lower():
        return "hydrogen-v1.1"
    if "hydrogen" in str(run_id).lower():
        return DEFAULT_CANDIDATE_ID
    return "hydrogen-v1.0"


def _run_entry(run_id: str | None) -> dict[str, Any]:
    """Live entry numbers recorded in a run's snapshot (single source of truth)."""
    strat_id = _run_strategy_id(run_id)
    if run_id:
        try:
            meta_p = RUNS_DIR / run_id / "run_meta.json"
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


def _hypothesis_text(candidate_id: str | None, *, null: bool,
                     baseline_id: str | None = None) -> str:
    """Formal Hydrogen v1.1 vs Hydrogen v1.0 hypothesis over active-window PnL."""
    strat_id = _run_strategy_id(candidate_id)
    base_strat_id = _run_strategy_id(baseline_id or DEFAULT_BASELINE_ID)

    if "hydrogen-v1.1" in str(strat_id).lower() or "v1_1" in str(strat_id).lower() or "v1.1" in str(strat_id).lower():
        cand_label = "Hydrogen_v1.1"
    elif "hydrogen-v1.0" in str(strat_id).lower() or "v1_0" in str(strat_id).lower() or "v1.0" in str(strat_id).lower():
        cand_label = "Hydrogen_v1.0"
    elif "hydrogen" in str(strat_id).lower():
        cand_label = f"Hydrogen_{_version_tag(strat_id)}"
    else:
        cand_label = f"{_version_tag(strat_id)}"

    if "hydrogen-v1.0" in str(base_strat_id).lower() or "v1_0" in str(base_strat_id).lower() or "v1.0" in str(base_strat_id).lower():
        base_label = "Hydrogen_v1.0"
    elif "hydrogen-v1.1" in str(base_strat_id).lower() or "v1_1" in str(base_strat_id).lower() or "v1.1" in str(base_strat_id).lower():
        base_label = "Hydrogen_v1.1"
    elif "hydrogen" in str(base_strat_id).lower():
        base_label = f"Hydrogen_{_version_tag(base_strat_id)}"
    elif "v2.6" in str(base_strat_id) or "v2_6" in str(base_strat_id):
        base_label = "DSP_v2.6"
    else:
        base_label = f"{_version_tag(base_strat_id)}"

    try:
        from bot import constants as C
        reg = C.STRATEGY_SETUPS.get(strat_id, {})
        blurb = reg.get("features", {}).get("blurb", "")
    except Exception:
        blurb = ""
    if not blurb:
        blurb = "dip-first pair-locking parameters"

    cand_display = cand_label.replace("_", " ")
    base_display = base_label.replace("_", " ")

    if null:
        return (f"H₀: μ_{cand_label} ≤ μ_{base_label} (and ≤ 0) — "
                f"{cand_display}'s {blurb} produce no statistically significant "
                f"improvement in mean active-window PnL over {base_display}.")
    return (f"H₁: μ_{cand_label} > μ_{base_label} and > 0 — "
            f"{cand_display} achieves a statistically significant positive expected "
            f"return per active window and outperforms {base_display} at α = 0.05 (one-tailed).")


def _run_info(run_id: str | None) -> dict[str, Any]:
    """Name/description/highlights/entry generated from a run's own recorded numbers."""
    from bot import constants as C
    strat_id = _run_strategy_id(run_id)
    entry = _run_entry(run_id)
    reg = C.STRATEGY_SETUPS.get(strat_id, {})
    name = reg.get("name", strat_id) if reg else strat_id
    try:
        _sig, desc, hl = C.describe_setup({"id": strat_id, "entry": entry or reg.get("entry", {})})
    except Exception:
        _sig, desc, hl = (reg.get("signature", strat_id), reg.get("description", ""), {})
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
                    if "dangerously-skip-permissions" in strat_id or "hydrogen" in str(strat_id).lower():
                        candidate_id = act_id
        except Exception:
            pass

    baseline_recs = _load_run_windows(baseline_id)
    baseline_stats = _compute_distribution_stats(
        baseline_recs, observed_windows=_count_observed_windows(baseline_id))

    candidate_recs = _load_run_windows(candidate_id) if candidate_id else []
    candidate_stats = _compute_distribution_stats(
        candidate_recs,
        observed_windows=_count_observed_windows(candidate_id) if candidate_id else 0)

    # Statistical Comparison (Welch's one-tailed two-sample t-test on ACTIVE windows)
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
    t_crit: float | None = None
    mu_crit: float | None = None
    se_diff_val = 0.0
    significant = False

    if n_a > 1 and n_b > 1:
        mean_diff = round(mu_b - mu_a, 4)
        se_diff_val = math.sqrt((var_a / n_a) + (var_b / n_b))

        # Welch-Satterthwaite degrees of freedom
        num = ((var_a / n_a) + (var_b / n_b)) ** 2
        denom = (((var_a / n_a) ** 2) / (n_a - 1)) + (((var_b / n_b) ** 2) / (n_b - 1))
        df = round(num / max(denom, 1e-9), 1)

        t_stat = round(mean_diff / max(se_diff_val, 1e-9), 4) if se_diff_val > 0 else 0.0
        # One-tailed p-value (testing mu_b > mu_a)
        p_value = round(max(0.0, 1.0 - _t_cdf(t_stat, df)), 4)

        # Dynamic critical threshold from the actual df (alpha = 0.05, one-tailed)
        t_crit = _t_critical(df, ALPHA)
        # Exact active-window mean the candidate must cross to reject H0.
        mu_crit = round(mu_a + t_crit * se_diff_val, 4) if se_diff_val > 0 else round(mu_a, 4)

        # Pooled SD for Cohen's d
        s_pooled = math.sqrt(((n_a - 1) * var_a + (n_b - 1) * var_b) / max(1, n_a + n_b - 2))
        cohen_d = round(mean_diff / max(s_pooled, 1e-9), 3) if s_pooled > 0 else 0.0

        # 95% Confidence Interval for (mu_b - mu_a)
        margin = 1.96 * se_diff_val
        ci_lower = round(mean_diff - margin, 4)
        ci_upper = round(mean_diff + margin, 4)

        gates_met = bool(
            n_b >= TARGET_SAMPLE_SIZE
            and candidate_stats["pairedWindows"] >= TARGET_PAIRED_WINDOWS
            and candidate_stats["subDollarPairs"] >= TARGET_SUB_DOLLAR_PAIRS
        )
        significant = bool(t_stat >= t_crit and p_value <= ALPHA and gates_met)

    # Status verdict string
    if n_b < 5:
        verdict = "Awaiting Sample Data"
        verdict_tone = "neutral"
    elif n_b < TARGET_SAMPLE_SIZE:
        verdict = f"Data Gathering ({n_b}/{TARGET_SAMPLE_SIZE} active)"
        verdict_tone = "info"
    elif significant:
        verdict = f"Statistically Significant Alpha (Reject H0, p={p_value:.3f})"
        verdict_tone = "success"
    elif n_a > 1 and n_b > 1 and t_stat >= t_crit and p_value <= ALPHA:
        verdict = (f"Significant but Gates Not Met "
                   f"(need {TARGET_SAMPLE_SIZE} active / {TARGET_PAIRED_WINDOWS} paired / "
                   f"{TARGET_SUB_DOLLAR_PAIRS} sub-$1.00)")
        verdict_tone = "accent"
    elif mu_b > mu_a:
        verdict = f"Trending Favorable (p={p_value:.3f}, need N={TARGET_SAMPLE_SIZE} active)"
        verdict_tone = "accent"
    else:
        verdict = f"No Edge Detected (Fail to Reject H0, p={p_value:.3f})"
        verdict_tone = "danger"

    histogram = _build_histogram(baseline_stats["pnlList"], candidate_stats["pnlList"], mu_crit)

    return {
        "status": "ready",
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline": {
            "runId": baseline_id,
            **_run_info(baseline_id),
            **baseline_stats,
        },
        "candidate": {
            "runId": candidate_id,
            **_run_info(candidate_id),
            "targetSamples": TARGET_SAMPLE_SIZE,
            "progressPct": round(min(100.0, (n_b / TARGET_SAMPLE_SIZE) * 100.0), 1),
            **candidate_stats,
        },
        "statistics": {
            "targetSampleSize": TARGET_SAMPLE_SIZE,
            "targetPaired": TARGET_PAIRED_WINDOWS,
            "targetSubDollar": TARGET_SUB_DOLLAR_PAIRS,
            "alpha": ALPHA,
            "confidenceLevel": "95%",
            "power": "80%",
            "tStatistic": t_stat,
            "tCritical": t_crit,
            "muCritical": mu_crit,
            "standardError": round(se_diff_val, 4),
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
            "nullHypothesis": _hypothesis_text(candidate_id, null=True, baseline_id=baseline_id),
            "altHypothesis": _hypothesis_text(candidate_id, null=False, baseline_id=baseline_id),
            "decisionRule": (
                f"Reject H₀ only when t ≥ t_crit(df) (p ≤ 0.05) AND candidate reaches "
                f"N = {TARGET_SAMPLE_SIZE} active windows, "
                f"{TARGET_PAIRED_WINDOWS} paired windows, and "
                f"{TARGET_SUB_DOLLAR_PAIRS}+ sub-$1.00 pairs; "
                f"μ_B must cross μ_crit" +
                (f" (${mu_crit:.4f})" if mu_crit is not None else "") +
                "."
            ),
        },
        "histogram": histogram,
    }


def start_candidate_test(candidate_id: str | None = None,
                         baseline_run_id: str | None = None) -> dict[str, Any]:
    """Switch the live config to a registry setup and start a run tracked as the A/B candidate."""
    from bot import api
    from bot.runs import find_run_id

    # 1. Update config to the registry's candidate parameters (single source of truth).
    from bot import constants as C
    candidate_id = candidate_id or DEFAULT_CANDIDATE_ID
    if candidate_id not in C.STRATEGY_SETUPS:
        raise ValueError(f"Unknown candidateId: {candidate_id}. "
                         f"Valid setups: {list(C.STRATEGY_SETUPS.keys())}")
    baseline_run_id = baseline_run_id or DEFAULT_BASELINE_ID
    if baseline_run_id != DEFAULT_BASELINE_ID:
        # The API forwards baselineRunId straight from the request body: resolve it
        # through the runs folder so a path cannot escape it.
        resolved = find_run_id(baseline_run_id)
        if not resolved:
            raise ValueError(f"Unknown baselineRunId: {baseline_run_id}")
        baseline_run_id = resolved
    _reg = C.STRATEGY_SETUPS[candidate_id]
    cfg = api.load_config()
    cfg["strategy"] = {
        "id": _reg["id"],
        "symbol": _reg["symbol"],
        "name": _reg["name"],
    }
    # Replace, don't merge: a leftover dipCurve/maxUnhedgedUsd from the previous
    # setup would otherwise keep sizing the new one (the curve shadows every
    # other sizing branch in select_ladder_clip).
    cfg["entry"] = dict(_reg["entry"])
    tmp = api.CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    tmp.replace(api.CONFIG_PATH)

    # 2. Stop any existing loop
    api.stop_loop_process()
    time.sleep(0.5)

    # 3. Generate run ID and register candidate
    if "hydrogen" in str(candidate_id).lower():
        tag = _version_tag(candidate_id).replace(".", "_")
        run_id = f"run_{time.strftime('%Y%m%d_%H%M%S')}_paper_hydrogen_{tag}"
    else:
        run_id = f"run_{time.strftime('%Y%m%d_%H%M%S')}_paper_dsp_{_version_tag(candidate_id).replace('.', '_')}"
    ab_state = {
        "baselineRunId": baseline_run_id,
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
        "baselineRunId": baseline_run_id,
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

