"""Polymarket market reader — Stage 1.

Gamma API field shapes verified live against the real API; see
docs/VERIFICATION_LEDGER.md §3, including the corrected finding that Gamma's
own `bestBid`/`bestAsk`/`spread` fields are authoritative for the midpoint —
no separate CLOB call is required for the canonical object.
"""
from datetime import datetime, timezone

import httpx

from rwoo.domain import classify_polymarket
from rwoo.models import CanonicalMarket

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_markets(
    limit: int = 5,
    closed: bool = False,
    offset: int = 0,
    client: httpx.Client | None = None,
) -> list[dict]:
    own_client = client is None
    client = client or httpx.Client(timeout=15)
    try:
        resp = client.get(
            f"{GAMMA_BASE_URL}/markets",
            params={"limit": limit, "closed": str(closed).lower(), "offset": offset},
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        if own_client:
            client.close()


def to_canonical(market: dict) -> CanonicalMarket:
    best_bid = market.get("bestBid")
    best_ask = market.get("bestAsk")
    if best_bid is None or best_ask is None:
        # Some markets (e.g. very new or very thin) may not have quoted a
        # book yet. Fall back to outcomePrices (Yes price) as a last resort,
        # with spread reported as unknown (0.0) rather than fabricated.
        import json as _json
        outcome_prices = market.get("outcomePrices")
        prices = _json.loads(outcome_prices) if isinstance(outcome_prices, str) else (outcome_prices or [])
        implied_prob = float(prices[0]) if prices else 0.5
        spread = 0.0
    else:
        best_bid = float(best_bid)
        best_ask = float(best_ask)
        implied_prob = (best_bid + best_ask) / 2
        spread = market.get("spread")
        spread = float(spread) if spread is not None else (best_ask - best_bid)

    event_tags: list[str] = []
    for ev in market.get("events") or []:
        for t in ev.get("tags") or []:
            label = t.get("label")
            if label:
                event_tags.append(label)

    domain = classify_polymarket(event_tags, market.get("question", ""))

    # implied_prob prices outcomes[0]. For a subject-vs-subject event that is a
    # generic "Yes", so the real subject is the market's groupItemTitle; fall
    # back to a non-Yes/No first outcome label.
    import json as _json
    outcomes_raw = market.get("outcomes")
    outcomes = _json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else (outcomes_raw or [])
    first_outcome = outcomes[0] if outcomes else None
    yes_subtitle = market.get("groupItemTitle") or (
        first_outcome if first_outcome and str(first_outcome).strip().lower() not in ("yes", "no") else None
    )

    return CanonicalMarket(
        venue="polymarket",
        market_id=market.get("conditionId", market.get("id", "")),
        question=market.get("question", ""),
        domain=domain,
        resolution_rule=market.get("description", ""),
        resolution_source=market.get("resolutionSource") or "see resolution rule text",
        resolution_time=market.get("endDate"),
        implied_prob=implied_prob,
        spread=spread,
        fetched_at=_now_iso(),
        yes_subtitle=yes_subtitle,
        trading_close_time=market.get("endDate"),
        market_status="closed" if market.get("closed") else ("active" if market.get("active", True) else "inactive"),
        raw=market,
    )


def fetch_canonical_markets(limit: int = 5, closed: bool = False, offset: int = 0) -> list[CanonicalMarket]:
    return [to_canonical(m) for m in fetch_markets(limit=limit, closed=closed, offset=offset)]


def fetch_canonical_market(market_id: str, client: httpx.Client | None = None) -> CanonicalMarket | None:
    """Single canonical market by Gamma id or condition id.

    Gamma's `/markets/{id}` path takes the numeric id; a caller holding a
    0x-prefixed condition id is matched through the `condition_ids` filter.
    Returns None when nothing matches.
    """
    own_client = client is None
    client = client or httpx.Client(timeout=15)
    try:
        if market_id.startswith("0x"):
            resp = client.get(f"{GAMMA_BASE_URL}/markets", params={"condition_ids": market_id})
            resp.raise_for_status()
            rows = resp.json()
            row = rows[0] if isinstance(rows, list) and rows else None
        else:
            resp = client.get(f"{GAMMA_BASE_URL}/markets/{market_id}")
            resp.raise_for_status()
            row = resp.json()
            if isinstance(row, list):
                row = row[0] if row else None
        return to_canonical(row) if row else None
    finally:
        if own_client:
            client.close()


def fetch_canonical_active_markets(max_markets: int = 500, page_size: int = 100) -> list[CanonicalMarket]:
    out: list[CanonicalMarket] = []
    offset = 0
    with httpx.Client(timeout=20) as client:
        while len(out) < max_markets:
            batch_size = min(page_size, max_markets - len(out))
            batch = fetch_markets(limit=batch_size, closed=False, offset=offset, client=client)
            if not batch:
                break
            out.extend(to_canonical(m) for m in batch)
            offset += len(batch)
            if len(batch) < batch_size:
                break
    return out
