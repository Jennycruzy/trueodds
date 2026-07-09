"""Phase 4 economics engine.

This is intentionally a conservative baseline, not a finished macro desk
model. For Kalshi core-CPI markets it pulls official BLS CPI-U less food and
energy data, computes real month-over-month changes, and estimates the target
event from two deterministic views of that same official history:

1. a long-window empirical distribution of reported monthly changes;
2. a trailing-recent empirical distribution.

Because this does not yet include a verified consensus-forecast distribution,
confidence is capped. The engine may produce a probability for end-to-end
testing, but the restraint layer should usually refuse strong action until a
proper forecast-distribution source is added and calibrated.
"""
from __future__ import annotations

import math
import os
import statistics
import time
from datetime import date, datetime, timezone

import httpx

from rwoo import economic_sources

BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_FLAT_CURRENT_URL = "https://download.bls.gov/pub/time.series/cu/cu.data.0.Current"
# Optional: a free registration key (data.bls.gov/registrationEngine/) raises
# the daily quota from ~25 to ~500 requests. Registration requires solving a
# CAPTCHA, so it can't be automated — set BLS_API_KEY once you have one; unset
# behaves exactly as before (unauthenticated, lower quota).
BLS_API_KEY_ENV = "BLS_API_KEY"
BLS_CORE_CPI_SA_SERIES = "CUSR0000SA0L1E"
BLS_HEADLINE_CPI_NSA_SERIES = "CUUR0000SA0"
BLS_HEADLINE_CPI_SA_SERIES = "CUSR0000SA0"
BLS_U3_SERIES = "LNS14000000"
BLS_PAYROLLS_SERIES = "CES0000000001"  # all employees, thousands, SA
HISTORY_START_YEAR = 2016

# The unauthenticated BLS v2 API allows only ~25 requests/day. A backtest
# scores many sibling markets (same event, different strike thresholds) that
# share the same decision date and therefore the same `as_of` cutoff — without
# caching, each one re-fetches the entire history separately and burns the
# daily quota in a handful of markets. Keyed on the exact query shape.
_CPI_SERIES_CACHE: dict[tuple[str, int, int], list[dict]] = {}

# Real BLS CPI release dates (release covers the PRIOR month's data). The
# primary BLS release schedule page is verified by `verify.py --phase 7` using
# a normal User-Agent; this table captures the window needed by the current
# no-lookahead Kalshi CPI backtest. Key = (reference_year, reference_month).
# None = release was canceled/unavailable (the October 2025 report was
# canceled due to a government shutdown) — real-world messiness, not smoothed
# over. Used ONLY to backtest without lookahead; the live engine (no `as_of`)
# is unaffected by this table.
CPI_RELEASE_DATES: dict[tuple[int, int], date | None] = {
    (2025, 10): None,
    (2025, 11): date(2025, 12, 18),
    (2025, 12): date(2026, 1, 13),
    (2026, 1): date(2026, 2, 13),
    (2026, 2): date(2026, 3, 11),
    (2026, 3): date(2026, 4, 10),
    (2026, 4): date(2026, 5, 12),
    (2026, 5): date(2026, 6, 10),
    (2026, 6): date(2026, 7, 14),
    (2026, 7): date(2026, 8, 12),
    (2026, 8): date(2026, 9, 11),
    (2026, 9): date(2026, 10, 14),
    (2026, 10): date(2026, 11, 10),
    (2026, 11): date(2026, 12, 10),
}


def release_date_for(year: int, month: int) -> date | None:
    if (year, month) in CPI_RELEASE_DATES:
        return CPI_RELEASE_DATES[(year, month)]
    # Outside the verified table (i.e. more than ~8 months before any
    # backtested decision date in this project's window): a deliberately
    # LATE conservative estimate — release day 20 of month+1, versus the real
    # observed pattern of day ~10-14. This errs toward excluding a value
    # rather than risking a lookahead false-include; it does not need to be
    # exact for months this far in the past relative to any decision date
    # we backtest against.
    next_month, next_year = (month + 1, year) if month < 12 else (1, year + 1)
    return date(next_year, next_month, 20)


