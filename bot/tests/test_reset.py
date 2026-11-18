"""Reset semantics: no stale windows/state survive POST /api/bot/reset.

Covers PR #78 follow-up issue: reset previously deleted only mirrored
windows plus the active state file, so runs()/state() could restore
pre-reset results. reset_paper_state() must clear the active workspace
windows dir too, and the fallback STATE_PATH when no workspace exists.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bot.api as api
from bot.runs import RunWorkspace


class TestResetPaperState(unittest.TestCase):
    def test_clears_active_workspace_windows_and_state(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            mirror = td / "mirror"
            mirror.mkdir()
            (mirror / "w1.json").write_text(json.dumps({"slug": "w1"}))
            (mirror / "w2.json").write_text(json.dumps({"slug": "w2"}))
            ws = RunWorkspace("run_reset_test", runs_root=td)
            ws.init_workspace()
            (ws.windows_dir / "win-a.json").write_text(json.dumps({"slug": "win-a"}))
            (ws.windows_dir / "win-b.json").write_text(json.dumps({"slug": "win-b"}))
            ws.state_path.write_text(json.dumps({"slug": "open", "fills": []}))
            with patch.object(api, "WINDOWS_MIRROR_DIR", mirror), patch.object(
                api, "resolve_run_workspace", return_value=ws
            ):
                cleared = api.reset_paper_state()
                self.assertEqual(cleared["mirror"], 2)
                self.assertEqual(cleared["workspace_windows"], 2)
                self.assertTrue(cleared["state"])
                self.assertEqual(list(mirror.glob("*.json")), [])
                self.assertEqual(list(ws.windows_dir.glob("*.json")), [])
                self.assertFalse(ws.state_path.exists())
                # Post-reset reads see nothing stale.
                self.assertEqual(api.runs(), [])
                self.assertIsNone(api.state())

    def test_clears_fallback_state_when_no_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            mirror = td / "mirror"
            mirror.mkdir()
            fallback = td / "state.json"
            fallback.write_text(json.dumps({"slug": "open", "fills": [{"minute": 0}]}))
            with patch.object(api, "WINDOWS_MIRROR_DIR", mirror), patch.object(
                api, "STATE_PATH", fallback
            ), patch.object(api, "resolve_run_workspace", return_value=None):
                cleared = api.reset_paper_state()
                self.assertTrue(cleared["state"])
                self.assertFalse(fallback.exists())
                self.assertIsNone(api.state())


if __name__ == "__main__":
    unittest.main()
