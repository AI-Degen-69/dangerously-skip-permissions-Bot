"""Pure clip-sizing helpers (hump curve, dip curve, ladder clip)."""

from . import constants as C
from .risk import clip_shares


HUMP_ANCHORS = [(0.07, 30.0), (0.10, 30.0), (0.40, 48.7), (0.50, 48.7), (0.70, 30.0)]


def hump_shares(price: float, max_clip: float) -> float:
    """Piecewise-linear hump clip, clamped outside the anchors."""
    try:
        px = float(price)
    except (TypeError, ValueError):
        return 10.0
    pts = HUMP_ANCHORS
    if px <= pts[0][0]:
        sh = pts[0][1]
    elif px >= pts[-1][0]:
        sh = pts[-1][1]
    else:
        sh = pts[-1][1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= px <= x1:
                a = (px - x0) / (x1 - x0) if x1 > x0 else 0.0
                sh = y0 + (y1 - y0) * a
                break
    return min(clip_shares(round(sh, 1), max_clip), max_clip)


def is_hump_curve(dip_curve) -> bool:
    """v2.7 hump flag: stored as the string "hump" (or {"type": "hump"})."""
    if dip_curve == "hump":
        return True
    return isinstance(dip_curve, dict) and dip_curve.get("type") == "hump"


def dip_curve_shares(curve: dict, price: float, max_clip: float) -> float | None:
    """Shares for a fresh dip from a linear inverse-dip curve, or None if the curve is unusable.

    curve = {"lo": 0.07, "hi": 0.45, "sharesLo": 33, "sharesHi": 8}: the fat
    end of the band (low price) gets the big clip, the thin end the small one,
    interpolated linearly in price and clamped outside the band.
    """
    try:
        lo = float(curve.get("lo", 0.07))
        hi = float(curve.get("hi", 0.45))
        s_lo = float(curve.get("sharesLo", 10.0))
        s_hi = float(curve.get("sharesHi", 10.0))
    except (AttributeError, TypeError, ValueError):
        # A typo in config.json must not crash the trading loop mid-window.
        return None
    a = min(max((price - lo) / (hi - lo), 0.0), 1.0) if hi > lo else 0.0
    return min(clip_shares(round(s_lo + (s_hi - s_lo) * a), max_clip), max_clip)


def select_ladder_clip(
    deficit: float,
    price: float,
    pair_cost: float | None = None,
    fill_idx: int = 0,
    default_clip: float = C.CLIP_SHARES_DEFAULT,
    max_clip: float = C.MAX_SHARES,
    whole_ladder: bool = True,
    current_lead: float = 0.0,
    dip_curve: dict | None = None,
    **kwargs,  # absorbs legacy unused kwargs
) -> float:
    """Select clip size.

    dip_curve (optional): linear inverse-dip curve that overrides the fresh-dip
    clip. Deficit-closing fills are unaffected (they snap to the deficit).
    """
    if deficit > 0:
        # Snap directly to the deficit capped at max_clip so we don't overshoot
        # or leave residual unhedged dust!
        return min(clip_shares(deficit, max_clip), max_clip)
    if is_hump_curve(dip_curve):
        return hump_shares(price, max_clip)
    if dip_curve:
        curve_clip = dip_curve_shares(dip_curve, price, max_clip)
        if curve_clip is not None:
            return curve_clip
        # Unusable curve values: fall through to the flat ladder clip.
    # Tweak 2: De-escalating clip sizes when leading side accumulates dips
    # Prevents huge runaway deficits from forming during early trending moves
    if current_lead >= 10.0:
        return min(clip_shares(10.0, max_clip), max_clip)
    if current_lead >= 5.0:
        return min(clip_shares(20.0, max_clip), max_clip)
    # Standard 30-share ladder clip on opening, deep dips (<=35c), or alternate fills
    if fill_idx % 2 == 0 or price <= 0.35:
        return min(clip_shares(default_clip, max_clip), max_clip)
    rungs = [r for r in (25.0, 20.0, 15.0, 10.0) if r <= max_clip]
    chosen = rungs[fill_idx % len(rungs)] if rungs else default_clip
    return min(clip_shares(chosen, max_clip), max_clip)
