"""Structured market parsers.

The scanner should see every market, but engines need typed inputs. This
module is the boundary between venue text/metadata and model inputs: it parses
only facts the venue exposes clearly, and returns explicit missing reasons for
everything else.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from rwoo.engines.weather import METRICS as WEATHER_ENGINE_METRICS
from rwoo.readers import kalshi
from rwoo.weather_stations import STATIONS, WEATHER_TIMEZONES, metric_for_series, station_for_series


@dataclass(frozen=True)
class ParsedMarket:
    domain: str
    family: str
    shape: str
    status: str
    reason: str
    metric: str | None = None
    location: str | None = None
    country: str | None = None
    target_date: str | None = None
    target_month: int | None = None
    target_year: int | None = None
    timezone_name: str | None = None
    strike_type: str | None = None
    floor_strike: float | None = None
    cap_strike: float | None = None
    settlement_source: str | None = None
    source_series: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def parse_market(market) -> ParsedMarket | None:
    if market.domain == "weather":
        return parse_weather_market(market)
    if market.domain == "economics":
        return parse_economics_market(market)
    if market.domain == "sports":
        return parse_sports_market(market)
    if market.domain == "commodities":
        return parse_commodity_market(market)
    return None


_WC_ELIM_RE = re.compile(
    r"^Will (.+?) get eliminated in the (.+?) of the 2026 (?:Men's )?FIFA World Cup", re.IGNORECASE
)
_WC_WIN_FINAL_RE = re.compile(
    r"^Will (.+?) win the Final of the 2026 (?:Men's )?FIFA World Cup", re.IGNORECASE
)
_WC_LIMITLESS_STAGE_RE = re.compile(
    r"^World Cup:\s*(.+?)\s+Stage of Elimination\s*-\s*(.+)$", re.IGNORECASE
)


def parse_sports_market(market) -> ParsedMarket | None:
    """World Cup stage-of-elimination markets (Kalshi KXWCSTAGEOFELIM titles
    and Limitless 'World Cup: <team> Stage of Elimination - <stage>' groups,
    both verified live 2026-07-09)."""
    from rwoo.engines.sports import stage_key_from_text  # local import to avoid a cycle at module load

    question = market.question or ""
    team = stage_text = None
    match = _WC_ELIM_RE.match(question)
    if match:
        team, stage_text = match.group(1), match.group(2)
    else:
        match = _WC_WIN_FINAL_RE.match(question)
        if match:
            team, stage_text = match.group(1), "champion"
        else:
            match = _WC_LIMITLESS_STAGE_RE.match(question)
            if match:
                team, stage_text = match.group(1), match.group(2)
    if team is None:
        return _parse_team_match_market(market) or _parse_tennis_match_market(market)
    stage_key = stage_key_from_text(stage_text)
    if stage_key is None:
        return ParsedMarket(
            domain="sports",
            family="sports.world_cup",
            shape="stage_of_elimination",
            status="parse_missing",
            reason=f"World Cup stage market recognized, but stage text {stage_text!r} is not mapped",
            location=team,
            settlement_source=market.resolution_source,
            raw={"question": question},
        )
    return ParsedMarket(
        domain="sports",
        family="sports.world_cup",
        shape="stage_of_elimination",
        status="engine_available",
        reason="supported World Cup stage-of-elimination market with parsed team and stage",
        location=team,
        source_series=stage_key,
        settlement_source=market.resolution_source,
        raw={"question": question},
    )


_TENNIS_KEYWORDS = (
    "wimbledon", "roland garros", "us open", "australian open", "atp", "wta", "tennis",
)
_VERSUS_SPLIT_RE = re.compile(r"\s+vs?\.?\s+", re.IGNORECASE)
_TEAM_SPLIT_RE = re.compile(r"\s+(?:vs?\.?|at)\s+", re.IGNORECASE)
# One-sided titles name the YES player directly and need no external label.
_WILL_BEAT_RE = re.compile(
    r"^Will (.+?) (?:beat|defeat|win against|get past|knock out|advance past) (.+?)\??$",
    re.IGNORECASE,
)
_RULE_YES_SUBJECT_RE = re.compile(
    r"resolves?\s+yes\s+if\s+(.+?)\s+(?:wins|beats|defeats|advances|is the winner)",
    re.IGNORECASE,
)


def _split_versus(question: str) -> tuple[str, str] | None:
    """Extract the two competitors from a '<A> vs <B>' title, tolerating a
    leading '<Tournament>:' prefix and a trailing ' - <question>' clause."""
    core = question.split(":", 1)[1] if ":" in question else question
    core = re.split(r"\s[-–—?]\s|\?", core, maxsplit=1)[0]
    parts = _VERSUS_SPLIT_RE.split(core.strip())
    if len(parts) != 2:
        return None
    a, b = parts[0].strip(" -"), parts[1].strip(" -")
    if not a or not b:
        return None
    return a, b


def _bind_yes_player(subject: str | None, player_a: str, player_b: str) -> str | None:
    """Bind the venue's YES-outcome label to exactly one of the two players.

    Returns the original player string that YES resolves to, or None when the
    subject is empty, names neither, or is decidable for both (e.g. a raw
    'A vs B' label). Binding is by shared normalized token so 'Carlos Alcaraz'
    still binds to a title that only said 'Alcaraz'; ambiguity fails closed."""
    from rwoo.engines.sports import _normal_name  # single normalization authority

    subj = _normal_name(subject or "")
    if not subj:
        return None
    subj_tokens = set(subj.split())
    hits = [
        original
        for original in (player_a, player_b)
        if _normal_name(original) == subj or (subj_tokens & set(_normal_name(original).split()))
    ]
    return hits[0] if len(hits) == 1 else None


def _tennis_parsed(market, yes_player: str, other_player: str, why: str) -> ParsedMarket:
    return ParsedMarket(
        domain="sports",
        family="sports.tennis",
        shape="match_winner",
        status="engine_available",
        reason=f"tennis head-to-head; {why}, so the engine prices P(YES player wins)",
        location=yes_player,        # engine computes P(location wins) == P(YES wins)
        source_series=other_player,
        settlement_source=market.resolution_source,
        raw={"question": market.question},
    )


def _parse_tennis_match_market(market) -> ParsedMarket | None:
    """Head-to-head tennis markets, priced by the UTS Elo engine.

    The YES side is never assumed from title word order. A one-sided
    'Will A beat B?' title names YES directly; a symmetric 'A vs B' title binds
    YES to a player via the venue's `yes_subtitle` (or the resolution rule).
    If YES cannot be bound to exactly one of the two players, the market is
    returned as parse_missing (non-actionable) rather than risk an inverted
    edge."""
    question = market.question or ""
    lowered = question.lower()
    if not any(keyword in lowered for keyword in _TENNIS_KEYWORDS):
        return None

    core = question.split(":", 1)[1].strip() if ":" in question else question.strip()
    one_sided = _WILL_BEAT_RE.match(core)
    if one_sided:
        return _tennis_parsed(
            market, one_sided.group(1).strip(), one_sided.group(2).strip(),
            "one-sided title names the YES player",
        )

    players = _split_versus(question)
    if players is None:
        return None  # a tennis market, but not a parseable head-to-head (e.g. a tournament winner)
    player_a, player_b = players

    subject = getattr(market, "yes_subtitle", None)
    if not subject:
        rule_match = _RULE_YES_SUBJECT_RE.search(market.resolution_rule or "")
        subject = rule_match.group(1) if rule_match else None

    yes_player = _bind_yes_player(subject, player_a, player_b)
    if yes_player is None:
        return ParsedMarket(
            domain="sports",
            family="sports.tennis",
            shape="match_winner",
            status="parse_missing",
            reason=(
                "tennis head-to-head recognized and the UTS Elo engine is wired, but the YES "
                "outcome could not be bound to one of the two players (no usable yes_subtitle or "
                "resolution-rule subject) — refusing rather than guessing which side YES is"
            ),
            location=player_a,
            source_series=player_b,
            settlement_source=market.resolution_source,
            raw={"question": question, "yes_subtitle": subject},
        )
    other_player = player_b if yes_player == player_a else player_a
    return _tennis_parsed(
        market, yes_player, other_player,
        "YES side bound to a specific player from venue metadata",
    )


def _parse_team_match_market(market) -> ParsedMarket | None:
    text = f"{market.question} {market.resolution_rule}".lower()
    if any(x in text for x in ("nba", "basketball")):
        family, label = "sports.nba", "NBA"
    elif any(x in text for x in ("mlb", "baseball", "world series")):
        family, label = "sports.mlb", "MLB"
    elif any(x in text for x in ("premier league", "champions league", "la liga", "serie a", "bundesliga", "club soccer")):
        family, label = "sports.club_soccer", "club soccer"
    else:
        return None
    core = market.question.split(":", 1)[-1]
    core = re.split(r"\s[-–—?]\s|\?", core, maxsplit=1)[0]
    parts = _TEAM_SPLIT_RE.split(core.strip())
    if len(parts) != 2:
        return None
    a, b = (p.strip(" -") for p in parts)
    yes = _bind_yes_player(getattr(market, "yes_subtitle", None), a, b)
    if yes is None:
        return ParsedMarket(domain="sports", family=family, shape="match_winner", status="parse_missing",
                            reason=f"{label} match recognized but YES could not be bound to one team",
                            location=a, source_series=b)
    return ParsedMarket(domain="sports", family=family, shape="match_winner", status="engine_available",
                        reason=f"{label} head-to-head with fail-closed YES binding",
                        location=yes, source_series=b if yes == a else a,
                        settlement_source=market.resolution_source)


def _kalshi_series(market) -> str:
    raw = market.raw if isinstance(market.raw, dict) else {}
    row = raw.get("market", {}) if isinstance(raw.get("market", {}), dict) else {}
    return str(row.get("series_ticker") or raw.get("series_ticker") or row.get("event_ticker", "").split("-", 1)[0])


def parse_commodity_market(market) -> ParsedMarket | None:
    """Bind only verified commodity shapes; everything else remains visible.

    Series metadata and structured strikes are authoritative. Text is used to
    identify the commodity only after the venue has routed the market into the
    commodities domain.
    """
    raw = market.raw if isinstance(market.raw, dict) else {}
    row = raw.get("market", {}) if isinstance(raw.get("market", {}), dict) else {}
    series = _kalshi_series(market).upper()
    text = f"{market.question} {market.resolution_rule}".lower()
    strike_type = row.get("strike_type")
    floor = row.get("floor_strike")
    cap = row.get("cap_strike")

    if series == "KXNGASMAX" and "energy information administration" in text:
        event_ticker = str(row.get("event_ticker") or "")
        year_match = re.search(r"-(\d{2})(?:[A-Z]{3}\d{2})?(?:$|-)", event_ticker)
        target_year = 2000 + int(year_match.group(1)) if year_match else None
        return ParsedMarket(
            domain="commodities", family="energy.henry_hub_spot", shape="annual_high",
            status="engine_available" if strike_type == "greater" and floor is not None else "parse_missing",
            reason="EIA-resolved Henry Hub annual-high contract with structured threshold",
            target_date=market.trading_close_time or market.resolution_time,
            target_year=target_year,
            metric="usd_per_mmbtu", strike_type=strike_type,
            floor_strike=float(floor) if floor is not None else None,
            cap_strike=float(cap) if cap is not None else None,
            settlement_source=market.resolution_source, source_series="DHHNGSP",
            raw={"series_ticker": series},
        )

    agriculture = any(word in text for word in ("corn", "wheat", "soybean", "cattle", "coffee", "cocoa", "sugar"))
    if agriculture:
        return ParsedMarket(
            domain="commodities", family="agriculture.commodity_price", shape="price_threshold_or_range",
            status="source_missing",
            reason="agricultural price contract recognized; approved live/history price feed is not configured",
            target_date=market.trading_close_time or market.resolution_time,
            strike_type=strike_type, floor_strike=float(floor) if floor is not None else None,
            cap_strike=float(cap) if cap is not None else None, settlement_source=market.resolution_source,
            source_series=series or None,
        )

    if any(word in text for word in ("wti", "brent", "crude oil", "natural gas", "gasoline", "heating oil")):
        return ParsedMarket(
            domain="commodities", family="energy.commodity_price", shape="price_threshold_or_range",
            status="source_missing",
            reason="energy price contract recognized; its exact ICE/Pyth/AAA source adapter is not configured",
            target_date=market.trading_close_time or market.resolution_time,
            strike_type=strike_type, floor_strike=float(floor) if floor is not None else None,
            cap_strike=float(cap) if cap is not None else None, settlement_source=market.resolution_source,
            source_series=series or None,
        )
    return None


def parse_weather_market(market) -> ParsedMarket:
    raw_market = market.raw.get("market", {}) if isinstance(market.raw, dict) else {}
    if market.venue == "kalshi":
        parsed = _parse_kalshi_weather_market(market, raw_market)
        if parsed is not None:
            return parsed

    structured = market.raw.get("weather") if isinstance(market.raw, dict) else None
    if isinstance(structured, dict):
        def field(*names):
            return next((structured[name] for name in names if structured.get(name) not in (None, "")), None)
        metric = field("metric", "weatherMetric", "variable")
        latitude, longitude = field("latitude", "lat"), field("longitude", "lon", "lng")
        timezone_name, target_date = field("timezone", "timezoneName"), field("target_date", "targetDate", "date")
        strike_type = field("strike_type", "strikeType")
        location = field("location", "station", "stationName")
        source = str(field("settlement_source", "settlementSource") or market.resolution_source or "")
        source_verified = bool(re.search(r"\b(NOAA|NWS|National Weather Service|Open-Meteo)\b", source, re.I))
        required = (metric, latitude, longitude, timezone_name, target_date, strike_type, location, source_verified)
        if metric in WEATHER_ENGINE_METRICS and all(value not in (None, "", False) for value in required):
            return ParsedMarket(
                domain="weather", family=_family_for_weather_metric(metric), shape=_shape_for_weather_metric(metric),
                status="engine_available", reason="venue supplied complete normalized weather metadata",
                metric=metric, location=location, target_date=target_date,
                timezone_name=timezone_name, strike_type=strike_type,
                floor_strike=_float_or_none(field("floor_strike", "floorStrike", "threshold")),
                cap_strike=_float_or_none(field("cap_strike", "capStrike")), settlement_source=source,
                raw={"lat": float(latitude), "lon": float(longitude),
                     "venue_weather": structured},
            )

    text = " ".join(part for part in (market.question, market.resolution_rule) if part)
    metric = _weather_metric_from_text(text)
    if metric is not None:
        engine_exists = metric in WEATHER_ENGINE_METRICS
        return ParsedMarket(
            domain="weather",
            family=_family_for_weather_metric(metric),
            shape=_shape_for_weather_metric(metric),
            status="parse_missing" if engine_exists else "model_missing",
            reason=(
                f"{metric} weather market is recognized and the {metric} engine exists, but this venue's "
                "market does not expose structured station/date/strike fields to feed it"
                if engine_exists
                else f"{metric} weather market is recognized, but that weather metric engine is not wired yet"
            ),
            metric=metric,
            settlement_source=market.resolution_source,
            raw={"question": market.question, "resolution_rule": market.resolution_rule},
        )
    return ParsedMarket(
        domain="weather",
        family="weather",
        shape="unparsed_weather",
        status="parse_missing",
        reason="weather market is included, but location/date/metric/strike parsing is not complete",
        settlement_source=market.resolution_source,
        raw={"question": market.question, "resolution_rule": market.resolution_rule},
    )


def parse_economics_market(market) -> ParsedMarket | None:
    if market.venue == "kalshi":
        parsed = _parse_kalshi_economics_market(market)
        if parsed is not None:
            return parsed

    text = " ".join(part for part in (market.question, market.resolution_rule) if part)
    parsed = _parse_headline_inflation_bins(text)
    if parsed is not None:
        country, month, cadence, strike_type, floor_strike, cap_strike = parsed
        status = "engine_available" if country == "US" else "source_missing"
        reason = (
            f"supported US headline-CPI {cadence} inflation market parsed into month/country/rounded bin"
            if status == "engine_available"
            else f"{country} headline-CPI market is parsed, but that country's official CPI source is not wired yet"
        )
        return ParsedMarket(
            domain="economics",
            family="economics.headline_cpi",
            shape="annual_yoy_bin_or_threshold" if cadence == "annual" else "monthly_bin_or_threshold",
            status=status,
            reason=reason,
            country=country,
            target_month=month,
            strike_type=strike_type,
            floor_strike=floor_strike,
            cap_strike=cap_strike,
            settlement_source=market.resolution_source,
            raw={"question": market.question, "resolution_rule": market.resolution_rule},
        )
    parsed = _parse_gdp_quarterly(text)
    if parsed is not None:
        quarter_label, strike_type, floor_strike, cap_strike = parsed
        return ParsedMarket(
            domain="economics",
            family="economics.gdp",
            shape="quarterly_growth_bin_or_threshold",
            status="engine_available",
            reason="supported US quarterly real-GDP market parsed into quarter and growth bin",
            country="US",
            target_year=int(quarter_label[:4]),
            strike_type=strike_type,
            floor_strike=floor_strike,
            cap_strike=cap_strike,
            settlement_source=market.resolution_source,
            source_series=quarter_label,
            raw={"question": market.question, "resolution_rule": market.resolution_rule},
        )
    if _is_fed_path_market(text):
        return ParsedMarket(
            domain="economics",
            family="economics.fed_rates",
            shape="rate_decision_or_path",
            status="source_missing",
            reason=(
                "Fed rate-path market is parsed, but pricing decisions at scheduled FOMC meetings "
                "needs a verified forward-looking rate-path distribution source (e.g. fed funds "
                "futures), which is not wired"
            ),
            settlement_source=market.resolution_source,
            raw={"question": market.question, "resolution_rule": market.resolution_rule},
        )
    recession = _parse_recession(text)
    if recession is not None:
        shape, quarter_label = recession
        if shape == "quarterly_decline" and quarter_label is not None:
            return ParsedMarket(
                domain="economics",
                family="economics.recession",
                shape=shape,
                status="engine_available",
                reason=(
                    "single-quarter real-GDP decline market parsed into a target quarter; "
                    "priced from the official Philadelphia Fed SPF RECESS anxious index"
                ),
                country="US",
                target_year=int(quarter_label[:4]),
                settlement_source=market.resolution_source,
                source_series=quarter_label,
                raw={"question": market.question, "resolution_rule": market.resolution_rule},
            )
        return ParsedMarket(
            domain="economics",
            family="economics.recession",
            shape=shape,
            status="source_missing",
            reason=(
                "recession market is parsed, but an NBER-style declaration (or a multi-quarter / "
                "year-level rule) has no verified probability source in this build; only a "
                "single-quarter real-GDP decline test can be priced from SPF RECESS"
            ),
            settlement_source=market.resolution_source,
            raw={"question": market.question, "resolution_rule": market.resolution_rule},
        )
    return None


_KALSHI_ECON_SERIES = {
    "KXCPIYOY": ("economics.headline_cpi", "annual_yoy_bin_or_threshold"),
    "KXECONSTATCPI": ("economics.headline_cpi", "monthly_bin_or_threshold"),
    "KXGDP": ("economics.gdp", "quarterly_growth_bin_or_threshold"),
    "KXU3": ("economics.labor", "unemployment_rate_threshold"),
    "KXPAYROLLS": ("economics.labor", "payrolls_change_threshold"),
    "KXFED": ("economics.fed_rates", "target_range_after_meeting"),
}


def _parse_kalshi_economics_market(market) -> ParsedMarket | None:
    """Kalshi economics series with structured strike fields. Shapes verified
    live 2026-07-09 against open markets in each series."""
    raw_market = market.raw.get("market", {}) if isinstance(market.raw, dict) else {}
    event_ticker = raw_market.get("event_ticker") or ""
    series_ticker = raw_market.get("series_ticker") or event_ticker.split("-", 1)[0]
    if series_ticker not in _KALSHI_ECON_SERIES:
        return None
    family, shape = _KALSHI_ECON_SERIES[series_ticker]

    month, year = _kalshi_event_month_year(event_ticker)
    strike_type = raw_market.get("strike_type")
    floor_strike = _float_or_none(raw_market.get("floor_strike"))
    cap_strike = _float_or_none(raw_market.get("cap_strike"))

    if series_ticker == "KXECONSTATCPI":
        # strike_type is 'custom': the rule is 'CPI month-over-month is
        # exactly X%' with X encoded in the ticker suffix (e.g. T-0.3).
        exact = _exact_value_from_ticker(raw_market.get("ticker") or "")
        if exact is None:
            return _econ_parse_missing(market, family, shape, "could not parse the exact MoM value from the ticker")
        strike_type, floor_strike, cap_strike = "between", exact - 0.05, exact + 0.05
    elif series_ticker == "KXGDP":
        quarter_label = _quarter_from_text(market.question) or _quarter_from_text(market.resolution_rule or "")
        if quarter_label is None or not strike_type:
            return _econ_parse_missing(market, family, shape, "could not parse the target quarter or strike fields")
        return ParsedMarket(
            domain="economics",
            family=family,
            shape=shape,
            status="engine_available",
            reason="supported Kalshi quarterly real-GDP market with structured strike fields",
            country="US",
            target_year=int(quarter_label[:4]),
            strike_type=str(strike_type),
            floor_strike=floor_strike,
            cap_strike=cap_strike,
            settlement_source=market.resolution_source,
            source_series=quarter_label,
            raw={"market": raw_market},
        )
    elif series_ticker == "KXFED":
        # Event ticker suffix names the meeting month, e.g. KXFED-27APR.
        if month is None or year is None or not strike_type:
            return _econ_parse_missing(market, family, shape, "could not parse the meeting month or strike fields")
        meeting_anchor = f"{year:04d}-{month:02d}-28"  # end-of-meeting-month anchor; engine uses the calendar
        return ParsedMarket(
            domain="economics",
            family=family,
            shape=shape,
            status="engine_available",
            reason=(
                "Kalshi fed-funds target market parsed; the engine prices it only when no scheduled "
                "FOMC meeting remains before the target and refuses otherwise"
            ),
            country="US",
            target_month=month,
            target_year=year,
            target_date=meeting_anchor,
            strike_type=str(strike_type),
            floor_strike=floor_strike,
            cap_strike=cap_strike,
            settlement_source=market.resolution_source,
            raw={"market": raw_market},
        )
    if not strike_type or month is None:
        return _econ_parse_missing(market, family, shape, "missing structured strike fields or target month")

    return ParsedMarket(
        domain="economics",
        family=family,
        shape=shape,
        status="engine_available",
        reason=f"supported Kalshi {family} market with structured strike fields",
        country="US",
        target_month=month,
        target_year=year,
        strike_type=str(strike_type),
        floor_strike=floor_strike,
        cap_strike=cap_strike,
        settlement_source=market.resolution_source,
        source_series=series_ticker,
        raw={"market": raw_market},
    )


def _econ_parse_missing(market, family: str, shape: str, why: str) -> ParsedMarket:
    return ParsedMarket(
        domain="economics",
        family=family,
        shape=shape,
        status="parse_missing",
        reason=f"Kalshi economics market recognized, but {why}",
        settlement_source=market.resolution_source,
        raw={"question": market.question},
    )


_MONTH_ABBRS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def _kalshi_event_month_year(event_ticker: str) -> tuple[int | None, int | None]:
    suffix = event_ticker.rsplit("-", 1)[-1]
    match = re.match(r"^(\d{2})([A-Z]{3})", suffix)
    if not match:
        return None, None
    year_2, month_abbr = match.groups()
    month = _MONTH_ABBRS.get(month_abbr)
    return month, (2000 + int(year_2)) if month else None


def _exact_value_from_ticker(ticker: str) -> float | None:
    match = re.search(r"-T(-?\d+(?:\.\d+)?)$", ticker)
    return float(match.group(1)) if match else None


def _quarter_from_text(text: str) -> str | None:
    match = re.search(r"\bQ([1-4])\s+(\d{4})\b", text)
    if match:
        return f"{match.group(2)}Q{match.group(1)}"
    match = re.search(r"\b(\d{4})\s*Q([1-4])\b", text)
    if match:
        return f"{match.group(1)}Q{match.group(2)}"
    return None


def _parse_gdp_quarterly(text: str) -> tuple[str, str, float | None, float | None] | None:
    """Limitless-style 'US GDP growth in Q2 2026? - >=3.5%' / '3.0-3.5%'."""
    if not re.search(r"\bGDP growth\b", text, flags=re.IGNORECASE):
        return None
    quarter_label = _quarter_from_text(text)
    if quarter_label is None:
        return None
    bin_match = re.search(r"-\s*([^-].*?%)\s*$", text)
    if not bin_match:
        return None
    strike = _parse_percent_range(bin_match.group(1))
    if strike is None:
        return None
    return (quarter_label, *strike)


def _parse_percent_range(value: str) -> tuple[str, float | None, float | None] | None:
    normalized = (
        value.strip()
        .replace("≤", "<=")
        .replace("≥", ">=")
        .replace("–", "-")
        .replace("—", "-")
        .replace("%", "")
    )
    range_match = re.match(r"^([-+]?\d+(?:\.\d+)?)\s*-\s*([-+]?\d+(?:\.\d+)?)$", normalized)
    if range_match:
        return "between", float(range_match.group(1)), float(range_match.group(2))
    lower_match = re.match(r"^(?:<=|<)\s*([-+]?\d+(?:\.\d+)?)$", normalized)
    if lower_match:
        return "less", None, float(lower_match.group(1))
    upper_match = re.match(r"^(?:>=|>)\s*([-+]?\d+(?:\.\d+)?)$", normalized)
    if upper_match:
        return "greater", float(upper_match.group(1)), None
    return None


def _is_fed_path_market(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(r"\bfed (?:rate )?(?:cut|hike|decision)\b", lowered)
        or re.search(r"\bfomc\b", lowered)
        or re.search(r"\brate cuts? happen\b", lowered)
    )


_GDP_DECLINE_RE = re.compile(
    r"\b(?:real\s+)?gdp\b[^.?!]*\b(?:decline|declines|fall|falls|contract|contracts|shrink|shrinks|negative)\b"
    r"|\b(?:decline|declines|fall|falls|contract|contracts|shrink|shrinks|negative)\b[^.?!]*\b(?:real\s+)?gdp\b",
    re.IGNORECASE,
)
_TWO_QUARTER_RE = re.compile(
    r"\b(?:two|2)\s+(?:consecutive|straight|successive)\s+quarters?\b", re.IGNORECASE
)


def _parse_recession(text: str) -> tuple[str, str | None] | None:
    """Classify a recession-shaped economics market.

    Returns ``(shape, quarter_label)`` or ``None`` when the text is not
    recession-shaped. The only routable shape is ``"quarterly_decline"``: a
    single-quarter real-GDP decline test with an explicit quarter, which the
    official SPF RECESS anxious index prices directly. Everything else
    (NBER-style declaration, multi-quarter or year-level rules) is
    ``"nber_declaration"`` — recognized but with no verified probability source,
    so it must stay non-actionable.
    """
    lowered = text.lower()
    is_gdp_decline = bool(_GDP_DECLINE_RE.search(text))
    if "recession" not in lowered and not is_gdp_decline:
        return None
    quarter_label = _quarter_from_text(text)
    single_quarter_decline = (
        is_gdp_decline
        and quarter_label is not None
        and "nber" not in lowered
        and not _TWO_QUARTER_RE.search(text)
    )
    if single_quarter_decline:
        return ("quarterly_decline", quarter_label)
    return ("nber_declaration", None)


def _parse_kalshi_weather_market(market, raw_market: dict[str, Any]) -> ParsedMarket | None:
    event_ticker = raw_market.get("event_ticker") or ""
    series_ticker = raw_market.get("series_ticker") or event_ticker.split("-", 1)[0]
    if not series_ticker:
        return None

    hurricane_counts = {
        "KXTROPSTORM": "named_storms",
        "KXHURCTOT": "hurricanes",
        "KXHURCTOTMAJ": "major_hurricanes",
    }
    if series_ticker in hurricane_counts:
        strike_type = raw_market.get("strike_type")
        floor = _float_or_none(raw_market.get("floor_strike"))
        ready = strike_type == "greater" and floor is not None
        _month, target_year = _kalshi_event_month_year(event_ticker)
        if target_year is None:
            timestamp = market.trading_close_time or market.resolution_time or ""
            year_match = re.match(r"^(20\d{2})", timestamp)
            target_year = int(year_match.group(1)) if year_match else None
        return ParsedMarket(
            domain="weather", family="weather.hurricane_season", shape="atlantic_season_count",
            status="engine_available" if ready else "parse_missing",
            reason="NOAA-resolved Atlantic seasonal count contract with structured threshold",
            metric=hurricane_counts[series_ticker], target_year=target_year,
            target_date=market.trading_close_time or market.resolution_time,
            strike_type=strike_type, floor_strike=floor,
            settlement_source=market.resolution_source, source_series=series_ticker,
            raw={"market": raw_market},
        )

    metric = _kalshi_weather_metric(series_ticker)
    if metric is None:
        return ParsedMarket(
            domain="weather",
            family="weather",
            shape="unknown_weather_series",
            status="parse_missing",
            reason=f"Kalshi weather series {series_ticker!r} is not mapped to a verified weather metric",
            source_series=series_ticker,
            settlement_source=market.resolution_source,
            raw={"market": raw_market},
        )

    if series_ticker not in STATIONS:
        return ParsedMarket(
            domain="weather",
            family=_family_for_weather_metric(metric),
            shape=_shape_for_weather_metric(metric),
            status="source_missing",
            reason=f"Kalshi weather series {series_ticker!r} has no verified station coordinates",
            metric=metric,
            source_series=series_ticker,
            settlement_source=market.resolution_source,
            raw={"market": raw_market},
        )
    if not event_ticker:
        return ParsedMarket(
            domain="weather",
            family=_family_for_weather_metric(metric),
            shape=_shape_for_weather_metric(metric),
            status="parse_missing",
            reason="Kalshi weather market is missing event_ticker, so target date cannot be parsed",
            metric=metric,
            source_series=series_ticker,
            settlement_source=market.resolution_source,
            raw={"market": raw_market},
        )

    strike_type = raw_market.get("strike_type")
    if not strike_type:
        return ParsedMarket(
            domain="weather",
            family=_family_for_weather_metric(metric),
            shape=_shape_for_weather_metric(metric),
            status="parse_missing",
            reason="Kalshi weather market is missing structured strike_type",
            metric=metric,
            source_series=series_ticker,
            settlement_source=market.resolution_source,
            raw={"market": raw_market},
        )

    station = station_for_series(series_ticker)
    status = "engine_available" if metric in WEATHER_ENGINE_METRICS else "model_missing"
    reason = (
        f"supported {metric} market with verified station/date/strike fields"
        if status == "engine_available"
        else f"{metric} weather market is parsed, but that weather metric engine is not wired yet"
    )
    return ParsedMarket(
        domain="weather",
        family=_family_for_weather_metric(metric),
        shape=_shape_for_weather_metric(metric),
        status=status,
        reason=reason,
        metric=metric,
        location=station.name,
        target_date=kalshi.parse_event_date(event_ticker),
        timezone_name=WEATHER_TIMEZONES.get(series_ticker, "UTC"),
        strike_type=str(strike_type),
        floor_strike=_float_or_none(raw_market.get("floor_strike")),
        cap_strike=_float_or_none(raw_market.get("cap_strike")),
        settlement_source=market.resolution_source,
        source_series=series_ticker,
        raw={
            "market": raw_market,
            "lat": station.lat,
            "lon": station.lon,
            "ghcnd_id": station.ghcnd_id,
        },
    )


def _kalshi_weather_metric(series_ticker: str) -> str | None:
    """Metric for a Kalshi weather series. The verified station registry is
    the source of truth; the prefix fallback only *recognizes* temperature
    series that are not registered yet (they then surface as source_missing
    because no verified station exists, rather than disappearing)."""
    registered = metric_for_series(series_ticker)
    if registered is not None:
        return registered
    if series_ticker.startswith("KXHIGH"):
        return "temperature_2m_max"
    if series_ticker.startswith("KXLOW"):
        return "temperature_2m_min"
    return None


def _family_for_weather_metric(metric: str) -> str:
    if metric.startswith("temperature"):
        return "weather.temperature"
    if metric in ("precipitation_sum", "snowfall_sum"):
        return "weather.precipitation"
    if metric.startswith("wind_"):
        return "weather.wind"
    return "weather"


def _weather_metric_from_text(text: str) -> str | None:
    lowered = text.lower()
    if re.search(r"\b(high temp|high temperature|daily high|max(?:imum)? temperature)\b", lowered):
        return "temperature_2m_max"
    if re.search(r"\b(low temp|low temperature|daily low|min(?:imum)? temperature)\b", lowered):
        return "temperature_2m_min"
    if re.search(r"\b(rainfall|rain|precipitation)\b", lowered):
        return "precipitation_sum"
    if re.search(r"\b(snowfall|snow)\b", lowered):
        return "snowfall_sum"
    if re.search(r"\b(wind gust|wind gusts|maximum gust)\b", lowered):
        return "wind_gusts_10m_max"
    if re.search(r"\b(wind speed|maximum wind|sustained wind)\b", lowered):
        return "wind_speed_10m_max"
    if re.search(r"\b(hurricane|storm)\b", lowered):
        return "wind_or_storm"
    return None


def _shape_for_weather_metric(metric: str) -> str:
    if metric == "temperature_2m_max":
        return "daily_high_threshold"
    if metric == "temperature_2m_min":
        return "daily_low_threshold"
    if metric == "precipitation_sum":
        return "daily_rain_threshold"
    if metric == "snowfall_sum":
        return "daily_snow_threshold"
    if metric in {"wind_speed_10m_max", "wind_gusts_10m_max"}:
        return "daily_wind_threshold"
    if metric == "wind_or_storm":
        return "wind_or_storm_threshold"
    return "unknown_weather_metric"


def _float_or_none(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _parse_headline_inflation_bins(
    text: str,
) -> tuple[str, int, str, str, float | None, float | None] | None:
    """Limitless-style '<Month> Inflation <Country> - <Annual|Monthly> - <bin>'."""
    match = re.search(
        r"\b("
        + "|".join(_MONTHS)
        + r")\s+inflation\s+([A-Za-z .]+?)\s*-\s*(annual|monthly)\s*-\s*(.+?)(?:\s|$)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    month_name, country_text, cadence, bin_text = match.groups()
    country = _normal_country(country_text)
    if not country:
        return None
    strike = _parse_rounded_percent_bin(bin_text)
    if strike is None:
        return None
    strike_type, floor_strike, cap_strike = strike
    return country, _MONTHS[month_name.lower()], cadence.lower(), strike_type, floor_strike, cap_strike


def _normal_country(value: str) -> str | None:
    cleaned = re.sub(r"[^A-Za-z]+", " ", value).strip().lower()
    aliases = {
        "us": "US",
        "u s": "US",
        "usa": "US",
        "united states": "US",
        "china": "China",
        "korea": "Korea",
        "south korea": "Korea",
    }
    return aliases.get(cleaned)


def _parse_rounded_percent_bin(value: str) -> tuple[str, float | None, float | None] | None:
    normalized = (
        value.strip()
        .replace("\u2264", "<=")
        .replace("\u2265", ">=")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("%", "")
    )
    range_match = re.match(r"^([-+]?\d+(?:\.\d+)?)\s*-\s*([-+]?\d+(?:\.\d+)?)$", normalized)
    if range_match:
        low, high = (float(range_match.group(1)), float(range_match.group(2)))
        return "between", low - 0.05, high + 0.05
    lower_match = re.match(r"^(?:<=|<)\s*([-+]?\d+(?:\.\d+)?)$", normalized)
    if lower_match:
        return "less", None, float(lower_match.group(1)) + 0.05
    upper_match = re.match(r"^(?:>=|>)\s*([-+]?\d+(?:\.\d+)?)$", normalized)
    if upper_match:
        return "greater", float(upper_match.group(1)) - 0.05, None
    plus_match = re.match(r"^([-+]?\d+(?:\.\d+)?)\s*\+$", normalized)
    if plus_match:
        return "greater", float(plus_match.group(1)) - 0.05, None
    exact_match = re.match(r"^([-+]?\d+(?:\.\d+)?)$", normalized)
    if exact_match:
        center = float(exact_match.group(1))
        return "between", center - 0.05, center + 0.05
    return None
