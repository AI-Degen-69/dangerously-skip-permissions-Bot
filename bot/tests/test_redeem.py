"""Tests for paper redeem batch job and API integration."""

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from bot import api
from bot.redeem import execute_redeem, get_target_workspace, redeemable
from bot.runs import RunWorkspace


class RedeemTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.tmp = Path(self.td.name)
        self.runs_root = self.tmp / "runs"
        self.legacy_runs = self.tmp / "paper_runs"
        self.legacy_runs.mkdir(parents=True, exist_ok=True)
        self.events_path = self.tmp / "events.jsonl"

    def tearDown(self):
        self.td.cleanup()

    def _create_workspace(self, run_id: str = "run_test") -> RunWorkspace:
        ws = RunWorkspace(run_id, runs_root=self.runs_root)
        ws.init_workspace()
        return ws

    def test_get_target_workspace_validation(self):
        with patch("bot.redeem.WORKSPACES_DIR", self.runs_root):
            with self.assertRaises(ValueError):
                get_target_workspace("nonexistent_run")

        ws = self._create_workspace("run_valid")
        with patch("bot.redeem.WORKSPACES_DIR", self.runs_root), \
             patch("bot.redeem.get_active_run_id", return_value="run_valid"):
            resolved = get_target_workspace()
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved.run_id, "run_valid")

    def test_redeemable_in_run_workspace(self):
        ws = self._create_workspace()
        win_file = ws.windows_dir / "btc-updown-5m-100.json"
        win_file.write_text(json.dumps({
            "event_slug": "btc-updown-5m-100",
            "winner": "Up",
            "cost_usd": 15.0,
            "payout_usd": 30.0,
            "fills": [{"shares": 30.0, "outcome": "Up", "price": 0.5}],
        }))
        pending_file = ws.windows_dir / "btc-updown-5m-200.json"
        pending_file.write_text(json.dumps({
            "event_slug": "btc-updown-5m-200",
            "pending": True,
            "winner": None,
        }))
        already_redeemed = ws.windows_dir / "btc-updown-5m-300.json"
        already_redeemed.write_text(json.dumps({
            "event_slug": "btc-updown-5m-300",
            "winner": "Down",
            "redeemedAt": "2026-11-08T00:00:00Z",
        }))

        with patch("bot.redeem.WORKSPACES_DIR", self.runs_root), \
             patch("bot.redeem.get_active_run_id", return_value=ws.run_id):
            due = redeemable(ws.run_id)

        self.assertEqual(len(due), 1)
        self.assertEqual(due[0][1]["event_slug"], "btc-updown-5m-100")

    def test_execute_redeem_dry_run_leaves_files_unmodified(self):
        ws = self._create_workspace()
        win_file = ws.windows_dir / "btc-updown-5m-100.json"
        content = {
            "event_slug": "btc-updown-5m-100",
            "winner": "Up",
            "cost_usd": 15.0,
            "payout_usd": 30.0,
            "fills": [{"shares": 30.0, "outcome": "Up", "price": 0.5}],
        }
        win_file.write_text(json.dumps(content))

        with patch("bot.redeem.WORKSPACES_DIR", self.runs_root), \
             patch("bot.redeem.get_active_run_id", return_value=ws.run_id):
            res = execute_redeem(run_id=ws.run_id, dry_run=True)

        self.assertTrue(res["ok"])
        self.assertEqual(res["redeemedCount"], 1)
        self.assertEqual(res["payoutUsd"], 30.0)
        # Verify file on disk has NOT been modified
        disk_data = json.loads(win_file.read_text())
        self.assertNotIn("redeemedAt", disk_data)

    def test_execute_redeem_mutates_files_and_syncs_legacy(self):
        ws = self._create_workspace()
        win_file = ws.windows_dir / "btc-updown-5m-100.json"
        content = {
            "event_slug": "btc-updown-5m-100",
            "winner": "Up",
            "cost_usd": 15.0,
            "payout_usd": 30.0,
            "fills": [{"shares": 30.0, "outcome": "Up", "price": 0.5}],
        }
        win_file.write_text(json.dumps(content))

        # Also place matching file in legacy folder
        legacy_file = self.legacy_runs / "btc-updown-5m-100.json"
        legacy_file.write_text(json.dumps(content))

        # Zero-payout losing window
        loss_file = ws.windows_dir / "btc-updown-5m-101.json"
        loss_file.write_text(json.dumps({
            "event_slug": "btc-updown-5m-101",
            "winner": "Down",
            "cost_usd": 10.0,
            "payout_usd": 0.0,
            "fills": [{"shares": 20.0, "outcome": "Up", "price": 0.5}],
        }))

        with patch("bot.redeem.WORKSPACES_DIR", self.runs_root), \
             patch("bot.redeem.get_active_run_id", return_value=ws.run_id), \
             patch("bot.redeem.RUNS_DIR", self.legacy_runs), \
             patch("bot.redeem.EVENTS_PATH", self.events_path):
            res = execute_redeem(run_id=ws.run_id, dry_run=False)

        self.assertTrue(res["ok"])
        self.assertEqual(res["redeemedCount"], 1)
        self.assertEqual(res["zeroCleanCount"], 1)
        self.assertEqual(res["payoutUsd"], 30.0)

        # Check primary file was updated
        primary_data = json.loads(win_file.read_text())
        self.assertIn("redeemedAt", primary_data)

        # Check legacy file was synced for active run
        legacy_data = json.loads(legacy_file.read_text())
        self.assertIn("redeemedAt", legacy_data)

        # Check losing file marked clean
        loss_data = json.loads(loss_file.read_text())
        self.assertIn("redeemedAt", loss_data)

        # Check event was written to workspace events file
        self.assertTrue(ws.events_file.exists())
        events = [json.loads(line) for line in ws.events_file.read_text().splitlines() if line]
        redeem_events = [e for e in events if e.get("kind") == "redeem"]
        self.assertEqual(len(redeem_events), 1)
        self.assertEqual(redeem_events[0]["detail"]["payout"], 30.0)

    def test_execute_redeem_historical_does_not_sync_legacy(self):
        ws = self._create_workspace("run_historical")
        win_file = ws.windows_dir / "btc-updown-5m-100.json"
        win_file.write_text(json.dumps({
            "event_slug": "btc-updown-5m-100",
            "winner": "Up",
            "cost_usd": 15.0,
            "payout_usd": 30.0,
            "fills": [{"shares": 30.0, "outcome": "Up", "price": 0.5}],
        }))

        # Legacy file belongs to active run, not historical
        legacy_file = self.legacy_runs / "btc-updown-5m-100.json"
        legacy_file.write_text(json.dumps({"old": True}))

        with patch("bot.redeem.WORKSPACES_DIR", self.runs_root), \
             patch("bot.redeem.get_active_run_id", return_value="run_active_different"), \
             patch("bot.redeem.RUNS_DIR", self.legacy_runs), \
             patch("bot.redeem.EVENTS_PATH", self.events_path):
            res = execute_redeem(run_id="run_historical", dry_run=False)

        self.assertTrue(res["ok"])
        legacy_data = json.loads(legacy_file.read_text())
        self.assertNotIn("redeemedAt", legacy_data)
        self.assertTrue(legacy_data.get("old"))

    def test_execute_redeem_skips_invalid_windows(self):
        ws = self._create_workspace()
        corrupt_file = ws.windows_dir / "btc-updown-5m-999.json"
        corrupt_file.write_text(json.dumps({
            "event_slug": "btc-updown-5m-999",
            "winner": "Up",
            "cost_usd": 15.0,
            "payout_usd": -50.0,  # Negative payout invalid
            "fills": [],
        }))

        with patch("bot.redeem.WORKSPACES_DIR", self.runs_root), \
             patch("bot.redeem.get_active_run_id", return_value=ws.run_id):
            res = execute_redeem(run_id=ws.run_id, dry_run=False)

        self.assertEqual(res["redeemedCount"], 0)
        self.assertEqual(len(res["warnings"]), 1)
        corrupt_data = json.loads(corrupt_file.read_text())
        self.assertNotIn("redeemedAt", corrupt_data)

    def test_execute_redeem_csv_output(self):
        ws = self._create_workspace()
        win_file = ws.windows_dir / "btc-updown-5m-100.json"
        win_file.write_text(json.dumps({
            "event_slug": "btc-updown-5m-100",
            "winner": "Up",
            "cost_usd": 15.0,
            "payout_usd": 30.0,
            "fills": [{"shares": 30.0, "outcome": "Up", "price": 0.5}],
        }))
        csv_file = self.tmp / "test_out.csv"

        with patch("bot.redeem.WORKSPACES_DIR", self.runs_root), \
             patch("bot.redeem.get_active_run_id", return_value=ws.run_id), \
             patch("bot.redeem.RUNS_DIR", self.legacy_runs), \
             patch("bot.redeem.EVENTS_PATH", self.events_path):
            res = execute_redeem(run_id=ws.run_id, dry_run=False, csv_path=str(csv_file))

        self.assertTrue(csv_file.exists())
        with csv_file.open(newline="") as f:
            reader = list(csv.reader(f))
        self.assertEqual(len(reader), 2)  # header + 1 row
        self.assertEqual(reader[1][2], "REDEEM")
        self.assertEqual(reader[1][4], "Up")
        self.assertEqual(float(reader[1][8]), 30.0)

    def test_api_redeem_endpoint(self):
        mock_result = {
            "ok": True,
            "redeemedCount": 2,
            "payoutUsd": 55.0,
            "redeemedAt": "2026-11-08T22:00:00Z",
        }

        handler = api.Handler.__new__(api.Handler)
        handler.path = "/api/bot/redeem"
        handler._body = lambda: {}
        handler._send = MagicMock()

        with patch.object(api, "is_view_only", return_value=False), \
             patch.object(api, "get_selected_run_id", return_value="run_test"), \
             patch("bot.redeem.execute_redeem", return_value=mock_result) as mock_exec:
            handler.do_POST()

        mock_exec.assert_called_once_with(run_id="run_test", dry_run=False)
        handler._send.assert_called_once_with(200, mock_result)

    def test_api_redeem_endpoint_view_only_blocked(self):
        handler = api.Handler.__new__(api.Handler)
        handler.path = "/api/bot/redeem"
        handler._body = lambda: {}
        handler._send = MagicMock()

        with patch.object(api, "is_view_only", return_value=True):
            handler.do_POST()

        handler._send.assert_called_once()
        self.assertEqual(handler._send.call_args[0][0], 400)
        self.assertTrue(handler._send.call_args[0][1].get("isViewOnly"))

    def test_perf_unredeemed_ignores_losing_windows(self):
        # Window that resolved Down, but bot only held Up shares (0 payout)
        losing_window = {
            "event_slug": "btc-updown-5m-001",
            "winner": "Down",
            "cost_usd": 15.0,
            "payout_usd": 0.0,
            "net_usd": -15.0,
            "fills": [{"shares": 30.0, "outcome": "Up", "price": 0.5}],
        }
        with patch.object(api, "runs", return_value=[losing_window]), \
             patch.object(api, "state", return_value=None), \
             patch.object(api, "loop_running", return_value=None), \
             patch.object(api, "load_config", return_value={"bankrollUsd": 1000.0}), \
             patch.object(api, "get_selected_run_id", return_value=None), \
             patch.object(api, "KILL_PATH") as kill_path:
            kill_path.exists.return_value = False
            p = api.perf()

        self.assertEqual(p["redeem"]["count"], 0)
        self.assertEqual(p["redeem"]["payoutUsd"], 0.0)
        self.assertFalse(any("unredeemed" in note["title"] for note in p["notes"]))


if __name__ == "__main__":
    unittest.main()
