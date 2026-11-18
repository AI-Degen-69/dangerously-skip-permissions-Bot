"""Run-store paths, runtime dirs, and run-id helpers."""

from __future__ import annotations


import logging
from datetime import datetime, timezone
from pathlib import Path


logger = logging.getLogger("bot.runs")

ROOT = Path(__file__).resolve().parent.parent.parent
BOT_DIR = ROOT / "bot"
DATA_DIR = ROOT / "data"
CONFIG_PATH = DATA_DIR / "config.json"
# Fallback journal used only when no run or workspace resolves (and for
# legacy-mirror redemptions). Per-run journals live at <run>/events.jsonl.
EVENTS_PATH = DATA_DIR / "events.jsonl"
PID_PATH = DATA_DIR / "loop.pid"
KILL_PATH = DATA_DIR / "kill"
LOG_PATH = DATA_DIR / "loop.log"
AB_STATE_PATH = DATA_DIR / "ab_test_state.json"
# Fallback live snapshot when no run resolves (normally per-run state.json).
STATE_PATH = DATA_DIR / "state.json"
# Flat copy of the windows of the run that synced last — not a run store.
WINDOWS_MIRROR_DIR = DATA_DIR / "windows_mirror"
RUNS_DIR = DATA_DIR / "runs"
ACTIVE_RUN_POINTER = RUNS_DIR / "active_run.json"
_WINDOWS_MIRROR_LEGACY_DIR = BOT_DIR / "paper_runs"

def ensure_data_dir() -> Path:
    """Create the shared runtime dir before PID or kill writes."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def migrate_windows_mirror(old_dir: Path | None = None, new_dir: Path | None = None) -> str:
    """Move the pre-rename mirror folder once.

    Returns "moved", "both-exist", "absent" or "error" so callers and tests can
    tell what happened without parsing logs.
    """
    old = old_dir or _WINDOWS_MIRROR_LEGACY_DIR
    new = new_dir or WINDOWS_MIRROR_DIR
    old_exists, new_exists = old.exists(), new.exists()
    if old_exists and new_exists:
        logger.warning(f"Both {old} and {new} exist; leaving them unchanged — merge by hand")
        return "both-exist"
    if not old_exists:
        return "absent"
    try:
        old.replace(new)
    except OSError as ex:
        logger.warning(f"Could not move {old} to {new}: {ex}")
        return "error"
    logger.info(f"moved windows mirror {old} -> {new}")
    return "moved"

def make_run_id(mode: str = "paper", label: str = "default", runs_root: Path = RUNS_DIR) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    clean_label = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in label)
    base_id = f"run_{ts}_{mode}_{clean_label}"
    candidate = base_id
    counter = 1
    while (runs_root / candidate).exists():
        candidate = f"{base_id}_{counter}"
        counter += 1
    return candidate
