"""End-to-end checks for analyze_mechanics.py on small synthetic ledgers.

The script is a top-level program, so each case runs it as a subprocess against a
temporary CSV and asserts on the printed summary lines.
"""
import csv
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CMD = [sys.executable, "-m", "scripts.leaderboard_traders.mechanics"]
ENV = {k: v for k, v in os.environ.items() if k != "TRADES_CSV"}
FIELDS = [
    "Proxy_Wallet", "Timestamp_UTC", "Type", "Market", "Outcome", "Side", "Price",
    "Shares", "USD_Amount", "Condition_ID", "Token_ID", "Transaction_Hash",
    "Market_Slug", "Event_Slug",
]


def row(type_, slug, outcome="", side="", price="", shares="", usd="", ts=""):
    record = {field: "" for field in FIELDS}
    record.update(Type=type_, Market_Slug=slug, Event_Slug=slug, Outcome=outcome,
                  Side=side, Price=price, Shares=shares, USD_Amount=usd,
                  Timestamp_UTC=ts)
    return record


def run_at(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return subprocess.run(
        [*CMD, str(path)],
        capture_output=True, text=True, encoding="utf-8", env=ENV,
        cwd=REPO_ROOT,
    )


def run(rows):
    with tempfile.TemporaryDirectory() as temp_dir:
        return run_at(pathlib.Path(temp_dir) / "ledger.csv", rows)


class AnalyzeMechanicsTests(unittest.TestCase):
    def test_winner_comes_from_the_redeem_rows(self):
        base = 1_700_000_000
        up_slug = f"btc-updown-5m-{base}"
        down_slug = f"btc-updown-5m-{base + 300}"
        rows = [
            row("TRADE", up_slug, "Up", "BUY", "0.6", "10", "6.0", f"2023-11-14T22:13:30+00:00"),
            row("TRADE", up_slug, "Down", "BUY", "0.4", "10", "4.0", f"2023-11-14T22:13:35+00:00"),
            row("REDEEM", up_slug, "Up", "", "0", "10", "10.0", f"2023-11-14T22:19:00+00:00"),
            row("REDEEM", up_slug, "Down", "", "0", "10", "0.0", f"2023-11-14T22:19:00+00:00"),
            row("TRADE", down_slug, "Up", "BUY", "0.5", "10", "5.0", f"2023-11-14T22:18:30+00:00"),
            row("TRADE", down_slug, "Down", "BUY", "0.5", "10", "5.0", f"2023-11-14T22:18:35+00:00"),
            row("REDEEM", down_slug, "Up", "", "0", "10", "0.0", f"2023-11-14T22:24:00+00:00"),
            row("REDEEM", down_slug, "Down", "", "0", "10", "10.0", f"2023-11-14T22:24:00+00:00"),
            # no REDEEM for this one: it must drop out of the win-dependent sections
            row("TRADE", f"btc-updown-5m-{base + 600}", "Up", "BUY", "0.5", "10", "5.0",
                "2023-11-14T22:23:30+00:00"),
        ]

        result = run(rows)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Markets with fills: 3 | with a REDEEM: 2", result.stdout)
        self.assertIn("markets analysed: 2", result.stdout)

    def test_a_sold_out_market_counts_without_a_redeem(self):
        base = 1_700_000_000
        slug = f"btc-updown-5m-{base}"
        rows = [
            row("TRADE", slug, "Up", "BUY", "0.5", "10", "5.0", "2023-11-14T22:13:30+00:00"),
            row("TRADE", slug, "Up", "SELL", "0.8", "10", "8.0", "2023-11-14T22:14:30+00:00"),
        ]

        result = run(rows)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Markets with fills: 1 | with a REDEEM: 0", result.stdout)
        self.assertIn("markets analysed: 1", result.stdout)
        self.assertIn("net $3", result.stdout)
        self.assertIn("outcome known from a REDEEM: 0", result.stdout)

    def test_a_merged_pair_counts_as_settled(self):
        base = 1_700_000_000
        slug = f"btc-updown-5m-{base}"
        rows = [
            row("TRADE", slug, "Up", "BUY", "0.5", "10", "5.0", "2023-11-14T22:13:30+00:00"),
            row("TRADE", slug, "Down", "BUY", "0.5", "10", "5.0", "2023-11-14T22:13:35+00:00"),
            row("MERGE", slug, "", "", "0", "10", "10.0", "2023-11-14T22:14:00+00:00"),
        ]

        result = run(rows)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Markets with fills: 1 | with a REDEEM: 0", result.stdout)
        self.assertIn("net $0", result.stdout)

    def test_empty_ledger_does_not_crash(self):
        result = run([])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Markets with fills: 0", result.stdout)
        self.assertIn("markets analysed: 0", result.stdout)

    def test_same_side_fills_form_one_run(self):
        base = 1_700_000_000
        slug = f"btc-updown-5m-{base}"
        rows = [
            row("TRADE", slug, "Up", "BUY", "0.5", "5", "2.5", f"2023-11-14T22:13:3{i}+00:00")
            for i in range(4)
        ]
        rows.append(row("REDEEM", slug, "Up", "", "0", "20", "20.0", "2023-11-14T22:19:00+00:00"))

        result = run(rows)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("markets with >=4 fills: 1", result.stdout)
        self.assertIn("mean same-side run length: 4.00", result.stdout)

    def test_a_fifteen_minute_market_is_timed_from_its_own_slug(self):
        base = 1_700_000_000
        slug = f"btc-updown-15m-{base}"
        rows = [
            row("TRADE", slug, "Up", "BUY", "0.5", "10", "5.0", "2023-11-14T22:13:30+00:00"),
            # 10 minutes in: the 15m market is still open, so it must not be valued.
            row("TRADE", f"btc-updown-5m-{base + 600}", "Up", "BUY", "0.5", "10", "5.0",
                "2023-11-14T22:20:00+00:00"),
        ]

        result = run(rows)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("markets analysed: 0", result.stdout)
        self.assertIn("excluded: 2 still open", result.stdout)

    def test_an_unresolved_closed_market_becomes_a_pnl_range(self):
        base = 1_700_000_000
        slug = f"btc-updown-5m-{base}"
        rows = [
            row("TRADE", slug, "Up", "BUY", "0.5", "10", "5.0", "2023-11-14T22:13:30+00:00"),
            # past the 5m close, in another market, and no REDEEM for the first one.
            row("TRADE", f"btc-updown-5m-{base + 600}", "Up", "BUY", "0.5", "10", "5.0",
                "2023-11-14T22:19:00+00:00"),
        ]

        result = run(rows)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("markets analysed: 1", result.stdout)
        self.assertIn("resolved exactly: 0  unresolved: 1", result.stdout)
        self.assertIn("unresolved pnl range $-5 .. $5", result.stdout)

    def test_rates_carry_a_wilson_95pct_interval(self):
        base = 1_700_000_000
        rows = []
        for i in range(6):
            slug = f"btc-updown-5m-{base + 300 * i}"
            stamp = 1_700_000_000 + 300 * i + 10
            ts = datetime.fromtimestamp(stamp, timezone.utc).isoformat()
            rows.append(row("TRADE", slug, "Up", "BUY", "0.5", "10", "5.0", ts))
            rows.append(row("REDEEM", slug, "Up", "", "0", "10", "10.0", ts))

        result = run(rows)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("100.0% [61-100]", result.stdout)

    def test_writes_markdown_into_the_account_analysis_folder(self):
        base = 1_700_000_000
        slug = f"btc-updown-5m-{base}"
        rows = [
            row("TRADE", slug, "Up", "BUY", "0.6", "10", "6.0", "2023-11-14T22:13:30+00:00"),
            row("TRADE", slug, "Down", "BUY", "0.4", "10", "4.0", "2023-11-14T22:13:35+00:00"),
            row("REDEEM", slug, "Up", "", "0", "10", "10.0", "2023-11-14T22:19:00+00:00"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = pathlib.Path(temp_dir) / "ledgers" / "acct" / "raw" / "acct_1.csv"
            csv_path.parent.mkdir(parents=True)
            result = run_at(csv_path, rows)
            target = (
                pathlib.Path(temp_dir) / "ledgers" / "acct" / "analysis" / "acct_1_mechanics.md"
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(target.is_file())
            self.assertFalse(target.with_name(target.name + ".tmp").exists())
            body = target.read_text(encoding="utf-8")
            self.assertIn("## 1. FIRST LEG", body)
            self.assertIn("| bucket | n | known |", body)
            self.assertIn("Wrote", result.stdout)
            self.assertNotIn("Wrote", body)

    def test_a_ledger_outside_ledgers_gets_the_report_next_to_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = pathlib.Path(temp_dir) / "other.csv"
            result = run_at(csv_path, [])
            target = pathlib.Path(temp_dir) / "other_mechanics.md"

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(target.is_file())

    def test_requires_a_ledger_argument(self):
        result = subprocess.run(
            CMD,
            capture_output=True, text=True, encoding="utf-8", env=ENV,
            cwd=REPO_ROOT,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("usage: python -m scripts.leaderboard_traders.mechanics", result.stderr)

    def test_missing_ledger_prints_a_message(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = pathlib.Path(temp_dir) / "nope.csv"
            result = subprocess.run(
                [*CMD, str(missing)],
                capture_output=True, text=True, encoding="utf-8", env=ENV,
                cwd=REPO_ROOT,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Ledger not found", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_a_csv_without_ledger_columns_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = pathlib.Path(temp_dir) / "notes.csv"
            path.write_text("foo,bar\n1,2\n", encoding="utf-8")
            result = subprocess.run(
                [*CMD, str(path)],
                capture_output=True, text=True, encoding="utf-8", env=ENV,
                cwd=REPO_ROOT,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing column(s)", result.stderr)
        self.assertIn("Timestamp_UTC", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
