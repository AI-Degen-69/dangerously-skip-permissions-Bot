"""Repeatable migration for existing installs: bot/ runtime files -> data/.

Moves (via os.rename, never copy/overwrite):
  bot/runs/<id>/            -> data/runs/<id>/        (archive; stop on conflict)
  bot/runs/active_run.json  -> data/runs/active_run.json (pointer)
  bot/windows_mirror/       -> data/windows_mirror/  (mirror; stop on conflict)
  bot/state.json            -> data/runs/<runId>/state.json when owned,
                               else data/state.json   (state)
  bot/events.jsonl          -> data/events.jsonl      (event fallback)
  bot/ab_test_state.json    -> data/ab_test_state.json (A/B)
  bot/config.json           -> data/config.json       (config; tracked)
  bot/kill                  -> data/kill              (kill)
  bot/loop.log              -> data/loop.log          (log)
  bot/loop.pid              -> data/loop.pid          (PID)
  bot/current               -> removed (link)

Refuses when:
  - a loop PID file holds a live, uncertain, or unreadable PID,
  - the desk API port is listening,
  - a rename would cross devices (os.rename raises EXDEV).

Single-file conflicts (destination exists) are skipped, never overwritten.
Run-folder and mirror conflicts stop the migration so histories never merge.

Usage:
  python scripts/migrate_runtime_data.py [--root PATH] [--api-port N] [--dry-run]
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import socket
import sys
from pathlib import Path


def repo_paths(repo_root: Path) -> dict[str, Path]:
    data = repo_root / "data"
    bot = repo_root / "bot"
    return {
        "repo": repo_root,
        "data_dir": data,
        "legacy_runs": bot / "runs",
        "runs": data / "runs",
        "legacy_mirror": bot / "windows_mirror",
        "mirror": data / "windows_mirror",
        "legacy_state": bot / "state.json",
        "fallback_state": data / "state.json",
        "legacy_events": bot / "events.jsonl",
        "events": data / "events.jsonl",
        "legacy_ab": bot / "ab_test_state.json",
        "ab": data / "ab_test_state.json",
        "legacy_config": bot / "config.json",
        "config": data / "config.json",
        "legacy_kill": bot / "kill",
        "kill": data / "kill",
        "legacy_log": bot / "loop.log",
        "log": data / "loop.log",
        "legacy_pid": bot / "loop.pid",
        "pid": data / "loop.pid",
        "legacy_link": bot / "current",
        "pointer": data / "runs" / "active_run.json",
    }


FILE_MOVES: tuple[tuple[str, str, str], ...] = (
    ("event", "legacy_events", "events"),
    ("A/B", "legacy_ab", "ab"),
    ("config", "legacy_config", "config"),
    ("kill", "legacy_kill", "kill"),
    ("log", "legacy_log", "log"),
    ("PID", "legacy_pid", "pid"),
)


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def pid_live(pid: int) -> bool | None:
    """True if live, False if dead, None if uncertain."""
    try:
        if os.name == "nt":
            import ctypes

            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not h:
                return False
            try:
                code = ctypes.c_ulong()
                ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
                return code.value == 259
            finally:
                ctypes.windll.kernel32.CloseHandle(h)
        else:
            os.kill(pid, 0)
            return True
    except PermissionError:
        return None
    except OSError:
        return False
    except Exception:
        return None


def pid_status(path: Path) -> str:
    """live | stale | uncertain | absent | unreadable."""
    if not path.exists():
        return "absent"
    pid = _read_pid(path)
    if pid is None:
        return "unreadable"
    res = pid_live(pid)
    if res is True:
        return "live"
    if res is False:
        return "stale"
    return "uncertain"


def api_listening(port: int) -> bool:
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def resolve_state_dst(repo_root: Path, run_id: str | None) -> Path:
    """Owned state goes to its run folder; otherwise the shared fallback."""
    P = repo_paths(repo_root)
    if run_id:
        clean = "".join(c for c in str(run_id) if c.isalnum() or c in ("-", "_"))
        if clean and (P["runs"] / clean).exists():
            return P["runs"] / clean / "state.json"
    return P["fallback_state"]


def migrate(repo_root: Path, api_port: int = 8789, dry_run: bool = False) -> dict:
    P = repo_paths(repo_root)
    actions: list[str] = []
    errors: list[str] = []
    skipped: list[str] = []

    for label, pp in (("legacy PID", P["legacy_pid"]), ("PID", P["pid"])):
        st = pid_status(pp)
        if st in ("live", "uncertain", "unreadable"):
            msg = f"refuse: {label} {pp} is {st}; stop the loop first"
            return {"ok": False, "actions": actions, "errors": [msg], "skipped": skipped}
    if api_listening(api_port):
        return {"ok": False, "actions": actions, "errors": [f"refuse: API port {api_port} is listening; stop the API first"], "skipped": skipped}

    def move_one(kind: str, src: Path, dst: Path, stop_on_conflict: bool = False) -> bool:
        if not src.exists() and not src.is_symlink():
            return True
        if dst.exists():
            if stop_on_conflict:
                errors.append(f"conflict: {dst} already exists; stop (merge by hand)")
                return False
            skipped.append(f"skip-conflict: {dst} already exists; leaving {src}")
            actions.append(f"skip {kind} {src} -> {dst} (destination exists)")
            return True
        if dry_run:
            actions.append(f"{kind} {src} -> {dst} (dry-run)")
            return True
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.rename(src, dst)
            actions.append(f"{kind} {src} -> {dst}")
            return True
        except OSError as ex:
            if ex.errno == errno.EXDEV:
                errors.append(f"refuse: {src} and {dst.parent} are on different devices; move manually")
            else:
                errors.append(f"error: {kind} {src} -> {dst}: {ex}")
            return False

    if not dry_run:
        try:
            P["data_dir"].mkdir(parents=True, exist_ok=True)
        except OSError as ex:
            return {"ok": False, "actions": actions, "errors": [f"error: cannot create {P['data_dir']}: {ex}"], "skipped": skipped}

    # Archive runs: wholesale when the destination is empty, else per run.
    if P["legacy_runs"].exists():
        if not P["runs"].exists():
            if dry_run:
                actions.append(f"archive {P['legacy_runs']} -> {P['runs']} (dry-run)")
            elif not move_one("archive", P["legacy_runs"], P["runs"], stop_on_conflict=True):
                return {"ok": False, "actions": actions, "errors": errors, "skipped": skipped}
        else:
            for child in sorted(P["legacy_runs"].iterdir()):
                if child.is_dir():
                    if not move_one("archive", child, P["runs"] / child.name, stop_on_conflict=True):
                        return {"ok": False, "actions": actions, "errors": errors, "skipped": skipped}
                elif child.name == "active_run.json":
                    if not move_one("pointer", child, P["pointer"]):
                        return {"ok": False, "actions": actions, "errors": errors, "skipped": skipped}
            if not dry_run:
                try:
                    P["legacy_runs"].rmdir()
                    actions.append(f"archive rmdir {P['legacy_runs']}")
                except OSError:
                    pass

    if P["legacy_mirror"].exists():
        if not move_one("mirror", P["legacy_mirror"], P["mirror"], stop_on_conflict=True):
            return {"ok": False, "actions": actions, "errors": errors, "skipped": skipped}

    if P["legacy_state"].exists():
        try:
            run_id = json.loads(P["legacy_state"].read_text(encoding="utf-8")).get("runId")
        except Exception:
            run_id = None
        if not move_one("state", P["legacy_state"], resolve_state_dst(repo_root, run_id)):
            return {"ok": False, "actions": actions, "errors": errors, "skipped": skipped}

    for kind, src_key, dst_key in FILE_MOVES:
        if P[src_key].exists():
            if not move_one(kind, P[src_key], P[dst_key]):
                return {"ok": False, "actions": actions, "errors": errors, "skipped": skipped}

    if P["legacy_link"].exists() or P["legacy_link"].is_symlink():
        if dry_run:
            actions.append(f"link remove {P['legacy_link']} (dry-run)")
        else:
            try:
                if P["legacy_link"].is_symlink() or P["legacy_link"].is_file():
                    P["legacy_link"].unlink()
                    actions.append(f"link remove {P['legacy_link']}")
                else:
                    skipped.append(f"skip-conflict: link {P['legacy_link']} is not a file/symlink")
            except OSError as ex:
                errors.append(f"error: link {P['legacy_link']}: {ex}")
                return {"ok": False, "actions": actions, "errors": errors, "skipped": skipped}

    ok = not errors
    summary = f"moves={len([a for a in actions if '->' in a and not a.startswith('skip')])} skipped={len(skipped)} errors={len(errors)}"
    actions.append(summary)
    if ok:
        actions.append("done: restart the API (scripts/restart_api.ps1) and the loop (python bot/live_paper.py --loop)")
    return {"ok": ok, "actions": actions, "errors": errors, "skipped": skipped}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent), help="repo root for testability")
    ap.add_argument("--api-port", type=int, default=8789)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    res = migrate(Path(args.root), api_port=args.api_port, dry_run=args.dry_run)
    for line in res["actions"]:
        print(line)
    for line in res["errors"]:
        print(line, file=sys.stderr)
    if res.get("skipped"):
        for line in res["skipped"]:
            print(line)
    if not res["ok"]:
        print("STOP: fix the error above, stop the API and loop, then re-run", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
