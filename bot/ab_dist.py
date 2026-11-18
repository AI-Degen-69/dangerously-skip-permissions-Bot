"""Distribution statistics and histograms over window records."""

from __future__ import annotations

import math
from typing import Any

from .ab_load import _quantile


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
        "pairedPnl": 0.0,
        "oneSidedPnl": 0.0,
        "oneSidedWindows": 0,
        "wins": 0,
        "losses": 0,
        "scratches": 0,
        "winRate": 0.0,
        "lossRate": 0.0,
        "netPnl": 0.0,
        "feesUsd": 0.0,
        "rebateUsd": 0.0,
        "netRebated": 0.0,
        "makerFeeBaseUsd": 0.0,
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
    paired_pnl = round(sum(r["net"] for r in paired), 2)
    one_sided = [r for r in active
                 if not ((r.get("upShares", 0.0) or 0.0) > 0 and (r.get("downShares", 0.0) or 0.0) > 0)]
    one_sided_windows = len(one_sided)
    one_sided_pnl = round(sum(r["net"] for r in one_sided), 2)

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
        "pairedPnl": paired_pnl,
        "oneSidedPnl": one_sided_pnl,
        "oneSidedWindows": one_sided_windows,
        "wins": wins,
        "losses": losses,
        "scratches": scratches,
        "winRate": round(wins / n, 4),
        "lossRate": round(losses / n, 4),
        "netPnl": round(net_sum, 2),
        "feesUsd": round(sum(r.get("feesUsd", 0.0) or 0.0 for r in active), 4),
        "rebateUsd": round(sum(r.get("rebate", 0.0) or 0.0 for r in active), 2),
        "netRebated": round(net_sum + sum(r.get("rebate", 0.0) or 0.0 for r in active), 2),
        "makerFeeBaseUsd": round(sum(r.get("makerFeeBaseUsd", 0.0) or 0.0 for r in active), 4),
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
