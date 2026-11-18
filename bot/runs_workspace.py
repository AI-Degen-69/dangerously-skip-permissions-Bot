"""Run workspace: per-run dirs, meta, windows mirror, settlement."""

from __future__ import annotations


import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("bot.runs")

from .runs_paths import RUNS_DIR, WINDOWS_MIRROR_DIR, utc_now_iso
from .runs_tape import (
    _TAPE_COUNTS,
    _TAPE_LOCK,
    _count_appended_lines,
    _load_tape_counts,
    _save_tape_counts,
    tape_segments,
)


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
        self.state_path = self.root / "state.json"
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
        out: dict[str, Any] = {
            "tapeDir": str(self.tape_dir),
            "prints": 0,
            "books": 0,
            "printsBytes": 0,
            "bookBytes": 0,
        }
        for key, stem, size_key in (
            ("prints", "prints", "printsBytes"),
            ("books", "book", "bookBytes"),
        ):
            try:
                total_bytes = 0
                total_lines = 0
                for path in tape_segments(self.tape_dir, stem):
                    size = path.stat().st_size
                    total_bytes += size
                    total_lines += self._count_lines(path, size)
                out[size_key] = total_bytes
                out[key] = total_lines
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

    def sync_windows_mirror(self, target_dir: Path | None = None) -> int:
        """Mirror this run's windows into the shared windows mirror (one-way).

        Redemption is owned by each run's own workspace file: the mirror is
        only a read cache of the active run, so it must never write
        redemption state back into a workspace file. A same-named mirror
        entry from another run is simply overwritten by this run's file.
        """
        dest = target_dir or WINDOWS_MIRROR_DIR
        dest.mkdir(parents=True, exist_ok=True)
        self.windows_dir.mkdir(parents=True, exist_ok=True)
        # 1. Mirror all windows from self.windows_dir into dest.
        for p in self.windows_dir.glob("*.json"):
            dest_file = dest / p.name
            try:
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
        dest = target_dir or WINDOWS_MIRROR_DIR
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
                    self._audit_record(data, winner)
                    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
                    if dest.exists():
                        (dest / p.name).write_text(json.dumps(data, indent=2), encoding="utf-8")
                    resolved_slugs.append(slug)
                    count += 1
            except Exception:
                continue
        return resolved_slugs

    def _audit_record(self, data: dict[str, Any], winner: str) -> None:
        """Stamp what the window's own tape could actually have filled.

        A window resolved outside the trading loop (crash recovery, desk restart)
        would otherwise carry a net with no fidelity, and the desk's attainable
        view would silently drop it.
        """
        from bot import constants as C
        from bot.fill_audit import attainable_indexes, audit_window
        from bot.tape_verifier import load_book_for_window, load_prints_for_window

        try:
            start = float(int(str(data.get("event_slug") or "").split("-")[-1]))
        except (TypeError, ValueError):
            return
        fills = data.get("fills") or []
        if not fills:
            return
        try:
            prints = load_prints_for_window(self.tape_dir, start, start + C.WINDOW_S)
        except OSError:
            return
        try:
            _book = load_book_for_window(self.tape_dir, start, start + C.WINDOW_S)
        except OSError:
            _book = None
        cid = data.get("condition_id")
        for i, ok in (attainable_indexes(fills, prints, cid) or {}).items():
            fills[i].setdefault("detail", {})["attainable"] = ok
        data["fidelity"] = audit_window(fills, prints, start, winner, cid, book=_book)