def _post_with_retry(url: str, json: dict, timeout: float = 25, attempts: int = 3) -> httpx.Response:
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            resp = httpx.post(url, json=json, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts:
                time.sleep(1.5 * attempt)
    raise last_exc


def _fetch_cpi_chunk(series_id: str, start_year: int, end_year: int) -> list[dict]:
    payload = {
        "seriesid": [series_id],
        "startyear": str(start_year),
        "endyear": str(end_year),
    }
    api_key = os.environ.get(BLS_API_KEY_ENV)
    if api_key:
        payload["registrationkey"] = api_key
    resp = _post_with_retry(BLS_URL, json=payload)
    data = resp.json()
    if data.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS request failed: {data}")
    return data["Results"]["series"][0]["data"]


def _fetch_core_cpi_chunk(start_year: int, end_year: int) -> list[dict]:
    return _fetch_cpi_chunk(BLS_CORE_CPI_SA_SERIES, start_year, end_year)


def _fetch_cpi_flat_file(series_id: str, start_year: int, end_year: int) -> list[dict]:
    """Official BLS flat-file fallback.

    The public API has a low unauthenticated daily quota. The BLS time-series
    mirror publishes the same CPI series as text files; it requires a normal
    User-Agent from this workspace but has no API quota. This is a fallback,
    not a replacement for the API shape verified in earlier phases.
    """
    resp = httpx.get(
        BLS_FLAT_CURRENT_URL,
        headers={"User-Agent": economic_sources.USER_AGENT},
        timeout=60,
    )
    resp.raise_for_status()
    rows = []
    for line in resp.text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4 or parts[0] != series_id:
            continue
        year = int(parts[1])
        if not start_year <= year <= end_year:
            continue
        rows.append(
            {
                "year": parts[1],
                "period": parts[2],
                "value": parts[3],
                "latest": "false",
            }
        )
    if not rows:
        raise RuntimeError(f"BLS flat-file fallback returned no CPI rows for {series_id}")
    return rows


def _fetch_core_cpi_flat_file(start_year: int, end_year: int) -> list[dict]:
    return _fetch_cpi_flat_file(BLS_CORE_CPI_SA_SERIES, start_year, end_year)


def _fetch_and_parse_full_history(
    start_year: int,
    end_year: int,
    series_id: str = BLS_CORE_CPI_SA_SERIES,
) -> list[dict]:
    """The full raw parsed history for [start_year, end_year], fetched once
    and cached — regardless of how many different `as_of` cutoffs later slice
    it. This is what keeps a many-market backtest inside BLS's real
    unauthenticated daily quota (~25 requests/day): one raw fetch serves every
    market's as-of filter instead of each market re-fetching the same years."""
    cache_key = (series_id, start_year, end_year)
    if cache_key in _CPI_SERIES_CACHE:
        return _CPI_SERIES_CACHE[cache_key]

    rows = []
    chunk_start = start_year
    try:
        while chunk_start <= end_year:
            chunk_end = min(chunk_start + 9, end_year)
            rows.extend(_fetch_cpi_chunk(series_id, chunk_start, chunk_end))
            chunk_start = chunk_end + 1
    except Exception:
        rows = _fetch_cpi_flat_file(series_id, start_year, end_year)

    parsed = []
    seen = set()
    for row in rows:
        period = row.get("period", "")
        value = row.get("value")
        if not period.startswith("M") or value in (None, "-"):
            continue
        year, month = int(row["year"]), int(period[1:])
        key = (year, month)
        if key in seen:
            continue
        seen.add(key)
        parsed.append(
            {
                "year": year,
                "month": month,
                "value": float(value),
                "latest": row.get("latest") == "true",
            }
        )
    parsed = sorted(parsed, key=lambda r: (r["year"], r["month"]))
    _CPI_SERIES_CACHE[cache_key] = parsed
    return parsed


def fetch_core_cpi_series(
    start_year: int = HISTORY_START_YEAR, end_year: int | None = None, as_of: date | None = None
) -> list[dict]:
    """Official BLS values, oldest first. Unavailable government-shutdown rows
    carry '-' and are skipped rather than coerced into numbers.

    `as_of`: if given, rows whose real BLS *release* date (not reference
    month — see CPI_RELEASE_DATES) falls after `as_of` are excluded. This is
    what makes a genuine no-lookahead backtest possible: BLS's API always
    returns the CURRENT full history, so the caller must filter by when a
    value actually became public, not merely which month it describes.
    """
    end_year = end_year or datetime.now(timezone.utc).year
    full_history = _fetch_and_parse_full_history(start_year, end_year, BLS_CORE_CPI_SA_SERIES)
    if as_of is None:
        return full_history
    out = []
    for row in full_history:
        rd = release_date_for(row["year"], row["month"])
        if rd is None or rd > as_of:
            continue
        out.append(row)
    return out


def fetch_headline_cpi_series(
    start_year: int = HISTORY_START_YEAR, end_year: int | None = None, as_of: date | None = None
) -> list[dict]:
    """Official BLS all-items CPI-U values, oldest first.

    This uses the not-seasonally-adjusted all-items CPI-U series because
    public annual headline CPI markets typically resolve against the reported
    12-month all-items figure before seasonal adjustment.
    """
    end_year = end_year or datetime.now(timezone.utc).year
    full_history = _fetch_and_parse_full_history(start_year, end_year, BLS_HEADLINE_CPI_NSA_SERIES)
    if as_of is None:
        return full_history
    out = []
    for row in full_history:
        rd = release_date_for(row["year"], row["month"])
        if rd is None or rd > as_of:
            continue
        out.append(row)
    return out


def month_over_month_changes(rows: list[dict]) -> list[dict]:
    changes = []
    for prev, cur in zip(rows, rows[1:]):
        pct = (cur["value"] - prev["value"]) / prev["value"] * 100
        reported_single_decimal = round(pct, 1)
        changes.append({**cur, "mom_pct": pct, "reported_single_decimal": reported_single_decimal})
    return changes


def year_over_year_changes(rows: list[dict]) -> list[dict]:
    values = {(row["year"], row["month"]): row["value"] for row in rows}
    changes = []
    for row in rows:
        prev = values.get((row["year"] - 1, row["month"]))
        if prev in (None, 0):
            continue
        pct = (row["value"] - prev) / prev * 100
        reported_single_decimal = round(pct, 1)
        changes.append({**row, "yoy_pct": pct, "reported_single_decimal": reported_single_decimal})
    return changes


def _event_probability(values: list[float], strike_type: str, floor_strike, cap_strike) -> float:
    if not values:
        raise ValueError("cannot compute probability from an empty history")
    if strike_type == "greater":
        hits = sum(1 for v in values if v > float(floor_strike))
    elif strike_type == "less":
        hits = sum(1 for v in values if v < float(cap_strike))
    elif strike_type == "between":
        hits = sum(1 for v in values if float(floor_strike) <= v <= float(cap_strike))
    else:
        raise ValueError(f"Unknown strike_type: {strike_type!r}")
    return hits / len(values)


def _normal_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _normal_event_probability(mean: float, std: float, strike_type: str, floor_strike, cap_strike) -> float:
    std = max(std, 0.03)
    if strike_type == "greater":
        return 1 - _normal_cdf((float(floor_strike) - mean) / std)
    if strike_type == "less":
        return _normal_cdf((float(cap_strike) - mean) / std)
    if strike_type == "between":
        return _normal_cdf((float(cap_strike) - mean) / std) - _normal_cdf((float(floor_strike) - mean) / std)
    raise ValueError(f"Unknown strike_type: {strike_type!r}")


def compute_core_cpi_probability(
    strike_type: str, floor_strike, cap_strike, target_month: int | None = None, as_of: date | None = None
) -> dict:
    rows = fetch_core_cpi_series(as_of=as_of)
    changes = month_over_month_changes(rows)
    if len(changes) < 36:
        return {
            "oracle_prob": None,
            "confidence": 0.0,
            "prob_low": None,
            "prob_high": None,
            "per_source_values": {"official_bls_rows": len(rows), "usable_monthly_changes": len(changes)},
            "method": "insufficient_bls_history",
            "data_freshness": datetime.now(timezone.utc).isoformat(),
            "base_rate": None,
            "refused": True,
            "reason": f"only {len(changes)} usable BLS monthly changes returned",
        }

    all_values = [c["reported_single_decimal"] for c in changes]
    same_month = [
        c["reported_single_decimal"] for c in changes if target_month is not None and c["month"] == target_month
    ]
    trailing = [c["reported_single_decimal"] for c in changes[-36:]]

    historical_prob = _event_probability(all_values, strike_type, floor_strike, cap_strike)
    trailing_prob = _event_probability(trailing, strike_type, floor_strike, cap_strike)
    model_probs = {
        "official_bls_all_history_empirical": historical_prob,
        "official_bls_trailing_36_months_empirical": trailing_prob,
    }
    if len(same_month) >= 5:
        model_probs["official_bls_same_calendar_month_empirical"] = _event_probability(
            same_month, strike_type, floor_strike, cap_strike
        )

    forecast_sources = {}
    if as_of is None:
        if target_month is not None:
            try:
                nowcasts = economic_sources.fetch_cleveland_nowcasts()
                current_year = datetime.now(timezone.utc).year
                nowcast = next((r for r in nowcasts if r.year == current_year and r.month == target_month), None)
                if nowcast is not None:
                    nowcast_sigma = max(0.05, statistics.pstdev(trailing[-36:]) if len(trailing) >= 2 else 0.10)
                    prob = _normal_event_probability(
                        nowcast.core_cpi_mom,
                        nowcast_sigma,
                        strike_type,
                        floor_strike,
                        cap_strike,
                    )
                    model_probs["cleveland_fed_core_cpi_nowcast_mom"] = min(1.0, max(0.0, prob))
                    forecast_sources["cleveland_fed"] = {
                        "source": "Federal Reserve Bank of Cleveland Inflation Nowcasting",
                        "target_month": f"{nowcast.year}-{nowcast.month:02d}",
                        "core_cpi_mom_nowcast": nowcast.core_cpi_mom,
                        "updated": nowcast.updated,
                        "distribution_sigma_from_recent_bls_mom": nowcast_sigma,
                    }
            except Exception as exc:  # noqa: BLE001
                forecast_sources["cleveland_fed_error"] = str(exc)

        target_year = datetime.now(timezone.utc).year
        try:
            spf_row = economic_sources.latest_spf_row_for_target(target_year)
            if spf_row is not None:
                spf_prob = economic_sources.event_probability_from_spf_monthly_equivalent(
                    spf_row.probabilities, strike_type, floor_strike, cap_strike
                )
                model_probs["philadelphia_fed_spf_core_cpi_q4q4_monthly_equivalent"] = spf_prob
                forecast_sources["philadelphia_fed_spf"] = {
                    "source": "Federal Reserve Bank of Philadelphia Survey of Professional Forecasters PRCCPI",
                    "survey": f"{spf_row.survey_year}:Q{spf_row.survey_quarter}",
                    "target_year": spf_row.target_year,
                    "source_available_at": spf_row.source_available_at,
                    "method_note": "annual Q4/Q4 core-CPI density converted to monthly-equivalent regime prior",
                }
        except Exception as exc:  # noqa: BLE001
            forecast_sources["philadelphia_fed_spf_error"] = str(exc)

    oracle_prob = statistics.fmean(model_probs.values())
    prob_low = min(model_probs.values())
    prob_high = max(model_probs.values())

    # Confidence is model agreement. It remains capped when only backward-
    # looking BLS history is available; live runs with official forward-looking
    # sources can earn a higher cap, but still cannot exceed agreement.
    raw_agreement = 1.0 - (prob_high - prob_low)
    has_forward_source = any(
        key.startswith("cleveland_fed") or key.startswith("philadelphia_fed_spf")
        for key in model_probs
    )
    confidence_cap = 0.72 if has_forward_source else 0.50
    confidence = min(confidence_cap, max(0.0, raw_agreement))
    latest = rows[-1]

    return {
        "oracle_prob": oracle_prob,
        "confidence": confidence,
        "prob_low": prob_low,
        "prob_high": prob_high,
        "per_model_prob": model_probs,
        "per_source_values": {
            "source": "BLS public API",
            "series": BLS_CORE_CPI_SA_SERIES,
            "latest_observation": f"{latest['year']}-{latest['month']:02d}",
            "latest_index_value": latest["value"],
            "usable_monthly_changes": len(changes),
            "same_month_samples": len(same_month),
            "recent_reported_single_decimal_values": all_values[-8:],
            "forward_forecast_sources": forecast_sources,
        },
        "method": (
            "official BLS seasonally adjusted core CPI history plus official forward-looking "
            "Cleveland Fed nowcast/SPF density when available -> deterministic ensemble probability"
        ),
        "data_freshness": datetime.now(timezone.utc).isoformat(),
        "base_rate": historical_prob,
        "refused": False,
    }


def compute_headline_cpi_annual_probability(
    strike_type: str,
    floor_strike,
    cap_strike,
    target_month: int | None = None,
    as_of: date | None = None,
) -> dict:
    rows = fetch_headline_cpi_series(as_of=as_of)
    changes = year_over_year_changes(rows)
    if len(changes) < 60:
        return {
            "oracle_prob": None,
            "confidence": 0.0,
            "prob_low": None,
            "prob_high": None,
            "per_source_values": {"official_bls_rows": len(rows), "usable_annual_changes": len(changes)},
            "method": "insufficient_bls_headline_cpi_history",
            "data_freshness": datetime.now(timezone.utc).isoformat(),
            "base_rate": None,
            "refused": True,
            "reason": f"only {len(changes)} usable BLS annual headline-CPI changes returned",
        }

    all_values = [c["reported_single_decimal"] for c in changes]
    trailing = [c["reported_single_decimal"] for c in changes[-36:]]
    same_month = [
        c["reported_single_decimal"] for c in changes if target_month is not None and c["month"] == target_month
    ]

    historical_prob = _event_probability(all_values, strike_type, floor_strike, cap_strike)
    trailing_prob = _event_probability(trailing, strike_type, floor_strike, cap_strike)
    model_probs = {
        "official_bls_all_history_empirical": historical_prob,
        "official_bls_trailing_36_months_empirical": trailing_prob,
    }
    if len(same_month) >= 5:
        model_probs["official_bls_same_calendar_month_empirical"] = _event_probability(
            same_month, strike_type, floor_strike, cap_strike
        )

    if len(trailing) >= 12:
        trailing_mean = statistics.fmean(trailing)
        trailing_std = statistics.pstdev(trailing)
        model_probs["official_bls_trailing_normal_fit"] = _normal_event_probability(
            trailing_mean,
            trailing_std,
            strike_type,
            floor_strike,
            cap_strike,
        )

    forecast_sources = {}
    if as_of is None and target_month is not None:
        # A month-specific official nowcast dominates backward-looking
        # history for the reference months it covers (typically the current
        # and adjacent months) — the July 2026 live check showed history-only
        # pricing pointing the OPPOSITE way from the official nowcast.
        try:
            yoy_nowcasts = economic_sources.fetch_cleveland_yoy_nowcasts()
            current_year = datetime.now(timezone.utc).year
            nowcast = next(
                (
                    r
                    for r in yoy_nowcasts
                    if r.month == target_month and r.year in (current_year, current_year + 1)
                ),
                None,
            )
            if nowcast is not None:
                recent_yoy = [c["yoy_pct"] for c in changes[-13:]]
                yoy_step_std = (
                    statistics.pstdev([b - a for a, b in zip(recent_yoy, recent_yoy[1:])])
                    if len(recent_yoy) >= 3
                    else 0.10
                )
                sigma = max(0.05, yoy_step_std)
                prob = _normal_event_probability(nowcast.cpi_yoy, sigma, strike_type, floor_strike, cap_strike)
                model_probs["cleveland_fed_headline_cpi_nowcast_yoy"] = min(1.0, max(0.0, prob))
                forecast_sources["cleveland_fed"] = {
                    "source": "Federal Reserve Bank of Cleveland Inflation Nowcasting (headline CPI YoY)",
                    "target_month": f"{nowcast.year}-{nowcast.month:02d}",
                    "cpi_yoy_nowcast": nowcast.cpi_yoy,
                    "updated": nowcast.updated,
                    "distribution_sigma_from_recent_yoy_steps": sigma,
                }
        except Exception as exc:  # noqa: BLE001
            forecast_sources["cleveland_fed_error"] = str(exc)

    has_forward = any(key.startswith("cleveland_fed") for key in model_probs)
    oracle_prob = statistics.fmean(model_probs.values())
    prob_low = min(model_probs.values())
    prob_high = max(model_probs.values())
    confidence = min(0.72 if has_forward else 0.50, max(0.0, 1.0 - (prob_high - prob_low)))
    latest = rows[-1]

    return {
        "oracle_prob": oracle_prob,
        "confidence": confidence,
        "prob_low": prob_low,
        "prob_high": prob_high,
        "per_model_prob": model_probs,
        "per_source_values": {
            "source": "BLS public API",
            "series": BLS_HEADLINE_CPI_NSA_SERIES,
            "latest_observation": f"{latest['year']}-{latest['month']:02d}",
            "latest_index_value": latest["value"],
            "usable_annual_changes": len(changes),
            "same_month_samples": len(same_month),
            "recent_reported_single_decimal_values": all_values[-8:],
            "forward_forecast_sources": forecast_sources,
        },
        "method": (
            "official BLS not-seasonally-adjusted all-items CPI-U annual changes -> "
            "deterministic empirical/normal-fit probability"
            + (
                "; plus official Cleveland Fed month-specific YoY nowcast"
                if any(k.startswith("cleveland_fed") for k in model_probs)
                else "; confidence capped because no forward-looking source covers this target month"
            )
        ),
        "data_freshness": datetime.now(timezone.utc).isoformat(),
        "base_rate": historical_prob,
        "refused": False,
    }


def compute_headline_cpi_monthly_probability(
    strike_type: str,
    floor_strike,
    cap_strike,
    target_month: int | None = None,
    as_of: date | None = None,
) -> dict:
    """US headline CPI month-over-month markets (seasonally adjusted, as
    reported in the BLS release's one-decimal MoM figure)."""
    rows = fetch_headline_cpi_sa_series(as_of=as_of)
    changes = month_over_month_changes(rows)
    if len(changes) < 36:
        return _refusal(
            "insufficient_bls_headline_cpi_sa_history",
            f"only {len(changes)} usable BLS SA headline monthly changes returned",
            {"official_bls_rows": len(rows)},
        )

    all_values = [c["reported_single_decimal"] for c in changes]
    trailing = [c["reported_single_decimal"] for c in changes[-36:]]
    same_month = [
        c["reported_single_decimal"] for c in changes if target_month is not None and c["month"] == target_month
    ]
    historical_prob = _event_probability(all_values, strike_type, floor_strike, cap_strike)
    model_probs = {
        "official_bls_all_history_empirical": historical_prob,
        "official_bls_trailing_36_months_empirical": _event_probability(
            trailing, strike_type, floor_strike, cap_strike
        ),
    }
    if len(same_month) >= 5:
        model_probs["official_bls_same_calendar_month_empirical"] = _event_probability(
            same_month, strike_type, floor_strike, cap_strike
        )

    forecast_sources = {}
    if as_of is None and target_month is not None:
        try:
            nowcasts = economic_sources.fetch_cleveland_nowcasts()
            current_year = datetime.now(timezone.utc).year
            nowcast = next(
                (r for r in nowcasts if r.month == target_month and r.year in (current_year, current_year + 1)),
                None,
            )
            if nowcast is not None:
                sigma = max(0.05, statistics.pstdev(trailing) if len(trailing) >= 2 else 0.10)
                prob = _normal_event_probability(nowcast.cpi_mom, sigma, strike_type, floor_strike, cap_strike)
                model_probs["cleveland_fed_headline_cpi_nowcast_mom"] = min(1.0, max(0.0, prob))
                forecast_sources["cleveland_fed"] = {
                    "source": "Federal Reserve Bank of Cleveland Inflation Nowcasting (headline CPI MoM)",
                    "target_month": f"{nowcast.year}-{nowcast.month:02d}",
                    "cpi_mom_nowcast": nowcast.cpi_mom,
                    "updated": nowcast.updated,
                    "distribution_sigma_from_recent_bls_mom": sigma,
                }
        except Exception as exc:  # noqa: BLE001
            forecast_sources["cleveland_fed_error"] = str(exc)

    return _ensemble_result(
        model_probs,
        confidence_cap=0.72 if any(k.startswith("cleveland_fed") for k in model_probs) else 0.50,
        base_rate=historical_prob,
        per_source_values={
            "source": "BLS public API / flat-file mirror",
            "series": BLS_HEADLINE_CPI_SA_SERIES,
            "latest_observation": f"{rows[-1]['year']}-{rows[-1]['month']:02d}",
            "usable_monthly_changes": len(changes),
            "recent_reported_single_decimal_values": all_values[-8:],
            "forward_forecast_sources": forecast_sources,
        },
        method=(
            "official BLS seasonally adjusted all-items CPI-U monthly changes plus official "
            "Cleveland Fed headline-CPI MoM nowcast when it covers the target month -> "
            "deterministic ensemble probability"
        ),
    )


def compute_gdp_quarterly_probability(
    strike_type: str,
    floor_strike,
    cap_strike,
    quarter_label: str,
) -> dict:
    """US real GDP quarterly growth markets (BEA advance estimate, QoQ SAAR),
    priced from the official Atlanta Fed GDPNow nowcast for that quarter."""
    nowcast = economic_sources.fetch_gdpnow_current()
    if nowcast.quarter_label != quarter_label:
        return _refusal(
            "gdpnow_quarter_mismatch",
            f"GDPNow currently tracks {nowcast.quarter_label}, not {quarter_label}; "
            "no verified nowcast source covers that quarter",
            {"gdpnow_quarter": nowcast.quarter_label},
        )
    sigma_tight = max(0.5, statistics.pstdev(nowcast.path_values) if len(nowcast.path_values) >= 2 else 1.0)
    sigma_wide = 2 * sigma_tight
    prob_tight = _normal_event_probability(nowcast.latest, sigma_tight, strike_type, floor_strike, cap_strike)
    prob_wide = _normal_event_probability(nowcast.latest, sigma_wide, strike_type, floor_strike, cap_strike)
    model_probs = {
        "atlanta_fed_gdpnow_normal_sigma_from_quarter_path": min(1.0, max(0.0, prob_tight)),
        "atlanta_fed_gdpnow_normal_sigma_doubled": min(1.0, max(0.0, prob_wide)),
    }
    return _ensemble_result(
        model_probs,
        confidence_cap=0.65,
        base_rate=prob_wide,
        per_source_values={
            "source": "Federal Reserve Bank of Atlanta GDPNow tracking workbook",
            "tracked_quarter": nowcast.quarter_label,
            "latest_nowcast_qoq_saar": nowcast.latest,
            "nowcast_runs_this_quarter": len(nowcast.path_values),
            "latest_run_date": nowcast.latest_date,
            "sigma_tight_from_nowcast_path": sigma_tight,
        },
        method=(
            "official Atlanta Fed GDPNow current-quarter nowcast -> normal CDF at two "
            "deterministic sigma choices (nowcast-path stdev, and doubled); confidence capped "
            "because sigma comes from the nowcast's own revision path, not a full error backtest"
        ),
    )


def compute_gdp_annual_probability(
    strike_type: str,
    floor_strike,
    cap_strike,
    target_year: int,
) -> dict:
    """US annual-average real GDP growth markets, priced from the official
    Philadelphia Fed SPF PRGDP probability bins (current bin era only)."""
    row = economic_sources.latest_spf_density_for_target("PRGDP", target_year)
    if row is None:
        return _refusal(
            "no_spf_prgdp_density",
            f"no current-era SPF PRGDP density covers target year {target_year}",
            {},
        )
    strict, mid, generous = economic_sources.event_probability_from_bins(
        row.probabilities, economic_sources.SPF_PRGDP_BINS, strike_type, floor_strike, cap_strike
    )
    return {
        "oracle_prob": mid,
        "confidence": min(0.66, max(0.0, 1.0 - (generous - strict))),
        "prob_low": strict,
        "prob_high": generous,
        "per_model_prob": {"spf_prgdp_strict": strict, "spf_prgdp_midpoint": mid, "spf_prgdp_generous": generous},
        "per_source_values": {
            "source": "Philadelphia Fed SPF PRGDP probability bins",
            "survey": f"{row.survey_year}:Q{row.survey_quarter}",
            "target_year": row.target_year,
            "source_available_at": row.source_available_at,
        },
        "method": (
            "official SPF real-GDP-growth density bins -> strict/uniform/generous bin integration; "
            "the strict-vs-generous gap is the uncertainty band"
        ),
        "data_freshness": datetime.now(timezone.utc).isoformat(),
        "base_rate": mid,
        "refused": False,
    }


def compute_unemployment_probability(
    strike_type: str,
    floor_strike,
    cap_strike,
    target_month: int,
    target_year: int,
) -> dict:
    """US U-3 unemployment monthly markets: current official level plus the
    empirical distribution of k-month-ahead changes, with the official SPF
    PRUNEMP annual-average density as an independent second model."""
    series = economic_sources.fetch_fred_series("UNRATE")
    if len(series) < 120:
        return _refusal("insufficient_unrate_history", f"only {len(series)} UNRATE rows returned", {})
    values = [v for _d, v in series]
    latest_date, latest = series[-1]
    months_ahead = max(1, (target_year - latest_date.year) * 12 + (target_month - latest_date.month))
    horizon = min(months_ahead, 18)
    deltas = [values[i + horizon] - values[i] for i in range(len(values) - horizon)]
    projected = [latest + d for d in deltas]
    empirical = _event_probability(projected, strike_type, floor_strike, cap_strike)
    model_probs = {"official_unrate_empirical_change_distribution": empirical}

    spf_note = None
    row = economic_sources.latest_spf_density_for_target("PRUNEMP", target_year)
    if row is not None:
        _s, mid, _g = economic_sources.event_probability_from_bins(
            row.probabilities, economic_sources.SPF_PRUNEMP_BINS, strike_type, floor_strike, cap_strike
        )
        model_probs["spf_prunemp_annual_average_midpoint"] = mid
        spf_note = (
            f"SPF PRUNEMP is an ANNUAL-AVERAGE density for {target_year}; using it for a "
            "single-month level is a disclosed approximation"
        )
    return _ensemble_result(
        model_probs,
        confidence_cap=0.60 if len(model_probs) > 1 else 0.50,
        base_rate=empirical,
        per_source_values={
            "sources": ["FRED UNRATE (official BLS U-3 mirror)", "Philadelphia Fed SPF PRUNEMP"],
            "latest_u3": latest,
            "latest_observation": latest_date.isoformat(),
            "months_ahead": months_ahead,
            "horizon_used": horizon,
            "spf_note": spf_note,
        },
        method=(
            "official U-3 history -> empirical k-month-ahead change distribution from the current "
            "level, plus official SPF annual-average unemployment density as an independent model"
        ),
    )


def compute_payrolls_probability(
    strike_type: str,
    floor_strike,
    cap_strike,
    target_month: int | None = None,
) -> dict:
    """US nonfarm payrolls monthly-change markets (BLS Employment Situation).
    History-only: no verified forward-looking payrolls distribution is wired,
    so confidence stays capped at 0.50."""
    series = economic_sources.fetch_fred_series("PAYEMS")  # thousands, SA
    if len(series) < 120:
        return _refusal("insufficient_payems_history", f"only {len(series)} PAYEMS rows returned", {})
    diffs_persons = [
        (series[i + 1][1] - series[i][1]) * 1000 for i in range(len(series) - 1)
    ]
    # The pandemic swings (±20M) would dominate any empirical distribution;
    # exclude only the 2020-03..2021-12 window, and say so.
    filtered = [
        d for (dte, _v), d in zip(series[1:], diffs_persons)
        if not (dte.year == 2020 and dte.month >= 3) and dte.year != 2021
    ]
    trailing = filtered[-36:]
    model_probs = {
        "official_payems_all_history_empirical_ex_pandemic": _event_probability(
            filtered, strike_type, floor_strike, cap_strike
        ),
        "official_payems_trailing_36_months_empirical": _event_probability(
            trailing, strike_type, floor_strike, cap_strike
        ),
    }
    return _ensemble_result(
        model_probs,
        confidence_cap=0.50,
        base_rate=model_probs["official_payems_all_history_empirical_ex_pandemic"],
        per_source_values={
            "source": "FRED PAYEMS (official BLS nonfarm payrolls mirror)",
            "latest_observation": series[-1][0].isoformat(),
            "latest_level_thousands": series[-1][1],
            "recent_monthly_changes_persons": [int(d) for d in diffs_persons[-6:]],
            "pandemic_exclusion": "2020-03 through 2021-12 excluded from the empirical distribution (disclosed)",
        },
        method=(
            "official nonfarm payrolls history -> empirical monthly-change distribution "
            "(pandemic window excluded, disclosed); confidence capped until a verified "
            "forward-looking payrolls distribution is added"
        ),
    )


def compute_fed_rate_probability(
    strike_type: str,
    floor_strike,
    cap_strike,
    target_date_iso: str,
) -> dict:
    """Fed funds target-range markets. Deterministically priceable ONLY when
    no scheduled FOMC meeting remains before the market's date: the range
    then holds unless an unscheduled intermeeting move happens, whose base
    rate is computed from the official daily target-range history. Markets
    with scheduled meetings in between are REFUSED: no verified
    forward-looking rate-path distribution source is wired."""
    target = date.fromisoformat(target_date_iso[:10])
    today = datetime.now(timezone.utc).date()
    meetings = economic_sources.fetch_fomc_meeting_dates()
    scheduled_between = [m for m in meetings if today < m <= target]
    series = economic_sources.fetch_fed_target_upper()
    current_date, current_upper = series[-1]
    if scheduled_between:
        return _refusal(
            "fed_path_source_missing",
            f"{len(scheduled_between)} scheduled FOMC meeting(s) fall before {target}; pricing them "
            "needs a verified forward-looking rate-path distribution (e.g. fed funds futures), "
            "which this build has not wired",
            {
                "current_target_upper": current_upper,
                "scheduled_meetings_before_target": [m.isoformat() for m in scheduled_between],
            },
        )
    # Base rate of a target change on any given day, from the full official
    # daily history (includes meeting days, so it OVERSTATES intermeeting
    # risk — a deliberately conservative direction).
    changes = sum(1 for (_, a), (_, b) in zip(series, series[1:]) if a != b)
    daily_change_rate = changes / max(1, len(series) - 1)
    days = max(0, (target - today).days)
    p_hold = (1 - daily_change_rate) ** days
    currently_true = _event_probability([current_upper], strike_type, floor_strike, cap_strike) >= 1.0
    if currently_true:
        oracle_prob = p_hold + (1 - p_hold) * 0.5  # direction-agnostic if a surprise move happens
        prob_low, prob_high = p_hold, 1.0
    else:
        oracle_prob = (1 - p_hold) * 0.5
        prob_low, prob_high = 0.0, 1 - p_hold
    return {
        "oracle_prob": oracle_prob,
        "confidence": min(0.85, p_hold),
        "prob_low": prob_low,
        "prob_high": prob_high,
        "per_model_prob": {"official_target_history_hold_probability": p_hold},
        "per_source_values": {
            "sources": ["FRED DFEDTARU (official daily target range upper limit)", "federalreserve.gov FOMC calendar"],
            "current_target_upper": current_upper,
            "current_as_of": current_date.isoformat(),
            "days_to_target": days,
            "daily_change_base_rate": daily_change_rate,
            "event_true_at_current_range": currently_true,
        },
        "method": (
            "no scheduled FOMC meeting before target -> current official target range holds unless an "
            "unscheduled move occurs; hold probability from the official daily-history change base rate "
            "(conservatively includes meeting-day changes)"
        ),
        "data_freshness": datetime.now(timezone.utc).isoformat(),
        "base_rate": p_hold,
        "refused": False,
    }


def compute_recession_quarter_probability(target_year: int, target_quarter: int) -> dict:
    """Probability that real GDP DECLINES in a specific quarter, from the
    official SPF anxious index (RECESS1..RECESS5). Only markets whose rule is
    a decline-in-quarter test should be routed here; NBER-declaration markets
    have no verified probability source in this build."""
    rows = economic_sources.fetch_spf_recess_rows()
    if not rows:
        return _refusal("no_spf_recess_rows", "SPF RECESS sheet returned no usable rows", {})
    latest = rows[-1]
    offset = (target_year - latest.survey_year) * 4 + (target_quarter - latest.survey_quarter)
    if not 0 <= offset <= 4:
        return _refusal(
            "recess_horizon_out_of_range",
            f"{target_year}Q{target_quarter} is {offset} quarters from the latest survey; "
            "SPF RECESS covers only the survey quarter through +4",
            {"latest_survey": f"{latest.survey_year}Q{latest.survey_quarter}"},
        )
    prob = latest.probabilities[offset]
    previous = rows[-2] if len(rows) >= 2 else None
    prev_prob = None
    if previous is not None:
        prev_offset = (target_year - previous.survey_year) * 4 + (target_quarter - previous.survey_quarter)
        if 0 <= prev_offset <= 4:
            prev_prob = previous.probabilities[prev_offset]
    band = sorted(p for p in (prob, prev_prob) if p is not None)
    return {
        "oracle_prob": prob,
        "confidence": min(0.60, 1.0 - (band[-1] - band[0])) if len(band) > 1 else 0.50,
        "prob_low": band[0],
        "prob_high": band[-1],
        "per_model_prob": {
            "spf_recess_latest_survey": prob,
            **({"spf_recess_previous_survey": prev_prob} if prev_prob is not None else {}),
        },
        "per_source_values": {
            "source": "Philadelphia Fed SPF RECESS (anxious index)",
            "latest_survey": f"{latest.survey_year}Q{latest.survey_quarter}",
            "target": f"{target_year}Q{target_quarter}",
            "source_available_at": latest.source_available_at,
        },
        "method": (
            "official SPF mean probability of a real-GDP decline in the target quarter; band from "
            "the previous survey's value for the same quarter"
        ),
        "data_freshness": datetime.now(timezone.utc).isoformat(),
        "base_rate": prob,
        "refused": False,
    }


def fetch_headline_cpi_sa_series(
    start_year: int = HISTORY_START_YEAR, end_year: int | None = None, as_of: date | None = None
) -> list[dict]:
    """Official BLS seasonally adjusted all-items CPI-U values, oldest first
    (the series behind reported headline MoM figures)."""
    end_year = end_year or datetime.now(timezone.utc).year
    full_history = _fetch_and_parse_full_history(start_year, end_year, BLS_HEADLINE_CPI_SA_SERIES)
    if as_of is None:
        return full_history
    out = []
    for row in full_history:
        rd = release_date_for(row["year"], row["month"])
        if rd is None or rd > as_of:
            continue
        out.append(row)
    return out


def _refusal(method: str, reason: str, per_source_values: dict) -> dict:
    return {
        "oracle_prob": None,
        "confidence": 0.0,
        "prob_low": None,
        "prob_high": None,
        "per_source_values": per_source_values,
        "method": method,
        "data_freshness": datetime.now(timezone.utc).isoformat(),
        "base_rate": None,
        "refused": True,
        "reason": reason,
    }


def _ensemble_result(
    model_probs: dict[str, float],
    *,
    confidence_cap: float,
    base_rate: float,
    per_source_values: dict,
    method: str,
) -> dict:
    oracle_prob = statistics.fmean(model_probs.values())
    prob_low = min(model_probs.values())
    prob_high = max(model_probs.values())
    return {
        "oracle_prob": oracle_prob,
        "confidence": min(confidence_cap, max(0.0, 1.0 - (prob_high - prob_low))),
        "prob_low": prob_low,
        "prob_high": prob_high,
        "per_model_prob": model_probs,
        "per_source_values": per_source_values,
        "method": method,
        "data_freshness": datetime.now(timezone.utc).isoformat(),
        "base_rate": base_rate,
        "refused": False,
    }
