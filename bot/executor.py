"""🎯 Hybrid Arbitrage Pairing & Certainty Sniping v1 (HAPCS-v1).

Microstructure Executor & Order Decision Engine.
Reconstructed and cross-validated against 16,855 fills from wallet
`dangerously-skip-permissions` across 288 consecutive 5-minute Bitcoin markets.

Core Strategy Pillars:
  1. Maker Dip Grid [7¢–50¢] (0% fee, up to 90-share unhedged lead)
  2. Dynamic Arbitrage Pairing (any price that reduces share deficit with pair cost ≤ $0.990)
  3. Resolution Certainty Snipe in Minute 4 [up to 97.5¢]
  4. Phase 0 Pre-Open Resting Orders ($T-310s \\to T-300s$)
  5. Settlement Lock ($T-12s \\to T-0s$)

Shell: public names and patch surface live here; pure logic lives in
exec_pricing / exec_sizing / exec_hydrogen / exec_ladder / exec_sim.
"""

import sys as _sys

from . import constants as C
from .exec_hydrogen import (
    H19_L1_CUTOFF_MATCHED,
    H19_L1_CUTOFF_SEC,
    H19_L1_PRICE_MAX,
    H19_L1_PRICE_MIN,
    H19_L1_PROBE_SHARES,
    H19_L2_PAIR_CAP,
    H19_L3_ASK_MAX,
    H19_L3_MARGINAL_MIN,
    H19_L3_PATIENCE_SEC,
    H19_LEAD_TOLERANCE,
    H20_ATM_MAX_BID,
    H20_DIP_TOUCH_MAX,
    H20_LEAD_TOLERANCE,
    v20_max_hedge_price,
)
from .exec_ladder import evaluate_microstructure_ladder as _ladder_impl
from .exec_pricing import MicrostructureDecision, compute_fill_usd, taker_fee_per_share
from .exec_sim import PaperFill, WindowPlan, m_quotas, pick_side, plan_window
from .exec_sizing import (
    HUMP_ANCHORS,
    dip_curve_shares,
    hump_shares,
    is_hump_curve,
    select_ladder_clip,
)

__all__ = [
    "HUMP_ANCHORS",
    "H19_L1_CUTOFF_MATCHED",
    "H19_L1_CUTOFF_SEC",
    "H19_L1_PRICE_MAX",
    "H19_L1_PRICE_MIN",
    "H19_L1_PROBE_SHARES",
    "H19_L2_PAIR_CAP",
    "H19_L3_ASK_MAX",
    "H19_L3_MARGINAL_MIN",
    "H19_L3_PATIENCE_SEC",
    "H19_LEAD_TOLERANCE",
    "H20_ATM_MAX_BID",
    "H20_DIP_TOUCH_MAX",
    "H20_LEAD_TOLERANCE",
    "MicrostructureDecision",
    "PaperFill",
    "WindowPlan",
    "compute_fill_usd",
    "dip_curve_shares",
    "evaluate_microstructure_ladder",
    "hump_shares",
    "is_hump_curve",
    "m_quotas",
    "pick_side",
    "plan_window",
    "select_ladder_clip",
    "taker_fee_per_share",
    "v20_max_hedge_price",
]


def evaluate_microstructure_ladder(
    quotes,
    inv,
    fill_idx,
    minute,
    strategy_id=C.STRATEGY_ID,
    min_fill=C.PRICE_FLOOR,
    max_fill=C.PRICE_CEILING,
    default_clip=C.CLIP_SHARES_DEFAULT,
    max_clip=C.MAX_SHARES,
    whole_ladder=True,
    benchmark_pair_cost=C.BENCHMARK_PAIR_COST,
    max_pair_cost=C.PAIR_COST_MAX,
    max_unhedged_usd=0.0,
    max_unhedged_shares=0.0,
    dip_curve=None,
    target_pair_cost=None,
    in_sweep_phase=False,
    rescue_max_pair_cost=C.RESCUE_PAIR_COST_MAX,
    rescue_ceiling=C.RESCUE_CEILING_PRICE,
    max_depth_shares=0.0,
    resting_size=None,
    leg1_max_price=None,
    leg2_max_price=None,
    taker_dip_max=None,
    taker_hedge_max_pair_cost=None,
    hedge_max_clip=None,
    late_rescue_start_sec=None,
    late_rescue_max_pair_cost=None,
    elapsed_sec=None,
    unhedged_step_cents=None,
    unhedged_probe_shares=None,
    open_orders=None,
    clip_schedule=None,
    _sizing_fn=None,
    **kwargs,
):
    """Shell wrapper preserving the patch surface.

    ``bot.replay`` monkeypatches ``bot.executor.select_ladder_clip``; the
    lookup below is dynamic so the patched sizing flows into the pure ladder.
    """
    mod = _sys.modules[__name__]
    sizing = _sizing_fn if _sizing_fn is not None else mod.select_ladder_clip
    return _ladder_impl(
        quotes,
        inv,
        fill_idx,
        minute,
        strategy_id=strategy_id,
        min_fill=min_fill,
        max_fill=max_fill,
        default_clip=default_clip,
        max_clip=max_clip,
        whole_ladder=whole_ladder,
        benchmark_pair_cost=benchmark_pair_cost,
        max_pair_cost=max_pair_cost,
        max_unhedged_usd=max_unhedged_usd,
        max_unhedged_shares=max_unhedged_shares,
        dip_curve=dip_curve,
        target_pair_cost=target_pair_cost,
        in_sweep_phase=in_sweep_phase,
        rescue_max_pair_cost=rescue_max_pair_cost,
        rescue_ceiling=rescue_ceiling,
        max_depth_shares=max_depth_shares,
        resting_size=resting_size,
        leg1_max_price=leg1_max_price,
        leg2_max_price=leg2_max_price,
        taker_dip_max=taker_dip_max,
        taker_hedge_max_pair_cost=taker_hedge_max_pair_cost,
        hedge_max_clip=hedge_max_clip,
        late_rescue_start_sec=late_rescue_start_sec,
        late_rescue_max_pair_cost=late_rescue_max_pair_cost,
        elapsed_sec=elapsed_sec,
        unhedged_step_cents=unhedged_step_cents,
        unhedged_probe_shares=unhedged_probe_shares,
        open_orders=open_orders,
        clip_schedule=clip_schedule,
        _sizing_fn=sizing,
        **kwargs,
    )
