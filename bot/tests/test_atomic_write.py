"""Safe atomic-write helper: unique temps, no torn targets, errors surface.

Covers the PR #78 follow-up: api/live_records/risk shared a fixed
`<name>.tmp` temp across processes, so overlapping writes could replace
or tear each other's temp file.
"""

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.atomic_write import atomic_write_json, atomic_write_text


class TestAtomicWriteHelper(unittest.TestCase):
    def test_round_trip_json_and_text(self):
        with tempfile.TemporaryDirectory() as td:
            jp = Path(td) / "state.json"
            atomic_write_json(jp, {"a": 1, "fills": []})
            self.assertEqual(json.loads(jp.read_text()), {"a": 1, "fills": []})
            tp = Path(td) / "note.txt"
            atomic_write_text(tp, "hello")
            self.assertEqual(tp.read_text(), "hello")

    def test_never_uses_fixed_shared_tmp_name(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "state.json"
            seen = []
            real_replace = os.replace

            def spy_replace(src, dst):
                seen.append(Path(src).name)
                return real_replace(src, dst)

            with patch("bot.atomic_write.os.replace", side_effect=spy_replace):
                atomic_write_json(target, {"n": 1})
                atomic_write_json(target, {"n": 2})
            self.assertEqual(len(seen), 2)
            self.assertNotIn("state.json.tmp", seen)
            self.assertNotEqual(seen[0], seen[1])
            self.assertEqual(
                [p.name for p in Path(td).glob("*.tmp")],
                [],
                "no temp files may be left behind",
            )

    def test_failed_replace_raises_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "config.json"
            target.write_text(json.dumps({"v": "old"}))
            with patch("bot.atomic_write.os.replace", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    atomic_write_json(target, {"v": "new"})
            # Target untouched, no temp litter.
            self.assertEqual(json.loads(target.read_text()), {"v": "old"})
            self.assertEqual(list(Path(td).glob("*.tmp")), [])

    def test_concurrent_writes_to_different_files_all_land(self):
        # Real topology: the API writes config/state while the loop writes
        # state -- different files, overlapping in time. Unique temp names
        # mean neither writer clobbers the other's temp.
        with tempfile.TemporaryDirectory() as td:
            errors = []

            def worker(n):
                try:
                    for _ in range(10):
                        atomic_write_json(Path(td) / f"f{n}.json", {"n": n})
                except Exception as ex:  # pragma: no cover
                    errors.append(ex)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
            self.assertEqual(errors, [])
            for i in range(8):
                self.assertEqual(
                    json.loads((Path(td) / f"f{i}.json").read_text()), {"n": i}
                )
            self.assertEqual(list(Path(td).glob("*.tmp")), [])


class TestAtomicWriteCallers(unittest.TestCase):
    def test_live_records_wrapper_persists(self):
        from bot.live_records import atomic_write_json_pure

        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "win.json"
            atomic_write_json_pure(target, {"slug": "w"})
            self.assertEqual(json.loads(target.read_text()), {"slug": "w"})
            self.assertEqual(list(Path(td).glob("*.tmp")), [])

    def test_risk_heartbeat_updates_without_fixed_tmp(self):
        import time

        from bot.risk import heartbeat

        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "state.json"
            target.write_text(json.dumps({"updatedAtMs": 1}))
            heartbeat(target)
            data = json.loads(target.read_text())
            self.assertGreaterEqual(data["updatedAtMs"], int(time.time() * 1000) - 5000)
            self.assertEqual(list(Path(td).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
