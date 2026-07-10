import unittest
from dataclasses import replace

from rwoo.cross_venue import cross_venue_edge
from tests.support import make_market


class CrossVenueEdgeTests(unittest.TestCase):
    def _market(self, venue, market_id, probability, spread=0.02, source="NOAA", time="2026-07-12T23:59:00+00:00"):
        base = make_market(
            venue=venue,
            market_id=market_id,
            question="Will the NYC high temperature exceed 90 F?",
            domain="weather",
            resolution_source=source,
        )
        return replace(base, resolution_time=time, implied_prob=probability, spread=spread)

    def test_refuses_similar_contract_with_different_source(self):
        result = cross_venue_edge(self._market("kalshi", "k", 0.4), self._market("polymarket", "p", 0.6, source="Weather.com"))
        self.assertFalse(result["actionable"])
        self.assertEqual(result["equivalence"]["classification"], "candidate_needs_rule_review")

    def test_finds_complementary_executable_edge(self):
        # Buy YES at ~0.31 and NO at ~0.31. Even conservative Kalshi fees leave an edge.
        result = cross_venue_edge(self._market("kalshi", "k", 0.30), self._market("polymarket", "p", 0.70))
        self.assertTrue(result["actionable"])
        self.assertGreater(result["edge"]["net_edge"], 0)

    def test_no_midpoint_only_false_positive(self):
        result = cross_venue_edge(
            self._market("kalshi", "k", 0.49, spread=0.10),
            self._market("polymarket", "p", 0.51, spread=0.10),
        )
        self.assertFalse(result["actionable"])


if __name__ == "__main__":
    unittest.main()
