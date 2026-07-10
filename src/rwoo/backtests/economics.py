"""Economics calibration backtest with a no-lookahead proof.

Real settled Kalshi core-CPI markets, scored against what the economics
engine would have said using ONLY BLS values whose real publication date
(not reference month) was already public as of the market's decision time.
No sample-size cap — every real settled KXCPICORE market is attempted.
"""
from __future__ import annotations

import time
import math
import statistics
from datetime import date, datetime, timedelta, timezone

import httpx

from rwoo.calibration import CalibrationRecord, probability_bucket
from rwoo import economic_sources
from rwoo.engines.economics import (
    compute_core_cpi_probability,
    compute_headline_cpi_annual_probability,
    compute_headline_cpi_monthly_probability,
    fetch_core_cpi_series,
    fetch_headline_cpi_sa_series,
    fetch_headline_cpi_series,
    month_over_month_changes,
    release_date_for,
    year_over_year_changes,
)
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

    included_rows = fetch_core_cpi_series(as_of=decision_date)
    included_release_dates = [
        release_date_for(row["year"], row["month"])
        for row in included_rows
        if release_date_for(row["year"], row["month"]) is not None
    ]
    if not included_release_dates:
        return {"refused": True, "reason": "no dated BLS observations were public by decision time"}
    result["decision_timestamp"] = decision_timestamp
    result["target_month"] = f"{target_year}-{target_month:02d}"
    result["source_available_at"] = max(included_release_dates).isoformat()
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
    gdp_records, gdp_raw_rows = build_spf_annual_gdp_backtest()
    records.extend(gdp_records)
    raw_rows.extend(gdp_raw_rows)
    gdpnow_records, gdpnow_raw_rows = build_gdpnow_quarterly_backtest()
    records.extend(gdpnow_records)
    raw_rows.extend(gdpnow_raw_rows)
    for builder in (build_headline_cpi_monthly_baseline, build_headline_cpi_annual_baseline):
        baseline_records, baseline_raw_rows = builder()
        records.extend(baseline_records)
        raw_rows.extend(baseline_raw_rows)
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


def _bin_contains(bounds: tuple[float | None, float | None, str], value: float) -> bool:
    low, high, _label = bounds
    if low is None:
        return value < float(high)
    if high is None:
        return value >= low
    return low <= value <= high


def build_spf_annual_gdp_backtest() -> tuple[list[CalibrationRecord], list[dict]]:
    """Score dated SPF PRGDP densities against realized annual real-GDP growth.

    PRGDP and FRED/BEA series A191RL1A225NBEA use the same annual-average over
    annual-average definition. Only the decoded 2024:Q2+ SPF bin regime is
    used. These records validate the SPF annual-GDP density path, not GDPNow.
    """
    actuals = {d.year: value for d, value in economic_sources.fetch_fred_series("A191RL1A225NBEA")}
    records: list[CalibrationRecord] = []
    raw_rows: list[dict] = []
    for row in economic_sources.fetch_spf_density_rows("PRGDP"):
        actual = actuals.get(row.target_year)
        if actual is None:
            raw_rows.append({
                "source": "philadelphia_fed_spf_prgdp",
                "spf_row": row,
                "engine_result": {"refused": True, "reason": f"no realized annual GDP for {row.target_year}"},
            })
            continue
        resolution = date(row.target_year + 1, 1, 31)
        for idx, probability in enumerate(row.probabilities):
            label = economic_sources.SPF_PRGDP_BINS[idx][2]
            result = {
                "refused": False,
                "oracle_prob": probability,
                "actual_annual_real_gdp_growth": actual,
                "source_available_at": row.source_available_at,
                "validation_scope": "SPF annual-GDP density only; does not validate GDPNow",
            }
            raw_rows.append({"source": "philadelphia_fed_spf_prgdp", "spf_row": row, "bin": label, "engine_result": result})
            records.append(CalibrationRecord(
                domain="economics",
                venue="philadelphia_fed_spf",
                market_id=f"SPF-PRGDP-{row.survey_year}Q{row.survey_quarter}-{row.horizon}-BIN{idx + 1}",
                question=f"Annual-average real GDP growth in {row.target_year}: {label}",
                decision_timestamp=row.source_available_at,
                resolution_timestamp=resolution.isoformat(),
                oracle_prob=probability,
                outcome=int(_bin_contains(economic_sources.SPF_PRGDP_BINS[idx], actual)),
                bucket=probability_bucket(probability),
                source_run=f"SPF {row.survey_year}:Q{row.survey_quarter} {row.horizon}",
                source_available_at=row.source_available_at,
                target_date=str(row.target_year),
            ))
    return records, raw_rows


