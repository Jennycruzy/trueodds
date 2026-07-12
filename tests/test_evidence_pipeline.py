import tempfile
import unittest
from pathlib import Path

from rwoo.evidence import EvidenceStore
from rwoo.identity import event_identity
from dataclasses import replace
from tests.support import make_market


def priced_record(**updates):
    row = {
        "venue": "kalshi", "market_id": "KXTEST-1", "question": "Will test resolve yes?",
        "domain": "weather", "family": "weather.temperature", "shape": "daily_maximum",
        "model_version": "weather-ensemble-v3-power-calibrated", "event_group_id": "weather.temperature:event1",
        "event_identity": {"target_date": "2026-07-12", "location": "NYC"},
        "fetched_at": "2026-07-10T10:00:00+00:00", "resolution_time": "2026-07-13T00:00:00Z",
        "resolution_rule": "Official rule", "resolution_source": "NOAA/NWS",
        "oracle_prob": .7, "prob_low": .65, "prob_high": .75, "confidence": .7,
        "implied_prob": .5, "spread": .02, "actionable": True, "side": "YES",
        "execution": {"entry_price": .51}, "why": {"summary": "models agree"},
    }
    row.update(updates)
    return row


class FakeResponse:
    def __init__(self, market): self.market = market
    def raise_for_status(self): return None
    def json(self): return {"market": self.market}


class FakeClient:
    def __init__(self, market): self.market = market
    def get(self, url): return FakeResponse(self.market)


class OfficialClient(FakeClient):
    def get(self, url, params=None, headers=None):
        if "ncei.noaa.gov" in url:
            response = FakeResponse({})
            response.json = lambda: [{"TMAX": "82"}]
            response.url = url
            return response
        return super().get(url)


class EvidencePipelineTests(unittest.TestCase):
    def test_strike_buckets_share_one_underlying_event_group(self):
        raw = {"market": {"event_ticker": "KXHIGHNY-26JUL12", "series_ticker": "KXHIGHNY",
                          "strike_type": "greater", "floor_strike": 80}}
        first = make_market(venue="kalshi", domain="weather", question="NYC high", raw=raw)
        second_raw = {"market": {**raw["market"], "floor_strike": 90}}
        second = replace(first, market_id="TEST-2", raw=second_raw)
        one = event_identity(first, "weather.temperature", "daily_maximum")
        two = event_identity(second, "weather.temperature", "daily_maximum")
        self.assertEqual(one["event_group_id"], two["event_group_id"])
        self.assertNotEqual(one["event_identity"]["floor_strike"], two["event_identity"]["floor_strike"])

    def test_daily_snapshot_deduplicates_same_market_and_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp) / "evidence.jsonl")
            first = store.collect_scan({"top": [priced_record()]})
            second = store.collect_scan({"top": [priced_record(fetched_at="2026-07-10T20:00:00+00:00")]})
            self.assertEqual(first["appended"], 1)
            self.assertEqual(second["appended"], 0)
            self.assertEqual(second["duplicates_skipped"], 1)

    def test_finalized_market_resolves_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp) / "evidence.jsonl")
            store.collect_scan({"top": [priced_record()]})
            result = store.resolve_pending(FakeClient({"status": "finalized", "result": "yes"}))
            self.assertEqual(result["resolved"], 1)
            report = store.report()
            self.assertEqual(report["resolved_forecasts"], 1)
            self.assertEqual(report["independent_resolved_event_groups"], 1)
            self.assertTrue(report["ledger_verification"]["valid"])
            weather = report["promotion_readiness"]["weather.temperature"]
            self.assertEqual(weather["model_version"], "weather-ensemble-v3-power-calibrated")
            self.assertEqual(weather["execution_interlock"], "locked")
            self.assertIn("market_and_paper_performance", weather)
            self.assertIn("drift_monitoring", weather)

    def test_open_market_remains_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp) / "evidence.jsonl")
            store.collect_scan({"top": [priced_record()]})
            result = store.resolve_pending(FakeClient({"status": "open", "result": ""}))
            self.assertEqual(result["pending"], 1)
            self.assertEqual(store.report()["resolved_forecasts"], 0)

    def test_official_weather_check_retries_after_venue_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp) / "evidence.jsonl")
            identity = {
                "target_date": "2026-07-12", "metric": "temperature_2m_max",
                "station_ghcnd_id": "GHCND:USW00094728", "strike_type": "greater",
                "floor_strike": 80, "cap_strike": None,
            }
            store.collect_scan({"top": [priced_record(event_identity=identity)]})
            store.resolve_pending(OfficialClient({"status": "finalized", "result": "yes"}))
            result = store.verify_official_sources(OfficialClient({}))
            self.assertEqual(result["resolved"], 1)
            promotion = store.report()["promotion_readiness"]["weather.temperature"]
            self.assertEqual(promotion["official_source_checks"], 1)
            self.assertEqual(promotion["official_source_concordance_rate"], 1.0)
            self.assertEqual(store.verify_official_sources(OfficialClient({}))["checked"], 0)

    def test_nonpriced_records_are_not_precommitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp) / "evidence.jsonl")
            result = store.collect_scan({"top": [priced_record(oracle_prob=None)]})
            self.assertEqual(result["appended"], 0)


if __name__ == "__main__":
    unittest.main()
