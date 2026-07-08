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

import statistics
import time
from datetime import datetime, timezone

import httpx

BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_CORE_CPI_SA_SERIES = "CUSR0000SA0L1E"
HISTORY_START_YEAR = 2016


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


def _fetch_core_cpi_chunk(start_year: int, end_year: int) -> list[dict]:
    resp = _post_with_retry(
        BLS_URL,
        json={
            "seriesid": [BLS_CORE_CPI_SA_SERIES],
            "startyear": str(start_year),
            "endyear": str(end_year),
        },
    )
    data = resp.json()
    if data.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS request failed: {data}")
    return data["Results"]["series"][0]["data"]


def fetch_core_cpi_series(start_year: int = HISTORY_START_YEAR, end_year: int | None = None) -> list[dict]:
    """Official BLS values, oldest first. Unavailable government-shutdown rows
    carry '-' and are skipped rather than coerced into numbers.

    The unauthenticated BLS API is range-limited; live Phase 4 verification
    caught that one oversized 2016-2026 request stopped at 2025-12 even though
    2026 observations existed. Query in <=10-year chunks so the latest official
    value is not silently dropped.
    """
    end_year = end_year or datetime.now(timezone.utc).year
    rows = []
    chunk_start = start_year
    while chunk_start <= end_year:
        chunk_end = min(chunk_start + 9, end_year)
        rows.extend(_fetch_core_cpi_chunk(chunk_start, chunk_end))
        chunk_start = chunk_end + 1

    parsed = []
    seen = set()
    for row in rows:
        period = row.get("period", "")
        value = row.get("value")
        if not period.startswith("M") or value in (None, "-"):
            continue
        key = (int(row["year"]), int(period[1:]))
        if key in seen:
            continue
        seen.add(key)
        parsed.append(
            {
                "year": int(row["year"]),
                "month": int(period[1:]),
                "value": float(value),
                "latest": row.get("latest") == "true",
            }
        )
    return sorted(parsed, key=lambda r: (r["year"], r["month"]))


def month_over_month_changes(rows: list[dict]) -> list[dict]:
    changes = []
    for prev, cur in zip(rows, rows[1:]):
        pct = (cur["value"] - prev["value"]) / prev["value"] * 100
        reported_single_decimal = round(pct, 1)
        changes.append({**cur, "mom_pct": pct, "reported_single_decimal": reported_single_decimal})
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


def compute_core_cpi_probability(strike_type: str, floor_strike, cap_strike, target_month: int | None = None) -> dict:
    rows = fetch_core_cpi_series()
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

    oracle_prob = statistics.fmean(model_probs.values())
    prob_low = min(model_probs.values())
    prob_high = max(model_probs.values())

    # Confidence is the model agreement, capped because this is official
    # history only; it is not a verified consensus-forecast distribution yet.
    raw_agreement = 1.0 - (prob_high - prob_low)
    confidence = min(0.50, max(0.0, raw_agreement))
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
        },
        "method": (
            "official BLS seasonally adjusted core CPI history -> single-decimal MoM changes -> "
            "empirical probability; confidence capped pending verified consensus forecast distribution"
        ),
        "data_freshness": datetime.now(timezone.utc).isoformat(),
        "base_rate": historical_prob,
        "refused": False,
    }
