from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx

from rwoo.adapters.polymarket import (
    BookLevel,
    HttpPolymarketDataSource,
    MarketSnapshot,
    OrderBook,
    PolymarketAdapter,
    to_decimal,
    validate_order,
)
from rwoo.execution import ExecutionCoordinator, ExecutionError, ExecutionStore, VenueResult

NOW = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)


def market(**changes) -> MarketSnapshot:
    base = dict(
        market_id="cond-1", question="Will it rain?",
        tokens={"YES": "tok-yes", "NO": "tok-no"},
        tick_size=Decimal("0.01"), minimum_order_size=Decimal("5"),
        active=True, closed=False, accepting_orders=True, timestamp=NOW,
    )
    base.update(changes)
    return MarketSnapshot(**base)


def book(asks=(("0.51", "500"),), bids=(("0.49", "500"),), ts=None) -> OrderBook:
    return OrderBook.build(
        "tok-yes",
        [BookLevel(Decimal(p), Decimal(s)) for p, s in bids],
        [BookLevel(Decimal(p), Decimal(s)) for p, s in asks],
        ts or NOW,
    )


def intent(**changes) -> dict:
    base = dict(venue="polymarket", market_id="cond-1", token_id="tok-yes",
                side="YES", price="0.50", quantity="10")
    base.update(changes)
    return base


class DecimalGuardTests(unittest.TestCase):
    def test_binary_float_is_refused(self):
        with self.assertRaises(ExecutionError) as ctx:
            to_decimal(0.51, name="price")
        self.assertEqual(ctx.exception.code, "INVALID_VENUE_DATA")

    def test_string_parses_exactly(self):
        self.assertEqual(to_decimal("0.510000", name="price"), Decimal("0.51"))


class ValidateTests(unittest.TestCase):
    def check(self, code, **kwargs):
        merged = dict(now=NOW, max_staleness_seconds=30)
        merged.update(kwargs)
        with self.assertRaises(ExecutionError) as ctx:
            validate_order(kwargs.get("intent", intent()), kwargs.get("market", market()),
                           kwargs.get("book", book()), now=merged["now"],
                           max_staleness_seconds=merged["max_staleness_seconds"],
                           max_marketable_premium=merged.get("max_marketable_premium"))
        self.assertEqual(ctx.exception.code, code)

    def test_good_order_passes_and_reports_book(self):
        assessment = validate_order(intent(), market(), book(), now=NOW, max_staleness_seconds=30)
        self.assertEqual(assessment.best_ask, "0.51")
        self.assertEqual(assessment.best_bid, "0.49")
        self.assertEqual(assessment.marketable_depth, "0")  # 0.50 limit rests below the 0.51 ask

    def test_binding_mismatch(self):
        self.check("MARKET_BINDING_MISMATCH", intent=intent(token_id="tok-wrong"))

    def test_tick_violation(self):
        self.check("TICK_SIZE_VIOLATION", intent=intent(price="0.505"))

    def test_below_minimum(self):
        self.check("BELOW_MIN_ORDER", intent=intent(quantity="1"))

    def test_stale_book(self):
        self.check("STALE_BOOK", book=book(ts=NOW - timedelta(seconds=120)))

    def test_market_not_accepting(self):
        self.check("VENUE_NOT_ACCEPTING", market=market(accepting_orders=False))

    def test_empty_book(self):
        self.check("EMPTY_BOOK", book=book(asks=()))

    def test_crossed_book(self):
        self.check("CROSSED_BOOK", book=book(asks=(("0.40", "10"),), bids=(("0.60", "10"),)))

    def test_price_protection(self):
        self.check("PRICE_PROTECTION", intent=intent(price="0.80"),
                   max_marketable_premium=Decimal("0.10"))

    def test_marketable_depth_is_summed_at_or_better(self):
        deep = book(asks=(("0.51", "300"), ("0.52", "200")))
        assessment = validate_order(intent(price="0.52"), market(), deep, now=NOW, max_staleness_seconds=30)
        self.assertEqual(assessment.marketable_depth, "500")


class RecordingSigner:
    def __init__(self):
        self.calls = []

    def submit(self, intent, assessment):
        self.calls.append(("submit", assessment))
        return VenueResult("OPEN", "venue-1")

    def cancel(self, intent):
        self.calls.append(("cancel",))
        return VenueResult("CANCELLED", "venue-1")

    def reconcile(self, intent):
        self.calls.append(("reconcile",))
        return VenueResult("FILLED", "venue-1")


class FakeSource:
    def __init__(self, market_snapshot, order_book):
        self._market = market_snapshot
        self._book = order_book

    def market(self, market_id):
        return self._market

    def book(self, token_id):
        return self._book


