"""Run lookup: find, activate, list, and resolve run workspaces."""

from __future__ import annotations


import json
import re
import sys
from pathlib import Path
from typing import Any

from .runs_paths import ACTIVE_RUN_POINTER, RUNS_DIR, utc_now_iso
from .runs_workspace import RunWorkspace


def _effective_runs_dir(explicit=None):
    if explicit is not None:
        return explicit
    shell = sys.modules.get("bot.runs")
    if shell is not None and getattr(shell, "RUNS_DIR", None) is not None:
        return getattr(shell, "RUNS_DIR")
    return RUNS_DIR


def find_run_id(query: str, runs_root: Path | None = None) -> str | None:
    """Find a run_id by exact match or substring match (e.g. '083527')."""
    runs_root = _effective_runs_dir(runs_root)
    if not runs_root.exists():
        return None
    clean = str(query).strip()
    if not clean:
        return None
    # Reject path traversal / directory separator characters
    if not re.match(r"^[a-zA-Z0-9_\-]+$", clean):
        return None
    # Check exact match
    exact = runs_root / clean
    if exact.is_dir() and (exact / "run_meta.json").exists():
        return clean
    # Check substring / prefix match (newest first)
    matches = []
    for d in sorted(runs_root.iterdir(), reverse=True):
        if d.is_dir() and (d / "run_meta.json").exists() and clean in d.name:
            matches.append(d.name)
    if matches:
        return matches[0]
    return None

def get_active_run_id() -> str | None:
    """Return the currently active or selected run_id from pointer file."""
    if not ACTIVE_RUN_POINTER.exists():
        return None
    try:
        data = json.loads(ACTIVE_RUN_POINTER.read_text(encoding="utf-8"))
        return data.get("activeRunId")
    except Exception:
        return None

def set_active_run_id(run_id: str | None) -> None:
    """Set or clear the active run pointer."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    if run_id is None:
        if ACTIVE_RUN_POINTER.exists():
            try:
                ACTIVE_RUN_POINTER.unlink()
            except Exception:
                pass
        return
    data = {"activeRunId": run_id, "updatedAt": utc_now_iso()}
    ACTIVE_RUN_POINTER.write_text(json.dumps(data, indent=2), encoding="utf-8")

def list_all_runs(runs_root: Path | None = None) -> list[dict[str, Any]]:
    """List all available run sessions ordered newest first."""
    runs_root = _effective_runs_dir(runs_root)
    if not runs_root.exists():
        return []
    active_id = get_active_run_id()
    results = []
    for d in sorted(runs_root.iterdir(), reverse=True):
        if not d.is_dir() or not (d / "run_meta.json").exists():
            continue
        ws = RunWorkspace(d.name, runs_root=runs_root)
        meta = ws.read_meta()
        if meta:
            item = meta.to_dict()
            item["isActive"] = (meta.run_id == active_id)
            item["windowsCount"] = len(list(ws.windows_dir.glob("*.json"))) if ws.windows_dir.exists() else 0
            results.append(item)
    return results

def resolve_run_workspace(run_id: str | None = None) -> RunWorkspace | None:
    """Resolve RunWorkspace by specific run_id or currently active run."""
    target_id = None
    if run_id:
        target_id = find_run_id(run_id) or run_id
    else:
        target_id = get_active_run_id()
    if not target_id:
        # Check if there are any runs at all; if so, pick latest
        all_runs = list_all_runs()
        if all_runs:
            target_id = all_runs[0]["runId"]
    runs_root = _effective_runs_dir(None)
    if target_id:
        try:
            ws = RunWorkspace(target_id, runs_root=runs_root)
            if ws.exists() or run_id is not None:
                return ws
        except ValueError:
            return None
    return None
