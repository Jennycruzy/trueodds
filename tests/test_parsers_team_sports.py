import unittest
from rwoo.parsers import parse_market
from tests.support import make_market


class TeamSportsParsingTests(unittest.TestCase):
    def test_mlb_match_binds_yes(self):
        market = make_market(domain="sports", question="MLB: New York Yankees at Boston Red Sox?",
                             yes_subtitle="Boston Red Sox")
        parsed = parse_market(market)
        self.assertEqual((parsed.family, parsed.status), ("sports.mlb", "engine_available"))
        self.assertEqual((parsed.location, parsed.source_series), ("Boston Red Sox", "New York Yankees"))

    def test_club_match_without_yes_binding_refuses(self):
        market = make_market(domain="sports", question="Premier League: Arsenal vs Chelsea?", yes_subtitle=None)
        parsed = parse_market(market)
        self.assertEqual((parsed.family, parsed.status), ("sports.club_soccer", "parse_missing"))


if __name__ == "__main__":
    unittest.main()
