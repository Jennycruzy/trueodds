"""Economics-market parsing shapes.

Covers the two economics paths in `parsers.py`:
  * Kalshi structured series (KXCPIYOY, KXECONSTATCPI, KXGDP, KXU3,
    KXPAYROLLS, KXFED) that carry strike fields in `market.raw`.
  * Limitless-style free-text CPI / GDP / Fed markets parsed from titles.
Each expected value is the parser's documented behavior, not a re-derivation.
"""
import unittest

from rwoo.parsers import parse_market
from tests.support import kalshi_raw, make_market


class KalshiEconomicsSeriesTests(unittest.TestCase):
    def test_cpi_yoy_annual_bin(self):
        m = make_market(
            venue="kalshi",
            domain="economics",
            question="Will year-over-year CPI be 2.5% to 3.0% in June?",
            raw=kalshi_raw(
                event_ticker="KXCPIYOY-26JUN",
                series_ticker="KXCPIYOY",
                strike_type="between",
                floor_strike="2.5",
                cap_strike="3.0",
            ),
        )
        parsed = parse_market(m)
        self.assertEqual(parsed.family, "economics.headline_cpi")
        self.assertEqual(parsed.shape, "annual_yoy_bin_or_threshold")
        self.assertEqual(parsed.status, "engine_available")
        self.assertEqual(parsed.country, "US")
        self.assertEqual(parsed.target_month, 6)
        self.assertEqual(parsed.target_year, 2026)
        self.assertEqual(parsed.strike_type, "between")
        self.assertEqual(parsed.floor_strike, 2.5)
        self.assertEqual(parsed.cap_strike, 3.0)
        self.assertEqual(parsed.source_series, "KXCPIYOY")

    def test_econstat_cpi_exact_monthly_bin_from_ticker(self):
        # KXECONSTATCPI is a 'CPI MoM is exactly X%' market; X lives in the
        # ticker suffix (-T0.3) and becomes a +/-0.05 between-band.
        m = make_market(
            venue="kalshi",
            domain="economics",
            question="Will CPI month-over-month be exactly 0.3% in June?",
            raw=kalshi_raw(
                event_ticker="KXECONSTATCPI-26JUN",
                series_ticker="KXECONSTATCPI",
                ticker="KXECONSTATCPI-26JUN-T0.3",
                strike_type="custom",
            ),
        )
        parsed = parse_market(m)
        self.assertEqual(parsed.family, "economics.headline_cpi")
        self.assertEqual(parsed.shape, "monthly_bin_or_threshold")
        self.assertEqual(parsed.status, "engine_available")
        self.assertEqual(parsed.strike_type, "between")
        self.assertAlmostEqual(parsed.floor_strike, 0.25)
        self.assertAlmostEqual(parsed.cap_strike, 0.35)
        self.assertEqual(parsed.target_month, 6)
        self.assertEqual(parsed.target_year, 2026)

    def test_econstat_cpi_unparseable_ticker_is_parse_missing(self):
        m = make_market(
            venue="kalshi",
            domain="economics",
            question="Will CPI month-over-month be exactly 0.3% in June?",
            raw=kalshi_raw(
                event_ticker="KXECONSTATCPI-26JUN",
                series_ticker="KXECONSTATCPI",
                ticker="KXECONSTATCPI-26JUN",  # no -T suffix
                strike_type="custom",
            ),
        )
        parsed = parse_market(m)
        self.assertEqual(parsed.status, "parse_missing")
        self.assertEqual(parsed.family, "economics.headline_cpi")

    def test_gdp_quarter_from_question(self):
        m = make_market(
            venue="kalshi",
            domain="economics",
            question="Will Q2 2026 real GDP growth be above 3%?",
            raw=kalshi_raw(
                event_ticker="KXGDP-26JUN",
                series_ticker="KXGDP",
                strike_type="greater",
                floor_strike="3.0",
            ),
        )
        parsed = parse_market(m)
        self.assertEqual(parsed.family, "economics.gdp")
        self.assertEqual(parsed.shape, "quarterly_growth_bin_or_threshold")
        self.assertEqual(parsed.status, "engine_available")
        self.assertEqual(parsed.country, "US")
        self.assertEqual(parsed.source_series, "2026Q2")
        self.assertEqual(parsed.target_year, 2026)

    def test_gdp_missing_quarter_is_parse_missing(self):
        m = make_market(
            venue="kalshi",
            domain="economics",
            question="Will real GDP growth be above 3%?",  # no quarter
            raw=kalshi_raw(
                event_ticker="KXGDP-26JUN",
                series_ticker="KXGDP",
                strike_type="greater",
                floor_strike="3.0",
            ),
        )
        parsed = parse_market(m)
        self.assertEqual(parsed.status, "parse_missing")
        self.assertEqual(parsed.family, "economics.gdp")

    def test_u3_unemployment_ticker(self):
        m = make_market(
            venue="kalshi",
            domain="economics",
            question="Will the June unemployment rate be above 4.2%?",
            raw=kalshi_raw(
                event_ticker="KXU3-26JUN",
                series_ticker="KXU3",
                strike_type="greater",
                floor_strike="4.2",
            ),
        )
        parsed = parse_market(m)
        self.assertEqual(parsed.family, "economics.labor")
        self.assertEqual(parsed.shape, "unemployment_rate_threshold")
        self.assertEqual(parsed.status, "engine_available")
        self.assertEqual(parsed.target_month, 6)
        self.assertEqual(parsed.source_series, "KXU3")

    def test_payrolls_ticker(self):
        m = make_market(
            venue="kalshi",
            domain="economics",
            question="Will June nonfarm payrolls rise more than 150k?",
            raw=kalshi_raw(
                event_ticker="KXPAYROLLS-26JUN",
                series_ticker="KXPAYROLLS",
                strike_type="greater",
                floor_strike="150",
            ),
        )
        parsed = parse_market(m)
        self.assertEqual(parsed.family, "economics.labor")
        self.assertEqual(parsed.shape, "payrolls_change_threshold")
        self.assertEqual(parsed.status, "engine_available")
        self.assertEqual(parsed.source_series, "KXPAYROLLS")

    def test_fed_meeting_ticker_sets_anchor(self):
        m = make_market(
            venue="kalshi",
            domain="economics",
            question="Will the fed funds target range be 4.25-4.50% after July?",
            raw=kalshi_raw(
                event_ticker="KXFED-26JUL",
                series_ticker="KXFED",
                strike_type="between",
                floor_strike="4.25",
                cap_strike="4.50",
            ),
        )
        parsed = parse_market(m)
        self.assertEqual(parsed.family, "economics.fed_rates")
        self.assertEqual(parsed.shape, "target_range_after_meeting")
        self.assertEqual(parsed.status, "engine_available")
        self.assertEqual(parsed.target_month, 7)
        self.assertEqual(parsed.target_year, 2026)
        self.assertEqual(parsed.target_date, "2026-07-28")

    def test_unknown_series_falls_through_to_none_or_text(self):
        # A Kalshi economics series we do not map should not be treated as a
        # structured series; with no free-text shape either, parse returns None.
        m = make_market(
            venue="kalshi",
            domain="economics",
            question="Some unmapped economic indicator market",
            raw=kalshi_raw(
                event_ticker="KXMYSTERY-26JUN",
                series_ticker="KXMYSTERY",
                strike_type="greater",
            ),
        )
        self.assertIsNone(parse_market(m))


