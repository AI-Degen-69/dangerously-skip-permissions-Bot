"""Redemption is owned by each run's workspace file, never the shared mirror.

Regression tests for the PR #78 follow-up: runs A and B holding the same
window filename must not leak redemption into each other through the
shared windows mirror.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.redeem import execute_redeem
from bot.runs import RunWorkspace


def _window(slug, winner="Up", redeemed_at=None):
    d = {
        "event_slug": slug,
        "winner": winner,
        "cost_usd": 15.0,
        "payout_usd": 30.0,
        "fills": [{"shares": 30.0, "outcome": winner, "price": 0.5}],
    }
    if redeemed_at is not None:
        d["redeemedAt"] = redeemed_at
    return d


class TestMirrorSyncOwnership(unittest.TestCase):
    def test_sync_never_copies_mirror_redemption_into_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            mirror = td / "mirror"
            mirror.mkdir()
            # Mirror holds run A's redeemed copy of the window...
            mirror.joinpath("w.json").write_text(
                json.dumps(_window("w", redeemed_at="2026-01-01T00:00:00Z"))
            )
            # ...while run B's own file is unredeemed.
            ws_b = RunWorkspace("run_b", runs_root=td)
            ws_b.init_workspace()
            ws_b.windows_dir.joinpath("w.json").write_text(json.dumps(_window("w")))

            ws_b.sync_windows_mirror(mirror)

            # B's file untouched: no redemption leaked in.
            b_data = json.loads(ws_b.windows_dir.joinpath("w.json").read_text())
            self.assertNotIn("redeemedAt", b_data)
            self.assertNotIn("redeemed", b_data)
            # Mirror now reflects B (unredeemed), not A.
            m_data = json.loads(mirror.joinpath("w.json").read_text())
            self.assertNotIn("redeemedAt", m_data)


class TestRedeemOwnership(unittest.TestCase):
    def _roots(self, td):
        return Path(td) / "runs"

    def test_historical_redeem_leaves_mirror_and_other_runs_alone(self):
        with tempfile.TemporaryDirectory() as td:
            runs_root = self._roots(td)
            mirror = Path(td) / "mirror"
            mirror.mkdir()
            # Mirror holds run A's redeemed window (same filename).
            mirror.joinpath("w.json").write_text(
                json.dumps(_window("w", redeemed_at="2026-01-01T00:00:00Z"))
            )
            ws_b = RunWorkspace("run_b", runs_root=runs_root)
            ws_b.init_workspace()
            ws_b.windows_dir.joinpath("w.json").write_text(json.dumps(_window("w")))
            ws_c = RunWorkspace("run_c", runs_root=runs_root)
            ws_c.init_workspace()

            with patch("bot.redeem.WORKSPACES_DIR", runs_root), patch(
                "bot.redeem.get_active_run_id", return_value="run_c"
            ), patch("bot.redeem.WINDOWS_MIRROR_DIR", mirror):
                res = execute_redeem(run_id="run_b", dry_run=False)

            self.assertEqual(res["redeemedCount"], 1)
            # B's own file redeemed with a fresh timestamp...
            b_data = json.loads(ws_b.windows_dir.joinpath("w.json").read_text())
            self.assertIn("redeemedAt", b_data)
            # ...but the mirror still carries A's original redemption.
            m_data = json.loads(mirror.joinpath("w.json").read_text())
            self.assertEqual(m_data["redeemedAt"], "2026-01-01T00:00:00Z")

    def test_legacy_redeem_does_not_touch_active_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            runs_root = self._roots(td)
            mirror = Path(td) / "mirror"
            mirror.mkdir()
            mirror.joinpath("w.json").write_text(json.dumps(_window("w")))
            ws_a = RunWorkspace("run_a", runs_root=runs_root)
            ws_a.init_workspace()
            ws_a.windows_dir.joinpath("w.json").write_text(json.dumps(_window("w")))
            events = Path(td) / "events.jsonl"

            with patch("bot.redeem.WORKSPACES_DIR", runs_root), patch(
                "bot.redeem.get_active_run_id", return_value="run_a"
            ), patch("bot.redeem.WINDOWS_MIRROR_DIR", mirror), patch(
                "bot.redeem.EVENTS_PATH", events
            ):
                res = execute_redeem(run_id="legacy", dry_run=False)

            self.assertEqual(res["redeemedCount"], 1)
            # Mirror file redeemed...
            self.assertIn(
                "redeemedAt", json.loads(mirror.joinpath("w.json").read_text())
            )
            # ...active run's own file untouched.
            a_data = json.loads(ws_a.windows_dir.joinpath("w.json").read_text())
            self.assertNotIn("redeemedAt", a_data)
            self.assertNotIn("redeemed", a_data)


if __name__ == "__main__":
    unittest.main()
