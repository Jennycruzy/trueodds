"""HTTP API tests — no network.

These exercise the ASP transport, schema, refusal semantics, receipts,
idempotency, payment gate, and error mapping by injecting a fake market fetcher
and evaluator through the app factory. The deterministic engines and real
readers are never called here, so the suite stays offline and fast — the same
discipline the existing parser tests follow.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from rwoo.api.app import create_app
from rwoo.api.config import Settings
from rwoo.api.errors import OracleError
from rwoo.models import CanonicalMarket
from rwoo.scanner import ScanRecord
from tests.support import ASGITestClient


def make_settings(tmp: str, **overrides) -> Settings:
    base = dict(
        api_base_url="http://testserver",
        public_base_url="http://testserver",
        trusted_hosts=["testserver", "localhost"],
        allowed_origins=["http://testserver"],
        decision_ledger_path=Path(tmp) / "decisions.jsonl",
        execution_db_path=Path(tmp) / "execution.sqlite3",
        calibration_report_path=Path(tmp) / "calibration_report.json",
    )
    base.update(overrides)
    return Settings(**base)


def a_market(venue="kalshi", market_id="KXHIGHNY-26JUL12-B85", domain="weather") -> CanonicalMarket:
    return CanonicalMarket(
        venue=venue, market_id=market_id, question="Will NYC high exceed 85F on 2026-07-12?",
        domain=domain, resolution_rule="Official NWS climate report daily maximum temperature.",
        resolution_source="NWS", resolution_time="2026-07-12T23:59:00Z",
        implied_prob=0.53, spread=0.04, fetched_at="2026-07-10T10:00:00+00:00",
        yes_subtitle="Yes", raw={"market": {}},
    )


def priced_record(market) -> ScanRecord:
    return ScanRecord(
        venue=market.venue, market_id=market.market_id, question=market.question,
        domain="weather", family="weather.temperature", shape="daily_maximum",
        coverage_status="actionable", missing=None, implied_prob=market.implied_prob,
        spread=market.spread, oracle_prob=0.71, prob_low=0.64, prob_high=0.77,
        confidence=0.68, side="YES", actionable=True, edge_points=0.18,
        total_friction=0.03, net_edge_points=0.15,
        reason="edge exceeds both the oracle's own uncertainty band and estimated friction",
        method="deterministic weather ensemble",
        why={
            "summary": "3 models span 66-75%", "method": "deterministic weather ensemble",
            "sources": {"open_meteo": "2026-07-10"},
            "model_probabilities": {"gfs": 0.75, "ecmwf": 0.66, "icon": 0.70},
            "model_count": 3, "model_range": [0.66, 0.75], "median_model_probability": 0.70,
            "largest_outlier": {"model": "gfs", "probability": 0.75},
        },
        execution={"yes_bid": 0.51, "yes_ask": 0.55, "side": "YES", "entry_price": 0.55,
                   "side_probability": 0.71, "estimated_fee_per_contract": 0.012,
                   "expected_profit_per_contract": 0.148, "expected_return_on_cost": 0.269},
        event_group_id="weather.temperature:abc123", event_identity={"target_date": "2026-07-12"},
        model_version="weather-ensemble-v2", resolution_rule=market.resolution_rule,
        resolution_source=market.resolution_source, venue_resolution_id=market.market_id,
        resolution_time=market.resolution_time, fetched_at=market.fetched_at,
    )


def client_for(tmp, *, evaluate=None, fetch=None, settings=None):
    settings = settings or make_settings(tmp)
    fetch = fetch or (lambda v, m: a_market(v, m))
    evaluate = evaluate or (lambda market: priced_record(market))
    app = create_app(settings, fetch_market=fetch, evaluate=evaluate)
    return ASGITestClient(app), settings


class CheckMarketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_priced_response_schema_and_numbers(self):
        client, _ = client_for(self.tmp)
        resp = client.post("/v1/check-market", json={"market": {"venue": "kalshi", "market_id": "KX-1"}})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["service"], "rwoo.check_market")
        self.assertEqual(body["status"], "priced")
        self.assertEqual(body["forecast"]["oracle_probability"], 0.71)
        self.assertEqual(body["forecast"]["probability_interval"], [0.64, 0.77])
        self.assertEqual(body["forecast"]["model_version"], "weather-ensemble-v2")
        self.assertTrue(body["forecast"]["model_agreement"]["available"])
        self.assertEqual(body["market_comparison"]["market_probability"], 0.53)
        self.assertTrue(body["market_comparison"]["actionable"])
        self.assertEqual(body["market_comparison"]["side"], "YES")
        self.assertEqual(body["calibration"]["scope"]["probability_band"], "0.7-0.8")

    def test_calibration_context_never_borrows_global_event_count(self):
        report_path = Path(self.tmp) / "calibration_report.json"
        report_path.write_text(json.dumps({
            "independent_resolved_event_groups": 186,
            "model_evidence": {"weather.temperature": {"weather-ensemble-v2": {
                "independent_event_groups": 0,
            }}},
            "promotion_readiness": {},
        }), encoding="utf-8")
        settings = make_settings(self.tmp, calibration_report_path=report_path)
        client, _ = client_for(self.tmp, settings=settings)
        body = client.post(
            "/v1/check-market",
            json={"market": {"venue": "kalshi", "market_id": "KX-1"}},
        ).json()
        self.assertEqual(body["calibration"]["independent_resolved_events"], 0)

    def test_request_id_header_and_no_store(self):
        client, _ = client_for(self.tmp)
        resp = client.post("/v1/check-market", json={"market": {"venue": "kalshi", "market_id": "KX-1"}})
        self.assertTrue(resp.headers.get("X-Request-ID", "").startswith("req_"))
        self.assertEqual(resp.headers.get("Cache-Control"), "no-store")
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")

    def test_client_request_id_is_echoed(self):
        client, _ = client_for(self.tmp)
        resp = client.post("/v1/check-market", json={"market": {"venue": "kalshi", "market_id": "KX-1"}},
                           headers={"X-Request-ID": "req_client_supplied"})
        self.assertEqual(resp.headers.get("X-Request-ID"), "req_client_supplied")
        self.assertEqual(resp.json()["request_id"], "req_client_supplied")

    def test_receipt_is_committed_and_linked(self):
        client, settings = client_for(self.tmp)
        body = client.post("/v1/check-market", json={"market": {"venue": "kalshi", "market_id": "KX-1"}}).json()
        rh = body["receipt"]["record_hash"]
        self.assertEqual(body["receipt"]["sequence"], 1)
        got = client.get(f"/v1/receipts/{rh}")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json()["payload"]["request_id"], body["request_id"])
        verify = client.get(f"/v1/receipts/{rh}/verify").json()
        self.assertTrue(verify["ledger_valid"])
        self.assertTrue(verify["found"])

    def test_missing_receipt_is_404(self):
        client, _ = client_for(self.tmp)
        resp = client.get("/v1/receipts/deadbeef")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"]["code"], "NOT_FOUND")

    def test_idempotency_key_returns_same_receipt(self):
        client, _ = client_for(self.tmp)
        headers = {"Idempotency-Key": "abc"}
        first_response = client.post(
            "/v1/check-market",
            json={"market": {"venue": "kalshi", "market_id": "KX-1"}},
            headers=headers,
        )
        first = first_response.json()
        second = client.post("/v1/check-market", json={"market": {"venue": "kalshi", "market_id": "KX-1"}}, headers=headers).json()
        self.assertEqual(first["receipt"]["record_hash"], second["receipt"]["record_hash"])
        replay = client.post(
            "/v1/check-market",
            json={"market": {"venue": "kalshi", "market_id": "KX-1"}},
            headers=headers,
        )
        self.assertEqual(replay.headers["X-Idempotent-Replay"], "true")
        self.assertEqual(replay.headers["X-Request-ID"], first_response.headers["X-Request-ID"])
        self.assertEqual(replay.json()["request_id"], replay.headers["X-Request-ID"])
        # exactly one receipt was committed
        listing = client.get(f"/v1/receipts/{first['receipt']['record_hash']}").json()
        self.assertEqual(listing["sequence"], 1)

    def test_unknown_entity_fails_closed_not_zero(self):
        # evaluate returns None (no engine) -> refusal, never a silent 0.0
        client, _ = client_for(self.tmp, evaluate=lambda m: None,
                               fetch=lambda v, m: a_market(v, m, domain="other"))
        body = client.post("/v1/check-market", json={"market": {"venue": "kalshi", "market_id": "KX-1"}}).json()
        self.assertEqual(body["status"], "refused")
        self.assertIn(body["reason_code"], {"UNSUPPORTED_MARKET", "ENTITY_UNBOUND", "MODEL_MISSING"})
        self.assertIsNone(body.get("forecast"))  # no fabricated probability
        self.assertIsNone(body.get("market_comparison"))
        self.assertIsNotNone(body["receipt"]["record_hash"])  # refusals are receipted too

    def test_unsupported_venue(self):
        def bad_fetch(v, m):
            raise OracleError("UNSUPPORTED_VENUE", "nope")
        client, _ = client_for(self.tmp, fetch=bad_fetch)
        resp = client.post("/v1/check-market", json={"market": {"venue": "betfair", "market_id": "1"}})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "UNSUPPORTED_VENUE")

    def test_market_not_found(self):
        def missing(v, m):
            raise OracleError("MARKET_NOT_FOUND", "gone")
        client, _ = client_for(self.tmp, fetch=missing)
        resp = client.post("/v1/check-market", json={"market": {"venue": "kalshi", "market_id": "X"}})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"]["code"], "MARKET_NOT_FOUND")

    def test_malformed_request_is_invalid_request(self):
        client, _ = client_for(self.tmp)
        resp = client.post("/v1/check-market", json={"market": {"venue": "kalshi"}})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "INVALID_REQUEST")

    def test_extra_field_rejected(self):
        client, _ = client_for(self.tmp)
        resp = client.post("/v1/check-market",
                           json={"market": {"venue": "kalshi", "market_id": "X"}, "surprise": 1})
        self.assertEqual(resp.status_code, 400)

    def test_idempotency_key_cannot_be_reused_for_changed_request(self):
        client, _ = client_for(self.tmp)
        headers = {"Idempotency-Key": "bound-key"}
        first = client.post(
            "/v1/check-market",
            json={"market": {"venue": "kalshi", "market_id": "A"}},
            headers=headers,
        )
        changed = client.post(
            "/v1/check-market",
            json={"market": {"venue": "kalshi", "market_id": "B"}},
            headers=headers,
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.json()["error"]["code"], "IDEMPOTENCY_CONFLICT")

    def test_body_too_large(self):
        client, _ = client_for(self.tmp, settings=make_settings(self.tmp, max_body_bytes=10))
        resp = client.post("/v1/check-market", json={"market": {"venue": "kalshi", "market_id": "X" * 100}})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "INVALID_REQUEST")


class PaymentGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_disabled_gate_is_noop(self):
        client, _ = client_for(self.tmp)
        resp = client.post("/v1/check-market", json={"market": {"venue": "kalshi", "market_id": "X"}})
        self.assertEqual(resp.status_code, 200)

    def test_enabled_without_settlement_config_fails_closed_at_boot(self):
        # Enabling payments without a configured recipient/asset/network/price
        # must refuse to boot rather than serve a paid endpoint for free.
        from rwoo.api.payment import PaymentConfig

        incomplete = PaymentConfig(enabled=True, mode="facilitator", environment="development")
        with self.assertRaises(RuntimeError):
            create_app(make_settings(self.tmp), fetch_market=lambda v, m: a_market(v, m),
                       evaluate=lambda m: priced_record(m), payment_config=incomplete)


class ExecutionApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def payload(self):
        return {
            "venue": "polymarket", "market_id": "market-1", "token_id": "token-yes",
            "side": "YES", "price": "0.42", "quantity": "2.5",
            "time_in_force": "GTC", "event_group_id": "weather.temperature:abc123",
        }

    def receipt(self, client):
        result = client.post(
            "/v1/check-market",
            json={"market": {"venue": "polymarket", "market_id": "market-1"}},
        ).json()
        return result["receipt"]["record_hash"]

    def test_prepare_requires_idempotency_key_and_is_durable(self):
        client, _ = client_for(self.tmp)
        payload = self.payload()
        payload["decision_receipt_hash"] = self.receipt(client)
        missing = client.post("/v1/executions/prepare", json=payload)
        self.assertEqual(missing.status_code, 400)
        first = client.post("/v1/executions/prepare", json=payload,
                            headers={"Idempotency-Key": "execution-1"})
        second = client.post("/v1/executions/prepare", json=payload,
                             headers={"Idempotency-Key": "execution-1"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["intent_id"], second.json()["intent_id"])
        inspected = client.get(f"/v1/executions/{first.json()['intent_id']}")
        self.assertEqual(inspected.json()["notional"], "1.05")

    def test_submit_fails_closed_by_default(self):
        client, _ = client_for(self.tmp)
        payload = self.payload()
        payload["decision_receipt_hash"] = self.receipt(client)
        prepared = client.post("/v1/executions/prepare", json=payload,
                               headers={"Idempotency-Key": "execution-2"}).json()
        response = client.post(f"/v1/executions/{prepared['intent_id']}/submit",
                               json={"operator_approval_id": "operator-1"})
        self.assertEqual(response.status_code, 423)
        self.assertEqual(response.json()["error"]["code"], "EXECUTION_DISABLED")
        state = client.get(f"/v1/executions/{prepared['intent_id']}").json()
        self.assertEqual(state["state"], "PREPARED")


class CrossVenueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_different_venue_required(self):
        client, _ = client_for(self.tmp, fetch=lambda v, m: a_market(v, m))
        resp = client.post("/v1/cross-venue-edge", json={
            "left": {"venue": "kalshi", "market_id": "A"},
            "right": {"venue": "kalshi", "market_id": "B"},
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "INVALID_REQUEST")

    def test_not_equivalent_is_not_actionable(self):
        def fetch(v, m):
            # two genuinely different questions -> not equivalent
            mk = a_market(v, m)
            mk.question = f"Question for {v} {m}"
            return mk
        client, _ = client_for(self.tmp, fetch=fetch)
        body = client.post("/v1/cross-venue-edge", json={
            "left": {"venue": "kalshi", "market_id": "A"},
            "right": {"venue": "polymarket", "market_id": "B"},
        }).json()
        self.assertFalse(body["actionable"])
        self.assertIn("risk", body["risk_disclosure"].lower())
        self.assertIsNotNone(body["receipt"]["record_hash"])

    def test_cross_venue_error_identifies_the_failing_side(self):
        def fetch(venue, market_id):
            if market_id == "MISSING":
                raise OracleError(
                    "MARKET_NOT_FOUND", "market missing",
                    details={"requested_market_id": market_id},
                )
            return a_market(venue, market_id)

        client, _ = client_for(self.tmp, fetch=fetch)
        response = client.post("/v1/cross-venue-edge", json={
            "left": {"venue": "kalshi", "market_id": "A"},
            "right": {"venue": "polymarket", "market_id": "MISSING"},
        })
        self.assertEqual(response.status_code, 404)
        details = response.json()["error"]["details"]
        self.assertEqual(details["side"], "right")
        self.assertEqual(details["market"], {
            "venue": "polymarket", "market_id": "MISSING",
        })


class OpsAndCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_health_and_ready(self):
        client, _ = client_for(self.tmp)
        self.assertEqual(client.get("/healthz").json()["status"], "ok")
        health = client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), client.get("/healthz").json())
        self.assertEqual(health.headers["Cache-Control"], "no-store")
        ready = client.get("/readyz")
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["status"], "ready")

    def test_cors_exposes_payment_and_idempotency_headers(self):
        client, _ = client_for(self.tmp)
        response = client.get("/health", headers={"Origin": "http://testserver"})
        exposed = response.headers.get("Access-Control-Expose-Headers", "").lower()
        for name in ("payment-required", "payment-response", "www-authenticate", "x-idempotent-replay"):
            self.assertIn(name, exposed)

    def test_version_and_metadata(self):
        client, _ = client_for(self.tmp)
        self.assertEqual(client.get("/version").json()["api_version"], "1.0.0")
        meta = client.get("/v1/service-metadata").json()
        self.assertFalse(meta["execution_enabled"])
        self.assertEqual(len(meta["services"]), 4)
        self.assertFalse(meta["payment"]["enabled"])  # disabled by default
        best = next(svc for svc in meta["services"] if svc["identifier"] == "rwoo.best_signals")
        self.assertEqual(best["command"], "rwoo_best_signals")
        self.assertEqual(best["display_name"], "Best Signals")
        for svc in meta["services"]:
            self.assertIsNone(svc["price_atomic"])  # no price until operator approval

    def test_supported_markets(self):
        client, _ = client_for(self.tmp)
        data = client.get("/v1/supported-markets").json()
        self.assertEqual(set(data["venues"]), {"kalshi", "polymarket", "limitless"})
        self.assertIn("weather.temperature", data["families"])
        self.assertNotIn("energy.commodity_price", data["families"])
        self.assertNotIn("agriculture.commodity_price", data["families"])
        self.assertIn("sports.world_cup", data["sports_families_currently_producing_candidates"])
        coverage = {row["family"]: row for row in data["sports_coverage"]}
        self.assertEqual(coverage["sports.world_cup"]["availability"], "live_signal_candidate")
        self.assertEqual(coverage["sports.nba"]["availability"], "conditional_engine")
        self.assertIn("current_sports_scan", data)
        expansion = {row["family"]: row for row in data["expanded_market_coverage"]}
        self.assertEqual(expansion["weather.hurricane_season"]["availability"], "live_signal_candidate")
        self.assertEqual(expansion["energy.henry_hub_spot"]["availability"], "live_signal_candidate")
        self.assertNotIn("agriculture.commodity_price", expansion)
        telemetry = data["internal_discovery_telemetry"]
        self.assertTrue(telemetry["not_product_capabilities"])
        internal = {row["family"]: row for row in telemetry["coverage"]}
        self.assertEqual(
            internal["agriculture.commodity_price"]["availability"],
            "exact_settlement_source_not_integrated",
        )

    def test_market_candidates_returns_current_resubmittable_ids(self):
        scan_path = Path(self.tmp) / "scan.json"
        scan_path.write_text(json.dumps({
            "created_at": datetime.now(timezone.utc).isoformat(),
            "top": [
                {"venue": "polymarket", "market_id": "0xabc", "question": "Fed decision",
                 "family": "economics.fed_rates", "market_status": "active"},
                {"venue": "polymarket", "market_id": "0xclosed", "question": "Old Fed",
                 "family": "economics.fed_rates", "market_status": "closed"},
            ],
        }), encoding="utf-8")
        client, _ = client_for(
            self.tmp,
            settings=make_settings(self.tmp, opportunity_scan_path=scan_path),
        )
        response = client.get("/v1/market-candidates?venue=polymarket&query=fed")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["candidates"][0]["market_id"], "0xabc")
        self.assertEqual(response.json()["count"], 1)

    def test_market_candidates_uses_live_fallback_when_scan_is_missing(self):
        missing = Path(self.tmp) / "missing-scan.json"
        client, _ = client_for(
            self.tmp,
            settings=make_settings(self.tmp, opportunity_scan_path=missing),
        )
        live = [{
            "venue": "polymarket", "market_id": "0xlive", "question": "Live Fed market",
            "family": None, "market_status": "active", "trading_close_time": None,
        }]
        with patch("rwoo.api.app.discover_live_candidates", return_value=(live, [])):
            response = client.get("/v1/market-candidates?venue=polymarket&query=fed")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "live_venue_fallback")
        self.assertEqual(response.json()["freshness_status"], "live")
        self.assertEqual(response.json()["candidates"][0]["market_id"], "0xlive")

    def test_market_candidates_returns_actionable_503_only_if_all_live_sources_fail(self):
        missing = Path(self.tmp) / "missing-scan.json"
        client, _ = client_for(
            self.tmp,
            settings=make_settings(self.tmp, opportunity_scan_path=missing),
        )
        errors = [
            {"venue": venue, "reason": "live_discovery_failed", "error_type": "ConnectError"}
            for venue in ("kalshi", "polymarket", "limitless")
        ]
        with patch("rwoo.api.app.discover_live_candidates", return_value=([], errors)):
            response = client.get("/v1/market-candidates")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "SOURCE_UNAVAILABLE")
        self.assertTrue(response.json()["error"]["details"]["retryable"])

    def test_calibration_empty_state_is_honest(self):
        client, _ = client_for(self.tmp)  # report file does not exist
        cal = client.get("/v1/calibration").json()
        self.assertFalse(cal["report_available"])
        self.assertEqual(cal["status"], "insufficient_evidence")
        self.assertEqual(cal["independent_resolved_event_groups"], 0)

    def test_calibration_reads_live_report_not_hardcoded(self):
        import json
        report = {
            "created_at": "2026-07-10T00:00:00+00:00",
            "precommitted_forecasts": 12, "resolved_forecasts": 5,
            "independent_resolved_event_groups": 4,
            "calibration": {"overall": {"count": 5, "brier_score": 0.19}},
            "promotion_readiness": {"weather.temperature": {
                "independent_event_groups": 4, "eligible": False, "next_checkpoint": 30,
                "criteria": {"independent_groups_at_least_30": False}}},
            "ledger_verification": {"valid": True},
        }
        path = Path(self.tmp) / "calibration_report.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        client, _ = client_for(self.tmp)
        cal = client.get("/v1/calibration").json()
        self.assertTrue(cal["report_available"])
        self.assertEqual(cal["precommitted_forecasts"], 12)
        self.assertEqual(cal["independent_resolved_event_groups"], 4)
        fam = client.get("/v1/calibration/weather.temperature").json()
        self.assertIn("weather.temperature", fam["families"])

    def test_calibration_model_route_is_exact_not_aggregate(self):
        import json
        v2 = {
            "model_version": "weather-ensemble-v2", "evidence_type": "prospective_exact_model_version",
            "precommitted_contract_rows": 20, "resolved_contract_rows": 12,
            "unresolved_contract_rows": 8, "independent_event_groups": 3,
            "calibration": {"count": 12, "brier_score": .13, "max_calibration_gap": .1},
            "precommitted_by_probability_band": {"0.1-0.2": 7},
            "calibration_by_probability_band": {"0.1-0.2": {"count": 5, "brier_score": .11}},
            "probability_band_gate": {"bands": [{"bucket": "0.1-0.2",
                "independent_event_groups": 2}]},
        }
        v3 = {
            "model_version": "weather-ensemble-v3-power-calibrated",
            "evidence_type": "prospective_exact_model_version",
            "precommitted_contract_rows": 9, "resolved_contract_rows": 0,
            "unresolved_contract_rows": 9, "independent_event_groups": 0, "calibration": None,
        }
        report = {
            "created_at": "2026-07-13T00:00:00+00:00", "precommitted_forecasts": 99,
            "resolved_forecasts": 50, "independent_resolved_event_groups": 10,
            "calibration": {"overall": {"count": 50}},
            "promotion_readiness": {"weather.temperature": {
                "model_version": "weather-ensemble-v3-power-calibrated", "eligible": False,
                "independent_event_groups": 0,
            }},
            "model_evidence": {"weather.temperature": {
                "weather-ensemble-v2": v2,
                "weather-ensemble-v3-power-calibrated": v3,
            }},
            "retrospective_validation": {"weather.temperature": {
                "target_model_version": "weather-ensemble-v3-power-calibrated",
                "source_model_version": "weather-ensemble-v2", "independent_event_groups": 3,
                "counts_toward_prospective_promotion": False,
            }},
        }
        path = Path(self.tmp) / "calibration_report.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        client, _ = client_for(self.tmp)

        exact = client.get("/v1/calibration/weather.temperature/weather-ensemble-v2").json()
        self.assertEqual(exact["resolved_forecasts"], 12)
        self.assertEqual(exact["independent_resolved_event_groups"], 3)
        self.assertEqual(exact["calibration"]["count"], 12)
        self.assertEqual(set(exact["model_evidence"]["weather.temperature"]), {"weather-ensemble-v2"})
        self.assertEqual(exact["retrospective_validation"]["weather.temperature"]["source_model_version"],
                         "weather-ensemble-v2")
        band = client.get(
            "/v1/calibration/weather.temperature/weather-ensemble-v2?probability_band=0.1-0.2"
        ).json()
        self.assertEqual(band["resolved_forecasts"], 5)
        self.assertEqual(band["unresolved_forecasts"], 2)
        self.assertEqual(band["independent_resolved_event_groups"], 2)
        self.assertEqual(band["calibration"]["brier_score"], .11)

    def test_unknown_calibration_scope_returns_actionable_404(self):
        client, _ = client_for(self.tmp)
        family = client.get("/v1/calibration/not.a.family")
        self.assertEqual(family.status_code, 404)
        self.assertIn(
            "weather.temperature",
            family.json()["error"]["details"]["available_families"],
        )
        model = client.get("/v1/calibration/weather.temperature/not-a-version")
        self.assertEqual(model.status_code, 404)
        self.assertIn(
            "weather-ensemble-v3-power-calibrated",
            model.json()["error"]["details"]["available_model_versions"],
        )

    def test_invalid_probability_band_returns_candidates(self):
        client, _ = client_for(self.tmp)
        response = client.get("/v1/calibration?probability_band=70-80")
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "0.7-0.8",
            response.json()["error"]["details"]["available_probability_bands"],
        )

    def test_evidence_status(self):
        client, _ = client_for(self.tmp)
        data = client.get("/v1/evidence/status").json()
        self.assertFalse(data["execution_enabled"])
        self.assertTrue(data["decision_ledger_verification"]["valid"])

    def test_openapi_servers_from_config(self):
        client, _ = client_for(self.tmp)
        schema = client.get("/openapi.json").json()
        self.assertEqual(schema["servers"], [{"url": "http://testserver"}])
        self.assertIn("/v1/check-market", schema["paths"])
        check = schema["paths"]["/v1/check-market"]["post"]
        self.assertIn("market` as an object", check["description"])
        self.assertIn("404", check["responses"])
        market_schema = schema["components"]["schemas"]["CheckMarketRequest"]
        self.assertIn("market", market_schema["required"])
        self.assertIn("venue and market_id", market_schema["properties"]["market"]["description"])
        cross = schema["paths"]["/v1/cross-venue-edge"]["post"]
        self.assertIn("left` and `right", cross["description"])
        self.assertIn("503", cross["responses"])
        calibration = schema["paths"]["/v1/calibration"]["get"]
        self.assertEqual(calibration["operationId"], "rwoo_get_calibration")
        self.assertIn("CalibrationResponse", json.dumps(calibration))
        self.assertEqual(schema["paths"]["/v1/signals"]["post"]["operationId"],
                         "rwoo_best_signals")


if __name__ == "__main__":
    unittest.main()
