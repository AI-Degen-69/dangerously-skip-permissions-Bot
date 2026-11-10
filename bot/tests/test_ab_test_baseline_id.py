import unittest

from bot.ab_test import start_candidate_test


class TestBaselineRunIdValidation(unittest.TestCase):
    """baselineRunId arrives from the API body: it must resolve inside the runs folder."""

    def test_rejects_a_path_that_escapes_the_runs_folder(self):
        with self.assertRaises(ValueError):
            start_candidate_test(baseline_run_id="../../../etc")

    def test_rejects_an_unknown_run_id(self):
        with self.assertRaises(ValueError):
            start_candidate_test(baseline_run_id="no_such_run_999999")


if __name__ == "__main__":
    unittest.main()
