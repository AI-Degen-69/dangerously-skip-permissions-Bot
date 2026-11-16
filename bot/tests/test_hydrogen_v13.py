"""Hydrogen v1.3 promotion: post-PR #56 candidate registry + archive isolation."""
import unittest
from bot import ab_test as ab
from bot import constants as C


class TestHydrogenV13Registry(unittest.TestCase):
    def test_v13_registered_with_v12_identical_params(self):
        v12 = C.STRATEGY_SETUPS.get("hydrogen-v1.2")
        v13 = C.STRATEGY_SETUPS.get("hydrogen-v1.3")
        self.assertIsNotNone(v12)
        self.assertIsNotNone(v13)
        # v1.3 is a build/engine bump, NOT a parameter change.
        self.assertEqual(v13["entry"], v12["entry"])
        self.assertEqual(v13["entry"]["maxShareLead"], 11.0)
        self.assertTrue(v13["entry"]["takerDipBalancedOnly"])
        self.assertEqual(v13["name"], "Hydrogen v1.3")

    def test_v13_is_default_candidate(self):
        self.assertEqual(ab.DEFAULT_CANDIDATE_ID, "hydrogen-v1.3")
        self.assertEqual(ab.CANDIDATE_DISPLAY_NAME, "Hydrogen v1.3")
        self.assertIn("hydrogen-v1.3", C.STRATEGY_SETUPS)


class TestArchivedRunExclusion(unittest.TestCase):
    def test_archived_prefix_detected(self):
        # Non-existent / empty runs are not archived.
        self.assertFalse(ab._is_archived_run("run_20990101_000000_paper_hydrogen_v9_9"))
        self.assertFalse(ab._is_archived_run(None))
        self.assertFalse(ab._is_archived_run(""))

    def test_strategy_id_mapping_covers_v13(self):
        self.assertEqual(
            ab._run_strategy_id("run_20261116_120000_paper_hydrogen_v1_3"),
            "hydrogen-v1.3",
        )
        self.assertEqual(
            ab._run_strategy_id("run_20261115_233630_paper_hydrogen_v1_2"),
            "hydrogen-v1.2",
        )


if __name__ == "__main__":
    unittest.main()
