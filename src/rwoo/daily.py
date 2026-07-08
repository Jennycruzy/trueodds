"""Daily proof loop.

This module builds one real market verdict, writes it to the append-only
receipt ledger, and publishes machine-readable plus markdown artifacts from
the same record. It does not post to social media by itself; the important
build invariant is that any public post can be generated from a committed
receipt rather than hand-written after the fact.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rwoo import edge, receipts
from rwoo.engines import weather
from rwoo.readers import kalshi
from rwoo.weather_stations import station_for_series

DEFAULT_LEDGER = Path("data/receipts/daily_proofs.jsonl")
DEFAULT_PUBLIC_JSON = Path("data/public/daily_proof_latest.json")
DEFAULT_PUBLIC_MD = Path("data/public/daily_proof_latest.md")
SERIES_TIMEZONES = {
    "KXHIGHNY": "America/New_York",
    "KXHIGHCHI": "America/Chicago",
    "KXHIGHLAX": "America/Los_Angeles",
    "KXHIGHMIA": "America/New_York",
    "KXHIGHDEN": "America/Denver",
}


def _pick_weather_market(series_ticker: str = "KXHIGHNY") -> tuple[Any, dict]:
    markets = kalshi.fetch_markets_for_event(
        # Use today's listed event when available by reading the series endpoint
        # indirectly through the market list; fall back to the first event ticker
        # embedded in a current market.
        event_ticker=_current_event_ticker(series_ticker)
    )
    tradable = [m for m in markets if m.spread >= 0 and m.raw.get("market", {}).get("strike_type")]
    if not tradable:
        raise RuntimeError(f"no structured tradable weather markets found for {series_ticker}")
    market = min(tradable, key=lambda m: abs(m.implied_prob - 0.5))
    return market, market.raw["market"]


def _current_event_ticker(series_ticker: str) -> str:
    import httpx

    resp = httpx.get(
        f"{kalshi.BASE_URL}/markets",
        params={"limit": 20, "series_ticker": series_ticker},
        timeout=15,
    )
    resp.raise_for_status()
    markets = resp.json().get("markets", [])
    for market in markets:
        if market.get("event_ticker"):
            return market["event_ticker"]
    raise RuntimeError(f"could not discover a current event_ticker for {series_ticker}")


def build_daily_proof(
    *,
    ledger_path: str | Path = DEFAULT_LEDGER,
    public_json_path: str | Path = DEFAULT_PUBLIC_JSON,
    public_md_path: str | Path = DEFAULT_PUBLIC_MD,
) -> dict[str, Any]:
    market, raw_market = _pick_weather_market("KXHIGHNY")
    station = station_for_series(raw_market["event_ticker"].split("-", 1)[0])
    target_date = kalshi.parse_event_date(raw_market["event_ticker"])
    engine_result = weather.compute_weather_probability(
        lat=station.lat,
        lon=station.lon,
        target_date=target_date,
        timezone_name=SERIES_TIMEZONES.get(raw_market["event_ticker"].split("-", 1)[0], "UTC"),
        strike_type=raw_market["strike_type"],
        floor_strike=raw_market.get("floor_strike"),
        cap_strike=raw_market.get("cap_strike"),
        include_base_rate=False,
    )
    qualified_edge = edge.compute_edge(market, engine_result, fee_multiplier=float(raw_market.get("fee_multiplier") or 1))
    payload = receipts.make_receipt_payload(
        venue=market.venue,
        market_id=market.market_id,
        resolution_rule=market.resolution_rule,
        oracle_prob=engine_result["oracle_prob"],
        implied_prob=market.implied_prob,
        edge=qualified_edge,
        confidence=engine_result.get("confidence"),
        sources={
            "station": station.name,
            "target_date": target_date,
            "per_source_values": engine_result.get("per_source_values"),
            "method": engine_result.get("method"),
        },
    )
    ledger = receipts.AppendOnlyLedger(ledger_path)
    record = ledger.append("daily_proof", payload)
    proof = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ledger_path": str(ledger_path),
        "record": asdict(record),
        "ledger_verification": ledger.verify(),
    }
    public_json_path = Path(public_json_path)
    public_md_path = Path(public_md_path)
    public_json_path.parent.mkdir(parents=True, exist_ok=True)
    public_json_path.write_text(json.dumps(proof, indent=2, sort_keys=True), encoding="utf-8")
    public_md_path.write_text(render_daily_markdown(proof), encoding="utf-8")
    return proof


def render_daily_markdown(proof: dict[str, Any]) -> str:
    payload = proof["record"]["payload"]
    edge_result = payload["edge"]
    return "\n".join(
        [
            "# Daily Real-World Odds Oracle Proof",
            "",
            f"- Created: {proof['created_at']}",
            f"- Market: {payload['venue']} / {payload['market_id']}",
            f"- Oracle probability: {payload['oracle_prob']:.4f}",
            f"- Market implied probability: {payload['implied_prob']:.4f}",
            f"- Actionable: {edge_result['actionable']}",
            f"- Reason: {edge_result['reason']}",
            f"- Receipt sequence: {proof['record']['sequence']}",
            f"- Receipt hash: `{proof['record']['record_hash']}`",
            f"- Ledger head: `{proof['record']['chain_hash']}`",
            "",
        ]
    )