class LimitlessTextEconomicsTests(unittest.TestCase):
    def test_annual_cpi_range_bin_us(self):
        m = make_market(
            venue="limitless",
            domain="economics",
            question="June Inflation US - Annual - 2.5-3.0%",
        )
        parsed = parse_market(m)
        self.assertEqual(parsed.family, "economics.headline_cpi")
        self.assertEqual(parsed.shape, "annual_yoy_bin_or_threshold")
        self.assertEqual(parsed.status, "engine_available")
        self.assertEqual(parsed.country, "US")
        self.assertEqual(parsed.target_month, 6)
        self.assertEqual(parsed.strike_type, "between")
        # range bins widen by half a rounding step on each side.
        self.assertAlmostEqual(parsed.floor_strike, 2.45)
        self.assertAlmostEqual(parsed.cap_strike, 3.05)

    def test_monthly_cpi_bin(self):
        m = make_market(
            venue="limitless",
            domain="economics",
            question="June Inflation US - Monthly - 0.2-0.4%",
        )
        parsed = parse_market(m)
        self.assertEqual(parsed.shape, "monthly_bin_or_threshold")
        self.assertEqual(parsed.status, "engine_available")

    def test_non_us_cpi_is_source_missing(self):
        m = make_market(
            venue="limitless",
            domain="economics",
            question="June Inflation China - Annual - 2.0-2.5%",
        )
        parsed = parse_market(m)
        self.assertEqual(parsed.family, "economics.headline_cpi")
        self.assertEqual(parsed.status, "source_missing")
        self.assertEqual(parsed.country, "China")

    def test_gdp_growth_greater_threshold(self):
        m = make_market(
            venue="limitless",
            domain="economics",
            question="US GDP growth in Q2 2026? - >=3.5%",
        )
        parsed = parse_market(m)
        self.assertEqual(parsed.family, "economics.gdp")
        self.assertEqual(parsed.status, "engine_available")
        self.assertEqual(parsed.strike_type, "greater")
        self.assertEqual(parsed.floor_strike, 3.5)
        self.assertIsNone(parsed.cap_strike)
        self.assertEqual(parsed.source_series, "2026Q2")

    def test_fed_path_market_is_source_missing(self):
        m = make_market(
            venue="limitless",
            domain="economics",
            question="Will the Fed cut rates at the next meeting?",
        )
        parsed = parse_market(m)
        self.assertEqual(parsed.family, "economics.fed_rates")
        self.assertEqual(parsed.status, "source_missing")

    def test_unrecognized_economics_text_returns_none(self):
        m = make_market(
            venue="limitless",
            domain="economics",
            question="Will consumer confidence be strong this year?",
        )
        self.assertIsNone(parse_market(m))


if __name__ == "__main__":
    unittest.main()
