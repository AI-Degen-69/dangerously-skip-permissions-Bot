"""Run-scoped session workspace manager for dangerously-skip-permissions paper bot.

Provides deterministic run sessions under `bot/runs/<run_id>/`:
  bot/runs/
    run_20261108_044500_paper_default/
      run_meta.json      (config snapshot, startedAt, endedAt, status)
      loop.log           (process output)
      loop.pid           (process ID)
      events.jsonl       (session decision journal)
      decisions.jsonl    (uncensored per-evaluation engine log: quotes + guard)
      windows/           (settled window json files)
      summary.json       (session KPIs / metrics)

For backward compatibility with existing tools and default paths:
  bot/current -> resolves to active run folder (or fallback to bot/ if no runs exist)
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("bot.runs")

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


# --- tape stats -------------------------------------------------------------
# The recorder appends to multi-GB files (book.jsonl passed 5 GB in one run),
# so re-counting every line per desk request took ~30s per call. Counts are
# incremental: only bytes appended since the last count are read, and the
# offsets are kept in `.tape_stats.json` next to the tape files so an API
# restart does not trigger a full rescan of several GB.
_TAPE_LOCK = threading.Lock()
_TAPE_COUNTS: dict[str, dict[str, int]] = {}
_TAPE_LOADED: set[str] = set()


def _tape_cache_file(tape_dir: Path) -> Path:
    return tape_dir / ".tape_stats.json"


def _count_appended_lines(path: Path, offset: int) -> tuple[int, int]:
    """Count complete lines appended after `offset`; return (lines, new_offset).

    A trailing partial line is left uncounted and re-read on the next call, so
    a line still being written is never counted twice.
    """
    lines = 0
    consumed = 0
    pending = b""
    with path.open("rb") as f:
        f.seek(offset)
        while True:
            block = f.read(1 << 20)
            if not block:
                break
            data = pending + block
            nl = data.rfind(b"\n")
            if nl < 0:
                pending = data
                continue
            lines += data.count(b"\n", 0, nl + 1)
            consumed += nl + 1
            pending = data[nl + 1 :]
    return lines, offset + consumed


def _load_tape_counts(tape_dir: Path) -> None:
    key = str(tape_dir)
    if key in _TAPE_LOADED:
        return
    _TAPE_LOADED.add(key)
    try:
        raw = json.loads(_tape_cache_file(tape_dir).read_text(encoding="utf-8"))
    except Exception:
        return
    for name, entry in raw.items():
        try:
            _TAPE_COUNTS[str(tape_dir / name)] = {
                "offset": int(entry["offset"]),
                "lines": int(entry["lines"]),
            }
        except Exception:
            continue


def _save_tape_counts(tape_dir: Path) -> None:
    payload = {
        Path(key).name: entry
        for key, entry in _TAPE_COUNTS.items()
        if Path(key).parent == tape_dir
    }
    target = _tape_cache_file(tape_dir)
    try:
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        pass


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
        self.decisions_file = self.root / "decisions.jsonl"
        self.log_file = self.root / "loop.log"
        self.pid_file = self.root / "loop.pid"
        self.summary_file = self.root / "summary.json"
        self.tape_dir = self.root / "tape"

    def tape_stats(self) -> dict[str, Any]:
        """Count tape files for the #35 trade-print recorder (prints + top-5 book).

        Counting is incremental and cached (see `_count_appended_lines`): the
        recorder writes multi-GB files, so a full re-read per request stalled the
        desk API for ~30s on a 5 GB book.jsonl.
        """
        prints_path = self.tape_dir / "prints.jsonl"
        book_path = self.tape_dir / "book.jsonl"
        out: dict[str, Any] = {
            "tapeDir": str(self.tape_dir),
            "prints": 0,
            "books": 0,
            "printsBytes": 0,
            "bookBytes": 0,
        }
        for key, path, size_key in (
            ("prints", prints_path, "printsBytes"),
            ("books", book_path, "bookBytes"),
        ):
            try:
                if path.exists():
                    size = path.stat().st_size
                    out[size_key] = size
                    out[key] = self._count_lines(path, size)
            except Exception:
                pass
        out["mb"] = round((out["printsBytes"] + out["bookBytes"]) / (1024 * 1024), 4)
        return out

    def _count_lines(self, path: Path, size: int) -> int:
        key = str(path)
        with _TAPE_LOCK:
            _load_tape_counts(self.tape_dir)
            entry = _TAPE_COUNTS.get(key) or {"offset": 0, "lines": 0}
            offset = int(entry.get("offset", 0))
            lines = int(entry.get("lines", 0))
            if size < offset:  # truncated or replaced under us
                offset, lines = 0, 0
            if size > offset:
                added, offset = _count_appended_lines(path, offset)
                lines += added
                _TAPE_COUNTS[key] = {"offset": offset, "lines": lines}
                _save_tape_counts(self.tape_dir)
            return lines

    def exists(self) -> bool:
        return self.root.exists() and self.meta_file.exists()

    def init_workspace(self, config: dict[str, Any] | None = None, mode: str = "paper", label: str = "default") -> RunMeta:
        self.root.mkdir(parents=True, exist_ok=True)
        self.windows_dir.mkdir(parents=True, exist_ok=True)
        existing = self.read_meta()
        if existing:
            existing.status = "running"
            existing.ended_at = None
            if config:
                merged_snap = dict(config)
                # Preserve the run's original starting capital / bankroll
                orig_snap = existing.config_snapshot or {}
                if "bankrollUsd" in orig_snap:
                    merged_snap["bankrollUsd"] = orig_snap["bankrollUsd"]
                if "initialCapitalUsd" in orig_snap:
                    merged_snap["initialCapitalUsd"] = orig_snap["initialCapitalUsd"]
                existing.config_snapshot = merged_snap
            self.save_meta(existing)
            return existing
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

    def sync_to_paper_runs(self, target_dir: Path | None = None) -> int:
        """Mirror all windows from self.windows_dir into active paper_runs, removing stale windows from other runs."""
        dest = target_dir or (BOT_DIR / "paper_runs")
        dest.mkdir(parents=True, exist_ok=True)
        self.windows_dir.mkdir(parents=True, exist_ok=True)
        # 1. Mirror all windows from self.windows_dir into dest, preserving redemption info
        for p in self.windows_dir.glob("*.json"):
            dest_file = dest / p.name
            try:
                if dest_file.exists():
                    try:
                        dest_data = json.loads(dest_file.read_text(encoding="utf-8"))
                        if dest_data.get("redeemed") or dest_data.get("redeemedAt"):
                            src_data = json.loads(p.read_text(encoding="utf-8"))
                            if not src_data.get("redeemed") and dest_data.get("redeemed"):
                                src_data["redeemed"] = dest_data["redeemed"]
                            if "redeemedAt" in dest_data and "redeemedAt" not in src_data:
                                src_data["redeemedAt"] = dest_data["redeemedAt"]
                            p.write_text(json.dumps(src_data, indent=2), encoding="utf-8")
                    except Exception as err:
                        logger.warning(f"Error checking redemption info in {dest_file}: {err}")
                shutil.copyfile(p, dest_file)
            except Exception as exc:
                logger.error(f"Failed to copy window file {p} to {dest_file}: {exc}")
                raise RuntimeError(f"Window sync failed for {p.name}: {exc}") from exc
        # 2. Clean up any windows in dest that do NOT exist in self.windows_dir
        ws_names = set(p.name for p in self.windows_dir.glob("*.json"))
        for p in dest.glob("*.json"):
            if p.name not in ws_names:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
        return len(ws_names)

    def settle_pending_windows(self, target_dir: Path | None = None, max_windows: int = 50) -> list[str]:
        """Check for any unsettled/pending windows in workspace and resolve via Polymarket if finalized."""
        resolved_slugs = []
        if not self.windows_dir.exists():
            return resolved_slugs
        dest = target_dir or (BOT_DIR / "paper_runs")
        try:
            from polymarket import PublicClient
            client = PublicClient()
        except Exception:
            return resolved_slugs

        count = 0
        for p in sorted(self.windows_dir.glob("*.json")):
            if count >= max_windows:
                break
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not data.get("pending") and data.get("winner"):
                continue
            slug = data.get("event_slug") or p.stem
            try:
                ev = client.get_event(slug=slug).model_dump()
                mk = (ev.get("markets") or [{}])[0]
                outs = mk.get("outcomes") or {}
                winner = None
                for _key, info in outs.items():
                    try:
                        if float(info.get("price") or 0) >= 1.0:
                            winner = info.get("label")
                            break
                    except (TypeError, ValueError):
                        continue
                if winner:
                    fills = data.get("fills", [])
                    cost = float(data.get("cost_usd", 0.0))
                    wshares = sum(f["shares"] for f in fills if f.get("outcome") == winner)
                    payout = round(wshares * 1.0, 2)
                    net = round(payout - cost, 2)
                    data["winner"] = winner
                    data["payout_usd"] = payout
                    data["net_usd"] = net
                    data.pop("pending", None)
                    data["resolvedAt"] = utc_now_iso()
                    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
                    if dest.exists():
                        (dest / p.name).write_text(json.dumps(data, indent=2), encoding="utf-8")
                    resolved_slugs.append(slug)
                    count += 1
            except Exception:
                continue
        return resolved_slugs


def find_run_id(query: str, runs_root: Path = RUNS_DIR) -> str | None:
    """Find a run_id by exact match or substring match (e.g. '083527')."""
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
    if target_id:
        try:
            ws = RunWorkspace(target_id)
            if ws.exists() or run_id is not None:
                return ws
        except ValueError:
            return None
    return None
