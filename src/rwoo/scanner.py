"""Opportunity scanner.

This module turns the single-market proof paths into a batch scanner. It still
does not trade automatically; it ranks markets where the deterministic oracle's
edge clears both its own uncertainty band and real trading friction.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rwoo import edge, weather_stations
from rwoo.coverage import classify_market_shape
from rwoo.engines import economics, energy, hurricane, sports, weather
from rwoo.parsers import parse_commodity_market, parse_economics_market, parse_sports_market, parse_weather_market
from rwoo.explanations import build_why_trace
from rwoo.cross_venue import find_cross_venue_edges
from rwoo.edge_audit import audit_scan, write_audit
from rwoo.identity import event_identity, model_version
from rwoo.readers import kalshi, limitless, noaa_hurricane, polymarket
from rwoo import economic_sources

# Every weather series with a verified station is swept completely; the
# registry in weather_stations.py is the single source of truth.
WEATHER_SERIES = sorted(weather_stations.SERIES)
# Kalshi economics series with a wired engine (or an honest engine-side
# refusal path, e.g. KXFED far-dated meetings).
ECONOMICS_SERIES = ["KXCPICORE", "KXECONSTATCPI", "KXCPIYOY", "KXGDP", "KXU3", "KXPAYROLLS", "KXFED"]
SPORTS_SERIES = ["KXWCSTAGEOFELIM"]
KALSHI_ACTIVE_DEFAULT_LIMIT = 2000
POLYMARKET_DEFAULT_LIMIT = 2000
LIMITLESS_DEFAULT_LIMIT = 1000
_SCAN_SOURCE_CACHE: dict[str, Any] = {}
EXPANSION_FAMILIES = (
    "weather.hurricane_season",
    "energy.henry_hub_spot",
    "energy.commodity_price",
    "agriculture.commodity_price",
)
DEFAULT_SCAN_JSON = Path(os.environ.get(
    "RWOO_OPPORTUNITY_SCAN_PATH", "data/public/opportunity_scan_latest.json",
))
DEFAULT_SCAN_MD = Path(os.environ.get(
    "RWOO_OPPORTUNITY_SCAN_MD_PATH", str(DEFAULT_SCAN_JSON.with_suffix(".md")),
))


def _scan_source(key: str, loader):
    if key not in _SCAN_SOURCE_CACHE:
        _SCAN_SOURCE_CACHE[key] = loader()
    return _SCAN_SOURCE_CACHE[key]


@dataclass
class ScanRecord:
    venue: str
    market_id: str
    question: str
    domain: str
    family: str
    shape: str
    coverage_status: str
    missing: str | None
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
    why: dict[str, Any]
    execution: dict[str, Any] | None
    event_group_id: str
    event_identity: dict[str, Any]
    model_version: str
    resolution_rule: str
    resolution_source: str
    venue_resolution_id: str
    resolution_time: str | None
    fetched_at: str
    trading_close_time: str | None = None
    market_status: str | None = None
    source_timestamp: str | None = None


def _bump_counter(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


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
    coverage = classify_market_shape(market)
    identity = event_identity(market, coverage.family, coverage.shape)
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
        family=coverage.family,
        shape=coverage.shape,
        coverage_status=_coverage_status_from_edge(qualified_edge),
        missing=None if qualified_edge.get("actionable") is True else _missing_from_edge(qualified_edge),
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
        why=build_why_trace(engine_result),
        execution=qualified_edge.get("execution"),
        event_group_id=identity["event_group_id"],
        event_identity=identity["event_identity"],
        model_version=model_version(coverage.family),
        resolution_rule=market.resolution_rule,
        resolution_source=market.resolution_source,
        venue_resolution_id=_venue_resolution_id(market),
        resolution_time=market.resolution_time,
        fetched_at=market.fetched_at,
        trading_close_time=market.trading_close_time,
        market_status=market.market_status,
        source_timestamp=engine_result.get("data_freshness"),
    )


def _coverage_status_from_edge(qualified_edge: dict) -> str:
    if qualified_edge.get("actionable") is True:
        return "actionable"
    reason = str(qualified_edge.get("reason", "")).lower()
    if "fee" in reason and "not quantified" in reason:
        return "fee_missing"
    return "wait"


def _missing_from_edge(qualified_edge: dict) -> str | None:
    reason = qualified_edge.get("reason")
    return str(reason) if reason else None


def _unsupported_record(market, reason: str) -> ScanRecord:
    coverage = classify_market_shape(market)
    identity = event_identity(market, coverage.family, coverage.shape)
    friction = edge.estimate_friction(
        market,
        fee_multiplier=_market_fee_multiplier(market) if market.venue == "kalshi" else 1,
    )
    return ScanRecord(
        venue=market.venue,
        market_id=market.market_id,
        question=market.question,
        domain=market.domain,
        family=coverage.family,
        shape=coverage.shape,
        coverage_status=coverage.status,
        missing=coverage.reason,
        implied_prob=market.implied_prob,
        spread=market.spread,
        oracle_prob=None,
        prob_low=None,
        prob_high=None,
        confidence=None,
        side=None,
        actionable=False,
        edge_points=None,
        total_friction=friction.get("total_friction"),
        net_edge_points=None,
        reason=f"included but not actionable: {coverage.reason or reason}",
        method=friction.get("method", ""),
        why={"summary": coverage.reason},
        execution=None,
        event_group_id=identity["event_group_id"],
        event_identity=identity["event_identity"],
        model_version=model_version(coverage.family),
        resolution_rule=market.resolution_rule,
        resolution_source=market.resolution_source,
        venue_resolution_id=_venue_resolution_id(market),
        resolution_time=market.resolution_time,
        fetched_at=market.fetched_at,
        trading_close_time=market.trading_close_time,
        market_status=market.market_status,
        source_timestamp=None,
    )


def _venue_resolution_id(market) -> str:
    if market.venue == "polymarket":
        return str(market.raw.get("id") or market.market_id)
    if market.venue == "limitless":
        raw_market = market.raw.get("market", {}) if isinstance(market.raw, dict) else {}
        return str(raw_market.get("slug") or raw_market.get("id") or market.market_id)
    return market.market_id


def evaluate_market(market) -> ScanRecord | None:
    raw_market = market.raw.get("market", {})
    engine_result: dict[str, Any] | None = None

    if market.domain == "weather":
        parsed = parse_weather_market(market)
        if parsed.status == "engine_available" and parsed.family == "weather.hurricane_season":
            engine_result = hurricane.compute_atlantic_season_count_probability(
                parsed.metric or "", parsed.strike_type or "", parsed.floor_strike,
                target_year=parsed.target_year,
                outlook=_scan_source("noaa_atlantic_outlook", noaa_hurricane.fetch_atlantic_outlook),
            )
        elif parsed.status != "engine_available" or parsed.metric not in weather.METRICS:
            return None
        else:
            lat = parsed.raw.get("lat")
            lon = parsed.raw.get("lon")
            if lat is None or lon is None or not parsed.target_date or not parsed.strike_type:
                return None
            engine_result = weather.compute_weather_probability(
                lat=lat,
                lon=lon,
                target_date=parsed.target_date,
                timezone_name=parsed.timezone_name or "UTC",
                strike_type=parsed.strike_type,
                floor_strike=parsed.floor_strike,
                cap_strike=parsed.cap_strike,
                include_base_rate=False,
                metric=parsed.metric,
            )
    elif market.domain == "economics":
        event_ticker = raw_market.get("event_ticker", "")
        if market.venue == "kalshi" and event_ticker.startswith("KXCPICORE-") and raw_market.get("strike_type"):
            engine_result = economics.compute_core_cpi_probability(
                strike_type=raw_market["strike_type"],
                floor_strike=raw_market.get("floor_strike"),
                cap_strike=raw_market.get("cap_strike"),
                target_month=_month_from_event_ticker(event_ticker),
            )
        else:
            parsed = parse_economics_market(market)
            if parsed is None or parsed.status != "engine_available":
                return None
            engine_result = _economics_engine_result(parsed)
            if engine_result is None:
                return None
    elif market.domain == "sports":
        parsed = parse_sports_market(market)
        if (
            parsed is not None
            and parsed.status == "engine_available"
            and parsed.shape == "stage_of_elimination"
            and parsed.location
            and parsed.source_series
        ):
            engine_result = sports.compute_world_cup_stage_probability(parsed.location, parsed.source_series)
        elif (
            parsed is not None
            and parsed.status == "engine_available"
            and parsed.shape == "match_winner"
            and parsed.family == "sports.tennis"
            and parsed.location
            and parsed.source_series
        ):
            engine_result = sports.compute_tennis_match_probability(parsed.location, parsed.source_series)
        elif parsed is not None and parsed.status == "engine_available" and parsed.shape == "match_winner" and parsed.location and parsed.source_series and parsed.family == "sports.mlb":
            engine_result = sports.compute_mlb_match_probability(parsed.location, parsed.source_series)
        elif parsed is not None and parsed.status == "engine_available" and parsed.shape == "match_winner" and parsed.location and parsed.source_series and parsed.family == "sports.club_soccer":
            engine_result = sports.compute_club_soccer_match_probability(parsed.location, parsed.source_series)
        elif parsed is not None and parsed.status == "engine_available" and parsed.shape == "match_winner" and parsed.location and parsed.source_series and parsed.family == "sports.nba":
            engine_result = sports.compute_nba_match_probability(parsed.location, parsed.source_series)
        elif market.venue == "polymarket" and market.question.endswith("win the 2026 FIFA World Cup?"):
            engine_result = sports.compute_world_cup_probability(market.question)
        elif market.venue == "limitless" and market.raw.get("limitless_supported_shape") == "world_cup_winner":
            engine_result = sports.compute_world_cup_probability(market.question)
        else:
            return None
    elif market.domain == "commodities":
        parsed = parse_commodity_market(market)
        if parsed is None or parsed.status != "engine_available":
            return None
        if parsed.family == "energy.henry_hub_spot" and parsed.target_date:
            engine_result = energy.compute_henry_hub_annual_high_probability(
                parsed.strike_type or "", parsed.floor_strike, parsed.target_date,
                target_year=parsed.target_year,
                issuance_date_iso=parsed.issuance_date,
                series=_scan_source("eia_dhhngsp", lambda: economic_sources.fetch_fred_series("DHHNGSP")),
            )
        else:
            return None
    else:
        return None

    qualified_edge = edge.compute_edge(
        market,
        engine_result,
        fee_multiplier=_market_fee_multiplier(market) if market.venue == "kalshi" else 1,
    )
    return _record_from_result(market, engine_result, qualified_edge)


def _economics_engine_result(parsed) -> dict | None:
    """Route a parsed economics market to its family engine."""
    if parsed.family == "economics.headline_cpi":
        if parsed.shape == "monthly_bin_or_threshold":
            return economics.compute_headline_cpi_monthly_probability(
                strike_type=parsed.strike_type,
                floor_strike=parsed.floor_strike,
                cap_strike=parsed.cap_strike,
                target_month=parsed.target_month,
            )
        return economics.compute_headline_cpi_annual_probability(
            strike_type=parsed.strike_type,
            floor_strike=parsed.floor_strike,
            cap_strike=parsed.cap_strike,
            target_month=parsed.target_month,
        )
    if parsed.family == "economics.gdp" and parsed.source_series:
        return economics.compute_gdp_quarterly_probability(
            strike_type=parsed.strike_type,
            floor_strike=parsed.floor_strike,
            cap_strike=parsed.cap_strike,
            quarter_label=parsed.source_series,
        )
    if parsed.family == "economics.labor":
        if parsed.shape == "unemployment_rate_threshold" and parsed.target_month and parsed.target_year:
            return economics.compute_unemployment_probability(
                strike_type=parsed.strike_type,
                floor_strike=parsed.floor_strike,
                cap_strike=parsed.cap_strike,
                target_month=parsed.target_month,
                target_year=parsed.target_year,
            )
        if parsed.shape == "payrolls_change_threshold":
            return economics.compute_payrolls_probability(
                strike_type=parsed.strike_type,
                floor_strike=parsed.floor_strike,
                cap_strike=parsed.cap_strike,
                target_month=parsed.target_month,
            )
        return None
    if parsed.family == "economics.fed_rates" and parsed.target_date:
        return economics.compute_fed_rate_probability(
            strike_type=parsed.strike_type,
            floor_strike=parsed.floor_strike,
            cap_strike=parsed.cap_strike,
            target_date_iso=parsed.target_date,
        )
    if (
        parsed.family == "economics.recession"
        and parsed.shape == "quarterly_decline"
        and parsed.source_series
    ):
        return economics.compute_recession_quarter_probability(
            int(parsed.source_series[:4]),
            int(parsed.source_series[-1]),
        )
    return None


def skip_reason(market) -> str:
    coverage = classify_market_shape(market)
    if market.venue == "limitless":
        if market.domain in {"weather", "economics", "sports", "commodities"}:
            return f"limitless_{coverage.family}_{coverage.shape}_{coverage.status}"
        return "limitless_other_domain_or_price_oracle_not_supported"
    if market.venue == "polymarket" and market.domain == "sports":
        return "polymarket_sports_not_world_cup_outright"
    if market.venue == "kalshi" and market.domain == "weather":
        return "kalshi_weather_missing_station_or_strike"
    if market.venue == "kalshi" and market.domain == "economics":
        return "kalshi_economics_not_core_cpi_strike"
    return f"{market.venue}_{market.domain}_not_supported"


def _should_include_unsupported(market) -> bool:
    return market.domain in {"weather", "economics", "sports", "commodities"}


def _expansion_series(series_rows: list[dict]) -> list[str]:
    """Select only source-bound series whose shapes have an implemented path."""
    selected = []
    for row in series_rows:
        title = str(row.get("title") or "").lower()
        sources = " ".join(str(item.get("name") or "") for item in (row.get("settlement_sources") or [])).lower()
        ticker = str(row.get("ticker") or "")
        if "energy information administration" in sources and "natural gas" in title:
            selected.append(ticker)
        elif title in {"number of hurricanes", "number of tropical storms", "number of major hurricanes"} and "oceanic and atmospheric administration" in sources:
            selected.append(ticker)
        elif "usda" in sources:
            selected.append(ticker)  # telemetry even when no engine/open market exists
    return sorted(set(selected))


def _unsupported_theme(market) -> str:
    text = f"{market.question} {market.resolution_rule}".lower()
    themes = (
        ("crypto_price", ("bitcoin", "ethereum", "solana", "crypto")),
        ("politics_elections", ("election", "president", "congress", "trump")),
        ("company_financial", ("stock price", "earnings", "market cap", "ipo")),
        ("entertainment", ("movie", "album", "stream", "box office", "award")),
        ("transportation", ("flight", "airline", "airport", "train")),
        ("public_health", ("cases", "hospital", "disease", "flu", "covid")),
    )
    return next((name for name, words in themes if any(word in text for word in words)), market.domain)


def _telemetry_rows(markets: list) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for market in markets:
        coverage = classify_market_shape(market)
        if coverage.status in {"engine_available", "actionable", "wait"}:
            continue
        key = (market.venue, market.domain, coverage.family, _unsupported_theme(market))
        row = buckets.setdefault(key, {
            "venue": market.venue, "domain": market.domain, "family": coverage.family,
            "theme": key[-1], "count": 0, "total_volume": 0.0, "sample_questions": [],
            "missing_statuses": {},
        })
        row["count"] += 1
        raw_market = market.raw.get("market", {}) if isinstance(market.raw, dict) else {}
        raw_volume = (
            raw_market.get("volume_fp") or market.raw.get("volumeNum")
            if isinstance(market.raw, dict) else 0
        )
        try:
            row["total_volume"] += float(raw_volume or 0)
        except (TypeError, ValueError):
            pass
        if market.question and market.question not in row["sample_questions"] and len(row["sample_questions"]) < 3:
            row["sample_questions"].append(market.question)
        statuses = row["missing_statuses"]
        statuses[coverage.status] = statuses.get(coverage.status, 0) + 1
    return sorted(buckets.values(), key=lambda row: (row["count"], row["total_volume"]), reverse=True)


def _score_record(record: ScanRecord) -> tuple[int, float, float]:
    net = record.net_edge_points
    if net is None or math.isnan(net):
        net = -1.0
    confidence = record.confidence if record.confidence is not None else 0.0
    return (1 if record.actionable else 0, net, confidence)


def _dedupe_markets(markets: list) -> list:
    seen: set[tuple[str, str]] = set()
    out = []
    for market in markets:
        key = (market.venue, market.market_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(market)
    return out


def scan_opportunities(
    *,
    max_weather_markets_per_series: int = 20,
    max_economics_markets: int = 40,
    kalshi_active_limit: int = KALSHI_ACTIVE_DEFAULT_LIMIT,
    polymarket_limit: int = POLYMARKET_DEFAULT_LIMIT,
    limitless_limit: int = LIMITLESS_DEFAULT_LIMIT,
    include_limitless: bool = True,
) -> dict[str, Any]:
    with economic_sources.source_cache_scope():
        return _scan_opportunities_impl(
            max_weather_markets_per_series=max_weather_markets_per_series,
            max_economics_markets=max_economics_markets,
            kalshi_active_limit=kalshi_active_limit,
            polymarket_limit=polymarket_limit,
            limitless_limit=limitless_limit,
            include_limitless=include_limitless,
        )


def _scan_opportunities_impl(
    *,
    max_weather_markets_per_series: int = 20,
    max_economics_markets: int = 40,
    kalshi_active_limit: int = KALSHI_ACTIVE_DEFAULT_LIMIT,
    polymarket_limit: int = POLYMARKET_DEFAULT_LIMIT,
    limitless_limit: int = LIMITLESS_DEFAULT_LIMIT,
    include_limitless: bool = True,
) -> dict[str, Any]:
    # A scan is one coherent source snapshot. Reuse within it, but never carry
    # observations into the next scheduled run.
    _SCAN_SOURCE_CACHE.clear()
    started_at = datetime.now(timezone.utc).isoformat()
    markets = []

    markets.extend(kalshi.fetch_canonical_active_markets(max_markets=kalshi_active_limit))
    markets.extend(
        kalshi.fetch_canonical_markets_for_series_batch(WEATHER_SERIES, limit=max_weather_markets_per_series)
    )
    markets.extend(
        kalshi.fetch_canonical_markets_for_series_batch(ECONOMICS_SERIES, limit=max_economics_markets)
    )
    markets.extend(
        kalshi.fetch_canonical_markets_for_series_batch(SPORTS_SERIES, limit=max_economics_markets)
    )
    discovered_rows = kalshi.fetch_series("Commodities") + kalshi.fetch_series("Climate and Weather")
    expansion_series = _expansion_series(discovered_rows)
    markets.extend(kalshi.fetch_canonical_markets_for_series_batch(expansion_series, limit=max_economics_markets))
    markets.extend(polymarket.fetch_canonical_active_markets(max_markets=polymarket_limit))
    if include_limitless:
        markets.extend(limitless.fetch_canonical_markets(active_limit=limitless_limit))
    markets = _dedupe_markets(markets)
    unsupported_telemetry = _telemetry_rows(markets)
    cross_venue = find_cross_venue_edges(markets)

    evaluated_records = []
    included_unsupported = []
    skipped = 0
    skip_reasons: dict[str, int] = {}
    included_unsupported_reasons: dict[str, int] = {}
    venue_counts: dict[str, int] = {}
    domain_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    coverage_status_counts: dict[str, int] = {}
    limitless_group_children_seen = 0
    errors = []
    for market in markets:
        _bump_counter(venue_counts, market.venue)
        _bump_counter(domain_counts, market.domain)
        coverage = classify_market_shape(market)
        _bump_counter(family_counts, coverage.family)
        if market.venue == "limitless" and market.raw.get("parent"):
            limitless_group_children_seen += 1
        try:
            record = evaluate_market(market)
            if record is None:
                reason = skip_reason(market)
                if _should_include_unsupported(market):
                    included_unsupported.append(_unsupported_record(market, reason))
                    _bump_counter(included_unsupported_reasons, reason)
                else:
                    skipped += 1
                    _bump_counter(skip_reasons, reason)
            else:
                evaluated_records.append(record)
        except Exception as exc:  # noqa: BLE001
            errors.append(
                {
                    "venue": market.venue,
                    "market_id": market.market_id,
                    "question": market.question,
                    "error": str(exc),
                }
            )

    records = evaluated_records + included_unsupported
    ranked = sorted(records, key=_score_record, reverse=True)
    actionable = [record for record in ranked if record.actionable]
    for record in records:
        _bump_counter(coverage_status_counts, record.coverage_status)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started_at,
        "markets_seen": len(markets),
        "markets_evaluated": len(evaluated_records),
        "markets_included": len(records),
        "markets_included_unsupported": len(included_unsupported),
        "markets_skipped": skipped,
        "venue_counts": venue_counts,
        "domain_counts": domain_counts,
        "family_counts": family_counts,
        "expansion_family_counts": {
            family: family_counts.get(family, 0) for family in EXPANSION_FAMILIES
        },
        "coverage_status_counts": coverage_status_counts,
        "skip_reasons": skip_reasons,
        "included_unsupported_reasons": included_unsupported_reasons,
        "unsupported_market_telemetry": unsupported_telemetry,
        "dynamically_discovered_expansion_series": expansion_series,
        "limitless_group_children_seen": limitless_group_children_seen,
        "errors": errors,
        "actionable_count": len(actionable),
        "cross_venue": {
            "candidate_count": len(cross_venue),
            "actionable_count": sum(row["actionable"] for row in cross_venue),
            "opportunities": cross_venue,
            "rule": "only exact-equivalent contracts may produce a cross-venue edge",
        },
        "top": [asdict(record) for record in ranked],
        "included_unsupported": [asdict(record) for record in included_unsupported],
        "action_rule": "YES if price < prob_low - costs; NO if price > prob_high + costs; otherwise no trade",
        "ingestion_boundary": (
            "every Kalshi series with a wired engine family is swept completely (all weather "
            "stations, all wired economics series, World Cup stages); the broad Kalshi census batch "
            "is capped because the full open universe measured >600k markets on 2026-07-09, "
            "dominated by combinatorial sports multigame/parlay series with no engine"
        ),
    }


def render_markdown(scan: dict[str, Any], limit: int = 20) -> str:
    lines = [
        "# Opportunity Scan",
        "",
        f"- Created: {scan['created_at']}",
        f"- Markets seen: {scan['markets_seen']}",
        f"- Markets evaluated: {scan['markets_evaluated']}",
        f"- Markets included: {scan.get('markets_included', len(scan['top']))}",
        f"- Included unsupported: {scan.get('markets_included_unsupported', 0)}",
        f"- Markets skipped: {scan['markets_skipped']}",
        f"- Actionable: {scan['actionable_count']}",
        f"- Rule: {scan['action_rule']}",
        "",
        "| Rank | Status | Venue | Family | Market | Side | Oracle | Market | Net edge | Cost | Reason |",
        "| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for idx, record in enumerate(scan["top"][:limit], start=1):
        action = record.get("coverage_status") or ("actionable" if record["actionable"] else "wait")
        oracle = _fmt_prob(record["oracle_prob"])
        implied = _fmt_prob(record["implied_prob"])
        net = _fmt_prob(record["net_edge_points"])
        cost = _fmt_prob(record["total_friction"])
        question = record["question"].replace("|", " ")
        reason = record["reason"].replace("|", " ")
        lines.append(
            f"| {idx} | {action} | {record['venue']} | {record.get('family', '')} | {question} | {record['side'] or ''} | "
            f"{oracle} | {implied} | {net} | {cost} | {reason} |"
        )
    if scan.get("included_unsupported_reasons"):
        lines.extend(["", "## Included Unsupported", ""])
        for reason, count in sorted(
            scan["included_unsupported_reasons"].items(),
            key=lambda item: item[1],
            reverse=True,
        )[:12]:
            lines.append(f"- {reason}: {count}")
        lines.extend([
            "",
            "| Venue | Domain | Family | Shape | Market | Reason |",
            "| --- | --- | --- | --- | --- | --- |",
        ])
        for record in scan.get("included_unsupported", [])[:20]:
            question = record["question"].replace("|", " ")
            reason = record["reason"].replace("|", " ")
            lines.append(
                f"| {record['venue']} | {record['domain']} | {record.get('family', '')} | "
                f"{record.get('shape', '')} | {question} | {reason} |"
            )
    if scan.get("skip_reasons"):
        lines.extend(["", "## Skip Reasons", ""])
        for reason, count in sorted(scan["skip_reasons"].items(), key=lambda item: item[1], reverse=True)[:12]:
            lines.append(f"- {reason}: {count}")
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
    json_path: str | Path = DEFAULT_SCAN_JSON,
    md_path: str | Path = DEFAULT_SCAN_MD,
) -> None:
    json_path = Path(json_path)
    md_path = Path(md_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_tmp = json_path.with_suffix(json_path.suffix + ".tmp")
    md_tmp = md_path.with_suffix(md_path.suffix + ".tmp")
    json_tmp.write_text(json.dumps(scan, indent=2, sort_keys=True), encoding="utf-8")
    md_tmp.write_text(render_markdown(scan), encoding="utf-8")
    json_tmp.replace(json_path)
    md_tmp.replace(md_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan live markets for cost-adjusted deterministic edges")
    parser.add_argument("--weather-limit", type=int, default=20)
    parser.add_argument("--economics-limit", type=int, default=40)
    parser.add_argument("--kalshi-active-limit", type=int, default=KALSHI_ACTIVE_DEFAULT_LIMIT)
    parser.add_argument("--polymarket-limit", type=int, default=POLYMARKET_DEFAULT_LIMIT)
    parser.add_argument("--limitless-limit", type=int, default=LIMITLESS_DEFAULT_LIMIT)
    parser.add_argument("--no-limitless", action="store_true", help="skip Limitless read-only market scan")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--write", action="store_true", help="write JSON/Markdown artifacts under data/public")
    parser.add_argument("--json", action="store_true", help="print raw JSON instead of markdown")
    args = parser.parse_args(argv)

    scan = scan_opportunities(
        max_weather_markets_per_series=args.weather_limit,
        max_economics_markets=args.economics_limit,
        kalshi_active_limit=args.kalshi_active_limit,
        polymarket_limit=args.polymarket_limit,
        limitless_limit=args.limitless_limit,
        include_limitless=not args.no_limitless,
    )
    if args.write:
        write_scan_artifacts(scan)
        write_audit(audit_scan(scan))
    if args.json:
        print(json.dumps(scan, indent=2, sort_keys=True))
    else:
        print(render_markdown(scan, limit=args.top))
    return 0 if not scan["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
