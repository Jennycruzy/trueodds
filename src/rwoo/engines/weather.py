"""Stage 2 — the weather engine (flagship domain).

Every number here is arithmetic over real API data. No LLM is called
anywhere in this module. The consensus probability comes from treating the
independent models' forecasts as an ensemble: their mean is the point
estimate, their spread (standard deviation) is the uncertainty, and a normal
CDF converts "how far the threshold is from the ensemble mean, in ensemble
standard deviations" into a probability. Confidence is a direct, documented
function of that same spread — tight agreement -> high confidence, wide
disagreement -> low confidence. This is a real, standard ensemble-forecast
technique (ensemble mean/spread as a probabilistic forecast), not a
dressed-up guess; its one built-in judgment call (the MIN_STD floor, below)
is stated plainly rather than hidden.

Field shapes verified live, see docs/VERIFICATION_LEDGER.md §1 (Open-Meteo)
and §12 (NASA POWER, added this phase).
"""
import math
import statistics
import time
from datetime import datetime, timezone

import httpx

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
_FORECAST_CACHE: dict[tuple[float, float, str, str], dict[str, float]] = {}
_HISTORICAL_CACHE: dict[tuple[float, float, int, int, int], dict[int, float]] = {}


def _get_with_retry(url: str, params: dict, timeout: float = 20, attempts: int = 3) -> httpx.Response:
    """Real network calls occasionally hit a transient connect/TLS timeout
    unrelated to the API itself. Retry a couple of times before surfacing an
    honest failure — this does not mask a genuinely unreachable API."""
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            resp = httpx.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts:
                time.sleep(1.5 * attempt)
    raise last_exc

# Verified live 2026-07-08: these three model identifiers are accepted by
# Open-Meteo's `models=` parameter and return independent forecast series.
MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless"]

# A 3-5 member ensemble can agree exactly (std=0) by chance even though real
# forecast uncertainty is never zero. This floor is a deliberate, documented
# choice — not a hidden fudge — so the engine never claims impossible 100%
# certainty off a handful of models. Chosen as roughly the typical
# instrument/model rounding granularity for a 1-day-out max-temp forecast.
MIN_STD_F = 1.5

# Supported Open-Meteo daily metrics. Each entry documents the unit the
# engine works in, the matching NASA POWER parameter for the climatological
# base rate (None = POWER has no equivalent daily series), the ensemble-std
# floor in that unit, and a confidence cap. Temperatures keep no extra cap
# (the band already carries the uncertainty). Precipitation/snowfall are
# zero-bounded and heavily skewed, so a normal CDF over a 3-model ensemble is
# a weaker assumption there — the cap keeps that stated instead of implicit.
METRICS: dict[str, dict] = {
    "temperature_2m_max": {
        "openmeteo_units": {"temperature_unit": "fahrenheit"},
        "nasa_power_param": "T2M_MAX",
        "min_std": MIN_STD_F,
        "confidence_cap": 1.0,
        "unit": "F",
    },
    "temperature_2m_min": {
        "openmeteo_units": {"temperature_unit": "fahrenheit"},
        "nasa_power_param": "T2M_MIN",
        "min_std": MIN_STD_F,
        "confidence_cap": 1.0,
        "unit": "F",
    },
    "precipitation_sum": {
        "openmeteo_units": {"precipitation_unit": "inch"},
        "nasa_power_param": "PRECTOTCORR",  # mm/day; converted to inches below
        "min_std": 0.05,
        "confidence_cap": 0.65,
        "unit": "in",
    },
    "snowfall_sum": {
        "openmeteo_units": {"precipitation_unit": "inch"},
        "nasa_power_param": None,  # NASA POWER has no daily snowfall series
        "min_std": 0.5,
        "confidence_cap": 0.65,
        "unit": "in",
    },
    "wind_speed_10m_max": {
        "openmeteo_units": {"wind_speed_unit": "mph"},
        "nasa_power_param": "WS10M_MAX",
        "min_std": 2.0,
        "confidence_cap": 0.60,
        "unit": "mph",
    },
    "wind_gusts_10m_max": {
        "openmeteo_units": {"wind_speed_unit": "mph"},
        "nasa_power_param": None,
        "min_std": 3.0,
        "confidence_cap": 0.55,
        "unit": "mph",
    },
}


def _normal_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def fetch_model_forecasts(
    lat: float,
    lon: float,
    target_date: str,
    timezone_name: str,
    metric: str = "temperature_2m_max",
) -> dict[str, float]:
    """target_date: 'YYYY-MM-DD'. Returns {model_name: forecast value} in the
    metric's documented unit (°F for temperatures, inches for precip/snow)."""
    if metric not in METRICS:
        raise ValueError(f"Unsupported weather metric: {metric!r}")
    cache_key = (round(lat, 4), round(lon, 4), target_date, timezone_name, metric)
    if cache_key in _FORECAST_CACHE:
        return dict(_FORECAST_CACHE[cache_key])
    resp = _get_with_retry(
        OPEN_METEO_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": metric,
            **METRICS[metric]["openmeteo_units"],
            "timezone": timezone_name,
            "models": ",".join(MODELS),
            "start_date": target_date,
            "end_date": target_date,
        },
    )
    data = resp.json()
    daily = data["daily"]
    out = {}
    for model in MODELS:
        key = f"{metric}_{model}"
        values = daily.get(key)
        if values and values[0] is not None:
            out[model] = values[0]
    _FORECAST_CACHE[cache_key] = dict(out)
    return out


