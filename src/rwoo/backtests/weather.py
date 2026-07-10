"""Weather calibration backtest with no-lookahead proof.

Inputs are real finalized Kalshi weather markets and archived Open-Meteo
Single Runs forecasts. The decision timestamp is each market's `open_time`.
The forecast run is the previous day's 06:00 UTC model cycle; Open-Meteo's
docs state global model outputs are typically available 4-6 hours after
initialisation, so this code records `run + 6h` and requires it to be before
the market open. If that proof fails, the record is refused.
"""
from __future__ import annotations

import hashlib
import json
import os
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Any

import httpx

from rwoo.calibration import CalibrationRecord, probability_bucket
from rwoo.engines.weather import METRICS, event_probability
from rwoo.readers import kalshi
from rwoo.weather_stations import metric_for_series, station_for_series

SINGLE_RUNS_URL = "https://single-runs-api.open-meteo.com/v1/forecast"
HISTORICAL_URL = "https://archive-api.open-meteo.com/v1/archive"
ARCHIVED_MODELS = ["ecmwf_ifs025", "gfs_global", "icon_global"]
_SINGLE_RUN_CACHE: dict[tuple[float, float, str, str, str], dict[str, float]] = {}
_DEFAULT_CACHE_DIR = Path(".cache/rwoo/open_meteo_single_runs")
ProgressCallback = Callable[[dict[str, Any]], None]


def _get_with_retry(url: str, params: dict, timeout: float = 45, attempts: int = 3) -> httpx.Response:
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


