"""Welch t-test primitives and pair-cost math."""

from __future__ import annotations

import math

from .ab_consts import ALPHA


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
