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

    @classmethod
    def build(cls, token_id: str, bids: Iterable[BookLevel], asks: Iterable[BookLevel],
              timestamp: datetime) -> "OrderBook":
        ordered_bids = tuple(sorted(bids, key=lambda level: level.price, reverse=True))
        ordered_asks = tuple(sorted(asks, key=lambda level: level.price))
        return cls(token_id, ordered_bids, ordered_asks, timestamp)

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


@dataclass(frozen=True)
class PreTradeAssessment:
    """Read-only, reportable result of a passing pre-trade check."""

    best_bid: str | None
    best_ask: str
    spread: str | None
    marketable_depth: str  # size resting at or better than the limit price
    book_age_seconds: float


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

    price = to_decimal(intent.get("price"), name="price")
    size = to_decimal(intent.get("quantity"), name="quantity")

    if market.tick_size <= 0:
        raise ExecutionError("VENUE_CONFIG_INVALID", "market tick size is not positive")
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
    return MarketSnapshot(
        market_id=str(payload.get("condition_id") or payload.get("market_id") or "").strip(),
        question=str(payload.get("question", "")),
        tokens=tokens,
        tick_size=to_decimal(payload.get("tick_size", "0"), name="tick_size"),
        minimum_order_size=to_decimal(payload.get("minimum_order_size", "0"), name="minimum_order_size"),
        active=bool(payload.get("active", False)),
        closed=bool(payload.get("closed", True)),
        accepting_orders=bool(payload.get("accepting_orders", False)),
        timestamp=now,
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

    return OrderBook.build(
        str(payload.get("asset_id") or payload.get("market") or "").strip(),
        levels("bids"), levels("asks"), _parse_timestamp(payload.get("timestamp")),
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
