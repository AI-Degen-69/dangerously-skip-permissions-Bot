"""Streamer trade-print observation path and tape rotation."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from .ws_models import TradePrint


# Tape rotation. The recorder appends continuously (book depth alone reached
# 5.4 GB in a day), so the active file is capped by size and archived as
# `<stem>.<epoch>.jsonl`; archives are pruned by age and count to keep the run
# directory bounded. Verification only needs prints from the current window, and
# readers walk segments oldest-first, so archived prints stay usable.
TAPE_SEGMENT_BYTES = {"prints": 32 * 1024 * 1024, "book": 128 * 1024 * 1024}
TAPE_ARCHIVE_BYTES = {"prints": 64 * 1024 * 1024, "book": 1024 * 1024 * 1024}
TAPE_RETENTION_S = 12 * 3600
TAPE_MAX_ARCHIVES = 12


def _tape_setting(name: str):
    """Resolve a TAPE_* limit through the ``bot.ws`` shell namespace.

    ``bot/tests/test_tape.py`` rebinds these via ``patch.object(ws, ...)`` on
    the shell module (same pattern as the executor's dynamic sizing lookup),
    so reads must follow the shell attribute, falling back to this module's
    global when the shell is not imported (e.g. ``python -m bot.ws`` runs the
    shell as ``__main__``).
    """
    shell = sys.modules.get("bot.ws")
    if shell is not None and hasattr(shell, name):
        return getattr(shell, name)
    return globals()[name]


class StreamerTapeMixin:
    """Trade-print handling and size/age/count-capped tape rotation."""

    def _parse_print_ts(self, raw: object) -> tuple:
        try:
            ms = int(str(raw))
            return (ms / 1000.0, str(raw))
        except Exception:
            now = time.time()
            return (now, str(raw) if raw else '')

    def _append_tape_line(self, kind: str, record: dict) -> None:
        if self.tape_dir is None:
            return
        try:
            self.tape_dir.mkdir(parents=True, exist_ok=True)
            fname = 'prints.jsonl' if kind == 'prints' else 'book.jsonl'
            path = self.tape_dir / fname
            self._rotate_tape(kind, path)
            with path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(record) + chr(10))
        except Exception:
            pass

    def _rotate_tape(self, kind: str, path: Path) -> None:
        """Archive the active segment once it reaches its cap, then prune old ones."""
        limit = TAPE_SEGMENT_BYTES.get(kind)
        if not limit or not path.exists() or path.stat().st_size < limit:
            return
        path.replace(self.tape_dir / f"{path.stem}.{int(time.time())}{path.suffix}")
        self._prune_tape(kind, path.stem, path.suffix)

    def _prune_tape(self, kind: str, stem: str, suffix: str = '.jsonl') -> None:
        """Drop archives past retention, past the count cap, or past the size budget."""
        archived: list[tuple[int, Path]] = []
        for seg in self.tape_dir.glob(f"{stem}.*{suffix}"):
            part = seg.name[len(stem) + 1 : -len(suffix)]
            if part.isdigit():
                archived.append((int(part), seg))
        archived.sort(key=lambda item: item[0])
        cutoff = time.time() - _tape_setting("TAPE_RETENTION_S")
        for ts, seg in list(archived):
            if ts < cutoff:
                seg.unlink(missing_ok=True)
                archived.remove((ts, seg))
        budget = _tape_setting("TAPE_ARCHIVE_BYTES").get(kind)
        while archived and (
            len(archived) > _tape_setting("TAPE_MAX_ARCHIVES")
            or (budget is not None and self._archive_bytes(archived) > budget)
        ):
            archived.pop(0)[1].unlink(missing_ok=True)

    @staticmethod
    def _archive_bytes(archived: list[tuple[int, Path]]) -> int:
        total = 0
        for _, seg in archived:
            try:
                total += seg.stat().st_size
            except OSError:
                continue
        return total

    def _handle_trade_print(self, item: dict) -> None:
        asset_id = str(item.get('asset_id', ''))
        if asset_id not in self.books:
            return
        try:
            price = float(item.get('price', 0.0))
            size = float(item.get('size', 0.0))
        except Exception:
            return
        if not (0.0 < price < 1.0 and size > 0):
            return
        side = str(item.get('side', '')).upper() or 'UNKNOWN'
        ts, raw = self._parse_print_ts(item.get('timestamp'))
        pr = TradePrint(ts=ts, asset_id=asset_id, price=price, size=size, side=side, timestamp_raw=raw, fee_rate_bps=str(item.get('fee_rate_bps', '')), market=str(item.get('market', '')))
        with self._lock:
            self.prints.append(pr)
            self.print_count += 1
            self.last_print_ts = ts
        if self.enable_trade_prints and self.tape_dir is not None:
            rec = dict(pr.to_dict())
            rec['slug_outcome'] = self.books[asset_id].outcome
            self._append_tape_line('prints', rec)
        cb = self.on_print
        if cb is not None:
            try:
                cb(pr)
            except Exception:
                pass

    def _maybe_append_book_tape(self, asset_id: str) -> None:
        if not self.enable_trade_prints or self.tape_dir is None:
            return
        if asset_id not in self.books:
            return
        top = self.depth(asset_id, levels=5)
        flat = json.dumps(top, sort_keys=True)
        if self._last_book_line.get(asset_id) == flat:
            return
        self._last_book_line[asset_id] = flat
        book = self.books[asset_id]
        self._append_tape_line('book', {'ts': book.last_update_ts, 'asset_id': asset_id, 'outcome': book.outcome, 'bids': top['bids'], 'asks': top['asks']})
