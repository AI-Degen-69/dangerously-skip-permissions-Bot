"""Run identity helpers: strategy ids, entries, hypothesis text, run info."""

from __future__ import annotations

import json
import re
from typing import Any

from .ab_consts import DEFAULT_BASELINE_ID, DEFAULT_CANDIDATE_ID, RUNS_DIR


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
    # Archived runs without meta label from the name: hydrogen_v1_4 -> hydrogen-v1.4.
    m = re.search(r"hydrogen[-_]v(\d+)[._](\d+)", str(run_id).lower())
    if m:
        return f"hydrogen-v{m.group(1)}.{m.group(2)}"
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
    """Formal candidate-vs-baseline hypothesis over active-window PnL."""
    strat_id = _run_strategy_id(candidate_id)
    base_strat_id = _run_strategy_id(baseline_id or DEFAULT_BASELINE_ID)

    if "hydrogen-v2.0" in str(strat_id).lower() or "v2_0" in str(strat_id).lower() or "v2.0" in str(strat_id).lower():
        cand_label = "Hydrogen_v2.0"
    elif "hydrogen-v1.9" in str(strat_id).lower() or "v1_9" in str(strat_id).lower() or "v1.9" in str(strat_id).lower():
        cand_label = "Hydrogen_v1.9"
    elif "hydrogen-v1.0" in str(strat_id).lower() or "v1_0" in str(strat_id).lower() or "v1.0" in str(strat_id).lower():
        cand_label = "Hydrogen_v1.0"
    elif "hydrogen" in str(strat_id).lower():
        cand_label = f"Hydrogen_{_version_tag(strat_id)}"
    else:
        cand_label = f"{_version_tag(strat_id)}"

    if "hydrogen-v1.0" in str(base_strat_id).lower() or "v1_0" in str(base_strat_id).lower() or "v1.0" in str(base_strat_id).lower():
        base_label = "Hydrogen_v1.0"
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

def _is_archived_run(run_id: str | None) -> bool:
    """True when a run's `run_meta.json` status starts with "archived".

    Archived runs (e.g. the tainted pre-PR #56 `hydrogen_v1_2` sessions) are
    excluded from baseline/candidate lookup so substring matches on the run
    folder name can never resurrect them into the A/B comparison.
    """
    if not run_id:
        return False
    try:
        meta_p = RUNS_DIR / run_id / "run_meta.json"
        if meta_p.exists():
            m = json.loads(meta_p.read_text(encoding="utf-8"))
            return str(m.get("status", "")).startswith("archived")
    except Exception:
        pass
    return False
