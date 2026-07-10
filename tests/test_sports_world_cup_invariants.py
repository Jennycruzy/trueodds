import unittest
from unittest.mock import patch

from rwoo.engines import sports


class WorldCupEntitySafetyTests(unittest.TestCase):
    def setUp(self):
        self.state = {"matches": [], "knockout_underway": True, "finished": False}
        self.ratings = {"spain": 2000.0, "france": 1950.0}
        self.solved = {
            "spain": {"champion": 0.6, "exit": {"runner_up": 0.4}},
            "france": {"champion": 0.4, "exit": {"runner_up": 0.6}},
        }

    def _patch_sources(self):
        return (
            patch.object(sports, "fetch_world_cup_state", return_value=self.state),
            patch.object(sports, "_live_ratings_by_key", return_value=self.ratings),
            patch.object(sports, "solve_remaining_bracket", return_value=self.solved),
        )

    def test_unknown_entity_refuses_instead_of_becoming_zero(self):
        patches = self._patch_sources()
        with patches[0], patches[1], patches[2]:
            result = sports._in_tournament_result("Atlantis", "champion")
        self.assertTrue(result["refused"])
        self.assertIsNone(result["oracle_prob"])
        self.assertEqual(result["confidence"], 0.0)

    def test_confederation_refuses_until_explicitly_aggregated(self):
        patches = self._patch_sources()
        with patches[0], patches[1], patches[2]:
            result = sports._in_tournament_result("Europe (UEFA)", "champion")
        self.assertTrue(result["refused"])
        self.assertIsNone(result["oracle_prob"])
        self.assertEqual(result["method"], "unsupported_or_unbound_world_cup_entity")

    def test_valid_team_probability_is_preserved(self):
        patches = self._patch_sources()
        with patches[0], patches[1], patches[2]:
            result = sports._in_tournament_result("Spain", "champion")
        self.assertFalse(result["refused"])
        self.assertAlmostEqual(result["oracle_prob"], 0.6)

    def test_champion_distribution_is_exhaustive(self):
        self.assertAlmostEqual(sum(v["champion"] for v in self.solved.values()), 1.0)

    def test_team_terminal_outcomes_are_exhaustive(self):
        for result in self.solved.values():
            self.assertAlmostEqual(result["champion"] + sum(result["exit"].values()), 1.0)


if __name__ == "__main__":
    unittest.main()
