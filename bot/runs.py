"""Run-scoped session workspace manager for dangerously-skip-permissions paper bot.

Provides deterministic run sessions under `bot/runs/<run_id>/`:
  bot/runs/
    run_20261108_044500_paper_default/
      run_meta.json      (config snapshot, startedAt, endedAt, status)
      loop.log           (process output)
      loop.pid           (process ID)
      events.jsonl       (session decision journal)
      windows/           (settled window json files)
      summary.json       (session KPIs / metrics)

For backward compatibility with existing tools and default paths:
  bot/current -> resolves to active run folder (or fallback to bot/ if no runs exist)
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BOT_DIR = ROOT / "bot"
RUNS_DIR = BOT_DIR / "runs"
ACTIVE_RUN_POINTER = RUNS_DIR / "active_run.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


@dataclass
class RunMeta:
    run_id: str
    started_at: str
    status: str = "running"  # "running" | "completed" | "interrupted" | "view_only"
    mode: str = "paper"
    label: str = "default"
    ended_at: str | None = None
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "startedAt": self.started_at,
            "status": self.status,
            "mode": self.mode,
            "label": self.label,
            "endedAt": self.ended_at,
            "configSnapshot": self.config_snapshot,
            "summary": self.summary,
        }


class RunWorkspace:
    """Manages files and paths for a single execution or archived run."""

    def __init__(self, run_id: str, runs_root: Path = RUNS_DIR):
        clean_id = "".join(c for c in str(run_id) if c.isalnum() or c in ("-", "_"))
        if not clean_id:
            raise ValueError(f"Invalid run_id: {run_id!r}")
        self.run_id = clean_id
        self.runs_root = runs_root
        self.root = (runs_root / self.run_id).resolve()
        try:
            self.root.relative_to(runs_root.resolve())
        except ValueError:
            raise ValueError(f"run_id {run_id!r} resolves outside runs_root")
        self.windows_dir = self.root / "windows"
        self.meta_file = self.root / "run_meta.json"
        self.events_file = self.root / "events.jsonl"
        self.log_file = self.root / "loop.log"
        self.pid_file = self.root / "loop.pid"
        self.summary_file = self.root / "summary.json"

    def exists(self) -> bool:
        return self.root.exists() and self.meta_file.exists()

    def init_workspace(self, config: dict[str, Any] | None = None, mode: str = "paper", label: str = "default") -> RunMeta:
        self.root.mkdir(parents=True, exist_ok=True)
        self.windows_dir.mkdir(parents=True, exist_ok=True)
        meta = RunMeta(
            run_id=self.run_id,
            started_at=utc_now_iso(),
            status="running",
            mode=mode,
            label=label,
            config_snapshot=config or {},
        )
        self.save_meta(meta)
        return meta

    def read_meta(self) -> RunMeta | None:
        if not self.meta_file.exists():
            return None
        try:
            data = json.loads(self.meta_file.read_text(encoding="utf-8"))
            return RunMeta(
                run_id=data.get("runId", self.run_id),
                started_at=data.get("startedAt", ""),
                status=data.get("status", "running"),
                mode=data.get("mode", "paper"),
                label=data.get("label", "default"),
                ended_at=data.get("endedAt"),
                config_snapshot=data.get("configSnapshot", {}),
                summary=data.get("summary", {}),
            )
        except Exception:
            return None

    def save_meta(self, meta: RunMeta) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.meta_file.write_text(json.dumps(meta.to_dict(), indent=2), encoding="utf-8")

    def finalize(self, status: str = "completed", summary: dict[str, Any] | None = None) -> None:
        meta = self.read_meta()
        if not meta:
            meta = RunMeta(run_id=self.run_id, started_at=utc_now_iso())
        meta.status = status
        meta.ended_at = utc_now_iso()
        if summary:
            meta.summary = summary
            try:
                self.summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            except Exception:
                pass
        self.save_meta(meta)

    def list_windows(self) -> list[dict[str, Any]]:
        out = []
        if self.windows_dir.exists():
            for p in sorted(self.windows_dir.glob("*.json")):
                try:
                    out.append(json.loads(p.read_text(encoding="utf-8")))
                except Exception:
                    continue
        return out


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


def list_all_runs(runs_root: Path = RUNS_DIR) -> list[dict[str, Any]]:
    """List all available run sessions ordered newest first."""
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
    target_id = run_id or get_active_run_id()
    if not target_id:
        # Check if there are any runs at all; if so, pick latest
        all_runs = list_all_runs()
        if all_runs:
            target_id = all_runs[0]["runId"]
    if target_id:
        try:
            ws = RunWorkspace(target_id)
            if ws.exists() or run_id is not None:
                return ws
        except ValueError:
            return None
    return None
