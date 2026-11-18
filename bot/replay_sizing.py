"""Pure hump sizing curve used by replay ablations.

Single source of truth lives in :mod:`bot.exec_sizing`; this module
re-exports it so ``bot.replay`` keeps its public names without a
second copy of the curve to drift.
"""

from .exec_sizing import HUMP_ANCHORS, hump_shares
from .risk import clip_shares

__all__ = ["HUMP_ANCHORS", "hump_shares", "make_hump_sizing"]

def make_hump_sizing(max_clip: float):
    """select_ladder_clip replacement: deficit branch verbatim, dip = hump.

    Same pattern as scratch/sizing_sim.py: the sizing curve is the parameter
    under test, the engine (evaluate_microstructure_ladder) is untouched.
    """

    def sizing(deficit, price, pair_cost=None, fill_idx=0, default_clip=None,
               max_clip=max_clip, whole_ladder=True, current_lead=0.0,
               dip_curve=None, **kwargs):
        if deficit > 0:
            return min(clip_shares(deficit, max_clip), max_clip)
        return hump_shares(price, max_clip)

    return sizing
