"""Run-window loading and observed-window counting for A/B inputs."""

from __future__ import annotations

import json
import math
from typing import Any

from . import constants as C
from .ab_consts import RUNS_DIR
from .ab_stats import _pair_cost
from .fill_audit import role_of


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

                # Taker-fee and maker-fee bases for the rebate-adjusted view.
                # Same precedence as api._window_row (canonical: role_of):
                # a recorded role, then a recorded fee, then legacy reason.
                taker_fees = 0.0
                maker_base = 0.0
                for f in fills:
                    try:
                        price = float(f.get("price", 0.0))
                        shares = float(f.get("shares", 0.0))
                    except (TypeError, ValueError):
                        continue
                    if price <= 0 or shares <= 0:
                        continue
                    base = shares * C.TAKER_FEE_COEFF * price * (1 - price)
                    if role_of(f) == "TAKER":
                        detail = f.get("detail") or {}
                        raw_fee = detail.get("feeUsd")
                        fee = float(raw_fee) if isinstance(raw_fee, (int, float)) and not isinstance(raw_fee, bool) else 0.0
                        taker_fees += fee if fee > 0 else base
                    else:
                        maker_base += base

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
                        "rebate": round(float(data.get("rebate_usd") or 0.0), 2),
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
                        "feesUsd": round(taker_fees, 4),
                        "makerFeeBaseUsd": round(maker_base, 4),
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
