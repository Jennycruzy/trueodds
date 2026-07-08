"""Economics calibration backtest with a no-lookahead proof.

Real settled Kalshi core-CPI markets, scored against what the economics
engine would have said using ONLY BLS values whose real publication date
(not reference month) was already public as of the market's decision time.
No sample-size cap — every real settled KXCPICORE market is attempted.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

import httpx

from rwoo.calibration import CalibrationRecord, probability_bucket
from rwoo import economic_sources
from rwoo.engines.economics import compute_core_cpi_probability, release_date_for
from rwoo.engines.economics import fetch_core_cpi_series
from rwoo.readers import kalshi

_MONTH_ABBR = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def _get_with_retry(url: str, params: dict, timeout: float = 25, attempts: int = 3) -> httpx.Response:
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


def fetch_finalized_cpi_markets(series_ticker: str = "KXCPICORE", page_size: int = 200) -> list[dict]:
    """Paginates through ALL settled markets for a series — no cap."""
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


def _parse_target_month(event_ticker: str) -> tuple[int, int]:
    """'KXCPICORE-26MAY' -> (2026, 5). Same convention as
    rwoo.readers.kalshi.parse_event_date, adapted for a monthly (no day)
    series."""
    suffix = event_ticker.rsplit("-", 1)[-1]
    year, month_abbr = suffix[:2], suffix[2:5]
    return 2000 + int(year), _MONTH_ABBR[month_abbr.upper()]


def compute_archived_cpi_probability(market: dict) -> dict:
    target_year, target_month = _parse_target_month(market["event_ticker"])
    decision_timestamp = market["open_time"]
    decision_date = datetime.fromisoformat(decision_timestamp.replace("Z", "+00:00")).date()

    # No-lookahead proof: the target month's own release must NOT already be
    # public as of the decision date — if it were, this market would already
    # be resolved, not a genuine forecast.
    target_release = release_date_for(target_year, target_month)
    if target_release is not None and target_release <= decision_date:
        return {
            "refused": True,
            "reason": (
                f"target month {target_year}-{target_month:02d}'s BLS release ({target_release}) "
                f"was already public by decision time ({decision_date}) — not a genuine forecast"
            ),
        }

    result = compute_core_cpi_probability(
        strike_type=market["strike_type"],
        floor_strike=market.get("floor_strike"),
        cap_strike=market.get("cap_strike"),
        target_month=target_month,
        as_of=decision_date,
    )
    if result.get("refused"):
        return result

    result["decision_timestamp"] = decision_timestamp
    result["target_month"] = f"{target_year}-{target_month:02d}"
    result["source_available_at"] = f"all included BLS values released on/before {decision_date.isoformat()}"
    return result


def build_economics_backtest(series_ticker: str = "KXCPICORE") -> tuple[list[CalibrationRecord], list[dict]]:
    records: list[CalibrationRecord] = []
    raw_rows = []
    markets = fetch_finalized_cpi_markets(series_ticker=series_ticker)
    for market in markets:
        try:
            result = compute_archived_cpi_probability(market)
        except Exception as exc:  # noqa: BLE001
            result = {"refused": True, "reason": f"error scoring this market: {exc}"}
        raw_rows.append({"market": market, "engine_result": result})
        if result.get("refused"):
            continue
        outcome = 1 if market["result"] == "yes" else 0
        record = CalibrationRecord(
            domain="economics",
            venue="kalshi",
            market_id=market["ticker"],
            question=market["title"],
            decision_timestamp=result["decision_timestamp"],
            resolution_timestamp=market.get("settlement_ts") or market.get("expiration_time"),
            oracle_prob=result["oracle_prob"],
            outcome=outcome,
            bucket=probability_bucket(result["oracle_prob"]),
            source_run=result["target_month"],
            source_available_at=result["source_available_at"],
            target_date=result["target_month"],
        )
        records.append(record)
    spf_records, spf_raw_rows = build_spf_core_cpi_backtest()
    records.extend(spf_records)
    raw_rows.extend(spf_raw_rows)
    return records, raw_rows


def _actual_core_cpi_q4q4_by_year() -> dict[int, float]:
    rows = fetch_core_cpi_series(start_year=2006)
    by_year: dict[int, list[float]] = {}
    for row in rows:
        if row["month"] in (10, 11, 12):
            by_year.setdefault(row["year"], []).append(float(row["value"]))
    actuals = {}
    for year, values in by_year.items():
        prev_values = by_year.get(year - 1)
        if len(values) == 3 and prev_values and len(prev_values) == 3:
            actuals[year] = (sum(values) / 3) / (sum(prev_values) / 3) * 100 - 100
    return actuals


def build_spf_core_cpi_backtest() -> tuple[list[CalibrationRecord], list[dict]]:
    """Official Philadelphia Fed SPF PRCCPI probability calibration.

    Each SPF row gives a 10-bin probability distribution for Q4/Q4 core CPI.
    We score every bin as a binary event against the realized BLS Q4/Q4 core
    CPI value. This produces many honest probability records from one official
    survey distribution without inventing pseudo-markets.
    """
    records: list[CalibrationRecord] = []
    raw_rows: list[dict] = []
    actuals = _actual_core_cpi_q4q4_by_year()
    spf_rows = economic_sources.fetch_spf_prccpi_rows()
    for row in spf_rows:
        actual = actuals.get(row.target_year)
        if actual is None:
            raw_rows.append(
                {
                    "source": "philadelphia_fed_spf_prccpi",
                    "spf_row": row,
                    "engine_result": {
                        "refused": True,
                        "reason": f"target year {row.target_year} does not have a full realized BLS Q4 yet",
                    },
                }
            )
            continue
        resolution = release_date_for(row.target_year, 12)
        for idx, probability in enumerate(row.probabilities):
            label = economic_sources.SPF_PRCCPI_BINS[idx][2]
            outcome = 1 if economic_sources.spf_bin_contains(idx, actual) else 0
            market_id = f"SPF-PRCCPI-{row.survey_year}Q{row.survey_quarter}-{row.horizon}-BIN{idx + 1}"
            result = {
                "refused": False,
                "oracle_prob": probability,
                "actual_core_cpi_q4q4": actual,
                "bin": label,
                "source_available_at": row.source_available_at,
                "method": "Philadelphia Fed SPF mean probability distribution for Q4/Q4 core CPI",
            }
            raw_rows.append(
                {
                    "source": "philadelphia_fed_spf_prccpi",
                    "spf_row": row,
                    "bin": label,
                    "engine_result": result,
                }
            )
            records.append(
                CalibrationRecord(
                    domain="economics",
                    venue="philadelphia_fed_spf",
                    market_id=market_id,
                    question=f"Core CPI Q4/Q4 inflation in {row.target_year}: {label}",
                    decision_timestamp=row.source_available_at,
                    resolution_timestamp=(resolution or date(row.target_year + 1, 1, 20)).isoformat(),
                    oracle_prob=probability,
                    outcome=outcome,
                    bucket=probability_bucket(probability),
                    source_run=f"SPF {row.survey_year}:Q{row.survey_quarter} {row.horizon}",
                    source_available_at=row.source_available_at,
                    target_date=str(row.target_year),
                )
            )
    return records, raw_rows
