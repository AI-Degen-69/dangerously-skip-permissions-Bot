"""Pure live record/settlement helpers — no `bot.live_paper` imports.

All filesystem/config seams are passed in explicitly by the shell.
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from bot.fill_audit import attainable_indexes


def build_decision_record_pure(
    slug: str,
    minute: int,
    in_sweep_phase: bool,
    imbalance: float,
    fills: int,
    cost: float,
    quotes: dict,
    decision,
) -> dict:
    up_q = (quotes.get("Up") or {})
    down_q = (quotes.get("Down") or {})
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "slug": slug,
        "minute": minute,
        "inSweepPhase": bool(in_sweep_phase),
        "imbalance": round(float(imbalance), 1),
        "fills": fills,
        "cost": round(float(cost), 2),
        "action": decision.action,
        "outcome": decision.outcome,
        "price": decision.price,
        "shares": decision.shares,
        "role": decision.role,
        "reason": decision.reason,
        "subReason": decision.sub_reason,
        "projectedPairCost": decision.projected_pair_cost,
        "shareDeficit": decision.share_deficit,
        "quotes": {
            "Up": {"bid": up_q.get("bid"), "ask": up_q.get("ask")},
            "Down": {"bid": down_q.get("bid"), "ask": down_q.get("ask")},
        },
    }


def stamp_attainable_pure(fills: list[dict], prints: list[dict], condition_id: str | None, final: bool = False) -> int:
    """Mark each fill the recorded selling could have filled. Returns changed count."""
    verdicts = attainable_indexes(fills, prints, condition_id)
    if verdicts is None:
        return 0
    changed = 0
    for i, ok in verdicts.items():
        detail = fills[i].setdefault("detail", {})
        if not ok and not final:
            continue
        if detail.get("attainable") is not ok:
            detail["attainable"] = ok
            changed += 1
    return changed


def atomic_write_json_pure(path: Path, data: object) -> None:
    raw = json.dumps(data)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(raw)
    for _ in range(5):
        try:
            tmp.replace(path)
            return
        except OSError:
            time.sleep(0.005)
    try:
        path.write_text(raw)
    except OSError as ex:
        print(f"warning: failed to persist {path}: {ex}", flush=True)


def settled_net_usd_pure(path: Path, day_start: int) -> float:
    tail = path.stem.rsplit("-", 1)[-1]
    if not tail.isdigit() or int(tail) < day_start:
        return 0.0
    try:
        d = json.loads(path.read_text())
        if not isinstance(d, dict) or d.get("pending"):
            return 0.0
        raw_net = d.get("net_usd")
        return float(raw_net) if raw_net is not None else 0.0
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return 0.0


def current_daily_pnl_pure(mirror_dir: Path, day_start: int) -> float:
    if not mirror_dir.exists():
        return 0.0
    return sum(settled_net_usd_pure(p, day_start) for p in mirror_dir.glob("btc-updown-5m-*.json"))


def risk_reason_code_pure(raw_reason: str) -> str:
    if "kill-switch" in raw_reason:
        return "kill-switch-engaged"
    if "daily loss cap" in raw_reason:
        return "daily-loss-cap"
    if "trade cap" in raw_reason:
        return "window-trade-cap"
    return raw_reason


def risk_detail_pure(raw_reason: str, daily_loss_usd: float, trades: int, risk_cfg: dict) -> dict:
    default_cap = float(risk_cfg.get("dailyLossCapUsd", 500.0))
    trade_cap = int(risk_cfg.get("maxFillsPerWindow", 500))
    if "daily loss cap" in raw_reason:
        m = re.search(r"daily loss cap \$?([0-9.]+(?:[eE][+-]?\d+)?)", raw_reason)
        cap = float(m.group(1)) if m else default_cap
        return {"lossUsd": round(abs(daily_loss_usd), 2), "capUsd": cap}
    if "trade cap" in raw_reason:
        m = re.search(r"trade cap (\d+)", raw_reason)
        cap = int(m.group(1)) if m else trade_cap
        return {"fills": trades, "cap": cap}
    return {}


def compute_settlement_pure(
    fills: list[dict],
    cost: float,
    taker_fees_usd: float,
    winner: str | None,
    rebate_rate: float,
) -> dict:
    """Pure settlement math extracted from `settle_slug` orchestration."""
    try:
        rate = float(rebate_rate)
    except (TypeError, ValueError):
        rate = 0.0
    if rate != rate:  # NaN guard
        rate = 0.0
    rate = min(1.0, max(0.0, rate))
    payout = None
    net = None
    rebate_usd = 0.0
    if winner:
        wshares = sum(float(f.get("shares", 0.0)) for f in fills if f.get("outcome") == winner)
        payout = round(wshares * 1.0, 2)
        net = round(payout - float(cost), 2)
        rebate_usd = round(rate * float(taker_fees_usd or 0.0), 2)
    net_rebated = round(net + rebate_usd, 2) if net is not None else None
    return {
        "payout": payout,
        "net": net,
        "rebate_usd": rebate_usd,
        "rebate_rate": rate,
        "net_rebated_usd": net_rebated,
    }
