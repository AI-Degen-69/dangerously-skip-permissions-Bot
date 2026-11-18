"""Process-safe atomic file writes (leaf helper, no `bot` imports).

Several writers persist the same files from separate processes: the desk
API (`bot/api.py` strategy/config routes) and the live loop (`risk.heartbeat`,
`live_records.atomic_write_json_pure`). A fixed `<name>.tmp` temporary is
shared by all of them, so overlapping writes can replace or tear each
other's temp file.

These helpers give every write its own temp name (pid + thread + counter),
flush + fsync before an atomic `os.replace`, and clean the temp up on
failure. They raise on failure so callers never report success for a write
that did not land; callers that must stay alive (heartbeat, live state)
keep their own try/except around the call.
"""

from __future__ import annotations

import itertools
import json
import os
import threading
from pathlib import Path

_counter = itertools.count()
_pid = os.getpid()


def _tmp_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.{_pid}.{threading.get_ident()}.{next(_counter)}.tmp")


def atomic_write_text(path: Path | str, text: str) -> None:
    """Write `text` to `path` atomically. Raises on failure."""
    target = Path(path)
    tmp = _tmp_path(target)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path | str, data: object, indent: int = 2) -> None:
    """Write `data` as JSON to `path` atomically. Raises on failure."""
    atomic_write_text(path, json.dumps(data, indent=indent))
