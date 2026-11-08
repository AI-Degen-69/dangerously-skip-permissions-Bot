"""Unit tests for run-scoped sessions and view-only safety."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from bot import api
from bot.runs import (
    RunWorkspace,
    get_active_run_id,
    list_all_runs,
    make_run_id,
    set_active_run_id,
)


class TestRunScopedSessions(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.orig_runs_dir = api.RUNS_DIR

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        api.set_selected_run_id(None)
        set_active_run_id(None)

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


if __name__ == "__main__":
    unittest.main()
