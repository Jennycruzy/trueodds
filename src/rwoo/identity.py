"""Stable event identities and explicit deterministic model versions."""
from __future__ import annotations

from rwoo.parsers import parse_market
from rwoo.receipts import hash_hex
from rwoo.weather_stations import metric_for_series, station_for_series


MODEL_VERSIONS = {
    "weather.temperature": "weather-ensemble-v3-power-calibrated",
    "weather.precipitation": "weather-hurdle-v2",
    "economics.core_cpi": "core-cpi-official-ensemble-v2",
    "economics.headline_cpi": "headline-cpi-official-ensemble-v2",
    "economics.gdp": "gdp-official-ensemble-v2",
    "economics.labor": "labor-official-history-v1",
    "economics.fed_rates": "fed-hold-only-v1",
    "economics.recession": "spf-recession-v1",
    "sports.world_cup": "world-cup-live-bracket-elo-v2",
    "sports.tennis": "tennis-uts-elo-v1",
    "sports.nba": "nba-point-differential-v1",
    "sports.mlb": "mlb-season-elo-v1",
    "sports.club_soccer": "clubelo-match-v1",
}


def model_version(family: str) -> str:
    return MODEL_VERSIONS.get(family, f"{family}-unversioned")


def event_identity(market, family: str, shape: str) -> dict:
    parsed = parse_market(market)
    semantic = {
        "domain": market.domain,
        "family": family,
        "shape": shape,
        "target_date": getattr(parsed, "target_date", None),
        "target_month": getattr(parsed, "target_month", None),
        "target_year": getattr(parsed, "target_year", None),
        "location": getattr(parsed, "location", None),
        "country": getattr(parsed, "country", None),
        "metric": getattr(parsed, "metric", None),
        "source_series": getattr(parsed, "source_series", None),
        "strike_type": getattr(parsed, "strike_type", None),
        "floor_strike": getattr(parsed, "floor_strike", None),
        "cap_strike": getattr(parsed, "cap_strike", None),
        "resolution_time": market.resolution_time,
    }
    if market.domain == "weather":
        raw_market = market.raw.get("market", {}) if isinstance(market.raw, dict) else {}
        event_ticker = raw_market.get("event_ticker") or ""
        series = raw_market.get("series_ticker") or event_ticker.split("-", 1)[0]
        if series:
            try:
                station = station_for_series(series)
                semantic.update({"series": series, "station_ghcnd_id": station.ghcnd_id,
                                 "station_name": station.name, "metric": metric_for_series(series)})
            except KeyError:
                pass
    # Some venue parsers cannot expose a richer identity. In that case the
    # normalized question keeps unrelated events from being grouped together.
    if not any(semantic[key] for key in ("target_date", "target_month", "location", "source_series")):
        semantic["question"] = " ".join((market.question or "").lower().split())
    grouping_identity = dict(semantic)
    for key in ("strike_type", "floor_strike", "cap_strike"):
        grouping_identity.pop(key, None)
    if shape == "stage_of_elimination":
        grouping_identity.pop("source_series", None)
    digest = hash_hex(grouping_identity)[:20]
    return {"event_group_id": f"{family}:{digest}", "event_identity": semantic}
