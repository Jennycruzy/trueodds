"""Market coverage classification.

This module answers a different question from `domain.py`: not just "what
domain is this market in?", but "what exact family/shape is it, and do we have
an engine for that shape yet?"
"""
from __future__ import annotations

from dataclasses import dataclass

from rwoo.parsers import parse_commodity_market, parse_economics_market, parse_sports_market, parse_weather_market


@dataclass(frozen=True)
class MarketCoverage:
    family: str
    shape: str
    status: str
    reason: str


def classify_market_shape(market) -> MarketCoverage:
    text = f"{market.question} {market.resolution_rule}".lower()
    raw_market = market.raw.get("market", {}) if isinstance(market.raw, dict) else {}

    if market.domain == "other":
        return MarketCoverage(
            family="other",
            shape="unsupported_domain",
            status="unsupported_domain",
            reason="outside weather/economics/sports/commodities coverage",
        )

    if market.venue == "kalshi" and market.domain == "weather":
        parsed = parse_weather_market(market)
        return MarketCoverage(
            family=parsed.family,
            shape=parsed.shape,
            status=parsed.status,
            reason=parsed.reason,
        )

    if market.venue == "kalshi" and market.domain == "economics":
        event_ticker = raw_market.get("event_ticker", "")
        if event_ticker.startswith("KXCPICORE-") and raw_market.get("strike_type"):
            return MarketCoverage(
                family="economics.core_cpi",
                shape="monthly_threshold",
                status="engine_available",
                reason="supported Kalshi core-CPI market with structured strike fields",
            )
        parsed = parse_economics_market(market)
        if parsed is not None:
            return MarketCoverage(
                family=parsed.family,
                shape=parsed.shape,
                status=parsed.status,
                reason=parsed.reason,
            )
        return _economics_shape_from_text(text, venue=market.venue)

    if market.domain == "sports":
        if market.question.endswith("win the 2026 FIFA World Cup?"):
            return MarketCoverage(
                family="sports.world_cup",
                shape="national_team_winner",
                status="engine_available",
                reason="supported World Cup national-team outright shape",
            )
        parsed = parse_sports_market(market)
        if parsed is not None:
            return MarketCoverage(
                family=parsed.family,
                shape=parsed.shape,
                status=parsed.status,
                reason=parsed.reason,
            )
        return _sports_shape_from_text(text, venue=market.venue)

    if market.domain == "commodities":
        parsed = parse_commodity_market(market)
        if parsed is not None:
            return MarketCoverage(parsed.family, parsed.shape, parsed.status, parsed.reason)
        return MarketCoverage(
            family="commodities", shape="unknown_commodity", status="parse_missing",
            reason=f"{market.venue} commodity market included, but its underlying/source/strike shape is not bound",
        )

    if market.domain == "economics":
        parsed = parse_economics_market(market)
        if parsed is not None:
            return MarketCoverage(
                family=parsed.family,
                shape=parsed.shape,
                status=parsed.status,
                reason=parsed.reason,
            )
        return _economics_shape_from_text(text, venue=market.venue)

    if market.domain == "weather":
        parsed = parse_weather_market(market)
        return MarketCoverage(
            family=parsed.family,
            shape=parsed.shape,
            status=parsed.status,
            reason=parsed.reason,
        )

    return MarketCoverage(
        family=market.domain,
        shape="unknown",
        status="model_missing",
        reason="domain market is included, but no matching shape classifier exists yet",
    )


