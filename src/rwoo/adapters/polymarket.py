"""Isolated, unfunded Polymarket execution adapter (scaffold).

This is step 1 of the execution release train in
``docs/PREDICTION_MARKET_EXECUTION_RESEARCH.md``: read-only public market data
plus exact-arithmetic pre-trade validation, behind a fail-closed adapter.

Fund safety is structural, not configurational:

* No private key, seed phrase, or wallet export is accepted anywhere here.
* ``submit`` / ``cancel`` / ``reconcile`` raise ``SIGNER_UNAVAILABLE`` unless an
  ``OrderSigner`` is explicitly injected. This scaffold ships no signer, so it
  is incapable of moving funds. A real signer is step 2 and must run in a
  separate, isolated, non-root process (see the research doc's execution
  boundary section).
* All venue prices and sizes are parsed to :class:`~decimal.Decimal`. Binary
  floating-point values are rejected at the boundary.

The HTTP data source below uses the public CLOB endpoints via an injected
``httpx`` client. Its field mapping is PROVISIONAL and must be verified and
pinned against the official ``Polymarket/py-sdk`` before any funded use; a
py-sdk-backed source can implement the same :class:`PolymarketDataSource`
protocol as a drop-in replacement.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Protocol

from rwoo.execution import ExecutionError, VenueResult, canonical


def to_decimal(value: Any, *, name: str) -> Decimal:
    """Parse a venue-supplied value into an exact, finite, non-negative Decimal.

    Binary floats are refused: precision must never be lost between the venue
    wire format and our arithmetic.
    """
    if isinstance(value, float):
        raise ExecutionError("INVALID_VENUE_DATA", f"{name} arrived as a binary float; refusing to lose precision")
    if not isinstance(value, (str, int)):
        raise ExecutionError("INVALID_VENUE_DATA", f"{name} must be a decimal string")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ExecutionError("INVALID_VENUE_DATA", f"{name} is not a valid decimal") from exc
    if not number.is_finite() or number < 0:
        raise ExecutionError("INVALID_VENUE_DATA", f"{name} must be finite and non-negative")
    return number


# The venue's documented tick sizes. Verified against live CLOB 2026-07-22.
# ``minimum_tick_size`` arrives from /markets as a JSON float, so it cannot go
# through ``to_decimal``; this allow-list is what keeps that narrow exception
# safe. Any value outside the set is treated as corrupt venue data.
ALLOWED_TICK_SIZES = (Decimal("0.1"), Decimal("0.01"), Decimal("0.001"), Decimal("0.0001"))


def tick_from_venue(value: Any, *, name: str = "tick_size") -> Decimal:
    """Parse a venue tick size, tolerating the float that /markets returns.

    ``to_decimal`` refuses binary floats because a lost digit in a price or size
    is unrecoverable. A tick size is different: it is drawn from a tiny, known
    set of exact values, so we can accept the float, round-trip it through
    ``str`` (shortest round-trip repr), and then require an exact match against
    that set. A float that does not land on a documented tick is rejected.
    """
    if isinstance(value, float):
        try:
            number = Decimal(str(value))
        except InvalidOperation as exc:
            raise ExecutionError("INVALID_VENUE_DATA", f"{name} is not a valid decimal") from exc
    else:
        number = to_decimal(value, name=name)
    if number not in ALLOWED_TICK_SIZES:
        raise ExecutionError(
            "INVALID_VENUE_DATA",
            f"{name} {canonical(number)} is not a documented Polymarket tick size",
        )
    return number


@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class OrderBook:
    token_id: str
    bids: tuple[BookLevel, ...]  # best (highest price) first
    asks: tuple[BookLevel, ...]  # best (lowest price) first
    timestamp: datetime
    # The /book endpoint independently reports the tick. Kept so the two
    # endpoints can be cross-checked before an order is priced.
    tick_size: Decimal | None = None

    @classmethod
    def build(cls, token_id: str, bids: Iterable[BookLevel], asks: Iterable[BookLevel],
              timestamp: datetime, tick_size: Decimal | None = None) -> "OrderBook":
        # The venue returns both sides worst-price-first; never rely on wire order.
        ordered_bids = tuple(sorted(bids, key=lambda level: level.price, reverse=True))
        ordered_asks = tuple(sorted(asks, key=lambda level: level.price))
        return cls(token_id, ordered_bids, ordered_asks, timestamp, tick_size)

    @property
    def best_bid(self) -> Decimal | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        return self.asks[0].price if self.asks else None


@dataclass(frozen=True)
class MarketSnapshot:
    market_id: str
    question: str
    tokens: dict[str, str]  # {"YES": token_id, "NO": token_id}
    tick_size: Decimal
    minimum_order_size: Decimal
    active: bool
    closed: bool
    accepting_orders: bool
    timestamp: datetime
    # Negative-risk markets settle through a different exchange contract and
    # carry different order semantics. Recorded here so the signed-order path
    # can gate on it rather than silently treating them as ordinary binaries.
    neg_risk: bool = False


@dataclass(frozen=True)
class PreTradeAssessment:
    """Read-only, reportable result of a passing pre-trade check."""

    best_bid: str | None
    best_ask: str
    spread: str | None
    marketable_depth: str  # size resting at or better than the limit price
    book_age_seconds: float


# --------------------------------------------------------------------------
# Settlement requirements
#
# A caller who is going to sign their own order has to fund and approve the
# right things first, and "USDC on Polygon" is not a sufficient answer: two
# distinct tokens on Polygon both report symbol "USDC" with 6 decimals.
# Polymarket settles in the *bridged* one. Funding native USDC leaves the agent
# holding a balance it cannot trade with.
#
# So the contract address is the authority and the symbol is a human label.
# Addresses verified against py-clob-client 0.34.6 ``get_contract_config`` and
# cross-checked on-chain (name/symbol/decimals) 2026-07-22.
POLYGON_CHAIN_ID = 137

COLLATERAL = {
    "address": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    "symbol": "USDC",
    "name": "USD Coin (PoS)",
    "decimals": 6,
}

# Same symbol, same decimals, same chain, different token. Named explicitly so
# the warning we emit can point at the exact thing not to fund.
NATIVE_USDC_NOT_COLLATERAL = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"

# The allowance spender depends on the market: negative-risk markets settle
# through a different exchange contract. Emitting one static address would tell
# a subset of callers to approve the wrong contract.
EXCHANGE_BY_MARKET_TYPE = {
    False: {"address": "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E", "role": "exchange"},
    True: {"address": "0xC5d563A36AE78145C45a50134d48A1215220f80a", "role": "neg_risk_exchange"},
}

SIGNATURE_TYPES = {0: "EOA", 1: "POLY_PROXY", 2: "GNOSIS_SAFE", 3: "POLY_1271"}


def settlement_requirements(market: MarketSnapshot, *, notional: Decimal | None = None) -> dict[str, Any]:
    """Describe what the caller must hold and approve to sign this order.

    Address-first and machine-readable, mirroring the shape the x402 payment
    challenge already uses (network / asset / decimals), so an agent can consume
    both with one parser. Computed per market rather than served statically,
    because ``neg_risk`` changes which contract needs the allowance.
    """
    exchange = EXCHANGE_BY_MARKET_TYPE[bool(market.neg_risk)]
    allowance: dict[str, Any] = {
        "spender": exchange["address"],
        "role": exchange["role"],
        "token": COLLATERAL["address"],
        "reason": "the exchange moves collateral on fill; approve before signing",
    }
    if notional is not None:
        allowance["minimum"] = canonical(notional)
    return {
        "chain": f"eip155:{POLYGON_CHAIN_ID}",
        "collateral": {
            **COLLATERAL,
            "caip19": f"eip155:{POLYGON_CHAIN_ID}/erc20:{COLLATERAL['address']}",
            "warning": (
                "Bridged USDC.e. This is NOT native USDC "
                f"({NATIVE_USDC_NOT_COLLATERAL}), which shares the symbol "
                "'USDC' and 6 decimals on this chain but cannot be traded here."
            ),
        },
        "gas_token": {
            "symbol": "POL",
            "note": "native Polygon gas; needed for approvals only, not per order",
        },
        "required_allowances": [allowance],
        "neg_risk_market": bool(market.neg_risk),
        "signature_types": {str(k): v for k, v in SIGNATURE_TYPES.items()},
        "custody": "the caller signs and holds funds throughout; this service never takes custody",
    }


# --------------------------------------------------------------------------
# Caller-submittable order package ("prepare and hand back")
#
# The service prepares and validates the intent; the caller signs it AND submits
# it themselves, from wherever they are lawfully able to trade. This keeps the
# service out of custody *and* out of the venue's geographic restrictions, which
# apply to whoever submits the order.
#
# For that to be usable, the response has to contain everything needed to sign
# and post -- domain, contract, exact integer amounts, endpoint. Returning an
# internal intent record is not enough: the caller cannot trade from it.
#
# Domain verified against py_order_utils (bundled with py-clob-client 0.34.6):
# name="Polymarket CTF Exchange", version="1", chainId, verifyingContract=the
# exchange for this market type.
EIP712_DOMAIN_NAME = "Polymarket CTF Exchange"
EIP712_DOMAIN_VERSION = "1"

# Venue-native side encoding for the signed struct: 0 = BUY, 1 = SELL. Our
# intents speak YES/NO (which outcome token) -- a different axis entirely.
VENUE_SIDE_BUY = 0
VENUE_SIDE_SELL = 1

COLLATERAL_BASE_UNITS = 10 ** 6


def _base_units(amount: Decimal, *, name: str) -> int:
    """Convert a decimal amount to exact integer base units, or refuse.

    Signed orders commit to integers. Rounding here would mean the caller signs
    an amount that differs from the one we validated and receipted, so a
    non-integral result is treated as a bug rather than quietly rounded.

    In practice this always divides exactly for a valid order: tick sizes bottom
    out at 0.0001 and sizes are whole contracts, so the product never exceeds
    six decimal places.
    """
    scaled = amount * COLLATERAL_BASE_UNITS
    if scaled != scaled.to_integral_value():
        raise ExecutionError(
            "INVALID_EXECUTION",
            f"{name} does not convert to exact base units; refusing to round a signed amount",
        )
    return int(scaled)


def submission_package(intent: dict[str, Any], market: MarketSnapshot,
                       assessment: PreTradeAssessment, *,
                       venue_side: str = "BUY",
                       fee_rate_bps: int = 0) -> dict[str, Any]:
    """Everything the caller needs to sign and submit this order themselves.

    Deliberately does NOT include ``salt``, ``maker``, ``signer`` or ``nonce``:
    those belong to the caller's wallet and are filled in locally. The service
    pins the economically meaningful fields -- token, amounts, side, fee -- so
    the decision receipt attests to exactly what gets signed.
    """
    if venue_side not in ("BUY", "SELL"):
        raise ExecutionError("INVALID_EXECUTION", "venue_side must be BUY or SELL")

    price = to_decimal(intent["price"], name="price")
    size = to_decimal(intent["quantity"], name="quantity")
    cost = price * size

    # A BUY gives collateral and receives outcome tokens; a SELL is the reverse.
    if venue_side == "BUY":
        maker_amount = _base_units(cost, name="maker amount")
        taker_amount = _base_units(size, name="taker amount")
    else:
        maker_amount = _base_units(size, name="maker amount")
        taker_amount = _base_units(cost, name="taker amount")

    exchange = EXCHANGE_BY_MARKET_TYPE[bool(market.neg_risk)]

    return {
        "venue": "polymarket",
        "submitted_by": "caller",
        "eip712": {
            "domain": {
                "name": EIP712_DOMAIN_NAME,
                "version": EIP712_DOMAIN_VERSION,
                "chainId": POLYGON_CHAIN_ID,
                "verifyingContract": exchange["address"],
            },
            "primary_type": "Order",
            # Pinned by the service; these are what the receipt attests to.
            "fields_fixed_by_oracle": {
                "tokenId": intent["token_id"],
                "makerAmount": str(maker_amount),
                "takerAmount": str(taker_amount),
                "side": VENUE_SIDE_BUY if venue_side == "BUY" else VENUE_SIDE_SELL,
                "feeRateBps": str(fee_rate_bps),
                "taker": "0x0000000000000000000000000000000000000000",
                "expiration": "0",
            },
            # Filled in locally by the caller's wallet; never supplied by us.
            "fields_supplied_by_caller": [
                "salt", "maker", "signer", "nonce", "signatureType",
            ],
        },
        "submission": {
            "method": "POST",
            "url": "https://clob.polymarket.com/order",
            "auth": (
                "Caller's own L2 headers (POLY_ADDRESS, POLY_SIGNATURE, "
                "POLY_TIMESTAMP, POLY_API_KEY, POLY_PASSPHRASE), derived from "
                "the caller's key. This service holds no credential."
            ),
            "body_shape": {"order": "<signed order>", "owner": "<caller api key>",
                           "orderType": intent.get("time_in_force", "GTC")},
            "note": (
                "Submit from a jurisdiction where you are permitted to trade. "
                "The venue applies its geographic restrictions to whoever "
                "submits the order. See "
                "https://docs.polymarket.com/developers/CLOB/geoblock"
            ),
        },
        "settlement": settlement_requirements(market, notional=cost),
        "pre_trade": {
            "best_bid": assessment.best_bid,
            "best_ask": assessment.best_ask,
            "spread": assessment.spread,
            "marketable_depth": assessment.marketable_depth,
            "book_age_seconds": assessment.book_age_seconds,
            "validated_against_tick": canonical(market.tick_size),
        },
        "human_summary": (
            f"{venue_side} {canonical(size)} {intent.get('side', '?')} contracts "
            f"at {canonical(price)} for {canonical(cost)} USDC.e collateral"
        ),
    }


class PolymarketDataSource(Protocol):
    def market(self, market_id: str) -> MarketSnapshot: ...
    def book(self, token_id: str) -> OrderBook: ...


class OrderSigner(Protocol):
    """Isolated funded signer. Deliberately unimplemented in this scaffold.

    Exception contract (relied on by ``ExecutionCoordinator``): raise
    ``ExecutionError`` ONLY for a pre-transmission refusal — a failure that
    provably occurs before any bytes reach the venue (e.g. an insufficient
    balance or allowance detected before signing). Once an order may have been
    transmitted, a transport/timeout failure must propagate as a non-
    ``ExecutionError`` exception so the coordinator marks it UNKNOWN and
    reconciles rather than assuming a rejection.
    """

    def submit(self, intent: dict[str, Any], assessment: PreTradeAssessment) -> VenueResult: ...
    def cancel(self, intent: dict[str, Any]) -> VenueResult: ...
    def reconcile(self, intent: dict[str, Any]) -> VenueResult: ...


def validate_order(intent: dict[str, Any], market: MarketSnapshot, book: OrderBook, *,
                   now: datetime, max_staleness_seconds: float,
                   max_marketable_premium: Decimal | None = None) -> PreTradeAssessment:
    """Fail-closed pre-trade gate. Raises ``ExecutionError`` on any hard failure.

    This is the re-fetch/revalidate step required immediately before signing:
    market status, YES/NO token binding, tick size, minimum size, book
    freshness, an empty/crossed book, and fat-finger price protection. Balance
    and allowance are intentionally out of scope here — they require an
    authenticated session and belong to the signer boundary (step 2).
    """
    side = intent.get("side")
    if side not in ("YES", "NO"):
        raise ExecutionError("MARKET_BINDING_MISMATCH", "order side must be YES or NO")
    if not (market.active and market.accepting_orders and not market.closed):
        raise ExecutionError("VENUE_NOT_ACCEPTING", "market is not currently accepting orders")

    expected_token = market.tokens.get(side)
    if not expected_token or expected_token != intent.get("token_id"):
        raise ExecutionError("MARKET_BINDING_MISMATCH", f"{side} token does not match the live market binding")

    # The book must be the book for the token being traded. Without this, a data
    # source that returns the wrong book prices the order against a different
    # market while every other check still passes.
    if book.token_id and book.token_id != expected_token:
        raise ExecutionError("MARKET_BINDING_MISMATCH", "order book does not belong to the order's token")

    price = to_decimal(intent.get("price"), name="price")
    size = to_decimal(intent.get("quantity"), name="quantity")

    if market.tick_size <= 0:
        raise ExecutionError("VENUE_CONFIG_INVALID", "market tick size is not positive")
    # /markets and /book each report the tick independently. Disagreement means
    # one of the two views is stale or wrong; refuse rather than pick a winner.
    if book.tick_size is not None and book.tick_size != market.tick_size:
        raise ExecutionError("VENUE_CONFIG_INVALID", "market and order book disagree on tick size")
    if price % market.tick_size != 0:
        raise ExecutionError("TICK_SIZE_VIOLATION", f"price is not a multiple of the {canonical(market.tick_size)} tick")
    if size < market.minimum_order_size:
        raise ExecutionError("BELOW_MIN_ORDER", f"size is below the venue minimum of {canonical(market.minimum_order_size)}")

    age = (now - book.timestamp).total_seconds()
    if age < 0 or age > max_staleness_seconds:
        raise ExecutionError("STALE_BOOK", "order book snapshot is stale or the clock is inconsistent")

    best_ask = book.best_ask
    if best_ask is None:
        raise ExecutionError("EMPTY_BOOK", "order book has no asks to price against")
    best_bid = book.best_bid
    if best_bid is not None and best_bid >= best_ask:
        raise ExecutionError("CROSSED_BOOK", "order book is crossed; refusing to price")

    if max_marketable_premium is not None and price > best_ask:
        premium = (price - best_ask) / best_ask
        if premium > max_marketable_premium:
            raise ExecutionError("PRICE_PROTECTION", "limit price exceeds best ask beyond the allowed premium")

    marketable_depth = sum((level.size for level in book.asks if level.price <= price), Decimal(0))
    spread = best_ask - best_bid if best_bid is not None else None
    return PreTradeAssessment(
        best_bid=canonical(best_bid) if best_bid is not None else None,
        best_ask=canonical(best_ask),
        spread=canonical(spread) if spread is not None else None,
        marketable_depth=canonical(marketable_depth),
        book_age_seconds=age,
    )


class PolymarketAdapter:
    """``ExecutionAdapter`` for Polymarket. Fails closed without an isolated signer."""

    def __init__(self, data_source: PolymarketDataSource, *, signer: OrderSigner | None = None,
                 max_staleness_seconds: float = 15.0, max_marketable_premium: Decimal | str | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.data_source = data_source
        self.signer = signer
        self.max_staleness_seconds = max_staleness_seconds
        self.max_marketable_premium = (
            Decimal(str(max_marketable_premium)) if max_marketable_premium is not None else None
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def validate(self, intent: dict[str, Any]) -> PreTradeAssessment:
        """Re-fetch the live market and book and run the pre-trade gate."""
        market = self.data_source.market(intent["market_id"])
        book = self.data_source.book(intent["token_id"])
        return validate_order(intent, market, book, now=self._clock(),
                              max_staleness_seconds=self.max_staleness_seconds,
                              max_marketable_premium=self.max_marketable_premium)

    def submit(self, intent: dict[str, Any]) -> VenueResult:
        assessment = self.validate(intent)  # always revalidate immediately before signing
        return self._require_signer().submit(intent, assessment)

    def cancel(self, intent: dict[str, Any]) -> VenueResult:
        return self._require_signer().cancel(intent)

    def reconcile(self, intent: dict[str, Any]) -> VenueResult:
        return self._require_signer().reconcile(intent)

    def _require_signer(self) -> OrderSigner:
        if self.signer is None:
            raise ExecutionError(
                "SIGNER_UNAVAILABLE",
                "no isolated signer is configured; funded actions are impossible in this build",
            )
        return self.signer


def _parse_market(payload: dict[str, Any], now: datetime) -> MarketSnapshot:
    tokens: dict[str, str] = {}
    for entry in payload.get("tokens") or []:
        outcome = str(entry.get("outcome", "")).strip().upper()
        token_id = str(entry.get("token_id", "")).strip()
        if outcome in ("YES", "NO") and token_id:
            tokens[outcome] = token_id
    # Verified against the live CLOB 2026-07-22: /markets returns
    # ``minimum_tick_size`` (float), not ``tick_size``. Reading the wrong key
    # silently yielded a zero tick, which rejected every order downstream.
    raw_tick = payload.get("minimum_tick_size", payload.get("tick_size"))
    if raw_tick is None:
        raise ExecutionError("VENUE_CONFIG_INVALID", "market payload carries no tick size")
    return MarketSnapshot(
        market_id=str(payload.get("condition_id") or payload.get("market_id") or "").strip(),
        question=str(payload.get("question", "")),
        tokens=tokens,
        tick_size=tick_from_venue(raw_tick, name="minimum_tick_size"),
        minimum_order_size=to_decimal(payload.get("minimum_order_size", "0"), name="minimum_order_size"),
        active=bool(payload.get("active", False)),
        closed=bool(payload.get("closed", True)),
        accepting_orders=bool(payload.get("accepting_orders", False)),
        timestamp=now,
        neg_risk=bool(payload.get("neg_risk", False)),
    )


def _parse_timestamp(value: Any) -> datetime:
    if value is None:
        raise ExecutionError("INVALID_VENUE_DATA", "order book is missing a timestamp")
    try:
        millis = int(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionError("INVALID_VENUE_DATA", "order book timestamp is not an epoch value") from exc
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)


def _parse_book(payload: dict[str, Any]) -> OrderBook:
    def levels(key: str) -> list[BookLevel]:
        parsed = []
        for entry in payload.get(key) or []:
            parsed.append(BookLevel(
                to_decimal(entry.get("price"), name="book price"),
                to_decimal(entry.get("size"), name="book size"),
            ))
        return parsed

    raw_tick = payload.get("tick_size")
    return OrderBook.build(
        str(payload.get("asset_id") or payload.get("market") or "").strip(),
        levels("bids"), levels("asks"), _parse_timestamp(payload.get("timestamp")),
        tick_from_venue(raw_tick, name="book tick_size") if raw_tick is not None else None,
    )


class HttpPolymarketDataSource:
    """Read-only public CLOB data over an injected ``httpx`` client.

    PROVISIONAL field mapping — verify and pin against the official py-sdk
    before any funded use. Holds no credentials; issues only public GETs.
    """

    def __init__(self, client: Any, *, base_url: str = "https://clob.polymarket.com",
                 clock: Callable[[], datetime] | None = None):
        self._client = client
        self._base = base_url.rstrip("/")
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def market(self, market_id: str) -> MarketSnapshot:
        response = self._client.get(f"{self._base}/markets/{market_id}")
        response.raise_for_status()
        return _parse_market(response.json(), self._clock())

    def book(self, token_id: str) -> OrderBook:
        response = self._client.get(f"{self._base}/book", params={"token_id": token_id})
        response.raise_for_status()
        return _parse_book(response.json())
