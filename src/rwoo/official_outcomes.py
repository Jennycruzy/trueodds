"""Direct official-source outcome checks, beginning with NOAA daily summaries."""
from __future__ import annotations

from typing import Any
import httpx

NOAA_DAILY_SUMMARIES = "https://www.ncei.noaa.gov/access/services/data/v1"


def event_happened(value: float, strike_type: str, floor: float | None, cap: float | None) -> bool:
    if strike_type in {"greater", "greater_than", "above"}:
        return value > float(floor)
    if strike_type in {"less", "less_than", "below"}:
        return value < float(cap if cap is not None else floor)
    if strike_type in {"between", "range"}:
        return float(floor) <= value <= float(cap)
    raise ValueError(f"unsupported strike type {strike_type!r}")


def resolve_weather_from_noaa(identity: dict[str, Any], client: httpx.Client) -> dict[str, Any]:
    station = str(identity.get("station_ghcnd_id") or "").replace("GHCND:", "")
    target_date, metric = identity.get("target_date"), identity.get("metric")
    datatype = {"temperature_2m_max": "TMAX", "temperature_2m_min": "TMIN"}.get(metric)
    if not station or not target_date or datatype is None:
        return {"status": "unsupported", "reason": "NOAA check supports registered high/low stations"}
    response = client.get(NOAA_DAILY_SUMMARIES, params={
        "dataset": "daily-summaries", "stations": station, "startDate": target_date,
        "endDate": target_date, "format": "json", "units": "standard", "includeAttributes": "false",
    }, headers={"User-Agent": "rwoo-evidence/1.0"})
    response.raise_for_status()
    rows = response.json()
    if not rows or rows[0].get(datatype) in (None, ""):
        return {"status": "pending", "reason": f"NOAA has not published {datatype} for {target_date}"}
    observed = float(rows[0][datatype])
    outcome = event_happened(observed, identity.get("strike_type"),
                             identity.get("floor_strike"), identity.get("cap_strike"))
    return {"status": "resolved", "outcome": int(outcome), "observed_value": observed,
            "datatype": datatype, "station": station, "target_date": target_date,
            "source": "NOAA NCEI Daily Summaries", "source_url": str(response.url)}