def fetch_historical_daily(
    lat: float,
    lon: float,
    month: int,
    day: int,
    years_back: int = 20,
    metric: str = "temperature_2m_max",
) -> dict[int, float]:
    """Real historical daily values for the same calendar day across
    `years_back` years, from NASA POWER, in the metric's engine unit. Used
    only for the climatological base rate — never for the forecast
    probability itself. Metrics without a POWER equivalent return {}."""
    power_param = METRICS[metric]["nasa_power_param"]
    if power_param is None:
        return {}
    cache_key = (round(lat, 4), round(lon, 4), month, day, years_back, power_param)
    if cache_key in _HISTORICAL_CACHE:
        return dict(_HISTORICAL_CACHE[cache_key])
    end_year = datetime.now(timezone.utc).year - 1  # last fully-observed year
    start_year = end_year - years_back + 1
    resp = _get_with_retry(
        NASA_POWER_URL,
        params={
            "parameters": power_param,
            "community": "RE",
            "longitude": lon,
            "latitude": lat,
            "start": f"{start_year}0101",
            "end": f"{end_year}1231",
            "format": "JSON",
        },
        timeout=30,
    )
    data = resp.json()
    series = data["properties"]["parameter"][power_param]
    target_suffix = f"{month:02d}{day:02d}"
    out = {}
    for date_str, value in series.items():
        if date_str[4:8] == target_suffix and value is not None and value > -900:  # NASA POWER fill value is -999
            year = int(date_str[:4])
            if power_param.startswith("T2M"):
                out[year] = value * 9 / 5 + 32  # POWER temperatures are °C
            elif power_param == "PRECTOTCORR":
                out[year] = value / 25.4  # POWER precipitation is mm/day
            else:
                out[year] = value
    _HISTORICAL_CACHE[cache_key] = dict(out)
    return out


def fetch_historical_daily_max(lat: float, lon: float, month: int, day: int, years_back: int = 20) -> dict[int, float]:
    return fetch_historical_daily(lat, lon, month, day, years_back, metric="temperature_2m_max")


def check_resolution(value: float, strike_type: str, floor_strike, cap_strike) -> bool:
    """Deterministic yes/no check against Kalshi's own structured strike
    fields — not a regex over the English rule text."""
    if strike_type == "greater":
        return value > floor_strike
    if strike_type == "less":
        return value < cap_strike
    if strike_type == "between":
        return floor_strike <= value <= cap_strike
    raise ValueError(f"Unknown strike_type: {strike_type!r}")


def _probability_from_ensemble(
    mean: float, std: float, strike_type: str, floor_strike, cap_strike, min_std: float = MIN_STD_F
) -> float:
    std = max(std, min_std)
    if strike_type == "greater":
        return 1 - _normal_cdf((floor_strike - mean) / std)
    if strike_type == "less":
        return _normal_cdf((cap_strike - mean) / std)
    if strike_type == "between":
        return _normal_cdf((cap_strike - mean) / std) - _normal_cdf((floor_strike - mean) / std)
    raise ValueError(f"Unknown strike_type: {strike_type!r}")


def event_probability(metric: str, values: list[float], strike_type: str, floor_strike, cap_strike) -> float:
    """Metric-aware event probability; precipitation uses an atom at zero."""
    spec = METRICS[metric]
    if metric not in {"precipitation_sum", "snowfall_sum"}:
        return _probability_from_ensemble(statistics.fmean(values), statistics.pstdev(values), strike_type,
                                          floor_strike, cap_strike, min_std=spec["min_std"])
    positives = [value for value in values if value > 0]
    occurrence = (len(positives) + 0.05) / (len(values) + 1.0)  # weak dry prior; never absolute 0/1
    mean = statistics.fmean(positives) if positives else 0.0
    std = statistics.pstdev(positives) if len(positives) > 1 else spec["min_std"]
    std = max(std, spec["min_std"])
    cdf_zero = _normal_cdf((0 - mean) / std)
    positive_mass = max(1e-12, 1 - cdf_zero)

    def positive_interval(low: float, high: float | None) -> float:
        low = max(0.0, low)
        cdf_low = _normal_cdf((low - mean) / std)
        cdf_high = 1.0 if high is None else _normal_cdf((max(0.0, high) - mean) / std)
        return max(0.0, min(1.0, (cdf_high - cdf_low) / positive_mass))

    if strike_type == "greater":
        return occurrence if float(floor_strike) <= 0 else occurrence * positive_interval(float(floor_strike), None)
    if strike_type == "less":
        if float(cap_strike) <= 0:
            return 0.0
        return (1 - occurrence) + occurrence * positive_interval(0.0, float(cap_strike))
    if strike_type == "between":
        dry = 1 - occurrence if float(floor_strike) <= 0 <= float(cap_strike) else 0.0
        return dry + occurrence * positive_interval(float(floor_strike), float(cap_strike))
    raise ValueError(f"Unknown strike_type: {strike_type!r}")


