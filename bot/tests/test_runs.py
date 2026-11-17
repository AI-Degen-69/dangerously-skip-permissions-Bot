"""Unit tests for run-scoped sessions and view-only safety."""

import json
import shutil
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch
from pathlib import Path

from bot import api, runs
from bot.runs import (
    RunWorkspace,
    find_run_id,
    get_active_run_id,
    list_all_runs,
    make_run_id,
    migrate_windows_mirror,
    set_active_run_id,
)


class TestRunScopedSessions(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.orig_runs_dir = api.WINDOWS_MIRROR_DIR
        self.orig_runs_root = runs.RUNS_DIR
        self.orig_active_pointer = runs.ACTIVE_RUN_POINTER
        runs.RUNS_DIR = self.tmp
        runs.ACTIVE_RUN_POINTER = self.tmp / "active_run.json"

    def tearDown(self):
        set_active_run_id(None)
        api.set_selected_run_id(None)
        runs.RUNS_DIR = self.orig_runs_root
        runs.ACTIVE_RUN_POINTER = self.orig_active_pointer
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_make_run_id_format(self):
        rid = make_run_id(mode="paper", label="test")
        self.assertTrue(rid.startswith("run_"))
        self.assertIn("paper", rid)
        self.assertIn("test", rid)

    def test_run_workspace_lifecycle(self):
        ws = RunWorkspace("run_test_1", runs_root=self.tmp)
        self.assertFalse(ws.exists())
        meta = ws.init_workspace(config={"bankrollUsd": 1000}, mode="paper", label="unit")
        self.assertTrue(ws.exists())
        self.assertEqual(meta.status, "running")

        # add a window
        (ws.windows_dir / "btc-1.json").write_text(json.dumps({"trades": 45, "net_usd": 12.5}))
        windows = ws.list_windows()
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["trades"], 45)

        # finalize
        ws.finalize(status="completed", summary={"netUsd": 12.5})
        updated = ws.read_meta()
        self.assertEqual(updated.status, "completed")
        self.assertEqual(updated.summary.get("netUsd"), 12.5)

    def test_view_only_logic(self):
        set_active_run_id("run_active_100")
        api.set_selected_run_id(None)
        self.assertFalse(api.is_view_only())

        # Select same as active -> not view only
        api.set_selected_run_id("run_active_100")
        self.assertFalse(api.is_view_only())

        # Select older run -> view only!
        api.set_selected_run_id("run_past_050")
        self.assertTrue(api.is_view_only())

    def test_path_traversal_protection(self):
        # Traversal characters should be stripped or rejected
        with self.assertRaises(ValueError):
            RunWorkspace("../..", runs_root=self.tmp)

        with self.assertRaises(ValueError):
            RunWorkspace("", runs_root=self.tmp)

        # Sanitized ID should stay within runs_root
        ws = RunWorkspace("run_valid_1", runs_root=self.tmp)
        self.assertEqual(ws.run_id, "run_valid_1")
        self.assertTrue(str(ws.root).startswith(str(self.tmp.resolve())))

    def test_make_run_id_collision(self):
        id1 = make_run_id(mode="paper", label="coll", runs_root=self.tmp)
        (self.tmp / id1).mkdir(parents=True, exist_ok=True)
        id2 = make_run_id(mode="paper", label="coll", runs_root=self.tmp)
        self.assertNotEqual(id1, id2)
        self.assertTrue(id2.startswith(id1))

    def test_find_run_id_exact_and_substring(self):
        ws = RunWorkspace("run_20261108_083527_paper_default", runs_root=self.tmp)
        ws.init_workspace()
        self.assertEqual(runs.find_run_id("run_20261108_083527_paper_default", runs_root=self.tmp), "run_20261108_083527_paper_default")
        self.assertEqual(runs.find_run_id("083527", runs_root=self.tmp), "run_20261108_083527_paper_default")
        self.assertIsNone(runs.find_run_id("999999", runs_root=self.tmp))

    def test_init_workspace_preserves_started_at_when_resuming(self):
        ws = RunWorkspace("run_test_resume", runs_root=self.tmp)
        meta1 = ws.init_workspace()
        orig_started = meta1.started_at
        ws.finalize(status="interrupted")
        self.assertEqual(ws.read_meta().status, "interrupted")

        # Re-init / resume
        meta2 = ws.init_workspace()
        self.assertEqual(meta2.started_at, orig_started)
        self.assertEqual(meta2.status, "running")
        self.assertIsNone(meta2.ended_at)

    def test_sync_windows_mirror(self):
        ws = RunWorkspace("run_test_sync", runs_root=self.tmp)
        ws.init_workspace()
        (ws.windows_dir / "btc-1.json").write_text(json.dumps({"trades": 10}))
        (ws.windows_dir / "btc-2.json").write_text(json.dumps({"trades": 20}))

        mirror_dir = self.tmp / "active_windows_mirror"
        mirror_dir.mkdir(parents=True, exist_ok=True)
        (mirror_dir / "stale-other-run.json").write_text(json.dumps({"trades": 99}))

        count = ws.sync_windows_mirror(mirror_dir)
        self.assertEqual(count, 2)
        self.assertTrue((mirror_dir / "btc-1.json").exists())
        self.assertTrue((mirror_dir / "btc-2.json").exists())
        self.assertFalse((mirror_dir / "stale-other-run.json").exists())

    def test_resume_run_handler(self):
        from io import BytesIO
        ws_old = RunWorkspace("run_20261108_083527_paper_default", runs_root=self.tmp)
        ws_old.init_workspace()
        (ws_old.windows_dir / "btc-1.json").write_text(json.dumps({"trades": 10}))

        set_active_run_id("run_other_111")
        api.set_selected_run_id(ws_old.run_id)
        self.assertTrue(api.is_view_only())

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

        handler = DummyHandler("/api/bot/resume-run", {"runId": "083527"})
        with patch.object(api, "stop_loop_process", return_value=None), \
             patch.object(api, "start_loop_process", return_value=12345), \
             patch.object(api, "find_run_id", return_value=ws_old.run_id), \
             patch.object(api, "RunWorkspace", side_effect=lambda rid: RunWorkspace(rid, runs_root=self.tmp)), \
             patch.object(api, "WINDOWS_MIRROR_DIR", self.tmp / "windows_mirror"), \
             patch.object(api, "EVENTS_PATH", self.tmp / "events.jsonl"), \
             patch.object(api, "STATE_PATH", self.tmp / "state.json"), \
             patch.object(api, "KILL_PATH", self.tmp / "kill"):
            handler.do_POST()
            self.assertEqual(handler.sent_status, 200)
            self.assertEqual(handler.sent_data["runId"], ws_old.run_id)
            self.assertEqual(handler.sent_data["running"], True)
            self.assertEqual(handler.sent_data["isViewOnly"], False)
            self.assertEqual(get_active_run_id(), ws_old.run_id)
            self.assertFalse(api.is_view_only())

    def test_preserve_starting_capital(self):
        ws = RunWorkspace("run_test_capital", runs_root=self.tmp)
        meta = ws.init_workspace(config={"bankrollUsd": 1000.0, "riskPct": 1.0})
        self.assertEqual(meta.config_snapshot["bankrollUsd"], 1000.0)

        # Reopen with updated config that has different capital
        meta_resumed = ws.init_workspace(config={"bankrollUsd": 2500.0, "riskPct": 2.0})
        # Original bankrollUsd must be preserved
        self.assertEqual(meta_resumed.config_snapshot["bankrollUsd"], 1000.0)
        self.assertEqual(meta_resumed.config_snapshot["riskPct"], 2.0)

    def test_sync_preserves_redemption(self):
        ws = RunWorkspace("run_test_redemption", runs_root=self.tmp)
        ws.init_workspace()
        win_file = ws.windows_dir / "settled_window_1.json"
        win_file.write_text(json.dumps({"slug": "btc-1", "net_usd": 15.0}), encoding="utf-8")

        dest_dir = self.tmp / "windows_mirror"
        dest_dir.mkdir(parents=True, exist_ok=True)
        # Destination already redeemed
        (dest_dir / "settled_window_1.json").write_text(
            json.dumps({"slug": "btc-1", "net_usd": 15.0, "redeemed": True, "redeemedAt": "2026-11-08T10:00:00Z"}),
            encoding="utf-8"
        )

        ws.sync_windows_mirror(dest_dir)
        # Check source was updated with redemption info
        src_data = json.loads(win_file.read_text(encoding="utf-8"))
        self.assertTrue(src_data.get("redeemed"))
        self.assertEqual(src_data.get("redeemedAt"), "2026-11-08T10:00:00Z")

    def test_find_run_id_rejects_path_traversal(self):
        self.assertIsNone(find_run_id("../secret", runs_root=self.tmp))
        self.assertIsNone(find_run_id("foo/bar", runs_root=self.tmp))
        self.assertIsNone(find_run_id("..\\win", runs_root=self.tmp))

    def test_start_rejects_unknown_run(self):
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

        handler = DummyHandler("/api/bot/start", {"runId": "nonexistent_run_999"})
        with patch.object(api, "find_run_id", return_value=None):
            handler.do_POST()
            self.assertEqual(handler.sent_status, 404)
            self.assertIn("error", handler.sent_data)

    def test_session_label_from_strategy_symbol(self):
        self.assertEqual(api.session_label({"strategy": {"symbol": "⚡ DSP-v2.6"}}), "dsp_v2_6")
        self.assertEqual(api.session_label({"strategy": {"symbol": "🎯 HAPCS-v1"}}), "hapcs_v1")
        self.assertEqual(api.session_label({}), "default")

    def test_start_new_session_creates_fresh_run(self):
        ws_old = RunWorkspace("run_20261108_083527_paper_default", runs_root=self.tmp)
        ws_old.init_workspace()
        set_active_run_id(ws_old.run_id)
        (self.tmp / "events.jsonl").write_text('{"kind": "entry"}\n')

        class DummyHandler(api.Handler):
            def __init__(self, path, body):
                self.path = path
                self.sent_status = None
                self.sent_data = None
                self._payload = body
            def _body(self):
                return self._payload
            def _send(self, status, payload):
                self.sent_status = status
                self.sent_data = payload

        new_id = "run_20261110_000000_paper_dsp_v2_6"
        handler = DummyHandler("/api/bot/start", {"newSession": True})
        with patch.object(api, "stop_loop_process", return_value=None), \
             patch.object(api, "start_loop_process", return_value=4242) as start_mock, \
             patch.object(api, "load_config", return_value={"strategy": {"symbol": "⚡ DSP-v2.6"}}), \
             patch.object(api, "make_run_id", return_value=new_id) as make_mock, \
             patch.object(api, "RunWorkspace", side_effect=lambda rid: RunWorkspace(rid, runs_root=self.tmp)), \
             patch.object(api, "WINDOWS_MIRROR_DIR", self.tmp / "windows_mirror"), \
             patch.object(api, "EVENTS_PATH", self.tmp / "events.jsonl"), \
             patch.object(api, "STATE_PATH", self.tmp / "state.json"), \
             patch.object(api, "KILL_PATH", self.tmp / "kill"):
            handler.do_POST()

        self.assertEqual(handler.sent_status, 200)
        self.assertEqual(handler.sent_data["runId"], new_id)
        make_mock.assert_called_once_with(mode="paper", label="dsp_v2_6")
        start_mock.assert_called_once_with(run_id=new_id)
        self.assertEqual(get_active_run_id(), new_id)
        meta = RunWorkspace(new_id, runs_root=self.tmp).read_meta()
        self.assertEqual(meta.label, "dsp_v2_6")
        self.assertEqual(meta.config_snapshot["strategy"]["symbol"], "⚡ DSP-v2.6")
        # Fresh session starts with an empty event journal.
        self.assertFalse((self.tmp / "events.jsonl").exists())


