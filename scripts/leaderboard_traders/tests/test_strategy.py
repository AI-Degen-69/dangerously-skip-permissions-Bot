import contextlib
import io
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from scripts.leaderboard_traders import strategy as SCRIPT


class SplitThirdsTests(unittest.TestCase):
    def test_three_days_give_one_day_each(self):
        self.assertEqual(SCRIPT.split_thirds(["a", "b", "c"]), [["a"], ["b"], ["c"]])

    def test_ninety_days_split_into_thirty(self):
        days = [f"day-{i:02d}" for i in range(90)]

        thirds = SCRIPT.split_thirds(days)

        self.assertEqual([len(part) for part in thirds], [30, 30, 30])
        self.assertEqual(thirds[0][0], "day-00")
        self.assertEqual(thirds[-1][-1], "day-89")

    def test_every_day_lands_in_exactly_one_phase(self):
        for n in (3, 4, 7, 30, 90, 91):
            days = [f"day-{i}" for i in range(n)]
            with self.subTest(n=n):
                thirds = SCRIPT.split_thirds(days)
                self.assertEqual([d for part in thirds for d in part], days)


class AnalysisTargetTests(unittest.TestCase):
    def test_raw_ledger_writes_into_the_account_analysis_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = pathlib.Path(temp_dir) / "ledgers" / "acct" / "raw" / "acct_1.csv"
            csv_path.parent.mkdir(parents=True)
            csv_path.write_text("", encoding="utf-8")

            target = SCRIPT.analysis_target(str(csv_path), "_strategy.md")

            self.assertEqual(
                target, pathlib.Path(temp_dir) / "ledgers" / "acct" / "analysis" / "acct_1_strategy.md"
            )
            self.assertTrue(target.parent.is_dir())

    def test_ledger_outside_ledgers_stays_next_to_the_csv(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = pathlib.Path(temp_dir) / "ledger.csv"
            csv_path.write_text("", encoding="utf-8")

            target = SCRIPT.analysis_target(str(csv_path), "_strategy.md")

            self.assertEqual(target, pathlib.Path(temp_dir) / "ledger_strategy.md")


class MainOutputTests(unittest.TestCase):
    def test_main_writes_the_analysis_into_the_account_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = (
                pathlib.Path(temp_dir) / "ledgers" / "acct" / "raw" / "acct_1.csv"
            )
            csv_path.parent.mkdir(parents=True)
            csv_path.write_text(",".join(SCRIPT.REQUIRED_COLUMNS) + "\n", encoding="utf-8")
            sections = (
                "section_a", "section_b", "section_c", "section_d", "section_e",
                "section_f", "section_g", "section_h", "section_i",
            )
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(SCRIPT, "PATH", str(csv_path)))
                stack.enter_context(
                    patch.object(
                        SCRIPT,
                        "load",
                        return_value=(None, SCRIPT.pd.DataFrame({"a": [1]}), None, None),
                    )
                )
                stack.enter_context(
                    patch.object(SCRIPT, "build_markets", return_value=(None, None))
                )
                for name in sections:
                    stack.enter_context(patch.object(SCRIPT, name))
                SCRIPT.main()

            target = (
                pathlib.Path(temp_dir)
                / "ledgers"
                / "acct"
                / "analysis"
                / "acct_1_strategy.md"
            )
            self.assertTrue(target.is_file())
            self.assertIn(
                "# Strategy reverse-engineering",
                target.read_text(encoding="utf-8"),
            )
            self.assertFalse(target.with_name(target.name + ".tmp").exists())


class BadLedgerTests(unittest.TestCase):
    def test_missing_ledger_exits_with_a_message(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = pathlib.Path(temp_dir) / "nope.csv"
            with patch.object(SCRIPT, "PATH", str(missing)):
                with self.assertRaises(SystemExit) as stopped:
                    SCRIPT.main()

        self.assertIn("Ledger not found", str(stopped.exception.code))

    def test_a_csv_without_ledger_columns_exits_with_a_message(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = pathlib.Path(temp_dir) / "notes.csv"
            path.write_text("foo,bar\n1,2\n", encoding="utf-8")
            errors = io.StringIO()
            with (
                patch.object(SCRIPT, "PATH", str(path)),
                contextlib.redirect_stderr(errors),
            ):
                with self.assertRaises(SystemExit) as stopped:
                    SCRIPT.main()

        self.assertEqual(stopped.exception.code, 1)
        self.assertIn("missing column(s)", errors.getvalue())
        self.assertIn("Timestamp_UTC", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
