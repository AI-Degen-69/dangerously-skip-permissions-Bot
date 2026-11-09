"""Risk: per-window caps, clip limiter, single-window invariant, kill-switch.

Frozen from CSV: 30-share default clip, 50 max, $3.8K max observed window.
Paper default caps sit just above observed max so fidelity runs never clip,
live micro-size must set DAILY_LOSS_CAP_USD explicitly (operator approves).
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

from . import constants as C


@dataclass
class RiskState:
    daily_loss_usd: float = 0.0
    killed: bool = False
    kill_reason: str = ""


DAILY_LOSS_CAP_USD = 500.0  # operator to confirm before any live size
MAX_USD_PER_WINDOW = 4000.0
MAX_TRADES_PER_WINDOW = 500


def clip_shares(want: float) -> float:
    return max(0.0, min(float(want), C.MAX_SHARES))


def check_window(trades: int, cost_usd: float, state: RiskState, kill_path: Path | str | None = None) -> str | None:
    if kill_path is not None and Path(kill_path).exists():
        state.killed = True
        state.kill_reason = "kill-switch file present"
    if state.killed:
        return f"killed: {state.kill_reason}"
    if trades >= MAX_TRADES_PER_WINDOW:
        return f"window trade cap {MAX_TRADES_PER_WINDOW}"
    if cost_usd >= MAX_USD_PER_WINDOW:
        return f"window cost cap ${MAX_USD_PER_WINDOW}"
    if state.daily_loss_usd <= -DAILY_LOSS_CAP_USD:
        state.killed = True
        state.kill_reason = f"daily loss cap ${DAILY_LOSS_CAP_USD}"
        return f"killed: {state.kill_reason}"
    return None


def kill(state: RiskState, reason: str) -> None:
    state.killed = True
    state.kill_reason = reason


# --- single-window invariant -------------------------------------------
# The loop trades one window at a time; a stale state.json from a crashed
# window must never merge into the next window's fills.
def assert_single_window(active_slug: str, state_path: Path | str = "bot/state.json") -> None:
    """Raise if another live window still owns the state file.
    
    If the file belongs to an expired window from the past (endMs <= now)
    or has a stale heartbeat (> HEARTBEAT_STALE_S), the previous process
    died/crashed ungracefully. In that case, retire the stale state file
    so the current window can trade rather than deadlock permanently.
    """
    p = Path(state_path)
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text())
        owner = data.get("slug")
        end_ms = data.get("endMs")
        updated_at = data.get("updatedAtMs")
    except Exception:
        return  # unreadable state never blocks; loop overwrites it
    if not owner or owner == active_slug:
        return

    now_ms = int(time.time() * 1000)
    is_expired = bool(end_ms and now_ms >= end_ms)
    heartbeat_stale = bool(updated_at and (now_ms - updated_at) > (HEARTBEAT_STALE_S * 1000))

    if is_expired or heartbeat_stale:
        try:
            p.unlink()
        except OSError:
            pass
        return

    raise RuntimeError(f"single-window violation: {owner} owns state, {active_slug} refused")


# --- heartbeats --------------------------------------------------------
# state.json updatedAtMs is the heartbeat; the desk shows "Last heartbeat"
# from its age. Stale = loop died mid-window.
HEARTBEAT_STALE_S = 120


def heartbeat(state_path: Path | str = "bot/state.json") -> None:
    """Touch updatedAtMs so the desk knows the loop is alive."""
    p = Path(state_path)
    if not p.exists():
        return
    try:
        st = json.loads(p.read_text())
    except Exception:
        return
    st["updatedAtMs"] = int(time.time() * 1000)
    try:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(st))
        tmp.replace(p)
    except OSError:
        pass


def heartbeat_age_s(state_path: Path | str = "bot/state.json") -> float | None:
    p = Path(state_path)
    try:
        updated = json.loads(p.read_text()).get("updatedAtMs")
    except Exception:
        return None
    if not updated:
        return None
    return max(0.0, time.time() - updated / 1000.0)


def is_stale(state_path: Path | str = "bot/state.json") -> bool:
    age = heartbeat_age_s(state_path)
    return age is not None and age > HEARTBEAT_STALE_S
