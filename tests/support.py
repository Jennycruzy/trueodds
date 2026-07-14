"""Shared test helpers.

`make_market` builds a `CanonicalMarket` with sane defaults so each test only
states the fields that matter to the parser under test. `kalshi_raw` builds the
`{"market": {...}}` envelope the Kalshi parsers read out of `market.raw`.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from rwoo.models import CanonicalMarket


class ASGITestClient:
    """Small synchronous facade over HTTPX's maintained ASGI transport.

    Starlette's synchronous TestClient has changed transport implementations
    across framework releases.  These tests only need HTTP requests, so using
    the public ASGI transport directly keeps them deterministic and avoids a
    thread-portal dependency.
    """

    def __init__(self, app, *, raise_server_exceptions: bool = True,
                 base_url: str = "http://testserver"):
        self.app = app
        self.raise_server_exceptions = raise_server_exceptions
        self.base_url = base_url

    def request(self, method: str, path: str, **kwargs):
        async def call():
            transport = httpx.ASGITransport(
                app=self.app, raise_app_exceptions=self.raise_server_exceptions,
            )
            async with httpx.AsyncClient(transport=transport, base_url=self.base_url) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(call())

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs):
        return self.request("POST", path, **kwargs)


def make_market(
    *,
    venue: str = "limitless",
    domain: str = "economics",
    question: str = "",
    resolution_rule: str = "",
    resolution_source: str = "official source",
    market_id: str = "TEST-1",
    yes_subtitle: str | None = None,
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
        yes_subtitle=yes_subtitle,
        raw=raw or {},
    )


def kalshi_raw(**market_fields: Any) -> dict[str, Any]:
    """Wrap Kalshi market fields the way the reader stores them."""
    return {"market": dict(market_fields)}
