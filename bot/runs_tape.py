"""Incremental tape counters and segment discovery for multi-GB tapes."""

from __future__ import annotations


import json
import os
import threading
from pathlib import Path


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

def tape_segments(tape_dir: Path, stem: str, suffix: str = ".jsonl") -> list[Path]:
    """Tape segments oldest-first: `prints.<epoch>.jsonl` … then `prints.jsonl`.

    The recorder rotates by size (see `TAPE_SEGMENT_BYTES` in bot/ws.py), so
    readers must walk the archives before the active file to stay chronological.
    """
    archived: list[tuple[int, Path]] = []
    for seg in tape_dir.glob(f"{stem}.*{suffix}"):
        part = seg.name[len(stem) + 1 : -len(suffix)]
        if part.isdigit():
            archived.append((int(part), seg))
    archived.sort(key=lambda item: item[0])
    out = [seg for _, seg in archived]
    active = tape_dir / f"{stem}{suffix}"
    if active.exists():
        out.append(active)
    return out

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
        if Path(key).parent == tape_dir and Path(key).exists()
    }
    target = _tape_cache_file(tape_dir)
    try:
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        pass
