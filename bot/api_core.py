"""Pure core helpers for the desk API.

No imports from bot.api. All inputs are explicit arguments; the
imperative shell in bot/api.py owns paths, run workspaces, and mutable
caches, and passes values in. This keeps the domain logic testable
without patching module globals.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

BANKROLL_DEFAULT = 1000.0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_config(bankroll_default: float = BANKROLL_DEFAULT) -> dict:
    return {"bankrollUsd": bankroll_default, "mode": "paper", "asset": "BTC",
            "intervals": ["5m"], "entry": {}, "risk": {}, "news": {"blackoutMinutes": 0, "events": []}}


def load_config_from_path(config_path: Path, bankroll_default: float = BANKROLL_DEFAULT) -> dict:
    try:
        return json.loads(config_path.read_text())
    except Exception:
        return default_config(bankroll_default)


def session_label(cfg: dict) -> str:
    """Run-id label for a new session, from the active strategy symbol."""
    strat = cfg.get("strategy") or {}
    raw = str(strat.get("symbol") or strat.get("id") or "")
    clean = "_".join("".join(c.lower() if c.isalnum() else " " for c in raw).split())
    return clean or "default"


def is_pending(r: dict) -> bool:
    return bool(r.get("pending")) or not r.get("winner")


def is_view_only_selected(selected_id: str | None, active_id: str | None) -> bool:
    if not selected_id:
        return False
    if not active_id:
        return False
    return selected_id != active_id


def read_mirror_windows(mirror_dir: Path) -> list[dict]:
    out: list[dict] = []
    try:
        if not mirror_dir.exists():
            return out
        for p in sorted(mirror_dir.glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except Exception:
                continue
    except Exception:
        pass
    return out


def try_read_state(target: Path):
    """Read a state file with a short retry. Returns (ok, state)."""
    for _ in range(3):
        try:
            return True, json.loads(target.read_text())
        except Exception:
            time.sleep(0.005)
    return False, None


def normalize_event(ev: dict, open_prices: dict[str, float]) -> dict:
    slug = ev.get("slug")
    detail = ev.setdefault("detail", {})
    if ev.get("reason") == "straddle-open" and slug and "price" in detail:
        try:
            open_prices[slug] = float(detail["price"])
        except (ValueError, TypeError):
            pass
    elif ev.get("reason") == "thesis-intact":
        ev["reason"] = "clip-fill"
        if "bid" in detail:
            detail["price"] = detail.pop("bid")
    elif ev.get("reason") == "kill-switch-file-present":
        ev["reason"] = "kill-switch-engaged"

    if ev.get("reason") in ("dust-quote", "extreme-price-skip", "no-liquidity", "spread-too-wide"):
        ev["kind"] = "refuse"
    elif ev.get("reason") == "m4-snipe":
        ev["kind"] = "snipe"
        ev["reason"] = "m4-snipe"
    elif ev.get("reason") in ("holding-to-resolution", "too-late-in-window"):
        ev["kind"] = "done"

    if ev.get("reason") == "hedge-leg" and "pairCost" not in detail and slug in open_prices and "price" in detail:
        try:
            detail["pairCost"] = round(open_prices[slug] + float(detail["price"]), 2)
            detail["leg1Price"] = open_prices[slug]
        except (ValueError, TypeError):
            pass
    return ev


def normalize_event_lines(lines: list[str]) -> list[dict]:
    out: list[dict] = []
    open_prices: dict[str, float] = {}
    for line in lines:
        try:
            out.append(normalize_event(json.loads(line), open_prices))
        except Exception:
            continue
    return out


def build_log_record(kind: str, reason: str, now_iso: str, **kw) -> dict:
    return {"ts": now_iso, "kind": kind, "mode": "paper", "reason": reason, **kw}
