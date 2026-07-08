"""Opportunity scanner.

This module turns the single-market proof paths into a batch scanner. It still
does not trade automatically; it ranks markets where the deterministic oracle's
edge clears both its own uncertainty band and real trading friction.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rwoo import edge
from rwoo.engines import economics, sports, weather
from rwoo.readers import kalshi, polymarket
from rwoo.weather_stations import STATIONS, station_for_series

WEATHER_SERIES = ["KXHIGHNY", "KXHIGHCHI", "KXHIGHLAX", "KXHIGHMIA", "KXHIGHDEN"]
ECONOMICS_SERIES = ["KXCPICORE"]
WEATHER_TIMEZONES = {
    "KXHIGHNY": "America/New_York",
    "KXHIGHCHI": "America/Chicago",
    "KXHIGHLAX": "America/Los_Angeles",
    "KXHIGHMIA": "America/New_York",
    "KXHIGHDEN": "America/Denver",
}


@dataclass
class ScanRecord:
    venue: str
    market_id: str
    question: str
    domain: str
    implied_prob: float
    spread: float
    oracle_prob: float | None
    prob_low: float | None
    prob_high: float | None
    confidence: float | None
    side: str | None
    actionable: bool
    edge_points: float | None
    total_friction: float | None
    net_edge_points: float | None
    reason: str
    method: str
    resolution_time: str | None
    fetched_at: str


def _month_from_event_ticker(event_ticker: str) -> int | None:
    month_abbr = event_ticker.rsplit("-", 1)[-1][2:5].upper()
    months = {
        "JAN": 1,
        "FEB": 2,
        "MAR": 3,
        "APR": 4,
        "MAY": 5,
        "JUN": 6,
        "JUL": 7,
        "AUG": 8,
        "SEP": 9,
        "OCT": 10,
        "NOV": 11,
        "DEC": 12,
    }
    return months.get(month_abbr)


def _market_fee_multiplier(market) -> float:
    raw_market = market.raw.get("market", {})
    return float(raw_market.get("fee_multiplier") or 1)


def _record_from_result(market, engine_result: dict, qualified_edge: dict) -> ScanRecord:
    friction = qualified_edge.get("friction") or {}
    edge_points = qualified_edge.get("edge_points")
    total_friction = friction.get("total_friction")
    net_edge = None
    if edge_points is not None and total_friction is not None:
        net_edge = abs(edge_points) - total_friction
    return ScanRecord(
        venue=market.venue,
        market_id=market.market_id,
        question=market.question,
        domain=market.domain,
        implied_prob=market.implied_prob,
        spread=market.spread,
        oracle_prob=engine_result.get("oracle_prob"),
        prob_low=engine_result.get("prob_low"),
        prob_high=engine_result.get("prob_high"),
        confidence=engine_result.get("confidence"),
        side=qualified_edge.get("side"),
        actionable=qualified_edge.get("actionable") is True,
        edge_points=edge_points,
        total_friction=total_friction,
        net_edge_points=net_edge,
        reason=qualified_edge.get("reason", ""),
        method=engine_result.get("method", ""),
        resolution_time=market.resolution_time,
        fetched_at=market.fetched_at,
    )


def evaluate_market(market) -> ScanRecord | None:
    raw_market = market.raw.get("market", {})
    engine_result: dict[str, Any] | None = None

    if market.venue == "kalshi" and market.domain == "weather":
        event_ticker = raw_market.get("event_ticker")
        series_ticker = (event_ticker or "").split("-", 1)[0]
        if not event_ticker or series_ticker not in STATIONS or not raw_market.get("strike_type"):
            return None
        station = station_for_series(series_ticker)
        target_date = kalshi.parse_event_date(event_ticker)
        engine_result = weather.compute_weather_probability(
            lat=station.lat,
            lon=station.lon,
            target_date=target_date,
            timezone_name=WEATHER_TIMEZONES.get(series_ticker, "UTC"),
            strike_type=raw_market["strike_type"],
            floor_strike=raw_market.get("floor_strike"),
            cap_strike=raw_market.get("cap_strike"),
            include_base_rate=False,
        )
    elif market.venue == "kalshi" and market.domain == "economics":
        event_ticker = raw_market.get("event_ticker", "")
        if not event_ticker.startswith("KXCPICORE-") or not raw_market.get("strike_type"):
            return None
        engine_result = economics.compute_core_cpi_probability(
            strike_type=raw_market["strike_type"],
            floor_strike=raw_market.get("floor_strike"),
            cap_strike=raw_market.get("cap_strike"),
            target_month=_month_from_event_ticker(event_ticker),
        )
    elif market.venue == "polymarket" and market.domain == "sports":
        if not market.question.endswith("win the 2026 FIFA World Cup?"):
            return None
        engine_result = sports.compute_world_cup_probability(market.question)
    else:
        return None

    qualified_edge = edge.compute_edge(
        market,
        engine_result,
        fee_multiplier=_market_fee_multiplier(market) if market.venue == "kalshi" else 1,
    )
    return _record_from_result(market, engine_result, qualified_edge)


def _score_record(record: ScanRecord) -> tuple[int, float, float]:
    net = record.net_edge_points
    if net is None or math.isnan(net):
        net = -1.0
    confidence = record.confidence if record.confidence is not None else 0.0
    return (1 if record.actionable else 0, net, confidence)


def scan_opportunities(
    *,
    max_weather_markets_per_series: int = 20,
    max_economics_markets: int = 40,
    polymarket_limit: int = 100,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    markets = []

    for series in WEATHER_SERIES:
        markets.extend(kalshi.fetch_canonical_markets_for_series(series, limit=max_weather_markets_per_series))
    for series in ECONOMICS_SERIES:
        markets.extend(kalshi.fetch_canonical_markets_for_series(series, limit=max_economics_markets))
    markets.extend(polymarket.fetch_canonical_markets(limit=polymarket_limit, closed=False))

    records = []
    skipped = 0
    errors = []
    for market in markets:
        try:
            record = evaluate_market(market)
            if record is None:
                skipped += 1
            else:
                records.append(record)
        except Exception as exc:  # noqa: BLE001
            errors.append(
                {
                    "venue": market.venue,
                    "market_id": market.market_id,
                    "question": market.question,
                    "error": str(exc),
                }
            )

    ranked = sorted(records, key=_score_record, reverse=True)
    actionable = [record for record in ranked if record.actionable]
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started_at,
        "markets_seen": len(markets),
        "markets_evaluated": len(records),
        "markets_skipped": skipped,
        "errors": errors,
        "actionable_count": len(actionable),
        "top": [asdict(record) for record in ranked],
        "action_rule": "YES if price < prob_low - costs; NO if price > prob_high + costs; otherwise no trade",
    }


def render_markdown(scan: dict[str, Any], limit: int = 20) -> str:
    lines = [
        "# Opportunity Scan",
        "",
        f"- Created: {scan['created_at']}",
        f"- Markets seen: {scan['markets_seen']}",
        f"- Markets evaluated: {scan['markets_evaluated']}",
        f"- Actionable: {scan['actionable_count']}",
        f"- Rule: {scan['action_rule']}",
        "",
        "| Rank | Action | Venue | Market | Side | Oracle | Market | Net edge | Cost | Reason |",
        "| ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for idx, record in enumerate(scan["top"][:limit], start=1):
        action = "TRADE" if record["actionable"] else "WAIT"
        oracle = _fmt_prob(record["oracle_prob"])
        implied = _fmt_prob(record["implied_prob"])
        net = _fmt_prob(record["net_edge_points"])
        cost = _fmt_prob(record["total_friction"])
        question = record["question"].replace("|", " ")
        reason = record["reason"].replace("|", " ")
        lines.append(
            f"| {idx} | {action} | {record['venue']} | {question} | {record['side'] or ''} | "
            f"{oracle} | {implied} | {net} | {cost} | {reason} |"
        )
    if scan["errors"]:
        lines.extend(["", "## Errors", ""])
        for err in scan["errors"][:10]:
            lines.append(f"- {err['venue']} {err['market_id']}: {err['error']}")
    lines.append("")
    return "\n".join(lines)


def _fmt_prob(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.4f}"


def write_scan_artifacts(
    scan: dict[str, Any],
    *,
    json_path: str | Path = "data/public/opportunity_scan_latest.json",
    md_path: str | Path = "data/public/opportunity_scan_latest.md",
) -> None:
    json_path = Path(json_path)
    md_path = Path(md_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(scan, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(render_markdown(scan), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan live markets for cost-adjusted deterministic edges")
    parser.add_argument("--weather-limit", type=int, default=20)
    parser.add_argument("--economics-limit", type=int, default=40)
    parser.add_argument("--polymarket-limit", type=int, default=100)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--write", action="store_true", help="write JSON/Markdown artifacts under data/public")
    parser.add_argument("--json", action="store_true", help="print raw JSON instead of markdown")
    args = parser.parse_args(argv)

    scan = scan_opportunities(
        max_weather_markets_per_series=args.weather_limit,
        max_economics_markets=args.economics_limit,
        polymarket_limit=args.polymarket_limit,
    )
    if args.write:
        write_scan_artifacts(scan)
    if args.json:
        print(json.dumps(scan, indent=2, sort_keys=True))
    else:
        print(render_markdown(scan, limit=args.top))
    return 0 if not scan["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
