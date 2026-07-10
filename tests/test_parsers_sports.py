"""World Cup stage-of-elimination title parsing.

Covers the three recognized title shapes (Kalshi 'get eliminated in the <stage>',
Kalshi 'win the Final', Limitless 'World Cup: <team> Stage of Elimination -
<stage>'), the stage-text -> stage-key mapping, and the non-match paths. The
parser only maps titles to stage keys; it never touches the live bracket.
"""
import unittest

from rwoo.parsers import parse_market
from tests.support import make_market


def _sports(question: str):
    return parse_market(make_market(venue="kalshi", domain="sports", question=question))


class WorldCupStageParsingTests(unittest.TestCase):
    def test_kalshi_eliminated_in_quarterfinals(self):
        parsed = _sports(
            "Will France get eliminated in the Quarterfinals of the 2026 FIFA World Cup?"
        )
        self.assertEqual(parsed.family, "sports.world_cup")
        self.assertEqual(parsed.shape, "stage_of_elimination")
        self.assertEqual(parsed.status, "engine_available")
        self.assertEqual(parsed.location, "France")
        self.assertEqual(parsed.source_series, "quarterfinals")

    def test_kalshi_mens_variant_and_semifinals(self):
        parsed = _sports(
            "Will Brazil get eliminated in the Semi-finals of the 2026 Men's FIFA World Cup?"
        )
        self.assertEqual(parsed.status, "engine_available")
        self.assertEqual(parsed.location, "Brazil")
        self.assertEqual(parsed.source_series, "semifinals")

    def test_win_the_final_maps_to_champion(self):
        parsed = _sports("Will Argentina win the Final of the 2026 FIFA World Cup?")
        self.assertEqual(parsed.status, "engine_available")
        self.assertEqual(parsed.location, "Argentina")
        self.assertEqual(parsed.source_series, "champion")

    def test_eliminated_in_the_final_is_runner_up(self):
        parsed = _sports(
            "Will Spain get eliminated in the Final of the 2026 FIFA World Cup?"
        )
        self.assertEqual(parsed.status, "engine_available")
        self.assertEqual(parsed.location, "Spain")
        self.assertEqual(parsed.source_series, "runner_up")

    def test_limitless_stage_group_title(self):
        parsed = parse_market(
            make_market(
                venue="limitless",
                domain="sports",
                question="World Cup: Portugal Stage of Elimination - Round of 16",
            )
        )
        self.assertEqual(parsed.status, "engine_available")
        self.assertEqual(parsed.location, "Portugal")
        self.assertEqual(parsed.source_series, "round_of_16")

    def test_unmapped_stage_text_is_parse_missing(self):
        parsed = _sports(
            "Will France get eliminated in the Preliminaries of the 2026 FIFA World Cup?"
        )
        self.assertEqual(parsed.status, "parse_missing")
        self.assertEqual(parsed.family, "sports.world_cup")
        self.assertEqual(parsed.location, "France")

    def test_non_world_cup_sports_question_returns_none(self):
        self.assertIsNone(_sports("Who will win the 2026 Super Bowl?"))


if __name__ == "__main__":
    unittest.main()