class AdapterTests(unittest.TestCase):
    def test_no_signer_fails_closed_on_every_funded_action(self):
        adapter = PolymarketAdapter(FakeSource(market(), book()), clock=lambda: NOW)
        for call in (adapter.submit, adapter.cancel, adapter.reconcile):
            with self.assertRaises(ExecutionError) as ctx:
                call(intent())
            self.assertEqual(ctx.exception.code, "SIGNER_UNAVAILABLE")

    def test_validation_runs_before_the_signer_is_ever_called(self):
        signer = RecordingSigner()
        adapter = PolymarketAdapter(FakeSource(market(), book()), signer=signer, clock=lambda: NOW)
        with self.assertRaises(ExecutionError) as ctx:
            adapter.submit(intent(price="0.505"))  # tick violation
        self.assertEqual(ctx.exception.code, "TICK_SIZE_VIOLATION")
        self.assertEqual(signer.calls, [])  # signer never touched on a rejected order

    def test_valid_submit_reaches_signer_with_assessment(self):
        signer = RecordingSigner()
        adapter = PolymarketAdapter(FakeSource(market(), book()), signer=signer, clock=lambda: NOW)
        result = adapter.submit(intent())
        self.assertEqual(result.state, "OPEN")
        self.assertEqual(signer.calls[0][0], "submit")
        self.assertEqual(signer.calls[0][1].best_ask, "0.51")


class HttpSourceTests(unittest.TestCase):
    def _client(self):
        def handler(request):
            if request.url.path.endswith("/book"):
                return httpx.Response(200, json={
                    "asset_id": "tok-yes", "timestamp": "1753185600000",
                    "bids": [{"price": "0.49", "size": "500"}],
                    "asks": [{"price": "0.51", "size": "400"}],
                })
            return httpx.Response(200, json={
                "condition_id": "cond-1", "question": "Will it rain?",
                "active": True, "closed": False, "accepting_orders": True,
                "tick_size": "0.01", "minimum_order_size": "5",
                "tokens": [
                    {"token_id": "tok-yes", "outcome": "Yes"},
                    {"token_id": "tok-no", "outcome": "No"},
                ],
            })
        return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://clob.polymarket.com")

    def test_public_payloads_parse_to_decimal(self):
        source = HttpPolymarketDataSource(self._client(), clock=lambda: NOW)
        snapshot = source.market("cond-1")
        self.assertEqual(snapshot.tokens["YES"], "tok-yes")
        self.assertEqual(snapshot.tick_size, Decimal("0.01"))
        self.assertTrue(snapshot.accepting_orders)

        order_book = source.book("tok-yes")
        self.assertEqual(order_book.best_ask, Decimal("0.51"))
        self.assertEqual(order_book.best_bid, Decimal("0.49"))
        self.assertIsInstance(order_book.asks[0].size, Decimal)


class CoordinatorIntegrationTests(unittest.TestCase):
    """PolymarketAdapter wired into the real ExecutionCoordinator."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "execution.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def coordinator(self, adapter):
        return ExecutionCoordinator(ExecutionStore(self.path), mode="live", adapter=adapter)

    def order(self, **changes):
        payload = dict(venue="polymarket", market_id="cond-1", token_id="tok-yes",
                       side="YES", price="0.50", quantity="10", time_in_force="GTC",
                       event_group_id="event-1", decision_receipt_hash="receipt-1")
        payload.update(changes)
        return payload

    def test_missing_signer_cleanly_rejects_never_unknown(self):
        adapter = PolymarketAdapter(FakeSource(market(), book()), clock=lambda: NOW)
        coordinator = self.coordinator(adapter)
        intent, _ = coordinator.prepare(self.order(), "key-nosigner")
        result = coordinator.submit(intent["intent_id"], "approval-1")
        self.assertEqual(result["state"], "REJECTED")
        self.assertEqual(result["events"][-1]["detail"]["code"], "SIGNER_UNAVAILABLE")

    def test_binding_failure_keeps_intent_prepared_and_retryable(self):
        wrong = market(tokens={"YES": "tok-other", "NO": "tok-no"})
        coordinator = self.coordinator(PolymarketAdapter(FakeSource(wrong, book()), clock=lambda: NOW))
        intent, _ = coordinator.prepare(self.order(), "key-binding")
        with self.assertRaises(ExecutionError) as ctx:
            coordinator.submit(intent["intent_id"], "approval-1")
        self.assertEqual(ctx.exception.code, "MARKET_BINDING_MISMATCH")
        self.assertEqual(coordinator.store.get(intent["intent_id"])["state"], "PREPARED")

    def test_valid_order_with_signer_reaches_open(self):
        signer = RecordingSigner()
        adapter = PolymarketAdapter(FakeSource(market(), book()), signer=signer, clock=lambda: NOW)
        coordinator = self.coordinator(adapter)
        intent, _ = coordinator.prepare(self.order(), "key-open")
        result = coordinator.submit(intent["intent_id"], "approval-1")
        self.assertEqual(result["state"], "OPEN")
        self.assertEqual(len(signer.calls), 1)


if __name__ == "__main__":
    unittest.main()
