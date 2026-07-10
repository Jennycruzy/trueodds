"""Shared test helpers.

`make_market` builds a `CanonicalMarket` with sane defaults so each test only
states the fields that matter to the parser under test. `kalshi_raw` builds the
`{"market": {...}}` envelope the Kalshi parsers read out of `market.raw`.
"""
from __future__ import annotations

from typing import Any

from rwoo.models import CanonicalMarket


def make_market(
    *,
    venue: str = "limitless",
    domain: str = "economics",
    question: str = "",
    resolution_rule: str = "",
    resolution_source: str = "official source",
    market_id: str = "TEST-1",
    raw: dict[str, Any] | None = None,
) -> CanonicalMarket:
    return CanonicalMarket(
        venue=venue,
        market_id=market_id,
        question=question,
        domain=domain,
        resolution_rule=resolution_rule,
        resolution_source=resolution_source,
        resolution_time="2026-07-15T00:00:00Z",
        implied_prob=0.5,
        spread=0.02,
        fetched_at="2026-07-10T00:00:00Z",
        raw=raw or {},
    )


def kalshi_raw(**market_fields: Any) -> dict[str, Any]:
    """Wrap Kalshi market fields the way the reader stores them."""
    return {"market": dict(market_fields)}