def build_gdpnow_quarterly_backtest() -> tuple[list[CalibrationRecord], list[dict]]:
    """Score official dated GDPNow forecasts against BEA advance estimates."""
    records, raw_rows = [], []
    thresholds = (-2.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
    forecasts = economic_sources.fetch_gdpnow_track_record()
    by_quarter: dict[str, list[float]] = {}
    for row in forecasts:
        path = by_quarter.setdefault(row.quarter_label, [])
        path.append(row.nowcast)
        sigma = max(0.5, statistics.pstdev(path) if len(path) > 1 else 1.0)
        for threshold in thresholds:
            z = (threshold - row.nowcast) / sigma
            probability = 1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
            result = {"refused": False, "oracle_prob": probability, "source_available_at": row.forecast_date.isoformat(),
                      "validation_scope": "official archived GDPNow forecast versus BEA advance estimate"}
            raw_rows.append({"source": "atlanta_fed_gdpnow_track_record", "forecast": row, "engine_result": result})
            records.append(CalibrationRecord(
                domain="economics", venue="atlanta_fed_gdpnow",
                market_id=f"GDPNOW-{row.quarter_label}-{row.forecast_date}-GT-{threshold:.1f}",
                question=f"BEA advance real GDP for {row.quarter_label} greater than {threshold:.1f}% SAAR",
                decision_timestamp=row.forecast_date.isoformat(), resolution_timestamp=row.publication_date.isoformat(),
                oracle_prob=probability, outcome=int(row.advance_estimate > threshold),
                bucket=probability_bucket(probability), source_run=f"GDPNow {row.forecast_date}",
                source_available_at=row.forecast_date.isoformat(), target_date=row.quarter_label,
            ))
    return records, raw_rows


_MONTHLY_THRESHOLDS = (-0.1, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6)
_ANNUAL_THRESHOLDS = (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0)


def _build_headline_cpi_baseline(monthly: bool) -> tuple[list[CalibrationRecord], list[dict]]:
    """Rolling history-only CPI baseline with an explicit limited claim.

    The predictor is cut off the day before the target release. Current BLS
    history is used, so SA revisions can affect the monthly inputs. No
    Cleveland Fed nowcast is supplied when ``as_of`` is set; consequently
    these records must never justify the live forward-source confidence cap.
    """
    rows = fetch_headline_cpi_sa_series() if monthly else fetch_headline_cpi_series()
    changes = month_over_month_changes(rows) if monthly else year_over_year_changes(rows)
    thresholds = _MONTHLY_THRESHOLDS if monthly else _ANNUAL_THRESHOLDS
    minimum_history = 36 if monthly else 60
    records: list[CalibrationRecord] = []
    raw_rows: list[dict] = []
    for target in changes:
        release = release_date_for(target["year"], target["month"])
        if release is None:
            continue
        decision = release - timedelta(days=1)
        available_rows = [r for r in rows if (release_date_for(r["year"], r["month"]) or date.max) <= decision]
        available_changes = month_over_month_changes(available_rows) if monthly else year_over_year_changes(available_rows)
        if len(available_changes) < minimum_history:
            continue
        latest_source_release = max(release_date_for(r["year"], r["month"]) for r in available_rows)
        for threshold in thresholds:
            compute = compute_headline_cpi_monthly_probability if monthly else compute_headline_cpi_annual_probability
            result = compute("greater", threshold, None, target_month=target["month"], as_of=decision)
            result["validation_scope"] = (
                "history-only current-vintage BLS baseline; Cleveland Fed forward source absent and not validated"
            )
            result["source_available_at"] = latest_source_release.isoformat()
            raw_rows.append({"source": "bls_headline_cpi_history_baseline", "target": target, "engine_result": result})
            if result.get("refused"):
                continue
            probability = result["oracle_prob"]
            family = "monthly" if monthly else "annual"
            records.append(CalibrationRecord(
                domain="economics",
                venue="bls_history_baseline",
                market_id=f"BLS-HEADLINE-{family.upper()}-{target['year']}{target['month']:02d}-GT-{threshold:.1f}",
                question=f"Headline CPI {family} change for {target['year']}-{target['month']:02d} greater than {threshold:.1f}%",
                decision_timestamp=decision.isoformat(),
                resolution_timestamp=release.isoformat(),
                oracle_prob=probability,
                outcome=int(target["reported_single_decimal"] > threshold),
                bucket=probability_bucket(probability),
                source_run="BLS history-only rolling baseline (current vintage)",
                source_available_at=latest_source_release.isoformat(),
                target_date=f"{target['year']}-{target['month']:02d}",
            ))
    return records, raw_rows


def build_headline_cpi_monthly_baseline() -> tuple[list[CalibrationRecord], list[dict]]:
    return _build_headline_cpi_baseline(monthly=True)


def build_headline_cpi_annual_baseline() -> tuple[list[CalibrationRecord], list[dict]]:
    return _build_headline_cpi_baseline(monthly=False)


def economics_no_lookahead_checks(records: list[CalibrationRecord]) -> list[dict]:
    """Return a timestamp proof for every economics calibration record."""
    def parse_utc(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    checks = []
    for record in records:
        try:
            source = parse_utc(record.source_available_at)
            decision = parse_utc(record.decision_timestamp)
            resolution = parse_utc(record.resolution_timestamp)
            passed = source <= decision < resolution
            reason = None if passed else "required source_available_at <= decision < resolution"
        except (TypeError, ValueError) as exc:
            passed = False
            reason = f"unparseable timestamp: {exc}"
        checks.append({"market_id": record.market_id, "passed": passed, "reason": reason})
    return checks
