"""Unit checks for scripts.leaderboard_traders.report_kit."""
import io
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from scripts.leaderboard_traders import report_kit


class AnalysisTargetTests(unittest.TestCase):
    def test_ledger_outside_any_root_stays_next_to_the_csv(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = pathlib.Path(temp_dir) / "ledger.csv"
            csv_path.write_text("", encoding="utf-8")

            target = report_kit.analysis_target(str(csv_path), "_strategy.md")

            self.assertEqual(target, pathlib.Path(temp_dir) / "ledger_strategy.md")

    def test_legacy_docs_ledger_still_reports_into_its_analysis_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = (
                pathlib.Path(temp_dir) / "ledgers" / "acct" / "raw" / "acct_1.csv"
            )
            csv_path.parent.mkdir(parents=True)
            csv_path.write_text("", encoding="utf-8")

            target = report_kit.analysis_target(str(csv_path), "_mechanics.md")

            self.assertEqual(
                target,
                pathlib.Path(temp_dir)
                / "ledgers" / "acct" / "analysis" / "acct_1_mechanics.md",
            )
            self.assertTrue(target.parent.is_dir())

    def test_data_root_ledger_reports_into_the_docs_analysis_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_root = pathlib.Path(temp_dir) / "data" / "leaderboard"
            docs_root = pathlib.Path(temp_dir) / "docs" / "ledgers"
            csv_path = raw_root / "acct" / "raw" / "acct_1.csv"
            csv_path.parent.mkdir(parents=True)
            csv_path.write_text("", encoding="utf-8")

            with (
                patch.object(report_kit, "RAW_ROOT", raw_root),
                patch.object(report_kit, "DOCS_ROOT", docs_root),
            ):
                target = report_kit.analysis_target(str(csv_path), "_strategy.md")

            self.assertEqual(
                target, docs_root / "acct" / "analysis" / "acct_1_strategy.md"
            )
            self.assertTrue(target.parent.is_dir())


class TeeTests(unittest.TestCase):
    def test_write_fans_out_to_every_stream_and_returns_the_length(self):
        first, second = io.StringIO(), io.StringIO()
        tee = report_kit.Tee(first, second)

        self.assertEqual(tee.write("hello"), 5)
        tee.flush()

        self.assertEqual(first.getvalue(), "hello")
        self.assertEqual(second.getvalue(), "hello")


if __name__ == "__main__":
    unittest.main()