def compute_weather_probability(
    lat: float,
    lon: float,
    target_date: str,
    timezone_name: str,
    strike_type: str,
    floor_strike,
    cap_strike,
    include_base_rate: bool = True,
    metric: str = "temperature_2m_max",
) -> dict:
    if metric not in METRICS:
        raise ValueError(f"Unsupported weather metric: {metric!r}")
    metric_spec = METRICS[metric]
    min_std = metric_spec["min_std"]
    forecasts = fetch_model_forecasts(lat, lon, target_date, timezone_name, metric=metric)
    if len(forecasts) < 2:
        return {
            "oracle_prob": None,
            "confidence": 0.0,
            "prob_low": None,
            "prob_high": None,
            "per_source_values": forecasts,
            "method": "insufficient_models",
            "data_freshness": datetime.now(timezone.utc).isoformat(),
            "base_rate": None,
            "refused": True,
            "reason": f"only {len(forecasts)} of {len(MODELS)} models returned a forecast",
        }

    values = list(forecasts.values())
    mean = statistics.fmean(values)
    std = statistics.pstdev(values)  # population stdev — these are all the models we asked for, not a sample
    raw_prob = event_probability(metric, values, strike_type, floor_strike, cap_strike)
    oracle_prob = min(1.0, max(0.0, raw_prob))

    per_model_vote = {
        model: check_resolution(v, strike_type, floor_strike, cap_strike) for model, v in forecasts.items()
    }
    frac_models_yes = sum(per_model_vote.values()) / len(per_model_vote)
    # Unanimity is direction-agnostic: 3 models unanimously voting "no" is
    # 100% agreement, not 0% — frac_models_yes alone reads backwards for that
    # case, so report both.
    model_unanimity = max(frac_models_yes, 1 - frac_models_yes)

    # Uncertainty band: what would the probability be if each individual
    # model, on its own, were the whole truth (with only the same MIN_STD_F
    # precision floor already defined above — no new constant introduced)?
    # The spread between the most bullish and least bullish of those
    # per-model probabilities *is* the ensemble's honest disagreement, in the
    # same units as oracle_prob itself — so Stage 3 can compare an implied
    # probability against this band directly, and confidence falls out of it
    # for free instead of needing a separately invented decay formula.
    per_model_prob = {
        model: min(
            1.0,
            max(0.0, event_probability(metric, [v], strike_type, floor_strike, cap_strike)),
        )
        for model, v in forecasts.items()
    }
    prob_low = min(oracle_prob, *per_model_prob.values())
    prob_high = max(oracle_prob, *per_model_prob.values())
    confidence = min(metric_spec["confidence_cap"], 1.0 - (prob_high - prob_low))

    historical = {}
    if include_base_rate:
        month, day = int(target_date[5:7]), int(target_date[8:10])
        historical = fetch_historical_daily(lat, lon, month, day, metric=metric)
    if not historical:
        base_rate = None
    else:
        hits = sum(1 for v in historical.values() if check_resolution(v, strike_type, floor_strike, cap_strike))
        base_rate = hits / len(historical)

    return {
        "oracle_prob": oracle_prob,
        "confidence": confidence,
        "prob_low": prob_low,
        "prob_high": prob_high,
        "per_model_prob": per_model_prob,
        "per_source_values": forecasts,
        "per_model_vote": per_model_vote,
        "frac_models_voting_yes": frac_models_yes,
        "model_unanimity": model_unanimity,
        "metric": metric,
        "metric_unit": metric_spec["unit"],
        "ensemble_mean_f": mean,
        "ensemble_std_f": std,
        "std_floored": std < min_std,
        "method": (
            f"ensemble mean/std of {metric} over {len(forecasts)} independent models -> normal CDF "
            f"P(resolves yes) vs. strike_type={strike_type}"
            f"{'' if metric_spec['confidence_cap'] >= 1.0 else '; confidence capped because a normal fit is a weak assumption for zero-bounded ' + metric}"
            f"{'' if include_base_rate else '; historical base-rate fetch intentionally skipped for this restraint-only check'}"
        ),
        "data_freshness": datetime.now(timezone.utc).isoformat(),
        "base_rate": base_rate,
        "base_rate_years": sorted(historical.keys()) if historical else [],
        "refused": False,
    }