class TestMigrateWindowsMirror(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = self.tmp / "old_windows"
        self.new = self.tmp / "new_windows"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed(self, folder: Path, name: str = "w.json", body: str = '{"a": 1}') -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_text(body, encoding="utf-8")
        return path

    def test_old_only_is_moved_and_keeps_files(self):
        seed = self._seed(self.old)
        body = seed.read_text(encoding="utf-8")

        self.assertEqual(migrate_windows_mirror(self.old, self.new), "moved")
        self.assertFalse(self.old.exists())
        self.assertEqual((self.new / "w.json").read_text(encoding="utf-8"), body)

    def test_both_existing_are_left_unchanged(self):
        self._seed(self.old, "old.json", '{"old": 1}')
        self._seed(self.new, "new.json", '{"new": 1}')

        with self.assertLogs("bot.runs", level="WARNING") as logs:
            self.assertEqual(migrate_windows_mirror(self.old, self.new), "both-exist")

        self.assertTrue((self.old / "old.json").exists())
        self.assertTrue((self.new / "new.json").exists())
        message = "\n".join(logs.output)
        self.assertIn(str(self.old), message)
        self.assertIn(str(self.new), message)

    def test_neither_folder_does_nothing(self):
        self.assertEqual(migrate_windows_mirror(self.old, self.new), "absent")
        self.assertFalse(self.old.exists())
        self.assertFalse(self.new.exists())

    def test_new_only_does_nothing(self):
        self._seed(self.new)
        self.assertEqual(migrate_windows_mirror(self.old, self.new), "absent")
        self.assertTrue((self.new / "w.json").exists())

    def test_oserror_leaves_old_files_and_does_not_raise(self):
        seed = self._seed(self.old)

        with patch.object(Path, "replace", side_effect=OSError("boom")):
            with self.assertLogs("bot.runs", level="WARNING"):
                self.assertEqual(migrate_windows_mirror(self.old, self.new), "error")

        self.assertTrue(seed.exists())
        self.assertFalse(self.new.exists())

    def test_second_call_after_move_is_a_noop(self):
        self._seed(self.old)
        self.assertEqual(migrate_windows_mirror(self.old, self.new), "moved")
        self.assertEqual(migrate_windows_mirror(self.old, self.new), "absent")
        self.assertTrue((self.new / "w.json").exists())


if __name__ == "__main__":
    unittest.main()
