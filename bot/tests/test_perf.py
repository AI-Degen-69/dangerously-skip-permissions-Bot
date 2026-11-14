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
    def build(self, runs: list[dict], *, running: bool = False, killed: bool = False, state: dict | None = None, config: dict | None = None) -> dict:
        cfg = {"bankrollUsd": 1000.0} if config is None else config
        with (
            patch.object(api, "runs", return_value=runs),
            patch.object(api, "state", return_value=state),
            patch.object(api, "loop_running", return_value=4321 if running else None),
            patch.object(api, "load_config", return_value=cfg),
            patch.object(api, "get_selected_run_id", return_value=None),
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

    def test_execution_health_cells_measure_the_run_not_a_frozen_tape(self):
        # Every fill carries a queue verdict: one attainable, one phantom.
        fills = [
            {**FILLS[0], "detail": {"attainable": True}},
            {**FILLS[1], "detail": {"attainable": False}},
            FILLS[2],
        ]
        run = paper_run(SLUG, fills, "Up")
        run["fidelity"] = {
            "makerFills": 2, "attainableFills": 1, "phantomFills": 1,
            "queueKnown": 2, "assumedShares": 58.0, "attainableShares": 30.0,
            "attainableCostUsd": 15.0, "attainablePayoutUsd": 30.0, "attainableNetUsd": 15.0,
        }
        perf = self.build([run])
        cells = {c["key"]: c for c in perf["cells"]}

        # 30 Up shares at 50c plus 14 Down shares at 40c; the $0.00 Up fill holds nothing.
        self.assertEqual(cells["totalShares"]["value"], "44 sh")
        self.assertTrue(cells["totalShares"]["big"])
        self.assertEqual(cells["totalShares"]["sub"][0], {"label": "Up", "value": "30", "tone": None})
        self.assertEqual(cells["paired"]["value"], "1")
        self.assertEqual(cells["paired"]["status"], "pass")
        self.assertIn({"label": "Lock-in", "value": "90.0¢", "tone": None}, cells["paired"]["sub"])
        self.assertEqual(cells["bothSides"]["status"], "pass")
        self.assertEqual(cells["zeroPrice"]["status"], "fail")
        self.assertEqual(cells["attainable"]["value"], "50%")
        # Two Up fills (30 and 14 shares), one Down fill of 14 at 40c.
        self.assertEqual(cells["fillsUp"]["value"], "2")
        self.assertEqual(cells["fillsDown"]["value"], "1")
        # No order counters in this run file, and both legs were taken.
        self.assertEqual(cells["orders"]["value"], "—")
        self.assertEqual(cells["single"]["value"], "0")
        self.assertEqual(perf["mShape"]["attainable"], [1, 0, 0, 0, 0])
        self.assertEqual(perf["mShape"]["phantom"], [0, 1, 0, 0, 0])
        self.assertNotIn("targets", perf)
        self.assertNotIn("gate", perf)

    def test_orders_cell_counts_what_the_loop_recorded(self):
        run = paper_run(SLUG, FILLS, "Up")
        run["orders_posted"] = 3
        run["orders_cancelled"] = 1
        perf = self.build([run])
        cells = {c["key"]: c for c in perf["cells"]}

        self.assertEqual(cells["orders"]["value"], "3")
        self.assertIn({"label": "Cancelled", "value": "1", "tone": None}, cells["orders"]["sub"])

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

    def test_bankroll_reads_custom_config_and_handles_invalid_value(self):
        perf_custom = self.build([paper_run(SLUG, FILLS, "Up")], config={"bankrollUsd": 2500.0})
        self.assertEqual(perf_custom["summary"]["bankrollUsd"], 2500.0)

        perf_invalid = self.build([paper_run(SLUG, FILLS, "Up")], config={"bankrollUsd": "invalid"})
        self.assertEqual(perf_invalid["summary"]["bankrollUsd"], 1000.0)

    def test_performance_kpis_calculation(self):
        slug1 = "btc-updown-5m-1794082800"
        slug2 = "btc-updown-5m-1794083100"
        slug3 = "btc-updown-5m-1794083400"
        run1 = paper_run(slug1, FILLS, "Up")
        run2 = paper_run(slug2, FILLS, None)
        run2["pending"] = False
        run2["net_usd"] = -20.6
        run2["payout_usd"] = 0.0
        run2["winner"] = "Down"
        run3 = paper_run(slug3, [{"minute": 0, "outcome": "Up", "price": 0.5, "shares": 20.0, "usd": 10.0}], "Up")

        perf = self.build([run1, run2, run3])
        s = perf["summary"]

        self.assertEqual(s["settled"], 3)
        self.assertEqual(s["winsCount"], 2)
        self.assertEqual(s["lossesCount"], 1)
        self.assertAlmostEqual(s["winRate"], 2 / 3, places=3)
        self.assertAlmostEqual(s["grossProfitUsd"], 33.4)
        self.assertAlmostEqual(s["grossLossUsd"], 20.6)
        self.assertAlmostEqual(s["profitFactor"], round(33.4 / 20.6, 2))
        self.assertAlmostEqual(s["avgWinUsd"], 16.7)
        self.assertAlmostEqual(s["avgLossUsd"], 20.6)
        self.assertAlmostEqual(s["expectancyUsd"], round((23.4 - 20.6 + 10.0) / 3, 2))
        self.assertAlmostEqual(s["breakEvenWinRate"], 0.5525, places=3)
        self.assertAlmostEqual(s["edgePct"], 11.42, places=1)
        self.assertAlmostEqual(s["sharpeRatio"], 61.34, places=1)
        self.assertAlmostEqual(s["sortinoRatio"], 116.31, places=1)
        self.assertEqual(s["maxWinStreak"], 1)
        self.assertEqual(s["maxLossStreak"], 1)
        self.assertEqual(s["currentStreak"], 1)
        self.assertEqual(s["upWindows"], 2)
        self.assertEqual(s["downWindows"], 1)



if __name__ == "__main__":
    unittest.main()
