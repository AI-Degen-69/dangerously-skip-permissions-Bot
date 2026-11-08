"""Desk fidelity/performance aggregation (`GET /api/bot/perf`)."""

import unittest
from unittest.mock import patch

from bot import api

SLUG = "btc-updown-5m-1794082800"

FILLS = [
    {"minute": 0, "outcome": "Up", "price": 0.50, "shares": 30.0, "usd": 15.0},
    {"minute": 1, "outcome": "Down", "price": 0.40, "shares": 14.0, "usd": 5.6},
    {"minute": 4, "outcome": "Up", "price": 0.0, "shares": 14.0, "usd": 0.0},
]


def paper_run(slug: str, fills: list[dict], winner: str | None) -> dict:
    """Shaped like bot/paper_runs/<slug>.json."""
    cost = round(sum(f["usd"] for f in fills), 2)
    won = sum(f["shares"] for f in fills if f["outcome"] == winner) if winner else 0.0
    payout = round(won, 2)
    run = {
        "event_slug": slug,
        "market": slug,
        "trades": len(fills),
        "cost_usd": cost,
        "payout_usd": payout,
        "net_usd": round(payout - cost, 2),
        "winner": winner,
        "fills": fills,
    }
    if winner is None:
        run["pending"] = True
    return run


class PerfTests(unittest.TestCase):
    def build(self, runs: list[dict], *, running: bool = False, killed: bool = False, state: dict | None = None) -> dict:
        with (
            patch.object(api, "runs", return_value=runs),
            patch.object(api, "state", return_value=state),
            patch.object(api, "loop_running", return_value=4321 if running else None),
            patch.object(api, "KILL_PATH") as kill_path,
        ):
            kill_path.exists.return_value = killed
            return api.perf()

    def test_settles_only_resolved_windows_and_scores_them(self):
        perf = self.build([paper_run(SLUG, FILLS, "Up")])
        summary = perf["summary"]

        self.assertEqual(summary["settled"], 1)
        self.assertEqual(summary["bankrollUsd"], 1000.0)
        self.assertEqual(summary["pending"], 0)
        self.assertEqual(summary["fills"], 3)
        self.assertAlmostEqual(summary["costUsd"], 20.6)
        self.assertAlmostEqual(summary["payoutUsd"], 44.0)
        self.assertAlmostEqual(summary["netUsd"], 23.4)
        self.assertEqual(summary["bothSides"], 1)
        self.assertEqual(summary["zeroPriceFills"], 1)
        self.assertEqual(perf["mShape"]["live"], [1, 1, 0, 0, 1])

    def test_pending_window_is_excluded_from_pnl(self):
        perf = self.build([paper_run(SLUG, FILLS, None)])

        self.assertEqual(perf["summary"]["settled"], 0)
        self.assertEqual(perf["summary"]["pending"], 1)
        self.assertEqual(perf["summary"]["netUsd"], 0)
        self.assertIsNone(perf["windows"][0]["netUsd"])

    def test_below_48_windows_every_metric_is_a_sample(self):
        perf = self.build([paper_run(SLUG, FILLS, "Up")])

        self.assertEqual(perf["gate"][0]["status"], "sample")
        self.assertTrue(all(row["status"] == "sample" for row in perf["gate"][1:]))
        self.assertTrue(any("Sample is 1/288 windows" == note["title"] for note in perf["notes"]))

    def test_redeem_queue_lists_unclaimed_winners(self):
        perf = self.build([paper_run(SLUG, FILLS, "Up")])

        self.assertEqual(perf["redeem"]["count"], 1)
        self.assertAlmostEqual(perf["redeem"]["payoutUsd"], 44.0)
        self.assertTrue(any("unredeemed" in note["title"] for note in perf["notes"]))

    def test_stopped_loop_is_reported(self):
        perf = self.build([], running=False)

        self.assertFalse(perf["health"]["loopRunning"])
        self.assertIn("Loop is stopped", [note["title"] for note in perf["notes"]])

    def test_kill_switch_is_reported(self):
        perf = self.build([], running=True, killed=True)

        self.assertTrue(perf["health"]["killSwitch"])
        self.assertIn("Kill switch engaged", [note["title"] for note in perf["notes"]])


if __name__ == "__main__":
    unittest.main()
