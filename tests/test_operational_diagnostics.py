from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rwoo.edge_audit import audit_scan, write_audit
from rwoo.evidence import EvidenceStore, write_backlog
from tests.test_evidence_pipeline import priced_record


def edge_row(**updates):
    row = priced_record(
        event_identity={
            "target_date": "2026-07-15",
            "metric": "temperature_2m_max",
            "station_ghcnd_id": "GHCND:USW00094728",
            "strike_type": "greater",
            "floor_strike": 80,
            "cap_strike": None,
        },
        oracle_prob=.80,
        prob_low=.74,
        prob_high=.86,
        implied_prob=.20,
        spread=.02,
        side="YES",
        net_edge_points=.58,
        execution={
            "yes_bid": .19,
            "yes_ask": .21,
            "side": "YES",
            "entry_price": .21,
            "side_probability": .80,
            "estimated_fee_per_contract": .01,
            "expected_profit_per_contract": .58,
        },
        source_timestamp="2026-07-14T09:55:00+00:00",
        trading_close_time="2026-07-15T18:00:00+00:00",
    )
    row.update(updates)
    return row


class EvidenceBacklogDiagnosticsTests(unittest.TestCase):
    def test_backlog_reports_exact_model_stages_without_writing(self):
        now = datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp) / "evidence.jsonl")
            store.collect_scan({"top": [
                priced_record(
                    market_id="DUE",
                    event_group_id="weather.temperature:due",
                    resolution_time="2026-07-14T10:00:00Z",
                ),
                priced_record(
                    market_id="FUTURE",
                    event_group_id="weather.temperature:future",
                    resolution_time="2026-07-15T10:00:00Z",
                ),
                priced_record(
                    market_id="RESOLVED",
                    event_group_id="weather.temperature:resolved",
                    resolution_time="2026-07-14T09:00:00Z",
                ),
            ]})
            resolved_key = next(
                row.payload["snapshot_key"] for row in store._records("forecast_precommit")
                if row.payload["market_id"] == "RESOLVED"
            )
            store.ledger.append("forecast_resolution", {
                "snapshot_key": resolved_key,
                "event_group_id": "weather.temperature:resolved",
                "outcome": 1,
                "closing_market_implied_prob": .55,
            })
            store.ledger.append("official_source_verification", {
                "snapshot_key": resolved_key,
                "event_group_id": "weather.temperature:resolved",
                "status": "resolved",
                "concordant": True,
            })
            before = store.ledger.verify()["record_count"]
            result = store.backlog(
                family="weather.temperature",
                model_version="weather-ensemble-v3-power-calibrated",
                now=now,
                latest_report={"created_at": (now - timedelta(hours=1)).isoformat()},
            )
            self.assertEqual(result["precommitted"]["contract_rows"], 3)
            self.assertEqual(result["eligible_to_resolve"]["contract_rows"], 1)
            self.assertEqual(result["eligible_at_last_evidence_run"]["contract_rows"], 1)
            self.assertEqual(result["waiting_for_resolution_time"]["contract_rows"], 1)
            self.assertEqual(result["venue_resolved"]["contract_rows"], 1)
            self.assertEqual(result["waiting_for_official_source"]["contract_rows"], 0)
            self.assertEqual(result["officially_verified"]["contract_rows"], 1)
            self.assertEqual(result["quote_coverage"]["pre_cutoff_quote_contracts"], 3)
            self.assertEqual(result["quote_coverage"]["resolved_with_closing_quote_contracts"], 1)
            self.assertEqual(result["oldest_eligible_forecast"]["market_id"], "DUE")
            self.assertEqual(store.ledger.verify()["record_count"], before)

    def test_backlog_flags_a_stale_report_without_writing(self):
        now = datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp) / "evidence.jsonl")
            result = store.backlog(
                now=now,
                latest_report={"created_at": (now - timedelta(hours=8)).isoformat()},
                max_report_age_hours=7,
            )
            self.assertEqual(result["status"], "attention")
            self.assertTrue(any("stale" in warning for warning in result["warnings"]))
            self.assertEqual(store.ledger.verify()["record_count"], 0)

    def test_backlog_artifact_write_is_atomic_and_derived_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "public" / "backlog.json"
            write_backlog({"status": "ok", "precommitted": {"contract_rows": 3}}, path)
            self.assertEqual(path.read_text(encoding="utf-8").count('"status"'), 1)
            self.assertFalse(path.with_suffix(".json.tmp").exists())


class LargeEdgeAuditTests(unittest.TestCase):
    def test_consistent_large_edge_passes_structural_audit(self):
        result = audit_scan({"created_at": "2026-07-14T10:00:00Z", "top": [edge_row()]})
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["structural_failures"], 0)

    def test_side_and_entry_inconsistencies_are_reported(self):
        broken = edge_row(
            side="NO",
            execution={
                "yes_bid": .19,
                "yes_ask": .21,
                "side": "NO",
                "entry_price": .21,
                "side_probability": .80,
                "estimated_fee_per_contract": .01,
                "expected_profit_per_contract": .58,
            },
        )
        result = audit_scan({"created_at": "2026-07-14T10:00:00Z", "top": [broken]})
        issues = result["rows"][0]["issues"]
        self.assertEqual(result["status"], "fail")
        self.assertTrue(any("expected YES" in issue for issue in issues))
        self.assertTrue(any("entry price" in issue for issue in issues))

    def test_edge_audit_artifact_write_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "public" / "edge-audit.json"
            write_audit({"status": "pass", "audited_rows": 30}, path)
            self.assertIn('"audited_rows": 30', path.read_text(encoding="utf-8"))
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
