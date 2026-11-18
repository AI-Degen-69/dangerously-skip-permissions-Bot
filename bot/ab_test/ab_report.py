"""A/B dashboard report builder over baseline and candidate runs."""

from __future__ import annotations

import json
import math
import time
from typing import Any

from bot import constants as C
from .ab_consts import (
    AB_STATE_PATH,
    ALPHA,
    DEFAULT_BASELINE_ID,
    DEFAULT_CANDIDATE_ID,
    RUNS_DIR,
    TARGET_PAIRED_WINDOWS,
    TARGET_SAMPLE_SIZE,
    TARGET_SUB_DOLLAR_PAIRS,
)
from .ab_dist import _build_histogram, _compute_distribution_stats
from .ab_load import _count_observed_windows, _load_run_windows
from .ab_meta import (
    _hypothesis_text,
    _is_archived_run,
    _run_info,
    _run_strategy_id,
)
from .ab_stats import _t_cdf, _t_critical


# Arm A was measured under the pre-PR #56 engine (no maker-hold / book-cross /
# complementary-fill handling). It stays frozen as the baseline, but the UI
# surfaces this caveat next to the comparison.
BASELINE_ENGINE_WARNING = (
    "Arm A (Hydrogen v1.0) was measured under the pre-PR #56 engine, before "
    "the maker-hold / CLOB book-cross / complementary-fill fix. Treat the "
    "A-vs-B gap as directional until the baseline is re-measured on the "
    "fixed engine."
)


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

    # Archived runs are never valid arms: a persisted pointer at a tainted
    # pre-PR #56 run is dropped so the dashboard starts the new candidate
    # from zero instead of inheriting 126 stale windows.
    if _is_archived_run(baseline_id):
        baseline_id = DEFAULT_BASELINE_ID
    if _is_archived_run(candidate_id):
        candidate_id = None

    # Prefer the live active run when the persisted candidate is stale:
    # if ab_test_state.json points to a strategy that no longer matches
    # DEFAULT_CANDIDATE_ID but active_run.json points to one that does,
    # follow active_run.json so the dashboard stays in sync with the loop.
    # Archived active runs are ignored for the same reason as above.
    active_meta_path = RUNS_DIR / "active_run.json"
    try:
        if active_meta_path.exists():
            ar = json.loads(active_meta_path.read_text(encoding="utf-8"))
            act_id = ar.get("activeRunId")
            if act_id and act_id != baseline_id and not _is_archived_run(act_id):
                if not candidate_id:
                    meta_p = RUNS_DIR / act_id / "run_meta.json"
                    if meta_p.exists():
                        m = json.loads(meta_p.read_text(encoding="utf-8"))
                        strat_id = m.get("configSnapshot", {}).get("strategy", {}).get("id", "")
                        if "dangerously-skip-permissions" in strat_id or "hydrogen" in str(strat_id).lower():
                            candidate_id = act_id
                elif _run_strategy_id(candidate_id) != DEFAULT_CANDIDATE_ID and _run_strategy_id(act_id) == DEFAULT_CANDIDATE_ID:
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
    stat_sig = False

    if n_a > 1 and n_b > 1:
        mean_diff = round(mu_b - mu_a, 4)
        se_diff_val = math.sqrt((var_a / n_a) + (var_b / n_b))

        # Welch-Satterthwaite degrees of freedom. Divide by the actual
        # denominator when it is positive: flooring a tiny-but-valid denom
        # (e.g. 1e-14 from near-identical samples) collapses df toward zero.
        num = ((var_a / n_a) + (var_b / n_b)) ** 2
        denom = (((var_a / n_a) ** 2) / (n_a - 1)) + (((var_b / n_b) ** 2) / (n_b - 1))
        df = round(num / denom, 1) if denom > 0 else 0.0

        t_stat = round(mean_diff / max(se_diff_val, 1e-9), 4) if se_diff_val > 0 else 0.0
        # One-tailed p-value (testing mu_b > mu_a)
        p_value = round(max(0.0, 1.0 - _t_cdf(t_stat, df)), 4)

        # Dynamic critical threshold from the actual df (alpha = 0.05, one-tailed)
        t_crit = _t_critical(df, ALPHA)
        # Exact active-window mean the candidate must cross to reject H0.
        mu_crit = round(mu_a + t_crit * se_diff_val, 4) if se_diff_val > 0 else round(mu_a, 4)
        # Degenerate inputs (e.g. zero variance) yield non-finite cutoffs;
        # the API type already allows null, and the frontend renders it.
        if not math.isfinite(t_crit):
            t_crit = None
        if not math.isfinite(mu_crit):
            mu_crit = None

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
        # H1 requires mu_B > 0 as well: one-sided one-sample t-test vs zero.
        se_b = math.sqrt(var_b / n_b) if var_b > 0 and n_b > 0 else 0.0
        t_crit_1samp = _t_critical(float(n_b - 1), ALPHA)
        b_positive = bool(
            se_b > 0
            and math.isfinite(t_crit_1samp)
            and (mu_b / se_b) >= t_crit_1samp
        )
        stat_sig = bool(
            t_crit is not None
            and t_stat >= t_crit
            and p_value <= ALPHA
            and b_positive
        )
        significant = bool(stat_sig and gates_met)

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
    elif stat_sig:
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

    # Wallet benchmark: the measured account's 21-day median all-in pair cost.
    # Reporting reference for realized pair cost, NOT a pairing gate.
    wallet_benchmark = C.WALLET_MEDIAN_PAIR_COST
    return {
        "status": "ready",
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "walletBenchmarkPairCost": wallet_benchmark,
        "baseline": {
            "runId": baseline_id,
            **_run_info(baseline_id),
            **baseline_stats,
        },
        "candidate": {
            "runId": candidate_id,
            **_run_info(candidate_id),
            "pairCostVsBenchmark": round(candidate_stats["meanPairCost"] - wallet_benchmark, 4),
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
        "baselineWarning": BASELINE_ENGINE_WARNING,
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
                "; and a one-sided one-sample t-test must reject μ_B ≤ 0 " +
                "(t_B ≥ t_crit(N_B − 1))."
            ),
        },
        "histogram": histogram,
    }
