"""NOAA seasonal Atlantic storm-count probability engine."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from rwoo.readers import noaa_hurricane

_Z_85 = 1.0364333894937898  # standard-normal 85th percentile; central 70% interval


def _survival(cut: float, mean: float, sigma: float) -> float:
    return 0.5 * math.erfc((cut - mean) / (sigma * math.sqrt(2)))


def _conditional_greater(floor: float, observed: int, mean: float, sigma: float) -> float:
    if observed > floor:
        return 1.0
    denominator = _survival(observed - 0.5, mean, sigma)
    if denominator <= 1e-12:
        return 0.0
    return min(1.0, max(0.0, _survival(floor + 0.5, mean, sigma) / denominator))


def _greater_probability(floor: float, observed: int, mean: float, sigma: float,
                         *, outlook_includes_observed: bool) -> float:
    if observed > floor:
        return 1.0
    if outlook_includes_observed:
        return min(1.0, max(0.0, _survival(floor + 0.5, mean, sigma)))
    return _conditional_greater(floor, observed, mean, sigma)


def compute_atlantic_season_count_probability(
    count_type: str, strike_type: str, floor_strike: float | None,
    *, target_year: int | None = None, outlook: dict | None = None,
) -> dict:
    if count_type not in {"named_storms", "hurricanes", "major_hurricanes"}:
        return {"refused": True, "oracle_prob": None, "reason": "unsupported Atlantic storm count type"}
    if strike_type != "greater" or floor_strike is None:
        return {"refused": True, "oracle_prob": None, "reason": "only structured greater-than count contracts are supported"}
    outlook = outlook or noaa_hurricane.fetch_atlantic_outlook()
    if target_year is not None and int(outlook.get("year") or 0) != int(target_year):
        return {"refused": True, "oracle_prob": None, "reason": "NOAA outlook year does not match the contract year"}
    low, high = outlook["ranges"][count_type]
    range_probability = float(outlook.get("range_probability") or 0.70)
    if not 0.5 <= range_probability < 1 or low > high:
        return {"refused": True, "oracle_prob": None, "reason": "invalid NOAA outlook interval metadata"}

    # NOAA supplies a central coverage interval rather than a full density.
    # The least-committal smooth conversion is a normal distribution centered
    # on the range midpoint whose stated interval has the same central mass.
    mean = (low + high) / 2
    half_width = (high - low + 1) / 2
    sigma = max(0.5, half_width / _Z_85)
    observed_meta = outlook.get("observed") or {}
    observed = int(observed_meta.get(count_type) or 0)
    includes_observed = bool(outlook.get("includes_season_to_date"))

    midpoint = _greater_probability(float(floor_strike), observed, mean, sigma,
                                    outlook_includes_observed=includes_observed)
    endpoint_low = _greater_probability(float(floor_strike), observed, float(low), sigma,
                                        outlook_includes_observed=includes_observed)
    endpoint_high = _greater_probability(float(floor_strike), observed, float(high), sigma,
                                         outlook_includes_observed=includes_observed)
    prob_low, prob_high = min(endpoint_low, midpoint, endpoint_high), max(endpoint_low, midpoint, endpoint_high)
    confidence = min(0.68, max(0.55, range_probability - 0.02 * (high - low)))
    return {
        "oracle_prob": midpoint, "confidence": confidence,
        "prob_low": prob_low, "prob_high": prob_high,
        "per_model_prob": {
            "noaa_range_low_center": endpoint_low,
            "noaa_range_midpoint_center": midpoint,
            "noaa_range_high_center": endpoint_high,
        },
        "per_source_values": {
            "source": "NOAA CPC Atlantic Hurricane Season Outlook",
            "source_url": outlook.get("source_url"), "outlook_year": outlook.get("year"),
            "issued": outlook.get("issued"), "stated_range": [low, high],
            "stated_range_probability": range_probability,
            "observed_count": observed, "observed_count_parsed": bool(observed_meta.get("parsed")),
            "outlook_includes_season_to_date": includes_observed,
            "observed_count_conditioning": "already incorporated by NOAA update" if includes_observed else "conditioned after preseason outlook",
        },
        "method": (
            "NOAA central seasonal count range -> continuity-corrected normal density with matching "
            "central coverage; conditioned on the NHC observed count when parseable; endpoint-centered "
            "views form the disclosed uncertainty interval"
        ),
        "data_freshness": outlook.get("fetched_at") or datetime.now(timezone.utc).isoformat(),
        "base_rate": midpoint, "refused": False,
    }
