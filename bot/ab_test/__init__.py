"""A/B Testing & Statistical Hypothesis Validation Module.

Compares the frozen, measured Hydrogen v1.0 baseline run
(DEFAULT_BASELINE_ID, `run_20261113_183248_paper_hydrogen_v1_0`) against the
Hydrogen v2.0 candidate (`hydrogen-v2.0`: two-sided simultaneous resting in the
42-47c ATM band and the 7-45c inverse-dip curve, <=$6 unhedged USD, with a
sub-$0.985 maker or <=$0.965 profit-lock taker).

Archived runs (`run_meta.json` status starting with "archived") are never
picked up as baseline or candidate, so the tainted pre-PR #56 v1.2 runs stay
out of the A/B comparison.

The statistical sample is ACTIVE traded windows only (`fills > 0`): zero-fill
windows never inflate N or dilute variance. Welch's one-tailed two-sample
t-test (alpha = 0.05, 80% power) with Welch-Satterthwaite df, a dynamic
`t_crit(df)`, and the exact rejection boundary
`mu_crit = mean_A + t_crit * SE`.

Shell: public names and the api-coupled candidate controls live here; pure
logic lives in ab_consts / ab_stats / ab_load / ab_dist / ab_meta / ab_report.
"""

from __future__ import annotations

import json
import time
from typing import Any

from .ab_consts import (
    AB_STATE_PATH,
    ALPHA,
    BASELINE_DISPLAY_NAME,
    CANDIDATE_DISPLAY_NAME,
    DEFAULT_BASELINE_ID,
    DEFAULT_CANDIDATE_ID,
    RUNS_DIR,
    TARGET_PAIRED_WINDOWS,
    TARGET_SAMPLE_SIZE,
    TARGET_SUB_DOLLAR_PAIRS,
)
from .ab_dist import (
    _build_histogram,
    _compute_distribution_stats,
    _empty_stats,
)
from .ab_load import _count_observed_windows, _load_run_windows, _quantile
from .ab_meta import (
    _hypothesis_text,
    _is_archived_run,
    _run_entry,
    _run_info,
    _run_strategy_id,
    _version_tag,
)
from .ab_report import BASELINE_ENGINE_WARNING, get_ab_test_data
from .ab_stats import _pair_cost, _t_cdf, _t_critical


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


__all__ = [
    "AB_STATE_PATH",
    "ALPHA",
    "BASELINE_DISPLAY_NAME",
    "BASELINE_ENGINE_WARNING",
    "CANDIDATE_DISPLAY_NAME",
    "DEFAULT_BASELINE_ID",
    "DEFAULT_CANDIDATE_ID",
    "RUNS_DIR",
    "TARGET_PAIRED_WINDOWS",
    "TARGET_SAMPLE_SIZE",
    "TARGET_SUB_DOLLAR_PAIRS",
    "_build_histogram",
    "_compute_distribution_stats",
    "_count_observed_windows",
    "_empty_stats",
    "_hypothesis_text",
    "_is_archived_run",
    "_load_run_windows",
    "_pair_cost",
    "_quantile",
    "_run_entry",
    "_run_info",
    "_run_strategy_id",
    "_t_cdf",
    "_t_critical",
    "_version_tag",
    "get_ab_test_data",
    "start_candidate_test",
    "stop_candidate_test",
]
