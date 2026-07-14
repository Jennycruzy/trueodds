from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rwoo.closing_quotes import capture_quotes
from rwoo.evidence import EvidenceStore
from rwoo.receipts import AppendOnlyLedger
from rwoo.readers import kalshi
from tests.test_evidence_pipeline import priced_record


def scan_row(now: datetime, **updates):
    row = priced_record(
        fetched_at=(now - timedelta(minutes=2)).isoformat(),
        event_identity={"target_date": now.date().isoformat(), "location": "NYC"},
        trading_close_time=(now + timedelta(hours=3)).isoformat(),
        resolution_time=(now + timedelta(hours=4)).isoformat(),
        market_status="open",
        execution={"yes_bid": .48, "yes_ask": .52, "entry_price": .52},
    )
    row.update(updates)
    return row


class ClosingQuoteTests(unittest.TestCase):
    def test_kalshi_depth_reader_accepts_current_fixed_point_envelope(self):
        class Response:
            status_code = 200
            def raise_for_status(self): return None
            def json(self):
                return {"orderbook_fp": {"yes_dollars": [["0.48", "12.00"]], "no_dollars": []}}

        class Client:
            def get(self, *_args, **_kwargs): return Response()

        depth = kalshi.fetch_orderbook("KXTEST", client=Client())
        self.assertEqual(depth["yes_dollars"][0], ["0.48", "12.00"])

    def test_regular_capture_appends_integrity_fields_and_deduplicates_bucket(self):
        now = datetime(2026, 7, 14, 12, 17, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = AppendOnlyLedger(Path(tmp) / "evidence.jsonl")
            EvidenceStore(ledger.path).collect_scan({"top": [scan_row(now)]})
            scan = {"created_at": now.isoformat(), "top": [scan_row(now)]}
            first = capture_quotes(scan=scan, ledger=ledger, mode="regular", now=now)
            second = capture_quotes(scan=scan, ledger=ledger, mode="regular", now=now)
            self.assertEqual(first["captured"], 1)
            self.assertEqual(second["captured"], 0)
            quote = [r.payload for r in ledger.read_records()
                     if r.record_type == "market_quote_snapshot"][-1]
            self.assertEqual((quote["yes_bid"], quote["yes_ask"]), (.48, .52))
            self.assertEqual(quote["raw_response_hash_scope"], "normalized_scan_record")
            self.assertFalse(quote["depth"]["available"])
            self.assertTrue(ledger.verify()["valid"])

    def test_near_close_fetches_targeted_quote_every_five_minute_bucket(self):
        now = datetime(2026, 7, 14, 12, 17, tzinfo=timezone.utc)
        row = scan_row(now, trading_close_time=(now + timedelta(minutes=40)).isoformat())
        calls = []

        def live(candidate, _client):
            calls.append(candidate["market_id"])
            return {
                "observed_at": now.isoformat(), "yes_bid": .60, "yes_ask": .64,
                "market_implied_prob": .62, "spread": .04, "last_trade": .61,
                "depth": {"available": True, "source": "test", "top_levels": {}},
                "raw_response_hash": "abc", "raw_response_hash_scope": "test",
                "quote_source": "targeted final-hour venue quote",
            }

        with tempfile.TemporaryDirectory() as tmp:
            ledger = AppendOnlyLedger(Path(tmp) / "evidence.jsonl")
            EvidenceStore(ledger.path).collect_scan({"top": [row]})
            result = capture_quotes(
                scan={"created_at": now.isoformat(), "top": [row]}, ledger=ledger,
                mode="near-close", now=now, live_fetcher=live,
            )
            self.assertEqual(result["captured"], 1)
            self.assertEqual(calls, ["KXTEST-1"])
            quote = [r.payload for r in ledger.read_records()
                     if r.record_type == "market_quote_snapshot"][-1]
            self.assertEqual(quote["capture_mode"], "near-close")
            self.assertTrue(quote["depth"]["available"])

    def test_near_close_ignores_distant_and_post_close_markets(self):
        now = datetime(2026, 7, 14, 12, 17, tzinfo=timezone.utc)
        distant = scan_row(now)
        closed = scan_row(now, market_id="CLOSED",
                          trading_close_time=(now - timedelta(seconds=1)).isoformat())
        with tempfile.TemporaryDirectory() as tmp:
            ledger = AppendOnlyLedger(Path(tmp) / "evidence.jsonl")
            store = EvidenceStore(ledger.path)
            store.collect_scan({"top": [distant, closed]})
            result = capture_quotes(
                scan={"created_at": now.isoformat(), "top": [distant, closed]},
                ledger=ledger, mode="near-close", now=now,
                live_fetcher=lambda *_: self.fail("no targeted fetch was eligible"),
            )
            self.assertEqual(result["eligible"], 0)
            self.assertEqual(result["captured"], 0)

    def test_stale_scan_fails_closed(self):
        now = datetime(2026, 7, 14, 12, 17, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            result = capture_quotes(
                scan={"created_at": (now - timedelta(hours=2)).isoformat(), "top": []},
                ledger=AppendOnlyLedger(Path(tmp) / "evidence.jsonl"),
                mode="regular", now=now,
            )
            self.assertIn("stale", result["refused"])


if __name__ == "__main__":
    unittest.main()
