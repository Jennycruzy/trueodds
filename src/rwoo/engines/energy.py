"""Conservative official-history energy probability engines."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timezone

from rwoo import economic_sources


def _calendar_year_ratios(series: list[tuple[date, float]], as_of: date,
                          target_year: int) -> list[tuple[int, float]]:
    """Independent historical remaining-year maxima at the same season point."""
    by_year: dict[int, list[tuple[date, float]]] = defaultdict(list)
    for day, value in series:
        if value > 0 and day.year < target_year:
            by_year[day.year].append((day, value))
    ratios = []
    for year, rows in sorted(by_year.items()):
        try:
            cutoff = date(year, as_of.month, as_of.day)
        except ValueError:
            cutoff = date(year, 2, 28)
        before = [(day, value) for day, value in rows if day <= cutoff]
        after = [value for day, value in rows if day > cutoff]
        if not before or not after or (cutoff - before[-1][0]).days > 7:
            continue
        ratios.append((year, max(after) / before[-1][1]))
    return ratios


def _hit_rate(ratios: list[tuple[int, float]], current: float, threshold: float) -> float:
    return sum(current * ratio > threshold for _year, ratio in ratios) / len(ratios)


def _wilson_interval(hits: int, total: int, z: float = 1.96) -> tuple[float, float]:
    p = hits / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return max(0.0, center - radius), min(1.0, center + radius)


def compute_henry_hub_annual_high_probability(
    strike_type: str, floor_strike: float | None, target_date_iso: str,
    *, target_year: int | None = None, series: list[tuple[date, float]] | None = None,
) -> dict:
    if strike_type != "greater" or floor_strike is None:
        return {"refused": True, "oracle_prob": None, "reason": "only annual-high greater-than contracts are supported"}
    series = series or economic_sources.fetch_fred_series("DHHNGSP")
    series = sorted((day, value) for day, value in series if value > 0)
    if len(series) < 750:
        return {"refused": True, "oracle_prob": None, "reason": f"insufficient Henry Hub daily history: {len(series)} rows"}
    target = date.fromisoformat(target_date_iso[:10])
    latest_date, current = series[-1]
    target_year = int(target_year or target.year)
    if latest_date.year != target_year:
        return {"refused": True, "oracle_prob": None, "reason": "annual-high model requires observations from the contract year"}
    if target <= latest_date:
        return {"refused": True, "oracle_prob": None, "reason": "target date is not after the latest source observation"}
    year_to_date = [value for day, value in series if day.year == target_year and day <= latest_date]
    if not year_to_date:
        return {"refused": True, "oracle_prob": None, "reason": "no observations exist for the contract year"}
    observed_max = max(year_to_date)
    already_observed = observed_max > float(floor_strike)
    if already_observed:
        probability = 1.0
        models = {"already_observed": 1.0}
        sample_count = 0
        prob_low = prob_high = 1.0
    else:
        ratios = _calendar_year_ratios(series, latest_date, target_year)
        recent_ratios = ratios[-10:]
        if len(ratios) < 10 or len(recent_ratios) < 5:
            return {"refused": True, "oracle_prob": None,
                    "reason": f"insufficient independent seasonal analog years: {len(ratios)}"}
        full = _hit_rate(ratios, current, float(floor_strike))
        recent = _hit_rate(recent_ratios, current, float(floor_strike))
        models = {"official_full_history_same_date_years": full,
                  "official_recent_10y_same_date_years": recent}
        probability = (full + recent) / 2
        sample_count = len(ratios)
        hits = sum(current * ratio > float(floor_strike) for _year, ratio in ratios)
        interval = _wilson_interval(hits, sample_count)
        prob_low = min(interval[0], full, recent)
        prob_high = max(interval[1], full, recent)
    values = list(models.values())
    agreement = max(values) - min(values)
    return {
        "oracle_prob": probability, "confidence": max(0.55, min(0.58, 0.58 - agreement)),
        "prob_low": prob_low, "prob_high": prob_high, "per_model_prob": models,
        "per_source_values": {
            "source": "EIA Henry Hub spot price DHHNGSP via the Federal Reserve FRED mirror",
            "latest_observation": latest_date.isoformat(), "latest_price_usd_per_mmbtu": current,
            "contract_year": target_year, "year_to_date_maximum": observed_max,
            "threshold": float(floor_strike), "target_date": target.isoformat(),
            "history_start": series[0][0].isoformat(), "independent_analog_years": sample_count,
        },
        "method": (
            "official daily Henry Hub history -> contract-year observed maximum, then independent "
            "same-calendar-date historical remaining-year maximum ratios; full-history and recent-10-year views are averaged"
        ),
        # Once the barrier has been observed, later publication lag cannot
        # reverse the outcome. For an unhit barrier, retain observation-date
        # freshness so a lagging series still fails closed.
        "data_freshness": (
            datetime.now(timezone.utc).isoformat() if already_observed
            else datetime.combine(latest_date, datetime.min.time(), tzinfo=timezone.utc).isoformat()
        ),
        "base_rate": probability, "refused": False,
    }


def backtest_henry_hub_annual_high(
    series: list[tuple[date, float]], *, thresholds: list[float],
    as_of_month: int = 7, as_of_day: int = 13,
    closing_prices: dict[tuple[int, float], float] | None = None,
) -> dict:
    """Leakage-safe rolling-year validation of the annual-high engine.

    Each evaluation uses only complete prior years plus observations available
    through the configured as-of date in the evaluation year. Closing market
    prices are optional and remain explicitly unavailable when not captured.
    """
    series = sorted((day, value) for day, value in series if value > 0)
    closing_prices = closing_prices or {}
    years = sorted({day.year for day, _value in series})
    rows = []
    for year in years:
        try:
            cutoff = date(year, as_of_month, as_of_day)
        except ValueError:
            cutoff = date(year, 2, 28)
        full_year = [value for day, value in series if day.year == year]
        available = [(day, value) for day, value in series
                     if day.year < year or (day.year == year and day <= cutoff)]
        if not full_year or not available or available[-1][0].year != year:
            continue
        prior_maxima = {
            prior: max(value for day, value in series if day.year == prior)
            for prior in years if prior < year
        }
        if len(prior_maxima) < 10:
            continue
        for threshold in thresholds:
            result = compute_henry_hub_annual_high_probability(
                "greater", float(threshold), date(year, 12, 31).isoformat(),
                target_year=year, series=available,
            )
            if result.get("refused"):
                continue
            outcome = int(max(full_year) > float(threshold))
            naive = sum(value > float(threshold) for value in prior_maxima.values()) / len(prior_maxima)
            market = closing_prices.get((year, float(threshold)))
            if market is not None and not 0 <= market <= 1:
                market = None
            rows.append({
                "year": year, "threshold": float(threshold), "outcome": outcome,
                "oracle_probability": result["oracle_prob"],
                "naive_prior_year_probability": naive,
                "closing_market_probability": market,
                "training_years": len(prior_maxima),
            })
    oracle_brier = (sum((row["oracle_probability"] - row["outcome"]) ** 2 for row in rows) / len(rows)) if rows else None
    naive_brier = (sum((row["naive_prior_year_probability"] - row["outcome"]) ** 2 for row in rows) / len(rows)) if rows else None
    market_rows = [row for row in rows if row["closing_market_probability"] is not None]
    market_brier = (sum((row["closing_market_probability"] - row["outcome"]) ** 2 for row in market_rows) / len(market_rows)) if market_rows else None
    return {
        "method": "rolling independent calendar years; no evaluation-year future observations enter its forecast",
        "independent_evaluation_years": len({row["year"] for row in rows}),
        "contract_rows": len(rows), "oracle_brier": oracle_brier,
        "naive_prior_year_brier": naive_brier,
        "beats_naive": bool(rows and oracle_brier is not None and naive_brier is not None and oracle_brier < naive_brier),
        "closing_market_rows": len(market_rows), "closing_market_brier": market_brier,
        "beats_closing_market": None if market_brier is None else oracle_brier < market_brier,
        "promotion_eligible": bool(rows and market_rows and oracle_brier < naive_brier and oracle_brier < market_brier),
        "rows": rows,
    }