def _economics_shape_from_text(text: str, venue: str) -> MarketCoverage:
    if "producer price index" in text:
        return MarketCoverage(
            family="economics.ppi",
            shape="inflation_bin_or_threshold",
            status="model_missing",
            reason=f"{venue} PPI market included; PPI engine is not wired yet",
        )
    if "consumer price index for all urban consumers" in text or "headline cpi" in text or "inflation" in text:
        if "one-month percent change" in text or "monthly" in text:
            return MarketCoverage(
                family="economics.headline_cpi",
                shape="monthly_bin_or_threshold",
                status="model_missing",
                reason=f"{venue} headline-CPI monthly market included; headline-CPI engine is not wired yet",
            )
        return MarketCoverage(
            family="economics.headline_cpi",
            shape="annual_bin_or_threshold",
            status="model_missing",
            reason=f"{venue} headline-CPI annual market included; headline-CPI engine is not wired yet",
        )
    if "gdp" in text or "gross domestic product" in text:
        return MarketCoverage(
            family="economics.gdp",
            shape="quarterly_growth_bin_or_threshold",
            status="model_missing",
            reason=f"{venue} GDP market included; GDP engine is not wired yet",
        )
    if "fed" in text or "fomc" in text or "federal funds" in text or "rate cut" in text:
        return MarketCoverage(
            family="economics.fed_rates",
            shape="rate_decision_or_path",
            status="model_missing",
            reason=f"{venue} Fed-rate market included; Fed-rate engine is not wired yet",
        )
    if "recession" in text:
        # Recession-shaped markets are normally classified by
        # parse_economics_market (single-quarter GDP-decline -> SPF RECESS
        # engine; NBER/multi-quarter -> source_missing). This fallback only
        # fires if that parser returned None on recession text.
        return MarketCoverage(
            family="economics.recession",
            shape="definition_trigger",
            status="source_missing",
            reason=(
                f"{venue} recession market included; only a single-quarter real-GDP decline test "
                "is priced (SPF RECESS), and this rule was not parsed into that shape"
            ),
        )
    if "unemployment" in text or "jobs" in text or "payroll" in text:
        return MarketCoverage(
            family="economics.labor",
            shape="labor_market_threshold",
            status="model_missing",
            reason=f"{venue} labor-market market included; labor engine is not wired yet",
        )
    return MarketCoverage(
        family="economics",
        shape="unknown_economics",
        status="parse_missing",
        reason=f"{venue} economics market included, but its rule has not been parsed into a known family",
    )


def _sports_shape_from_text(text: str, venue: str) -> MarketCoverage:
    if "wimbledon" in text and " vs " in text:
        # Head-to-head tennis is parsed and priced upstream (parse_sports_market
        # -> UTS Elo engine); reaching here means the two players could not be
        # split out of the title, not that the engine is missing.
        return MarketCoverage(
            family="sports.tennis",
            shape="match_winner",
            status="parse_missing",
            reason=(
                f"{venue} tennis head-to-head recognized and the Ultimate Tennis Statistics Elo engine "
                "is wired, but the two players could not be parsed from this title"
            ),
        )
    if "wimbledon" in text and "winner" in text:
        return MarketCoverage(
            family="sports.tennis",
            shape="tournament_winner",
            status="model_missing",
            reason=(
                f"{venue} tennis outright market included; the Ultimate Tennis Statistics Elo source is "
                "reachable (verified 2026-07-10), but a tournament draw/bracket simulation is not wired yet"
            ),
        )
    if "nba" in text and ("champion" in text or "winner" in text):
        return MarketCoverage(
            family="sports.nba",
            shape="league_champion",
            status="model_missing",
            reason=(
                f"{venue} NBA champion market included; the ESPN standings source is reachable (verified "
                "2026-07-10) and a head-to-head point-differential engine exists, but a season/playoff "
                "champion simulation is not wired yet"
            ),
        )
    if "nhl" in text and ("champion" in text or "winner" in text):
        return MarketCoverage(
            family="sports.nhl",
            shape="league_champion",
            status="model_missing",
            reason=(
                f"{venue} NHL champion market included; the official NHL API is verified reachable "
                "(2026-07-09), but an offseason standings-only prior for next season's champion cannot "
                "honestly clear the restraint confidence floor, so the engine is deferred until the "
                "2026-27 season provides real results"
            ),
        )
    if "world cup" in text and "stage of elimination" in text:
        return MarketCoverage(
            family="sports.world_cup",
            shape="stage_of_elimination",
            status="parse_missing",
            reason=f"{venue} World Cup stage market recognized, but team/stage could not be parsed from its title",
        )
    if "world cup" in text and ("matchup" in text or "top goalscorer" in text or "goal" in text):
        return MarketCoverage(
            family="sports.world_cup",
            shape="prop_or_exact_outcome",
            status="model_missing",
            reason=f"{venue} World Cup prop/exact-outcome market included; prop engine is not wired yet",
        )
    if "esports" in text or "cs " in text or "counter-strike" in text or "league of legends" in text:
        return MarketCoverage(
            family="sports.esports",
            shape="match_or_tournament",
            status="source_missing",
            reason=f"{venue} esports market included; reliable source/model path has not been approved yet",
        )
    return MarketCoverage(
        family="sports",
        shape="unknown_sports",
        status="parse_missing",
        reason=f"{venue} sports market included, but its rule has not been parsed into a known family",
    )
