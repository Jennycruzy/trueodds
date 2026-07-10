"""Weather-market parsing: Kalshi series/station routing and free-text metrics.

Covers the Kalshi structured path (`_parse_kalshi_weather_market`): registered
series route to verified station coordinates and a target date parsed from the
event ticker; unmapped or unregistered series surface explicit missing statuses.
Also covers the free-text metric classifier used for non-Kalshi venues.
"""
import unittest
from unittest.mock import patch

from rwoo.parsers import parse_market
from rwoo.engines.weather import compute_weather_probability, event_probability
from tests.support import kalshi_raw, make_market
from rwoo.weather_stations import station_for_series


def _kalshi_weather(series_ticker, event_ticker, **fields):
    raw = kalshi_raw(series_ticker=series_ticker, event_ticker=event_ticker, **fields)
    return parse_market(make_market(venue="kalshi", domain="weather", raw=raw))


class KalshiWeatherRoutingTests(unittest.TestCase):
    def test_registered_high_series_routes_to_station(self):
        parsed = _kalshi_weather(
            "KXHIGHNY", "KXHIGHNY-26JUL09", strike_type="greater", floor_strike="90"
        )
        self.assertEqual(parsed.family, "weather.temperature")
        self.assertEqual(parsed.shape, "daily_high_threshold")
        self.assertEqual(parsed.status, "engine_available")
        self.assertEqual(parsed.metric, "temperature_2m_max")
        self.assertEqual(parsed.location, station_for_series("KXHIGHNY").name)
        self.assertEqual(parsed.target_date, "2026-07-09")
        self.assertEqual(parsed.source_series, "KXHIGHNY")
        # verified station coordinates ride along in raw for the engine.
        self.assertEqual(parsed.raw["ghcnd_id"], station_for_series("KXHIGHNY").ghcnd_id)

    def test_registered_low_series_routes_to_min_metric(self):
        parsed = _kalshi_weather(
            "KXLOWTNYC", "KXLOWTNYC-26JUL09", strike_type="less", cap_strike="70"
        )
        self.assertEqual(parsed.family, "weather.temperature")
        self.assertEqual(parsed.shape, "daily_low_threshold")
        self.assertEqual(parsed.status, "engine_available")
        self.assertEqual(parsed.metric, "temperature_2m_min")

    def test_unmapped_series_is_parse_missing(self):
        parsed = _kalshi_weather("KXWINDNY", "KXWINDNY-26JUL09", strike_type="greater")
        self.assertEqual(parsed.status, "parse_missing")
        self.assertEqual(parsed.shape, "unknown_weather_series")
        self.assertEqual(parsed.source_series, "KXWINDNY")

    def test_recognized_temperature_series_without_station_is_source_missing(self):
        # Starts with KXHIGH so it is recognized as a high-temp series, but it
        # has no verified station coordinates -> source_missing, not silent drop.
        parsed = _kalshi_weather("KXHIGHZZZ", "KXHIGHZZZ-26JUL09", strike_type="greater")
        self.assertEqual(parsed.status, "source_missing")
        self.assertEqual(parsed.metric, "temperature_2m_max")
        self.assertEqual(parsed.shape, "daily_high_threshold")

    def test_registered_series_missing_strike_type_is_parse_missing(self):
        parsed = _kalshi_weather("KXHIGHNY", "KXHIGHNY-26JUL09")  # no strike_type
        self.assertEqual(parsed.status, "parse_missing")
        self.assertIn("strike_type", parsed.reason)

    def test_registered_series_missing_event_ticker_is_parse_missing(self):
        parsed = _kalshi_weather("KXHIGHNY", "", strike_type="greater")
        self.assertEqual(parsed.status, "parse_missing")
        self.assertIn("event_ticker", parsed.reason)


class FreeTextWeatherMetricTests(unittest.TestCase):
    def _text(self, question):
        return parse_market(make_market(venue="limitless", domain="weather", question=question))

    def test_daily_high_text_engine_exists_but_unstructured(self):
        parsed = self._text("Will the daily high in NYC exceed 90F on July 9?")
        self.assertEqual(parsed.family, "weather.temperature")
        self.assertEqual(parsed.shape, "daily_high_threshold")
        self.assertEqual(parsed.metric, "temperature_2m_max")
        # engine exists, but no structured station/date/strike -> parse_missing
        self.assertEqual(parsed.status, "parse_missing")

    def test_snowfall_text_maps_to_precipitation_family(self):
        parsed = self._text("Will it snow more than 2 inches tomorrow?")
        self.assertEqual(parsed.family, "weather.precipitation")
        self.assertEqual(parsed.shape, "daily_snow_threshold")
        self.assertEqual(parsed.metric, "snowfall_sum")
        self.assertEqual(parsed.status, "parse_missing")

    def test_wind_text_engine_exists_but_is_unstructured(self):
        parsed = self._text("Will wind gusts exceed 50 mph during the storm?")
        self.assertEqual(parsed.metric, "wind_gusts_10m_max")
        self.assertEqual(parsed.shape, "daily_wind_threshold")
        self.assertEqual(parsed.status, "parse_missing")

    def test_structured_limitless_weather_routes_to_engine(self):
        market = make_market(venue="limitless", domain="weather", question="NYC wind gust")
        market.raw["weather"] = {"metric": "wind_gusts_10m_max", "latitude": 40.7789,
            "longitude": -73.9692, "timezone": "America/New_York", "target_date": "2026-07-12",
            "strike_type": "greater", "floor_strike": 40, "location": "Central Park",
            "settlement_source": "National Weather Service"}
        parsed = parse_market(market)
        self.assertEqual((parsed.family, parsed.status), ("weather.wind", "engine_available"))
        self.assertEqual(parsed.raw["lat"], 40.7789)

    def test_unparseable_weather_text(self):
        parsed = self._text("Will the weather be pleasant this weekend?")
        self.assertEqual(parsed.shape, "unparsed_weather")
        self.assertEqual(parsed.status, "parse_missing")

    def test_zero_snow_ensemble_has_near_zero_positive_tail(self):
        probability = event_probability("snowfall_sum", [0.0, 0.0, 0.0], "greater", 0.1, None)
        self.assertLess(probability, 0.02)

    def test_dry_mass_is_included_in_less_than_event(self):
        probability = event_probability("precipitation_sum", [0.0, 0.0, 0.2], "less", None, 0.1)
        self.assertGreater(probability, 0.70)

    @patch("rwoo.engines.weather.fetch_model_forecasts", return_value={"a": 0.0, "b": 0.0, "c": 0.0})
    def test_oracle_probability_is_inside_uncertainty_band(self, _fetch):
        result = compute_weather_probability(0, 0, "2026-07-12", "UTC", "greater", 0.1, None,
                                             include_base_rate=False, metric="snowfall_sum")
        self.assertLessEqual(result["prob_low"], result["oracle_prob"])
        self.assertLessEqual(result["oracle_prob"], result["prob_high"])


if __name__ == "__main__":
    unittest.main()
