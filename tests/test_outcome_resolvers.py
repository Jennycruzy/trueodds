import tempfile
import unittest
from pathlib import Path

from rwoo.evidence import EvidenceStore
from rwoo.official_outcomes import event_happened, resolve_weather_from_noaa
from tests.test_evidence_pipeline import priced_record


class Response:
    def __init__(self, data): self.data = data; self.url = "https://official.test/result"
    def raise_for_status(self): return None
    def json(self): return self.data


class RoutingClient:
    def __init__(self, responses): self.responses = responses
    def get(self, url, **kwargs):
        for needle, response in self.responses.items():
            if needle in url: return Response(response)
        raise AssertionError(f"unexpected URL {url}")


class OutcomeResolverTests(unittest.TestCase):
    def _resolve(self, record, responses):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp) / "evidence.jsonl")
            store.collect_scan({"top": [record]})
            result = store.resolve_pending(RoutingClient(responses))
            return result, store.report()

    def test_polymarket_closed_winner(self):
        record = priced_record(venue="polymarket", market_id="condition", venue_resolution_id="123")
        result, report = self._resolve(record, {"polymarket": {"closed": True, "outcomes": '["Yes","No"]', "outcomePrices": '["1","0"]'}})
        self.assertEqual(result["resolved"], 1)
        self.assertEqual(report["resolved_forecasts"], 1)

    def test_limitless_resolved_winner(self):
        record = priced_record(venue="limitless", market_id="condition", venue_resolution_id="slug")
        result, _ = self._resolve(record, {"limitless": {"status": "RESOLVED", "winningOutcome": "YES"}})
        self.assertEqual(result["resolved"], 1)

    def test_noaa_weather_concordance(self):
        identity = {"station_ghcnd_id": "GHCND:USW00094728", "target_date": "2026-07-10",
                    "metric": "temperature_2m_max", "strike_type": "greater", "floor_strike": 85, "cap_strike": None}
        result = resolve_weather_from_noaa(identity, RoutingClient({"ncei": [{"TMAX": "91"}]}))
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["outcome"], 1)

    def test_range_boundaries_are_inclusive(self):
        self.assertTrue(event_happened(90, "between", 90, 91))
        self.assertTrue(event_happened(91, "between", 90, 91))


if __name__ == "__main__":
    unittest.main()
