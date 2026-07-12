"""Public site tests — no network.

Renders every page against controlled temp artifacts and asserts that shown
metrics come from the artifacts (never hardcoded), that missing artifacts render
honest empty states, and that accessibility basics hold.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from rwoo.api.config import Settings
from rwoo.site.app import create_site

ROUTES = ["/", "/docs", "/playground", "/calibration", "/markets", "/receipts",
          "/methodology", "/status", "/privacy", "/terms",
          "/robots.txt", "/sitemap.xml", "/favicon.svg", "/healthz"]


def settings_for(tmp: str, *, scan=None, report=None, **overrides) -> Settings:
    d = Path(tmp)
    scan_path = d / "opportunity_scan_latest.json"
    report_path = d / "calibration_report_latest.json"
    if scan is not None:
        scan_path.write_text(json.dumps(scan), encoding="utf-8")
    if report is not None:
        report_path.write_text(json.dumps(report), encoding="utf-8")
    base = dict(
        api_base_url="http://api.testserver", public_base_url="http://testserver",
        opportunity_scan_path=scan_path, calibration_report_path=report_path,
        decision_ledger_path=d / "decisions.jsonl",
    )
    base.update(overrides)
    return Settings(**base)


def a_scan(question="Will NYC high exceed 85F on 2026-07-12?"):
    return {
        "created_at": "2026-07-10T12:00:00+00:00",
        "markets_seen": 4210, "markets_evaluated": 130, "markets_included": 44, "actionable_count": 3,
        "venue_counts": {"kalshi": 30, "polymarket": 10, "limitless": 4},
        "domain_counts": {"weather": 20, "economics": 15, "sports": 9},
        "coverage_status_counts": {"actionable": 3, "wait": 41},
        "top": [{
            "venue": "kalshi", "market_id": "KX-1", "question": question,
            "domain": "weather", "family": "weather.temperature",
            "oracle_prob": 0.71, "prob_low": 0.64, "prob_high": 0.77, "confidence": 0.68,
            "implied_prob": 0.53, "spread": 0.04, "side": "YES", "actionable": True,
            "edge_points": 0.18, "reason": "edge clears uncertainty and friction",
            "why": {"summary": "3 models agree", "model_probabilities": {"gfs": 0.75, "ecmwf": 0.66}},
        }],
    }


def a_report():
    return {
        "created_at": "2026-07-10T00:00:00+00:00",
        "precommitted_forecasts": 12, "resolved_forecasts": 5, "unresolved_forecasts": 7,
        "independent_resolved_event_groups": 4,
        "calibration": {"overall": {"count": 5, "brier_score": 0.191, "max_calibration_gap": 0.12,
                                    "reliability": [{"bucket": "0.6-0.7", "count": 3, "mean_predicted": 0.65, "actual_hit_rate": 0.67}]}},
        "promotion_readiness": {"weather.temperature": {
            "independent_event_groups": 4, "eligible": False, "next_checkpoint": 30,
            "official_source_concordance_rate": 1.0, "official_source_checks": 4,
            "criteria": {"independent_groups_at_least_30": False}}},
        "ledger_verification": {"valid": True, "record_count": 24},
        "selection_policy": "all priced records precommitted; losses retained",
    }


def client(settings):
    return TestClient(create_site(settings))


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_all_routes_200(self):
        c = client(settings_for(self.tmp, scan=a_scan()))
        for r in ROUTES:
            self.assertEqual(c.get(r).status_code, 200, r)

    def test_security_headers(self):
        c = client(settings_for(self.tmp))
        h = c.get("/").headers
        self.assertEqual(h.get("X-Content-Type-Options"), "nosniff")

    def test_accessibility_basics(self):
        c = client(settings_for(self.tmp, scan=a_scan()))
        for r in ["/", "/docs", "/calibration", "/markets", "/status"]:
            html = c.get(r).text
            self.assertIn('lang="en"', html, r)
            self.assertIn("Skip to content", html, r)
            self.assertIn("<h1", html, r)


class LiveDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_landing_shows_real_example_from_scan(self):
        q = "Will Berlin exceed 30C on 2026-08-01?"
        c = client(settings_for(self.tmp, scan=a_scan(question=q)))
        html = c.get("/").text
        self.assertIn(q, html)          # the real question, verbatim
        self.assertIn("71.0%", html)    # oracle_prob from the artifact, not hardcoded
        self.assertIn("weather-ensemble-v3-power-calibrated", html)  # model version derived from family

    def test_landing_empty_when_no_scan(self):
        c = client(settings_for(self.tmp))  # no scan file
        html = c.get("/").text
        self.assertIn("never fabricates a verdict", html.lower())

    def test_markets_reflects_scan_counts(self):
        c = client(settings_for(self.tmp, scan=a_scan()))
        html = c.get("/markets").text
        self.assertIn("4210", html)  # markets_seen from artifact
        self.assertIn("44", html)    # markets_included

    def test_calibration_empty_state_honest(self):
        c = client(settings_for(self.tmp))  # no report
        html = c.get("/calibration").text
        self.assertIn("accumulating", html.lower())
        self.assertIn("No calibration report", html)

    def test_calibration_renders_report(self):
        c = client(settings_for(self.tmp, report=a_report()))
        html = c.get("/calibration").text
        self.assertIn("0.191", html)   # brier from artifact
        self.assertIn("weather.temperature", html)
        self.assertIn("Evidence ledger verified", html)

    def test_no_none_leak_in_cells(self):
        import re
        c = client(settings_for(self.tmp, scan=a_scan(), report=a_report()))
        for r in ["/", "/calibration", "/markets", "/status"]:
            html = c.get(r).text
            self.assertEqual(len(re.findall(r">\s*None\s*<", html)), 0, r)


class LegalPagesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_privacy_terms_pending_without_entity(self):
        c = client(settings_for(self.tmp, legal_entity=""))
        self.assertIn("Operator identity pending", c.get("/privacy").text)
        self.assertIn("Operator identity pending", c.get("/terms").text)

    def test_privacy_names_entity_when_configured(self):
        c = client(settings_for(self.tmp, legal_entity="Example Oracle Ltd"))
        self.assertIn("Example Oracle Ltd", c.get("/privacy").text)


if __name__ == "__main__":
    unittest.main()
