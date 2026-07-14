from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from rwoo.engines.energy import backtest_henry_hub_annual_high, compute_henry_hub_annual_high_probability
from rwoo.domain import classify_polymarket
from rwoo.parsers import parse_market
from rwoo.scanner import _SCAN_SOURCE_CACHE, _expansion_series, _scan_source, scan_opportunities
from tests.support import kalshi_raw, make_market


class EnergyEngineTests(unittest.TestCase):
    def test_empirical_barrier_probability_is_bounded(self):
        start = date(2000, 1, 1)
        series = [(start + timedelta(days=i), 3.0 + ((i % 50) / 100)) for i in range(20 * 365)]
        target = (series[-1][0] + timedelta(days=60)).isoformat()
        result = compute_henry_hub_annual_high_probability(
            "greater", 3.75, target, target_year=series[-1][0].year, series=series,
        )
        self.assertFalse(result["refused"])
        self.assertLessEqual(result["prob_low"], result["oracle_prob"])
        self.assertLessEqual(result["oracle_prob"], result["prob_high"])

    def test_year_to_date_maximum_makes_already_hit_threshold_certain(self):
        start = date(1997, 1, 1)
        series = [(start + timedelta(days=i), 3.0)
                  for i in range((date(2026, 7, 1) - start).days)]
        series.append((date(2026, 1, 23), 30.72))
        series.append((date(2026, 7, 1), 2.90))
        result = compute_henry_hub_annual_high_probability(
            "greater", 10.0, "2027-01-01", target_year=2026, series=series,
        )
        self.assertEqual(result["oracle_prob"], 1.0)
        self.assertEqual(result["per_source_values"]["year_to_date_maximum"], 30.72)
        freshness = datetime.fromisoformat(result["data_freshness"])
        self.assertLess((datetime.now(timezone.utc) - freshness).total_seconds(), 5)

    def test_short_history_refuses(self):
        result = compute_henry_hub_annual_high_probability(
            "greater", 4, "2027-01-01", series=[(date(2026, 1, 1), 3.0)],
        )
        self.assertTrue(result["refused"])

    def test_backtest_uses_independent_years_and_requires_market_benchmark(self):
        start = date(1997, 1, 1)
        end = date(2026, 1, 1)
        series = []
        day = start
        while day < end:
            seasonal = 1.2 if day.month in {1, 2, 12} else 0.0
            cycle = (day.year % 5) * .25
            series.append((day, 3.0 + seasonal + cycle))
            day += timedelta(days=1)
        result = backtest_henry_hub_annual_high(series, thresholds=[4.0, 5.0])
        self.assertGreaterEqual(result["independent_evaluation_years"], 10)
        self.assertEqual(result["contract_rows"], result["independent_evaluation_years"] * 2)
        self.assertIsNotNone(result["oracle_brier"])
        self.assertIsNotNone(result["naive_prior_year_brier"])
        self.assertEqual(result["closing_market_rows"], 0)
        self.assertIsNone(result["beats_closing_market"])
        self.assertFalse(result["promotion_eligible"])

    def test_backtest_scores_supplied_closing_market_prices(self):
        start = date(1997, 1, 1)
        end = date(2020, 1, 1)
        series = []
        day = start
        while day < end:
            series.append((day, 3.0 + (1.5 if day.month == 12 else 0.0)))
            day += timedelta(days=1)
        prices = {(year, 4.0): .9 for year in range(2007, 2020)}
        result = backtest_henry_hub_annual_high(
            series, thresholds=[4.0], closing_prices=prices,
        )
        self.assertEqual(result["closing_market_rows"], result["contract_rows"])
        self.assertIsNotNone(result["closing_market_brier"])


