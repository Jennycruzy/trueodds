from __future__ import annotations

import json
import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from rwoo.api.app import create_app
from tests.test_api import make_settings


class SignalEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        now = datetime.now(timezone.utc)
        self.scan = Path(self.tmp) / "scan.json"
        self.calibration = Path(self.tmp) / "calibration.json"
        row = {
            "venue": "kalshi", "market_id": "KX-OPEN", "question": "Will it be hot?",
            "domain": "weather", "family": "weather.temperature", "actionable": True,
            "side": "YES", "oracle_prob": .7, "prob_low": .64, "prob_high": .76,
            "implied_prob": .5, "spread": .04, "net_edge_points": .14, "confidence": .7,
            "execution": {"entry_price": .52, "expected_profit_per_contract": .16},
            "trading_close_time": (now + timedelta(hours=4)).isoformat(), "market_status": "open",
            "fetched_at": (now - timedelta(minutes=2)).isoformat(),
            "source_timestamp": (now - timedelta(minutes=10)).isoformat(),
            "model_version": "weather-ensemble-v3-power-calibrated",
            "event_identity": {"target_date": now.date().isoformat()},
        }
        near = dict(row, market_id="KX-NEAR", trading_close_time=(now + timedelta(minutes=5)).isoformat())
        world_cup = dict(
            row, venue="polymarket", market_id="WC-OPEN",
            question="Will Brazil win the 2026 FIFA World Cup?", domain="sports",
            family="sports.world_cup", model_version="world-cup-live-bracket-elo-v2",
        )
        self.scan.write_text(json.dumps({"created_at": now.isoformat(), "top": [near, row, world_cup]}))
        self.calibration.write_text(json.dumps({"promotion_readiness": {"weather.temperature": {
            "model_version": "weather-ensemble-v3-power-calibrated", "independent_event_groups": 0,
            "eligible": False,
        }}, "retrospective_validation": {"weather.temperature": {
            "target_model_version": "weather-ensemble-v3-power-calibrated",
            "source_model_version": "weather-ensemble-v2", "independent_event_groups": 160,
            "contract_rows": 1200, "transformed_calibration": {"brier_score": .1201},
            "grouped_walk_forward": {"improved": True},
            "counts_toward_prospective_promotion": False,
        }}}))
        settings = make_settings(self.tmp, opportunity_scan_path=self.scan,
                                 calibration_report_path=self.calibration)
        self.app = create_app(settings)

    def request(self, method: str, path: str, **kwargs):
        async def call():
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.request(method, path, **kwargs)
        return asyncio.run(call())

    def test_natural_language_returns_ranked_open_signal(self):
        response = self.request("POST", "/v1/signals", json={"message": "Give me the best weather signals now"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([row["market_id"] for row in body["signals"]], ["KX-OPEN"])
        self.assertEqual(body["filters"]["rejected"]["near_close"], 1)
        self.assertFalse(body["signals"][0]["execution_recommended"])
        self.assertEqual(body["signals"][0]["risk_label"], "experimental_current_model")
        retrospective = body["signals"][0]["retrospective_validation"]
        self.assertEqual(retrospective["independent_event_groups"], 160)
        self.assertTrue(retrospective["walk_forward_improved"])
        self.assertFalse(retrospective["counts_toward_prospective_promotion"])
        self.assertIsNotNone(body["signals"][0]["signal_expires_at"])
        self.assertIsNotNone(body["signals"][0]["quote_timestamp"])
        self.assertIsNotNone(body["signals"][0]["source_timestamp"])

    def test_cursor_pages_stable_scan_results(self):
        first = self.request("POST", "/v1/signals", json={"message": "best signals", "limit": 1}).json()
        self.assertEqual(first["pagination"]["total_matching"], 2)
        cursor = first["pagination"]["next_cursor"]
        self.assertIsNotNone(cursor)
        second = self.request("POST", "/v1/signals", json={
            "message": "best signals", "limit": 1, "cursor": cursor,
        }).json()
        self.assertEqual(second["signals"][0]["rank"], 2)
        self.assertIsNone(second["pagination"]["next_cursor"])

    def test_root_text_compatibility(self):
        response = self.request("POST", "/", json={"message": "best signals"})
        self.assertEqual(response.status_code, 200)

    def test_world_cup_request_filters_exact_sports_family(self):
        response = self.request("POST", "/v1/signals", json={"message": "Give me the best World Cup signals"})
        body = response.json()
        self.assertEqual([row["market_id"] for row in body["signals"]], ["WC-OPEN"])
        self.assertEqual(body["filters"]["domain"], "sports")
        self.assertEqual(body["filters"]["family"], "sports.world_cup")

    def test_basketball_request_does_not_substitute_another_signal(self):
        response = self.request("POST", "/v1/signals", json={"message": "Give me basketball odds"})
        body = response.json()
        self.assertEqual(body["status"], "no_signal")
        self.assertEqual(body["signals"], [])
        self.assertEqual(body["filters"]["family"], "sports.nba")

    def test_hurricane_request_filters_exact_weather_family(self):
        response = self.request("POST", "/v1/signals", json={"message": "best hurricane signals"})
        body = response.json()
        self.assertEqual(body["status"], "no_signal")
        self.assertEqual(body["filters"]["domain"], "weather")
        self.assertEqual(body["filters"]["family"], "weather.hurricane_season")

    def test_natural_gas_request_filters_exact_energy_family(self):
        response = self.request("POST", "/v1/signals", json={"message": "best Henry Hub natural gas signals"})
        body = response.json()
        self.assertEqual(body["status"], "no_signal")
        self.assertEqual(body["filters"]["domain"], "commodities")
        self.assertEqual(body["filters"]["family"], "energy.henry_hub_spot")

    def test_stale_scan_fails_closed(self):
        data = json.loads(self.scan.read_text())
        data["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.scan.write_text(json.dumps(data))
        response = self.request("POST", "/v1/signals", json={"message": "best signals"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "SIGNALS_STALE")

    def test_elapsed_weather_day_is_not_a_signal_even_if_trading_remains_open(self):
        data = json.loads(self.scan.read_text())
        for row in data["top"]:
            if row.get("family") == "weather.temperature":
                row["event_identity"] = {
                    "target_date": (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat(),
                }
        self.scan.write_text(json.dumps(data))
        body = self.request("POST", "/v1/signals", json={
            "message": "Give me the best weather signals now",
        }).json()
        self.assertEqual(body["status"], "no_signal")
        self.assertGreaterEqual(body["filters"]["rejected"]["event_elapsed"], 1)


if __name__ == "__main__":
    unittest.main()