def _cache_path(cache_key: tuple, cache_dir: str | Path | None = None) -> Path:
    base = Path(cache_dir or os.environ.get("RWOO_OPEN_METEO_CACHE_DIR") or _DEFAULT_CACHE_DIR)
    key_json = json.dumps(cache_key, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(key_json.encode("utf-8")).hexdigest()
    return base / f"{digest}.json"


def _load_cached_single_run(cache_key: tuple[float, float, str, str], cache_dir: str | Path | None = None) -> dict | None:
    path = _cache_path(cache_key, cache_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _store_cached_single_run(
    cache_key: tuple,
    params: dict,
    raw_response: dict,
    parsed_daily_max: dict[str, float],
    cache_dir: str | Path | None = None,
) -> None:
    path = _cache_path(cache_key, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "source_url": SINGLE_RUNS_URL,
                "params": params,
                "raw_response": raw_response,
                "parsed_daily_values": parsed_daily_max,
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _target_date_from_event(event_ticker: str) -> str:
    return kalshi.parse_event_date(event_ticker)


def _previous_day_06z(target_date: str) -> str:
    target = datetime.fromisoformat(target_date).replace(tzinfo=timezone.utc)
    run = target - timedelta(days=1)
    return run.replace(hour=6, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")


def _run_available_at(run: str) -> str:
    run_dt = datetime.fromisoformat(run).replace(tzinfo=timezone.utc)
    return (run_dt + timedelta(hours=6)).isoformat()


def fetch_finalized_weather_markets(series_ticker: str = "KXHIGHNY", page_size: int = 200) -> list[dict]:
    """Paginates through ALL settled markets for a series — not one page.
    There is no artificial cap here; the real ceiling is whatever Kalshi
    actually has, discovered by following `cursor` until it's exhausted."""
    all_markets: list[dict] = []
    cursor = None
    while True:
        params = {"series_ticker": series_ticker, "status": "settled", "limit": page_size}
        if cursor:
            params["cursor"] = cursor
        resp = _get_with_retry(f"{kalshi.BASE_URL}/markets", params=params)
        data = resp.json()
        page = data.get("markets", [])
        all_markets.extend(page)
        cursor = data.get("cursor")
        if not cursor or not page:
            break
    return [m for m in all_markets if m.get("status") == "finalized" and m.get("result") in {"yes", "no"}]


def fetch_single_run_all_models(
    lat: float,
    lon: float,
    target_date: str,
    run: str,
    timezone_name: str = "America/New_York",
    metric: str = "temperature_2m_max",
    cache_dir: str | Path | None = None,
) -> dict[str, float]:
    """One HTTP call for all archived models at once (Single Runs supports
    comma-separated `models=`, confirmed live) instead of one call per model
    — this is what makes pulling hundreds of real records practical."""
    cache_key = (round(lat, 4), round(lon, 4), target_date, run, metric)
    if cache_key in _SINGLE_RUN_CACHE:
        return dict(_SINGLE_RUN_CACHE[cache_key])
    cached = _load_cached_single_run(cache_key, cache_dir)
    if cached and isinstance(cached.get("parsed_daily_values"), dict):
        parsed = {k: float(v) for k, v in cached["parsed_daily_values"].items()}
        _SINGLE_RUN_CACHE[cache_key] = dict(parsed)
        return parsed
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": {
            "temperature_2m_max": "temperature_2m", "temperature_2m_min": "temperature_2m",
            "precipitation_sum": "precipitation", "snowfall_sum": "snowfall",
            "wind_speed_10m_max": "wind_speed_10m", "wind_gusts_10m_max": "wind_gusts_10m",
        }[metric],
        **METRICS[metric]["openmeteo_units"],
        "timezone": timezone_name,
        "models": ",".join(ARCHIVED_MODELS),
        "run": run,
        "forecast_days": 4,
    }
    resp = _get_with_retry(
        SINGLE_RUNS_URL,
        params=params,
        timeout=25,
        attempts=2,
    )
    data = resp.json()
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    out: dict[str, float] = {}
    for model in ARCHIVED_MODELS:
        variable = params["hourly"]
        model_values = hourly.get(f"{variable}_{model}")
        if not model_values:
            continue
        values = [v for ts, v in zip(times, model_values) if ts.startswith(target_date) and v is not None]
        if values:
            out[model] = sum(values) if metric in {"precipitation_sum", "snowfall_sum"} else (
                min(values) if metric == "temperature_2m_min" else max(values)
            )
    _SINGLE_RUN_CACHE[cache_key] = dict(out)
    _store_cached_single_run(cache_key, params, data, out, cache_dir)
    return out


def compute_archived_probability(market: dict, series_ticker: str = "KXHIGHNY") -> dict:
    target_date = _target_date_from_event(market["event_ticker"])
    run = _previous_day_06z(target_date)
    available_at = _run_available_at(run)
    decision_timestamp = market["open_time"]
    if _parse_dt(available_at) > _parse_dt(decision_timestamp):
        return {
            "refused": True,
            "reason": f"forecast run availability {available_at} is after market open {decision_timestamp}",
        }

    station = station_for_series(series_ticker)
    metric = metric_for_series(series_ticker) or "temperature_2m_max"
    forecasts = fetch_single_run_all_models(station.lat, station.lon, target_date, run, metric=metric)
    if len(forecasts) < 2:
        return {
            "refused": True,
            "reason": f"only {len(forecasts)} archived model forecasts returned",
            "per_source_values": forecasts,
        }

    values = list(forecasts.values())
    mean = statistics.fmean(values)
    std = statistics.pstdev(values)
    prob = min(
        1.0,
        max(
            0.0,
            event_probability(metric, values, market["strike_type"],
                              market.get("floor_strike"), market.get("cap_strike")),
        ),
    )
    per_model_prob = {
        model: min(
            1.0,
            max(
                0.0,
                event_probability(metric, [value], market["strike_type"],
                                  market.get("floor_strike"), market.get("cap_strike")),
            ),
        )
        for model, value in forecasts.items()
    }
    return {
        "refused": False,
        "oracle_prob": prob,
        "prob_low": min(per_model_prob.values()),
        "prob_high": max(per_model_prob.values()),
        "per_model_prob": per_model_prob,
        "per_source_values": forecasts,
        "ensemble_mean_f": mean,
        "ensemble_std_f": std,
        "source_run": run,
        "source_available_at": available_at,
        "decision_timestamp": decision_timestamp,
        "target_date": target_date,
        "method": "Open-Meteo Single Runs previous-day 06Z archived ensemble -> same Stage-2 normal-CDF transform",
    }


def build_weather_backtest_for_series(
    series_ticker: str,
    stop_after_successful: int | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[list[CalibrationRecord], list[dict]]:
    """No sample-size cap by default: every real finalized market for this
    series is attempted. Records are only excluded by genuine constraints —
    the no-lookahead check, or the archived-forecast source simply not
    covering that date (Open-Meteo's Single Runs archive has a real, finite
    rolling window; verified live rather than assumed, see
    docs/VERIFICATION_LEDGER.md) — never by an arbitrary count.

    `stop_after_successful` is NOT a data-scarcity cap — it exists only so a
    caller that just needs to demonstrate the mechanism (e.g. Phase 6's
    receipt demo) doesn't have to wait for hundreds of real records it
    doesn't need. The real calibration backtest (Phase 5) never sets it."""
    records: list[CalibrationRecord] = []
    raw_rows = []
    markets = fetch_finalized_weather_markets(series_ticker=series_ticker)
    if progress:
        progress({"event": "series_markets_loaded", "series": series_ticker, "market_count": len(markets)})
    for attempted, market in enumerate(markets, start=1):
        if stop_after_successful is not None and len(records) >= stop_after_successful:
            break
        try:
            result = compute_archived_probability(market, series_ticker=series_ticker)
        except Exception as exc:  # noqa: BLE001 — one flaky call must not abort a multi-hundred-record run
            result = {"refused": True, "reason": f"network/parse error for this market: {exc}"}
        raw_rows.append({"market": market, "engine_result": result})
        if result.get("refused"):
            if progress and (attempted == 1 or attempted % 25 == 0):
                progress(
                    {
                        "event": "series_progress",
                        "series": series_ticker,
                        "attempted": attempted,
                        "records": len(records),
                        "refused": len(raw_rows) - len(records),
                    }
                )
            continue
        outcome = 1 if market["result"] == "yes" else 0
        record = CalibrationRecord(
            domain="weather",
            venue="kalshi",
            market_id=market["ticker"],
            question=market["title"],
            decision_timestamp=result["decision_timestamp"],
            resolution_timestamp=market.get("settlement_ts") or market.get("expiration_time"),
            oracle_prob=result["oracle_prob"],
            outcome=outcome,
            bucket=probability_bucket(result["oracle_prob"]),
            source_run=result["source_run"],
            source_available_at=result["source_available_at"],
            target_date=result["target_date"],
        )
        records.append(record)
        if progress and (len(records) == 1 or len(records) % 5 == 0):
            progress(
                {
                    "event": "series_progress",
                    "series": series_ticker,
                    "attempted": attempted,
                    "records": len(records),
                    "refused": len(raw_rows) - len(records),
                }
            )
    if progress:
        progress(
            {
                "event": "series_done",
                "series": series_ticker,
                "attempted": len(raw_rows),
                "records": len(records),
                "refused": len(raw_rows) - len(records),
                "stopped_after_successful": stop_after_successful,
            }
        )
    return records, raw_rows


def build_weather_backtest(
    series_tickers: list[str] | None = None,
    stop_after_successful_per_series: int | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[list[CalibrationRecord], list[dict]]:
    """Runs the backtest across every verified weather station by default
    (all of docs/VERIFICATION_LEDGER.md §1.3's registry) — not just NYC.
    Real ceiling only: whatever Kalshi has settled and Open-Meteo's archive
    still covers. `stop_after_successful_per_series` is an explicit runtime
    control for verification/demo commands; leaving it as None runs the no-cap
    path."""
    from rwoo.weather_stations import STATIONS

    series_tickers = series_tickers or list(STATIONS.keys())
    all_records: list[CalibrationRecord] = []
    all_raw_rows: list[dict] = []
    for series_ticker in series_tickers:
        records, raw_rows = build_weather_backtest_for_series(
            series_ticker,
            stop_after_successful=stop_after_successful_per_series,
            progress=progress,
        )
        all_records.extend(records)
        all_raw_rows.extend(raw_rows)
    return all_records, all_raw_rows


_METRIC_THRESHOLDS = {
    "precipitation_sum": (0.0, 0.1, 0.5, 1.0),
    "snowfall_sum": (0.0, 1.0, 3.0, 6.0),
    "wind_speed_10m_max": (10.0, 20.0, 30.0, 40.0),
    "wind_gusts_10m_max": (20.0, 30.0, 40.0, 50.0),
}


def fetch_historical_observation(lat: float, lon: float, target_date: str, timezone_name: str, metric: str) -> float:
    data = _get_with_retry(HISTORICAL_URL, params={
        "latitude": lat, "longitude": lon, "start_date": target_date, "end_date": target_date,
        "daily": metric, "timezone": timezone_name, **METRICS[metric]["openmeteo_units"],
    }).json()
    values = data.get("daily", {}).get(metric) or []
    if not values or values[0] is None:
        raise RuntimeError(f"no historical {metric} observation for {target_date}")
    return float(values[0])


def build_metric_skill_backtest(metric: str, stations: list | None = None, days: int = 21) -> tuple[list[CalibrationRecord], list[dict]]:
    """Forecast-skill calibration where no resolved venue markets exist.

    Previous-day archived model runs are scored against Open-Meteo historical
    reanalysis. This validates the metric transform, not venue settlement.
    """
    from rwoo.weather_stations import STATIONS_BY_CODE, STATION_TIMEZONES
    if metric not in _METRIC_THRESHOLDS:
        raise ValueError(f"no skill thresholds configured for {metric}")
    stations = stations or list(STATIONS_BY_CODE.items())
    records, raw_rows = [], []
    today = datetime.now(timezone.utc).date()
    for code, station in stations:
        timezone_name = STATION_TIMEZONES[code]
        for offset in range(7, 7 + days):  # allow reanalysis publication lag
            target = (today - timedelta(days=offset)).isoformat(); run = _previous_day_06z(target)
            try:
                forecasts = fetch_single_run_all_models(station.lat, station.lon, target, run,
                                                        timezone_name=timezone_name, metric=metric)
                actual = fetch_historical_observation(station.lat, station.lon, target, timezone_name, metric)
                if len(forecasts) < 2:
                    raise RuntimeError("fewer than two archived models")
            except Exception as exc:  # noqa: BLE001
                raw_rows.append({"station": code, "target": target, "refused": True, "reason": str(exc)})
                continue
            mean, std = statistics.fmean(forecasts.values()), statistics.pstdev(forecasts.values())
            for threshold in _METRIC_THRESHOLDS[metric]:
                probability = event_probability(metric, list(forecasts.values()), "greater", threshold, None)
                record = CalibrationRecord(
                    domain="weather", venue="open_meteo_skill", market_id=f"{metric}-{code}-{target}-GT-{threshold}",
                    question=f"{metric} at {code} on {target} greater than {threshold}",
                    decision_timestamp=_run_available_at(run), resolution_timestamp=f"{target}T23:59:59+00:00",
                    oracle_prob=max(0.0, min(1.0, probability)), outcome=int(actual > threshold),
                    bucket=probability_bucket(probability), source_run=run, source_available_at=_run_available_at(run),
                    target_date=target,
                )
                records.append(record)
            raw_rows.append({"station": code, "target": target, "refused": False, "forecasts": forecasts,
                             "historical_reanalysis": actual, "validation_scope": "forecast skill, not venue settlement"})
    return records, raw_rows
