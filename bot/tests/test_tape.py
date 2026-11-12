"""Unit tests for the #35 trade-print tape wiring (run-scoped files + desk toggle)."""

import json
import shutil
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from bot import api, live_paper, runs
from bot.runs import RunWorkspace


class DummyHandler(api.Handler):
    def __init__(self, path, body):
        self.path = path
        self.rfile = BytesIO(json.dumps(body).encode())
        self.headers = {"Content-Length": str(len(json.dumps(body)))}
        self.wfile = BytesIO()
        self.sent_status = None
        self.sent_data = None

    def _send(self, status, payload):
        self.sent_status = status
        self.sent_data = payload


class TestTapeStats(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ws = RunWorkspace("run_tape_unit", runs_root=self.tmp)
        self.ws.init_workspace(config={}, mode="paper", label="unit")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_tape_reports_zeros(self):
        stats = self.ws.tape_stats()
        self.assertEqual(stats["prints"], 0)
        self.assertEqual(stats["books"], 0)
        self.assertEqual(stats["mb"], 0.0)
        self.assertTrue(stats["tapeDir"].endswith("tape"))

    def test_counts_lines_and_bytes(self):
        self.ws.tape_dir.mkdir(parents=True, exist_ok=True)
        (self.ws.tape_dir / "prints.jsonl").write_text(
            '{"price": 0.2}\n{"price": 0.19}\n', encoding="utf-8"
        )
        (self.ws.tape_dir / "book.jsonl").write_text(
            '{"bids": []}\n', encoding="utf-8"
        )
        stats = self.ws.tape_stats()
        self.assertEqual(stats["prints"], 2)
        self.assertEqual(stats["books"], 1)
        self.assertGreater(stats["printsBytes"], 0)
        self.assertGreater(stats["bookBytes"], 0)
        self.assertEqual(
            stats["mb"],
            round((stats["printsBytes"] + stats["bookBytes"]) / (1024 * 1024), 4),
        )


class TestTapeStatsIncremental(unittest.TestCase):
    """tape_stats() must not re-read the whole file on every call."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ws = RunWorkspace("run_tape_inc", runs_root=self.tmp)
        self.ws.init_workspace(config={}, mode="paper", label="unit")
        self.ws.tape_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_appended_lines_are_added_not_recounted(self):
        book = self.ws.tape_dir / "book.jsonl"
        book.write_text('{"a": 1}\n', encoding="utf-8")
        self.assertEqual(self.ws.tape_stats()["books"], 1)
        with book.open("a", encoding="utf-8") as f:
            f.write('{"a": 2}\n{"a": 3}\n')
        self.assertEqual(self.ws.tape_stats()["books"], 3)

    def test_partial_line_is_not_counted_until_complete(self):
        prints = self.ws.tape_dir / "prints.jsonl"
        prints.write_text('{"p": 1}\n{"p": ', encoding="utf-8")
        self.assertEqual(self.ws.tape_stats()["prints"], 1)
        with prints.open("a", encoding="utf-8") as f:
            f.write('2}\n')
        self.assertEqual(self.ws.tape_stats()["prints"], 2)

    def test_truncated_file_is_recounted_from_zero(self):
        book = self.ws.tape_dir / "book.jsonl"
        book.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
        self.assertEqual(self.ws.tape_stats()["books"], 2)
        book.write_text('{"b": 1}\n', encoding="utf-8")
        self.assertEqual(self.ws.tape_stats()["books"], 1)

    def test_counts_are_reused_after_cache_is_dropped(self):
        book = self.ws.tape_dir / "book.jsonl"
        book.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
        self.assertEqual(self.ws.tape_stats()["books"], 2)
        # Simulate a fresh process: in-memory state gone, .tape_stats.json remains.
        runs._TAPE_COUNTS.clear()
        runs._TAPE_LOADED.clear()
        self.assertEqual(self.ws.tape_stats()["books"], 2)
        self.assertTrue((self.ws.tape_dir / ".tape_stats.json").exists())


class TestTapeDirIfEnabled(unittest.TestCase):
    def test_disabled_returns_none(self):
        with patch.object(live_paper, "load_cfg", return_value={"entry": {"tapeEnabled": False}}):
            self.assertIsNone(live_paper.tape_dir_if_enabled())

    def test_enabled_without_workspace_returns_none(self):
        with patch.object(live_paper, "load_cfg", return_value={"entry": {"tapeEnabled": True}}), \
             patch.object(live_paper, "get_current_workspace", return_value=None):
            self.assertIsNone(live_paper.tape_dir_if_enabled())

    def test_enabled_returns_run_tape_dir(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            ws = RunWorkspace("run_tape_live", runs_root=tmp)
            ws.init_workspace(config={}, mode="paper", label="unit")
            with patch.object(live_paper, "load_cfg", return_value={"entry": {"tapeEnabled": True}}), \
                 patch.object(live_paper, "get_current_workspace", return_value=ws):
                td = live_paper.tape_dir_if_enabled()
            self.assertEqual(td, ws.tape_dir)
            self.assertTrue(ws.tape_dir.exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestTapeEndpoints(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg_path = self.tmp / "config.json"
        self.cfg_path.write_text(json.dumps({"entry": {}}), encoding="utf-8")
        self.ws = RunWorkspace("run_tape_api", runs_root=self.tmp)
        self.ws.init_workspace(config={}, mode="paper", label="unit")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patch(self):
        return (
            patch.object(api, "CONFIG_PATH", self.cfg_path),
            patch.object(api, "EVENTS_PATH", self.tmp / "events.jsonl"),
            patch.object(api, "get_active_run_id", return_value=None),
            patch.object(api, "resolve_run_workspace", return_value=self.ws),
        )

    def test_post_rejects_non_bool(self):
        handler = DummyHandler("/api/bot/tape", {"enabled": "yes"})
        p1, p2, p3, p4 = self._patch()
        with p1, p2, p3, p4:
            handler.do_POST()
        self.assertEqual(handler.sent_status, 400)

    def test_post_toggles_config(self):
        handler = DummyHandler("/api/bot/tape", {"enabled": True})
        p1, p2, p3, p4 = self._patch()
        with p1, p2, p3, p4:
            handler.do_POST()
        self.assertEqual(handler.sent_status, 200)
        self.assertTrue(handler.sent_data["enabled"])
        cfg = json.loads(self.cfg_path.read_text(encoding="utf-8"))
        self.assertTrue(cfg["entry"]["tapeEnabled"])

    def test_get_returns_status_shape(self):
        handler = DummyHandler("/api/bot/tape", {})
        p1, p2, p3, p4 = self._patch()
        with p1, p2, p3, p4:
            handler.do_GET()
        self.assertEqual(handler.sent_status, 200)
        for key in ("enabled", "runId", "tapeDir", "prints", "books", "mb"):
            self.assertIn(key, handler.sent_data)


if __name__ == "__main__":
    unittest.main()
