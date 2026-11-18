"""Pure loop-process helpers for the desk API.

No imports from bot.api. Process startup/kill and the PID file stay in
the bot/api.py shell, which passes explicit values in here.
"""
import os
import sys
from pathlib import Path


def _win_alive(pid: int) -> bool:
    import ctypes
    try:
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    except Exception:
        return False
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        return code.value == 259  # STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def parse_pid_file(pid_path: Path) -> int | None:
    try:
        return int(pid_path.read_text().strip())
    except Exception:
        return None


def pid_is_alive(pid: int, win_alive=_win_alive) -> bool:
    try:
        if os.name == "nt":
            return bool(win_alive(pid))
        return os.kill(pid, 0) is None
    except Exception:
        return False


def build_loop_command(run_id: str | None = None) -> list[str]:
    cmd = [sys.executable, "bot/live_paper.py", "--loop"]
    if run_id:
        cmd.extend(["--run-id", run_id])
    return cmd


def loop_env() -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def summarize_tape(run_id: str | None, tape_stats: dict, fills: list[dict]) -> dict:
    verification: dict = {}
    try:
        from bot.tape_verifier import verification_summary
        if fills:
            verification = verification_summary(fills)
    except Exception:
        pass
    return {
        "enabled": True,
        "runId": run_id,
        "tapeDir": tape_stats.get("tapeDir"),
        "prints": tape_stats.get("prints", 0),
        "books": tape_stats.get("books", 0),
        "mb": tape_stats.get("mb", 0.0),
        "verification": verification,
    }
