"""Weather-market parsing: Kalshi series/station routing and free-text metrics.

Covers the Kalshi structured path (`_parse_kalshi_weather_market`): registered
series route to verified station coordinates and a target date parsed from the
event ticker; unmapped or unregistered series surface explicit missing statuses.
Also covers the free-text metric classifier used for non-Kalshi venues.
"""
import unittest

from rwoo.parsers import parse_market
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

    def test_wind_text_is_model_missing(self):
        parsed = self._text("Will wind gusts exceed 50 mph during the storm?")
        self.assertEqual(parsed.metric, "wind_or_storm")
        self.assertEqual(parsed.shape, "wind_or_storm_threshold")
        # no wind engine wired -> model_missing
        self.assertEqual(parsed.status, "model_missing")

    def test_unparseable_weather_text(self):
        parsed = self._text("Will the weather be pleasant this weekend?")
        self.assertEqual(parsed.shape, "unparsed_weather")
        self.assertEqual(parsed.status, "parse_missing")


if __name__ == "__main__":
    unittest.main()