class CommodityParsingTests(unittest.TestCase):
    def test_scan_source_snapshot_loads_once(self):
        _SCAN_SOURCE_CACHE.clear()
        calls = []
        first = _scan_source("source", lambda: calls.append(1) or {"value": 1})
        second = _scan_source("source", lambda: calls.append(2) or {"value": 2})
        self.assertIs(first, second)
        self.assertEqual(calls, [1])

    def test_eia_henry_hub_contract_routes_to_engine(self):
        raw = kalshi_raw(series_ticker="KXNGASMAX", event_ticker="KXNGASMAX-26",
                         strike_type="greater", floor_strike="5")
        market = make_market(
            venue="kalshi", domain="commodities", question="Will Henry Hub natural gas exceed $5?",
            resolution_rule="The Energy Information Administration reports the Henry Hub spot price.",
            resolution_source="U.S. Energy Information Administration", raw=raw,
        )
        parsed = parse_market(market)
        self.assertEqual((parsed.family, parsed.status), ("energy.henry_hub_spot", "engine_available"))
        self.assertEqual(parsed.floor_strike, 5.0)
        self.assertEqual(parsed.target_year, 2026)

    def test_dated_henry_hub_event_ticker_preserves_contract_year(self):
        raw = kalshi_raw(series_ticker="KXNGASMAX", event_ticker="KXNGASMAX-26DEC31",
                         strike_type="greater", floor_strike="5")
        market = make_market(
            venue="kalshi", domain="commodities", question="Will Henry Hub natural gas exceed $5?",
            resolution_rule="The Energy Information Administration reports the Henry Hub spot price.",
            resolution_source="U.S. Energy Information Administration", raw=raw,
        )
        self.assertEqual(parse_market(market).target_year, 2026)

    def test_person_named_brent_is_not_crude_oil(self):
        self.assertEqual(
            classify_polymarket([], "Will Brent Bien win the Wyoming primary?"),
            "other",
        )

    def test_agriculture_contract_is_visible_but_source_gated(self):
        market = make_market(
            venue="kalshi", domain="commodities", question="Will corn exceed $5?",
            raw=kalshi_raw(series_ticker="KXCORNW", strike_type="greater", floor_strike="5"),
        )
        parsed = parse_market(market)
        self.assertEqual((parsed.family, parsed.status),
                         ("agriculture.commodity_price", "source_missing"))

    def test_expansion_series_requires_verified_source_metadata(self):
        rows = [
            {"ticker": "KXNGASMAX", "title": "Natural gas annual high",
             "settlement_sources": [{"name": "Energy Information Administration"}]},
            {"ticker": "KXHURCTOT", "title": "Number of hurricanes",
             "settlement_sources": [{"name": "National Oceanic and Atmospheric Administration"}]},
            {"ticker": "FAKE", "title": "Natural gas annual high", "settlement_sources": []},
        ]
        self.assertEqual(_expansion_series(rows), ["KXHURCTOT", "KXNGASMAX"])

    @patch("rwoo.scanner.limitless.fetch_canonical_markets", return_value=[])
    @patch("rwoo.scanner.polymarket.fetch_canonical_active_markets", return_value=[])
    @patch("rwoo.scanner.kalshi.fetch_canonical_markets_for_series_batch", return_value=[])
    @patch("rwoo.scanner.kalshi.fetch_canonical_active_markets", return_value=[])
    @patch("rwoo.scanner.kalshi.fetch_series")
    def test_scan_discovers_expansion_series_without_fixed_ticker_list(
        self, fetch_series, _active, batch, _poly, _limitless,
    ):
        fetch_series.side_effect = [
            [{"ticker": "KXNGASMAX", "title": "Natural gas annual high",
              "settlement_sources": [{"name": "Energy Information Administration"}]}],
            [{"ticker": "KXHURCTOT", "title": "Number of hurricanes",
              "settlement_sources": [{"name": "National Oceanic and Atmospheric Administration"}]}],
        ]
        scan = scan_opportunities()
        self.assertEqual(scan["dynamically_discovered_expansion_series"],
                         ["KXHURCTOT", "KXNGASMAX"])
        self.assertEqual(scan["expansion_family_counts"], {
            "weather.hurricane_season": 0,
            "energy.henry_hub_spot": 0,
            "energy.commodity_price": 0,
            "agriculture.commodity_price": 0,
        })
        self.assertIn(["KXHURCTOT", "KXNGASMAX"], [call.args[0] for call in batch.call_args_list])


if __name__ == "__main__":
    unittest.main()
