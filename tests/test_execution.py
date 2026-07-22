from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rwoo.execution import ExecutionCoordinator, ExecutionError, ExecutionStore, VenueResult


def order(**changes):
    payload = {
        "venue": "polymarket", "market_id": "market-1", "token_id": "token-yes",
        "side": "YES", "price": "0.333333", "quantity": "3",
        "time_in_force": "GTC", "event_group_id": "event-1",
        "decision_receipt_hash": "receipt-1",
    }
    payload.update(changes)
    return payload


class FakeAdapter:
    def __init__(self, result=None, error=None):
        self.result = result or VenueResult("OPEN", "venue-1")
        self.error = error
        self.submissions = 0

    def submit(self, intent):
        self.submissions += 1
        if self.error:
            raise self.error
        return self.result

    def cancel(self, intent):
        return VenueResult("CANCELLED", intent.get("venue_order_id"))

    def reconcile(self, intent):
        return self.result


class ExecutionCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "execution.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def coordinator(self, **kwargs):
        return ExecutionCoordinator(ExecutionStore(self.path), **kwargs)

    def test_exact_arithmetic_and_durable_restart(self):
        coordinator = self.coordinator()
        intent, replay = coordinator.prepare(order(), "key-1")
        self.assertFalse(replay)
        self.assertEqual(intent["notional"], "0.999999")
        restarted = self.coordinator().store.get(intent["intent_id"])
        self.assertEqual(restarted["state"], "PREPARED")

    def test_float_input_is_rejected(self):
        with self.assertRaisesRegex(ExecutionError, "decimal string"):
            self.coordinator().prepare(order(price=0.4), "key-float")

    def test_idempotency_replays_and_conflicts(self):
        coordinator = self.coordinator()
        first, replay = coordinator.prepare(order(), "same-key")
        second, replay = coordinator.prepare(order(), "same-key")
        self.assertTrue(replay)
        self.assertEqual(first["intent_id"], second["intent_id"])
        with self.assertRaisesRegex(ExecutionError, "bound"):
            coordinator.prepare(order(quantity="4"), "same-key")

    def test_disabled_mode_never_submits(self):
        coordinator = self.coordinator()
        intent, _ = coordinator.prepare(order(), "key-disabled")
        with self.assertRaisesRegex(ExecutionError, "locked"):
            coordinator.submit(intent["intent_id"], "approval")
        self.assertEqual(coordinator.store.get(intent["intent_id"])["state"], "PREPARED")

    def test_ambiguous_submit_is_unknown_not_rejected(self):
        adapter = FakeAdapter(error=TimeoutError())
        coordinator = self.coordinator(mode="live", adapter=adapter)
        intent, _ = coordinator.prepare(order(), "key-timeout")
        result = coordinator.submit(intent["intent_id"], "approval-1")
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(adapter.submissions, 1)
        with self.assertRaisesRegex(ExecutionError, "cannot transition"):
            coordinator.submit(intent["intent_id"], "approval-1")
        self.assertEqual(adapter.submissions, 1)

    def test_prepared_intent_can_be_cancelled_without_adapter(self):
        coordinator = self.coordinator()
        intent, _ = coordinator.prepare(order(), "key-cancel")
        result = coordinator.cancel(intent["intent_id"])
        self.assertEqual(result["state"], "CANCELLED")

    def test_limit_is_enforced_exactly(self):
        coordinator = self.coordinator(max_order_usd="1.00")
        coordinator.prepare(order(price="0.50", quantity="2"), "at-limit")
        with self.assertRaisesRegex(ExecutionError, "limit"):
            coordinator.prepare(order(price="0.500001", quantity="2"), "over-limit")


if __name__ == "__main__":
    unittest.main()
