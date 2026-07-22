"""Contract tests against *captured live* Polymarket CLOB payloads.

The hand-built fixtures in ``test_polymarket_adapter.py`` are useful for
exercising branches, but they encode what we *assumed* the venue returns. They
passed while ``_parse_market`` read a ``tick_size`` key that Polymarket does not
emit — the resulting zero tick would have rejected every real order.

The JSON in ``tests/fixtures/`` is a verbatim capture from the live CLOB
(2026-07-22). These tests exist so a wrong assumption about the wire format
fails here instead of at the first funded order. Re-capture when the venue
changes; do not hand-edit the fixtures to make a test pass.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from rwoo.adapters.polymarket import (
    ALLOWED_TICK_SIZES,
    _parse_book,
    _parse_market,
    tick_from_venue,
    validate_order,
)
from rwoo.execution import ExecutionError

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class LiveMarketContractTests(unittest.TestCase):
    def setUp(self):
        self.payload = load("polymarket_live_market.json")

    def test_venue_does_not_emit_a_tick_size_key(self):
        # Regression guard. If this ever fails the venue changed its schema and
        # the parser's fallback ordering must be re-verified, not just widened.
        self.assertNotIn("tick_size", self.payload)
        self.assertIn("minimum_tick_size", self.payload)

    def test_tick_is_parsed_exactly_and_is_not_zero(self):
        snapshot = _parse_market(self.payload, NOW)
        self.assertEqual(snapshot.tick_size, Decimal("0.001"))
        self.assertGreater(snapshot.tick_size, 0)

    def test_tick_arrives_as_a_float_and_still_lands_exact(self):
        self.assertIsInstance(self.payload["minimum_tick_size"], float)
        self.assertEqual(_parse_market(self.payload, NOW).tick_size, Decimal("0.001"))

    def test_missing_tick_is_refused_rather_than_defaulted_to_zero(self):
        payload = {k: v for k, v in self.payload.items() if k != "minimum_tick_size"}
        with self.assertRaises(ExecutionError) as ctx:
            _parse_market(payload, NOW)
        self.assertEqual(ctx.exception.code, "VENUE_CONFIG_INVALID")

    def test_outcomes_are_title_case_on_the_wire_and_normalize_to_yes_no(self):
        outcomes = [t["outcome"] for t in self.payload["tokens"]]
        self.assertEqual(sorted(outcomes), ["No", "Yes"])
        self.assertEqual(set(_parse_market(self.payload, NOW).tokens), {"YES", "NO"})

    def test_integer_minimum_order_size_is_accepted(self):
        self.assertIsInstance(self.payload["minimum_order_size"], int)
        self.assertEqual(_parse_market(self.payload, NOW).minimum_order_size, Decimal("5"))

    def test_neg_risk_flag_is_carried_through(self):
        self.assertIs(_parse_market(self.payload, NOW).neg_risk, False)


class LiveBookContractTests(unittest.TestCase):
    def setUp(self):
        self.payload = load("polymarket_live_book.json")

    def test_timestamp_is_a_string_of_epoch_millis(self):
        self.assertIsInstance(self.payload["timestamp"], str)
        self.assertIsInstance(_parse_book(self.payload).timestamp, datetime)

    def test_wire_order_is_worst_first_and_is_re_sorted(self):
        wire_asks = [Decimal(level["price"]) for level in self.payload["asks"]]
        self.assertEqual(wire_asks, sorted(wire_asks, reverse=True), "venue sends asks descending")
        parsed = _parse_book(self.payload)
        self.assertEqual(parsed.best_ask, min(wire_asks))
        wire_bids = [Decimal(level["price"]) for level in self.payload["bids"]]
        self.assertEqual(parsed.best_bid, max(wire_bids))

    def test_book_reports_its_own_tick_as_a_decimal_string(self):
        self.assertEqual(_parse_book(self.payload).tick_size, Decimal("0.001"))


class LiveCrossCheckTests(unittest.TestCase):
    """The two endpoints must agree before an order is priced."""

    def setUp(self):
        self.market = _parse_market(load("polymarket_live_market.json"), NOW)
        self.book = _parse_book(load("polymarket_live_book.json"))
        self.now = self.book.timestamp + timedelta(seconds=1)
        self.intent = {
            "side": "YES",
            "token_id": self.market.tokens["YES"],
            "price": "0.022",
            "quantity": "10",
        }

    def test_real_payloads_validate_end_to_end(self):
        assessment = validate_order(self.intent, self.market, self.book,
                                    now=self.now, max_staleness_seconds=15)
        self.assertEqual(assessment.best_ask, "0.02")

    def test_price_off_tick_is_rejected_against_the_real_tick(self):
        # 0.0225 is not a multiple of the live 0.001 tick. Under the old parser
        # the tick was 0.000 and this order was rejected for the wrong reason.
        with self.assertRaises(ExecutionError) as ctx:
            validate_order({**self.intent, "price": "0.0225"}, self.market, self.book,
                           now=self.now, max_staleness_seconds=15)
        self.assertEqual(ctx.exception.code, "TICK_SIZE_VIOLATION")

    def test_disagreeing_ticks_are_refused(self):
        book = self.book.__class__(self.book.token_id, self.book.bids, self.book.asks,
                                   self.book.timestamp, Decimal("0.01"))
        with self.assertRaises(ExecutionError) as ctx:
            validate_order(self.intent, self.market, book, now=self.now, max_staleness_seconds=15)
        self.assertEqual(ctx.exception.code, "VENUE_CONFIG_INVALID")

    def test_book_for_the_wrong_token_is_refused(self):
        book = self.book.__class__("some-other-token", self.book.bids, self.book.asks,
                                   self.book.timestamp, self.book.tick_size)
        with self.assertRaises(ExecutionError) as ctx:
            validate_order(self.intent, self.market, book, now=self.now, max_staleness_seconds=15)
        self.assertEqual(ctx.exception.code, "MARKET_BINDING_MISMATCH")


class TickAllowListTests(unittest.TestCase):
    def test_every_documented_tick_round_trips_from_float(self):
        for tick in ALLOWED_TICK_SIZES:
            self.assertEqual(tick_from_venue(float(tick)), tick)

    def test_undocumented_tick_is_refused(self):
        for value in (0.005, 0.0, 1.0, "0.002"):
            with self.assertRaises(ExecutionError) as ctx:
                tick_from_venue(value)
            self.assertEqual(ctx.exception.code, "INVALID_VENUE_DATA")


class SettlementRequirementsTests(unittest.TestCase):
    """What the caller must fund and approve, stated address-first."""

    def setUp(self):
        from rwoo.adapters.polymarket import settlement_requirements
        self.build = settlement_requirements
        self.market = _parse_market(load("polymarket_live_market.json"), NOW)

    def test_collateral_matches_the_sdk_contract_config(self):
        # Guards against drift from py-clob-client's get_contract_config(137).
        req = self.build(self.market)
        self.assertEqual(req["collateral"]["address"],
                         "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
        self.assertEqual(req["collateral"]["decimals"], 6)
        self.assertEqual(req["chain"], "eip155:137")

    def test_native_usdc_is_called_out_as_the_wrong_token(self):
        from rwoo.adapters.polymarket import NATIVE_USDC_NOT_COLLATERAL
        warning = self.build(self.market)["collateral"]["warning"]
        self.assertIn(NATIVE_USDC_NOT_COLLATERAL, warning)
        self.assertNotEqual(NATIVE_USDC_NOT_COLLATERAL,
                            self.build(self.market)["collateral"]["address"])

    def test_allowance_spender_follows_the_market_type(self):
        import dataclasses
        normal = self.build(self.market)["required_allowances"][0]
        self.assertEqual(normal["role"], "exchange")
        self.assertEqual(normal["spender"], "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E")

        neg = self.build(dataclasses.replace(self.market, neg_risk=True))["required_allowances"][0]
        self.assertEqual(neg["role"], "neg_risk_exchange")
        self.assertEqual(neg["spender"], "0xC5d563A36AE78145C45a50134d48A1215220f80a")
        self.assertNotEqual(normal["spender"], neg["spender"])

    def test_notional_is_rendered_canonically_when_supplied(self):
        req = self.build(self.market, notional=Decimal("0.100"))
        self.assertEqual(req["required_allowances"][0]["minimum"], "0.1")

    def test_notional_is_omitted_when_unknown(self):
        self.assertNotIn("minimum", self.build(self.market)["required_allowances"][0])

    def test_response_is_json_serialisable_for_an_agent(self):
        json.dumps(self.build(self.market, notional=Decimal("1.5")))




class SubmissionPackageTests(unittest.TestCase):
    """The hand-back package must be sufficient for a caller to sign and post."""

    def setUp(self):
        from rwoo.adapters.polymarket import submission_package
        self.build = submission_package
        self.market = _parse_market(load("polymarket_live_market.json"), NOW)
        self.book = _parse_book(load("polymarket_live_book.json"))
        self.intent = {
            "side": "YES", "token_id": self.market.tokens["YES"],
            "price": "0.008", "quantity": "138", "time_in_force": "GTC",
        }
        self.assessment = validate_order(
            {**self.intent, "price": "0.02"}, self.market, self.book,
            now=self.book.timestamp + timedelta(seconds=1), max_staleness_seconds=15)

    def package(self, **kw):
        return self.build(self.intent, self.market, self.assessment, **kw)

    def test_domain_matches_the_sdk(self):
        domain = self.package()["eip712"]["domain"]
        self.assertEqual(domain["name"], "Polymarket CTF Exchange")
        self.assertEqual(domain["version"], "1")
        self.assertEqual(domain["chainId"], 137)

    def test_verifying_contract_follows_the_market_type(self):
        import dataclasses
        normal = self.package()["eip712"]["domain"]["verifyingContract"]
        neg_market = dataclasses.replace(self.market, neg_risk=True)
        neg = self.build(self.intent, neg_market, self.assessment)["eip712"]["domain"]["verifyingContract"]
        self.assertEqual(normal, "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E")
        self.assertEqual(neg, "0xC5d563A36AE78145C45a50134d48A1215220f80a")
        self.assertNotEqual(normal, neg)

    def test_buy_amounts_are_exact_integers_in_base_units(self):
        fixed = self.package(venue_side="BUY")["eip712"]["fields_fixed_by_oracle"]
        # 0.008 * 138 = 1.104 USDC -> 1_104_000 base units; 138 contracts -> 138_000_000
        self.assertEqual(fixed["makerAmount"], "1104000")
        self.assertEqual(fixed["takerAmount"], "138000000")
        self.assertEqual(fixed["side"], 0)

    def test_sell_reverses_the_amounts(self):
        fixed = self.package(venue_side="SELL")["eip712"]["fields_fixed_by_oracle"]
        self.assertEqual(fixed["makerAmount"], "138000000")
        self.assertEqual(fixed["takerAmount"], "1104000")
        self.assertEqual(fixed["side"], 1)

    def test_non_integral_amount_is_refused_not_rounded(self):
        from rwoo.adapters.polymarket import _base_units
        with self.assertRaises(ExecutionError) as ctx:
            _base_units(Decimal("0.0000001"), name="test")
        self.assertEqual(ctx.exception.code, "INVALID_EXECUTION")

    def test_caller_owned_fields_are_never_supplied_by_us(self):
        eip = self.package()["eip712"]
        for field in ("salt", "maker", "signer", "nonce", "signatureType"):
            self.assertIn(field, eip["fields_supplied_by_caller"])
            self.assertNotIn(field, eip["fields_fixed_by_oracle"])

    def test_service_declares_it_holds_no_credential(self):
        pkg = self.package()
        self.assertEqual(pkg["submitted_by"], "caller")
        self.assertIn("holds no credential", pkg["submission"]["auth"])

    def test_geographic_restriction_is_surfaced_to_the_caller(self):
        # The caller submits, so the caller owns this constraint. Saying so is
        # the whole point of the hand-back model.
        self.assertIn("geoblock", self.package()["submission"]["note"])

    def test_package_carries_settlement_and_pre_trade_context(self):
        pkg = self.package()
        self.assertEqual(pkg["settlement"]["collateral"]["address"],
                         "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
        self.assertEqual(pkg["settlement"]["required_allowances"][0]["minimum"], "1.104")
        self.assertEqual(pkg["pre_trade"]["validated_against_tick"], "0.001")

    def test_package_is_json_serialisable(self):
        json.dumps(self.package())

if __name__ == "__main__":
    unittest.main()
