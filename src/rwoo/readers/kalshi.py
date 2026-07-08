"""Kalshi market reader — Stage 1.

Base URL, auth (none needed for public market reads), and field shapes are
all verified live against the real API; see docs/VERIFICATION_LEDGER.md §2.
"""
from datetime import datetime, timezone

import httpx

from rwoo.domain import classify_kalshi
from rwoo.models import CanonicalMarket

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

_MONTH_ABBR = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
    "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}


def parse_event_date(event_ticker: str) -> str:
    """Kalshi daily-event tickers encode the target calendar date in their
    suffix, e.g. 'KXHIGHNY-26JUL09' -> 2026-07-09. This is the unambiguous
    source for "which local calendar day does this market measure" — the
    event's `strike_date` field is a UTC settlement-cutoff timestamp that
    often falls in the early hours of the *next* day, so parsing it directly
    as the target date would be off by one for late-closing series."""
    suffix = event_ticker.rsplit("-", 1)[-1]
    year, month_abbr, day = suffix[:2], suffix[2:5], suffix[5:7]
    month = _MONTH_ABBR[month_abbr.upper()]
    return f"20{year}-{month}-{day}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_event(event_ticker: str, client: httpx.Client | None = None) -> dict:
    """Fetch a Kalshi event, which embeds its markets and its
    settlement_sources — the event level is where category and the named
    official settlement source live (verified live, Ledger §2)."""
    own_client = client is None
    client = client or httpx.Client(timeout=15)
    try:
        resp = client.get(f"{BASE_URL}/events/{event_ticker}")
        resp.raise_for_status()
        return resp.json()
    finally:
        if own_client:
            client.close()


def fetch_markets(series_ticker: str, limit: int = 100, client: httpx.Client | None = None) -> list[dict]:
    own_client = client is None
    client = client or httpx.Client(timeout=15)
    try:
        resp = client.get(
            f"{BASE_URL}/markets",
            params={"limit": limit, "series_ticker": series_ticker},
        )
        resp.raise_for_status()
        return resp.json().get("markets", [])
    finally:
        if own_client:
            client.close()


def _series_category(series_ticker: str) -> str | None:
    if series_ticker.startswith(("KXHIGH", "KXLOW")):
        return "Climate and Weather"
    if series_ticker.startswith(("KXCPI", "KXFED", "KXGDP", "KXU3", "KXPAYROLLS")):
        return "Economics"
    if series_ticker.startswith(("KXMENWORLDCUP", "KXNBA", "KXNFL", "KXMLB", "KXNHL")):
        return "Sports"
    return None


def to_canonical(event: dict, market: dict) -> CanonicalMarket:
    ev = event["event"]
    settlement_sources = ev.get("settlement_sources") or []
    resolution_source = ", ".join(
        f"{s.get('name')} ({s.get('url')})" for s in settlement_sources
    ) or "not specified in event metadata"

    yes_bid = float(market.get("yes_bid_dollars", 0) or 0)
    yes_ask = float(market.get("yes_ask_dollars", 0) or 0)
    implied_prob = (yes_bid + yes_ask) / 2
    spread = yes_ask - yes_bid

    domain = classify_kalshi(ev.get("category"), market.get("title", ""))

    return CanonicalMarket(
        venue="kalshi",
        market_id=market["ticker"],
        question=market.get("title") or ev.get("title", ""),
        domain=domain,
        resolution_rule=market.get("rules_primary", ""),
        resolution_source=resolution_source,
        resolution_time=market.get("expiration_time") or ev.get("strike_date"),
        implied_prob=implied_prob,
        spread=spread,
        fetched_at=_now_iso(),
        raw={"event": ev, "market": market},
    )


def market_row_to_canonical(market: dict) -> CanonicalMarket:
    series_ticker = market.get("series_ticker") or market.get("event_ticker", "").split("-", 1)[0]
    category = _series_category(series_ticker)
    yes_bid = float(market.get("yes_bid_dollars", 0) or 0)
    yes_ask = float(market.get("yes_ask_dollars", 0) or 0)
    implied_prob = (yes_bid + yes_ask) / 2
    spread = yes_ask - yes_bid
    title = market.get("title", "")

    return CanonicalMarket(
        venue="kalshi",
        market_id=market["ticker"],
        question=title,
        domain=classify_kalshi(category, title),
        resolution_rule=market.get("rules_primary", ""),
        resolution_source=market.get("settlement_source") or "see resolution rule text",
        resolution_time=market.get("expiration_time") or market.get("latest_expiration_time"),
        implied_prob=implied_prob,
        spread=spread,
        fetched_at=_now_iso(),
        raw={"market": market, "series_ticker": series_ticker},
    )


def fetch_markets_for_event(event_ticker: str, client: httpx.Client | None = None) -> list[CanonicalMarket]:
    data = fetch_event(event_ticker, client=client)
    event = {"event": data["event"]}
    return [to_canonical(event, m) for m in data.get("markets", [])]


def fetch_canonical_markets_for_series(
    series_ticker: str,
    limit: int = 100,
    client: httpx.Client | None = None,
) -> list[CanonicalMarket]:
    return [market_row_to_canonical(m) for m in fetch_markets(series_ticker, limit=limit, client=client)]
