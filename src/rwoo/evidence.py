"""Continuous precommitted forecast evidence and resolution pipeline."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from rwoo.calibration import (
    WEATHER_V3_CALIBRATION_GAMMA, WEATHER_V3_SOURCE_MODEL, CalibrationRecord,
    calibration_breakdown, fit_power_recalibration, grouped_walk_forward,
    power_transform, probability_bucket,
)
from rwoo.identity import MODEL_VERSIONS
from rwoo.receipts import AppendOnlyLedger, hash_hex
from rwoo.scanner import scan_opportunities
from rwoo.official_outcomes import event_happened, resolve_weather_from_noaa

DEFAULT_LEDGER = Path(os.environ.get(
    "RWOO_EVIDENCE_LEDGER_PATH", "data/receipts/forecast_evidence.jsonl",
))
DEFAULT_REPORT = Path(os.environ.get(
    "RWOO_CALIBRATION_REPORT_PATH", "data/public/calibration_report_latest.json",
))
DEFAULT_REPORT_MD = Path(os.environ.get(
    "RWOO_CALIBRATION_REPORT_MD_PATH", str(DEFAULT_REPORT.with_suffix(".md")),
))
DEFAULT_BACKLOG = Path(os.environ.get(
    "RWOO_EVIDENCE_BACKLOG_PATH", str(DEFAULT_REPORT.with_name("evidence_backlog_latest.json")),
))
KALSHI_MARKET_URL = "https://api.elections.kalshi.com/trade-api/v2/markets/{market_id}"
POLYMARKET_URL = "https://gamma-api.polymarket.com/markets/{market_id}"
LIMITLESS_URL = "https://api.limitless.exchange/markets/{market_id}"
WEATHER_PRODUCTION_MODEL = MODEL_VERSIONS["weather.temperature"]
CHECKPOINTS = (30, 100, 250, 500)
MIN_BAND_GROUPS = 30
MIN_DRIFT_GROUPS = 20
MIN_CLOSING_PRICE_GROUP_COVERAGE = 0.80


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _datetime_or_none(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _day(timestamp: str) -> str:
    return timestamp[:10]


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
        return number if 0 <= number <= 1 else None
    except (TypeError, ValueError):
        return None


def _resolution_due(payload: dict[str, Any], now: datetime | None = None) -> bool:
    """Avoid polling a venue before its declared resolution time.

    Legacy rows or malformed timestamps are still queried so a bad historical
    value cannot strand an otherwise resolvable forecast forever.
    """
    raw = payload.get("resolution_time")
    if not raw:
        return True
    try:
        due = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return True
    return due <= (now or datetime.now(timezone.utc))


def _prospective_eligible(record: dict[str, Any]) -> tuple[bool, str | None]:
    """Reject forecasts created after the underlying event can be known."""
    if record.get("family") not in {"weather.temperature", "weather.precipitation"}:
        return True, None
    identity = record.get("event_identity") or {}
    target = identity.get("target_date")
    created = record.get("fetched_at")
    try:
        if datetime.fromisoformat(str(created).replace("Z", "+00:00")).date() > datetime.fromisoformat(str(target)[:10]).date():
            return False, "daily weather target date had elapsed before forecast creation"
    except (TypeError, ValueError):
        return False, "daily weather forecast lacks a valid target or creation date"
    return True, None


def _quote_before_cutoff(quote: dict[str, Any], forecast: dict[str, Any] | None) -> bool:
    observed = quote.get("observed_at")
    cutoffs = [quote.get("trading_close_time")]
    if forecast:
        cutoffs.append(forecast.get("resolution_time"))
    try:
        observed_at = datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return False
    for raw in cutoffs:
        if not raw:
            continue
        try:
            cutoff = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if cutoff.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if observed_at > cutoff:
            return False
    return True


def _band_gate(records: list[CalibrationRecord]) -> dict[str, Any]:
    rows = calibration_breakdown(records, width=.1)["overall"]["reliability"] if records else []
    groups_by_band: dict[str, set[str]] = {}
    for record in records:
        groups_by_band.setdefault(probability_bucket(record.oracle_prob, .1), set()).add(record.source_run)
    bands = []
    for row in rows:
        groups = len(groups_by_band.get(row["bucket"], set()))
        gap = abs(row["mean_predicted"] - row["actual_hit_rate"])
        bands.append({**row, "independent_event_groups": groups, "calibration_gap": gap,
                      "adequately_sampled": groups >= MIN_BAND_GROUPS,
                      "passes": groups < MIN_BAND_GROUPS or gap <= .15})
    adequate = [row for row in bands if row["adequately_sampled"]]
    return {"minimum_independent_groups_per_band": MIN_BAND_GROUPS, "bands": bands,
            "adequately_sampled_bands": len(adequate),
            "all_adequately_sampled_bands_pass": all(row["passes"] for row in adequate)}


def _market_performance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"contract_rows": 0, "oracle_brier": None, "market_brier": None,
                "oracle_brier_advantage": None, "closing_price_rows": 0,
                "closing_market_brier": None, "closing_price_event_groups": 0,
                "closing_price_group_coverage": 0.0,
                "closing_subset_oracle_brier": None,
                "closing_oracle_brier_advantage": None,
                "paper_strategy": {"selection": "highest expected-profit actionable contract per independent event",
                                   "trades": 0, "wins": 0, "net_pnl_per_one_contract": 0.0,
                                   "return_on_cost": None, "positive_after_fees_and_spread": False,
                                   "trades_detail": []}}
    oracle_brier = sum((r["forecast"]["oracle_prob"] - r["resolution"]["outcome"]) ** 2 for r in rows) / len(rows)
    market_rows = [r for r in rows if _float_or_none(r["forecast"].get("market_implied_prob")) is not None]
    market_brier = (sum((r["forecast"]["market_implied_prob"] - r["resolution"]["outcome"]) ** 2
                        for r in market_rows) / len(market_rows)) if market_rows else None
    closing_rows = [r for r in rows if _float_or_none(r["resolution"].get("closing_market_implied_prob")) is not None]
    closing_brier = (sum((r["resolution"]["closing_market_implied_prob"] - r["resolution"]["outcome"]) ** 2
                         for r in closing_rows) / len(closing_rows)) if closing_rows else None
    closing_oracle_brier = (sum((r["forecast"]["oracle_prob"] - r["resolution"]["outcome"]) ** 2
                                for r in closing_rows) / len(closing_rows)) if closing_rows else None
    all_groups = {r["forecast"]["event_group_id"] for r in rows}
    closing_groups = {r["forecast"]["event_group_id"] for r in closing_rows}
    # One paper position per independent event prevents threshold-rich events
    # from masquerading as many independent profitable bets.
    candidates: dict[str, dict[str, Any]] = {}
    for row in rows:
        f, outcome = row["forecast"], row["resolution"]["outcome"]
        execution = f.get("execution") or {}
        if not f.get("actionable") or f.get("side") not in {"YES", "NO"}:
            continue
        entry = _float_or_none(execution.get("entry_price"))
        fee = float(execution.get("estimated_fee_per_contract") or 0)
        if entry is None:
            continue
        won = outcome == 1 if f["side"] == "YES" else outcome == 0
        pnl = (1.0 if won else 0.0) - entry - fee
        item = {"event_group_id": f["event_group_id"], "market_id": f["market_id"], "side": f["side"],
                "entry_price": entry, "fees": fee, "outcome": outcome, "net_pnl": pnl,
                "expected_profit": execution.get("expected_profit_per_contract")}
        old = candidates.get(f["event_group_id"])
        if old is None or float(item["expected_profit"] or -1) > float(old["expected_profit"] or -1):
            candidates[f["event_group_id"]] = item
    trades = list(candidates.values())
    net = sum(t["net_pnl"] for t in trades)
    cost = sum(t["entry_price"] + t["fees"] for t in trades)
    return {"contract_rows": len(rows), "market_benchmark_rows": len(market_rows),
            "oracle_brier": oracle_brier, "market_brier": market_brier,
            "oracle_brier_advantage": market_brier - oracle_brier if market_brier is not None else None,
            "closing_price_rows": len(closing_rows), "closing_market_brier": closing_brier,
            "closing_subset_oracle_brier": closing_oracle_brier,
            "closing_oracle_brier_advantage": (
                closing_brier - closing_oracle_brier if closing_brier is not None else None
            ),
            "closing_price_event_groups": len(closing_groups),
            "closing_price_group_coverage": len(closing_groups) / len(all_groups) if all_groups else 0.0,
            "paper_strategy": {"selection": "highest expected-profit actionable contract per independent event",
                               "trades": len(trades), "wins": sum(t["net_pnl"] > 0 for t in trades),
                               "net_pnl_per_one_contract": net, "return_on_cost": net / cost if cost else None,
                               "positive_after_fees_and_spread": bool(trades and net > 0), "trades_detail": trades}}


def _segment_drift(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dimensions: dict[str, dict[str, list[dict[str, Any]]]] = {k: {} for k in ("station", "metric", "forecast_horizon", "weather_regime")}
    for row in rows:
        f = row["forecast"]; identity = f.get("event_identity") or {}
        try:
            target = datetime.fromisoformat(str(identity.get("target_date")))
            created = datetime.fromisoformat(f["forecast_created_at"].replace("Z", "+00:00")).replace(tzinfo=None)
            days = (target - created).total_seconds() / 86400
            horizon = "same_day" if days < 1 else "one_day" if days < 2 else "two_plus_days"
        except (TypeError, ValueError):
            horizon = "unknown"
        try:
            month = int(str(identity.get("target_date"))[5:7]); regime = "warm_season" if 4 <= month <= 9 else "cool_season"
        except (TypeError, ValueError):
            regime = "unknown"
        values = {"station": identity.get("station_ghcnd_id") or identity.get("location") or "unknown",
                  "metric": identity.get("metric") or "unknown", "forecast_horizon": horizon,
                  "weather_regime": regime}
        for dimension, value in values.items(): dimensions[dimension].setdefault(str(value), []).append(row)
    output = {}
    alerts = []
    for dimension, segments in dimensions.items():
        output[dimension] = []
        for name, values in sorted(segments.items()):
            groups = len({v["forecast"]["event_group_id"] for v in values})
            brier = sum((v["forecast"]["oracle_prob"] - v["resolution"]["outcome"]) ** 2 for v in values) / len(values)
            item = {"segment": name, "independent_event_groups": groups, "contract_rows": len(values),
                    "brier_score": brier, "adequately_sampled": groups >= MIN_DRIFT_GROUPS,
                    "alert": groups >= MIN_DRIFT_GROUPS and brier > .20}
            output[dimension].append(item)
            if item["alert"]: alerts.append({"dimension": dimension, **item})
    return {"minimum_groups_per_segment": MIN_DRIFT_GROUPS, "dimensions": output,
            "alerts": alerts, "passes": not alerts}


class EvidenceStore:
    def __init__(self, path: str | Path = DEFAULT_LEDGER):
        self.ledger = AppendOnlyLedger(path)

    def _records(self, record_type: str | None = None):
        rows = self.ledger.read_records()
        return [row for row in rows if record_type is None or row.record_type == record_type]

    def backlog(
        self,
        *,
        family: str | None = None,
        model_version: str | None = None,
        now: datetime | None = None,
        latest_report: dict[str, Any] | None = None,
        max_report_age_hours: float = 7.0,
    ) -> dict[str, Any]:
        """Summarize evidence progress without polling venues or writing records.

        This is deliberately separate from ``report``: operators can diagnose a
        resolution backlog without refreshing artifacts, touching the model, or
        changing anything served by the public API.
        """
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        records = self._records()

        def selected(payload: dict[str, Any]) -> bool:
            return (
                (family is None or payload.get("family") == family)
                and (model_version is None or payload.get("model_version") == model_version)
            )

        precommits = {
            row.payload["snapshot_key"]: row.payload
            for row in records
            if row.record_type == "forecast_precommit"
            and row.payload.get("snapshot_key")
            and selected(row.payload)
        }
        resolutions = {
            row.payload["snapshot_key"]: row.payload
            for row in records
            if row.record_type == "forecast_resolution"
            and row.payload.get("snapshot_key") in precommits
        }
        verified = {
            row.payload["snapshot_key"]: row.payload
            for row in records
            if row.record_type == "official_source_verification"
            and row.payload.get("snapshot_key") in precommits
            and row.payload.get("status") == "resolved"
        }
        selected_snapshot_keys = set(precommits)
        selected_market_keys = {
            (
                str(payload.get("venue") or ""),
                str(payload.get("market_id") or ""),
                str(payload.get("model_version") or ""),
            )
            for payload in precommits.values()
        }
        quotes = [
            row.payload for row in records
            if row.record_type == "market_quote_snapshot"
            and (
                row.payload.get("forecast_snapshot_key") in selected_snapshot_keys
                or (
                    str(row.payload.get("venue") or ""),
                    str(row.payload.get("market_id") or ""),
                    str(row.payload.get("model_version") or model_version or ""),
                ) in selected_market_keys
                or (
                    not row.payload.get("model_version")
                    and any(
                        venue == str(row.payload.get("venue") or "")
                        and market_id == str(row.payload.get("market_id") or "")
                        for venue, market_id, _version in selected_market_keys
                    )
                )
            )
        ]
        quotes_by_snapshot: dict[str, list[dict[str, Any]]] = {}
        quotes_by_market: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for quote in quotes:
            snapshot_key = quote.get("forecast_snapshot_key")
            if snapshot_key:
                quotes_by_snapshot.setdefault(str(snapshot_key), []).append(quote)
            market_key = (str(quote.get("venue") or ""), str(quote.get("market_id") or ""))
            quotes_by_market.setdefault(market_key, []).append(quote)

        unresolved = [payload for key, payload in precommits.items() if key not in resolutions]
        due = [payload for payload in unresolved if _resolution_due(payload, now)]
        future = [payload for payload in unresolved if not _resolution_due(payload, now)]
        resolved_payloads = list(resolutions.values())
        waiting_official = [
            precommits[key] for key in resolutions
            if precommits[key].get("domain") == "weather" and key not in verified
        ]
        verified_payloads = [precommits[key] for key in verified]

        report_created_at = _datetime_or_none((latest_report or {}).get("created_at"))
        report_age_hours = (
            (now - report_created_at).total_seconds() / 3600 if report_created_at else None
        )
        due_at_last_report = [
            payload for payload in due
            if report_created_at is not None
            and (_datetime_or_none(payload.get("resolution_time")) or datetime.min.replace(tzinfo=timezone.utc))
            <= report_created_at
        ]

        quote_keys: set[str] = set()
        targeted_keys: set[str] = set()
        for key, forecast in precommits.items():
            matching = [
                quote for quote in (
                    quotes_by_snapshot.get(key, [])
                    + quotes_by_market.get((str(forecast.get("venue") or ""), str(forecast.get("market_id") or "")), [])
                )
                if (
                    quote.get("forecast_snapshot_key") == key
                    or (
                        quote.get("venue") == forecast.get("venue")
                        and quote.get("market_id") == forecast.get("market_id")
                    )
                )
                and _quote_before_cutoff(quote, forecast)
            ]
            if matching:
                quote_keys.add(key)
            if any(
                quote.get("capture_mode") == "near-close"
                or quote.get("quote_source") == "targeted final-hour venue quote"
                for quote in matching
            ):
                targeted_keys.add(key)

        closing_keys = {
            key for key, payload in resolutions.items()
            if _float_or_none(payload.get("closing_market_implied_prob")) is not None
        }

        def summary(payloads: list[dict[str, Any]]) -> dict[str, int]:
            return {
                "contract_rows": len(payloads),
                "independent_event_groups": len({
                    str(payload.get("event_group_id")) for payload in payloads
                    if payload.get("event_group_id")
                }),
            }

        def oldest(payloads: list[dict[str, Any]]) -> dict[str, Any] | None:
            dated = [
                (timestamp, payload)
                for payload in payloads
                if (timestamp := _datetime_or_none(payload.get("forecast_created_at"))) is not None
            ]
            if not dated:
                return None
            timestamp, payload = min(dated, key=lambda item: item[0])
            return {
                "snapshot_key": payload.get("snapshot_key"),
                "event_group_id": payload.get("event_group_id"),
                "venue": payload.get("venue"),
                "market_id": payload.get("market_id"),
                "forecast_created_at": timestamp.isoformat(),
                "resolution_time": payload.get("resolution_time"),
            }

        warnings = []
        if report_created_at is None:
            warnings.append("latest calibration report is unavailable or lacks a valid created_at timestamp")
        elif report_age_hours is not None and report_age_hours > max_report_age_hours:
            warnings.append(
                f"latest calibration report is stale ({report_age_hours:.1f}h > {max_report_age_hours:.1f}h)"
            )
        if due_at_last_report:
            warnings.append(
                f"{len(due_at_last_report)} due forecast(s) remained unresolved after the latest evidence report"
            )
        if waiting_official:
            warnings.append(
                f"{len(waiting_official)} resolved weather forecast(s) still await official-source verification"
            )

        latest_ledger_write = max(
            (_datetime_or_none(row.created_at) for row in records), default=None,
            key=lambda value: value or datetime.min.replace(tzinfo=timezone.utc),
        )
        return {
            "generated_at": now.isoformat(),
            "status": "attention" if warnings else "ok",
            "filters": {"family": family, "model_version": model_version},
            "precommitted": summary(list(precommits.values())),
            "waiting_for_resolution_time": summary(future),
            "eligible_to_resolve": summary(due),
            "eligible_at_last_evidence_run": summary(due_at_last_report),
            "venue_resolved": summary(resolved_payloads),
            "waiting_for_official_source": summary(waiting_official),
            "officially_verified": summary(verified_payloads),
            "quote_coverage": {
                "pre_cutoff_quote_contracts": len(quote_keys),
                "pre_cutoff_quote_rate": len(quote_keys) / len(precommits) if precommits else 0.0,
                "targeted_final_hour_contracts": len(targeted_keys),
                "resolved_with_closing_quote_contracts": len(closing_keys),
                "resolved_with_closing_quote_rate": len(closing_keys) / len(resolutions) if resolutions else 0.0,
            },
            "oldest_unresolved_forecast": oldest(unresolved),
            "oldest_eligible_forecast": oldest(due),
            "last_successful_evidence_report": report_created_at.isoformat() if report_created_at else None,
            "report_age_hours": report_age_hours,
            "latest_ledger_write": latest_ledger_write.isoformat() if latest_ledger_write else None,
            "warnings": warnings,
            "ledger_verification": self.ledger.verify(),
        }

    def collect_scan(self, scan: dict[str, Any]) -> dict[str, Any]:
        existing = {
            row.payload["snapshot_key"]
            for row in self._records("forecast_precommit")
            if "snapshot_key" in row.payload
        }
        existing_quotes = {
            row.payload["quote_key"] for row in self._records("market_quote_snapshot")
            if "quote_key" in row.payload
        }
        appended = skipped = quotes_appended = prospective_ineligible_skipped = 0
        pending_records: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []
        for record in scan["top"]:
            if record.get("oracle_prob") is None:
                continue
            eligible, _reason = _prospective_eligible(record)
            if not eligible:
                prospective_ineligible_skipped += 1
                continue
            forecast_at = record["fetched_at"]
            snapshot_key = ":".join(
                (record["venue"], record["market_id"], record["model_version"], _day(forecast_at))
            )
            quote_key = ":".join((snapshot_key, forecast_at[:13]))
            if quote_key not in existing_quotes:
                quote_payload = {
                    "quote_key": quote_key, "forecast_snapshot_key": snapshot_key,
                    "event_group_id": record["event_group_id"], "venue": record["venue"],
                    "market_id": record["market_id"], "model_version": record["model_version"],
                    "observed_at": forecast_at, "market_implied_prob": record["implied_prob"],
                    "spread": record["spread"], "execution": record.get("execution"),
                    "trading_close_time": record.get("trading_close_time"),
                    "event_target_date": (record.get("event_identity") or {}).get("target_date"),
                    "yes_bid": (record.get("execution") or {}).get("yes_bid"),
                    "yes_ask": (record.get("execution") or {}).get("yes_ask"),
                    "last_trade": None, "depth": {"available": False, "source": "scanner artifact"},
                    "quote_source": "six-hour evidence scan",
                    "raw_response_hash": hash_hex(record),
                    "raw_response_hash_scope": "normalized_scan_record",
                }
                pending_records.append(("market_quote_snapshot", quote_payload, None))
                existing_quotes.add(quote_key)
                quotes_appended += 1
            if snapshot_key in existing:
                skipped += 1
                continue
            payload = {
                "snapshot_key": snapshot_key,
                "event_group_id": record["event_group_id"],
                "event_identity": record["event_identity"],
                "venue": record["venue"],
                "market_id": record["market_id"],
                "venue_resolution_id": record.get("venue_resolution_id") or record["market_id"],
                "question": record["question"],
                "domain": record["domain"],
                "family": record["family"],
                "shape": record["shape"],
                "model_version": record["model_version"],
                "forecast_created_at": forecast_at,
                "resolution_time": record["resolution_time"],
                "resolution_rule": record["resolution_rule"],
                "resolution_rule_hash": hash_hex(record["resolution_rule"]),
                "resolution_source": record["resolution_source"],
                "oracle_prob": record["oracle_prob"],
                "prob_low": record["prob_low"],
                "prob_high": record["prob_high"],
                "confidence": record["confidence"],
                "market_implied_prob": record["implied_prob"],
                "spread": record["spread"],
                "trading_close_time": record.get("trading_close_time"),
                "actionable": record["actionable"],
                "side": record["side"],
                "execution": record.get("execution"),
                "why": record.get("why"),
            }
            pending_records.append(("forecast_precommit", payload, None))
            existing.add(snapshot_key)
            appended += 1
        self.ledger.append_many(pending_records)
        return {"appended": appended, "duplicates_skipped": skipped,
                "prospective_ineligible_skipped": prospective_ineligible_skipped,
                "quote_snapshots_appended": quotes_appended, "ledger": self.ledger.verify()}

    def resolve_pending(self, client: httpx.Client | None = None) -> dict[str, Any]:
        own_client = client is None
        client = client or httpx.Client(timeout=20)
        precommits = self._records("forecast_precommit")
        quote_snapshots: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for quote in self._records("market_quote_snapshot"):
            market_key = (str(quote.payload.get("venue") or ""), str(quote.payload.get("market_id") or ""))
            if all(market_key):
                quote_snapshots.setdefault(market_key, []).append(quote.payload)
        resolved_keys = {row.payload["snapshot_key"] for row in self._records("forecast_resolution")}
        resolved = pending = unsupported = errors = 0
        error_breakdown: dict[str, int] = {}
        try:
            for row in precommits:
                payload = row.payload
                key = payload["snapshot_key"]
                if key in resolved_keys:
                    continue
                if not _resolution_due(payload):
                    pending += 1
                    continue
                try:
                    venue = payload["venue"]
                    if venue in {"polymarket", "limitless"} and not payload.get("venue_resolution_id"):
                        unsupported += 1
                        continue
                    resolution_id = payload.get("venue_resolution_id") or payload["market_id"]
                    if venue == "kalshi":
                        response = client.get(KALSHI_MARKET_URL.format(market_id=resolution_id)); response.raise_for_status()
                        market = response.json().get("market", response.json())
                        result, status = str(market.get("result") or "").lower(), str(market.get("status") or "").lower()
                        outcome = (1 if result == "yes" else 0) if status == "finalized" and result in {"yes", "no"} else None
                    elif venue == "polymarket":
                        response = client.get(POLYMARKET_URL.format(market_id=resolution_id)); response.raise_for_status()
                        market = response.json()
                        raw_outcomes, raw_prices = market.get("outcomes") or [], market.get("outcomePrices") or []
                        outcomes = json.loads(raw_outcomes) if isinstance(raw_outcomes, str) else raw_outcomes
                        prices = json.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices
                        status = "closed" if market.get("closed") else "open"
                        result, outcome = "", None
                        if status == "closed" and len(outcomes) == len(prices) and prices:
                            winners = [i for i, price in enumerate(prices) if float(price) >= .999]
                            if len(winners) == 1:
                                result = str(outcomes[winners[0]]).lower()
                                outcome = 1 if winners[0] == 0 else 0
                    elif venue == "limitless":
                        response = client.get(LIMITLESS_URL.format(market_id=resolution_id)); response.raise_for_status()
                        market = response.json().get("data", response.json())
                        status = str(market.get("status") or "").lower()
                        winning = market.get("winningOutcome") or market.get("winningOutcomeIndex")
                        result, outcome = "", None
                        if status == "resolved" and winning is not None:
                            result = str(winning).lower()
                            outcome = 1 if result in {"yes", "0"} or winning == 0 else 0
                    else:
                        unsupported += 1
                        continue
                    if outcome is None:
                        pending += 1
                        continue
                    candidates = [quote for quote in quote_snapshots.get((venue, payload["market_id"]), [])
                                  if _quote_before_cutoff(quote, payload)]
                    final_quote = max(candidates, key=lambda quote: quote.get("observed_at", ""), default=None)
                    if final_quote:
                        closing_probability = _float_or_none(final_quote.get("market_implied_prob"))
                        closing_source = final_quote.get("quote_source") or "latest pre-resolution scanner quote"
                        closing_observed_at = final_quote.get("observed_at")
                    else:
                        # A quote first observed during the resolution check is
                        # not demonstrably pre-close. Never relabel it as a
                        # closing forecast, even if the venue still exposes a
                        # stale bid/ask or last trade after settlement.
                        closing_probability, closing_source = None, None
                        closing_observed_at = None
                    official = None
                    if payload["domain"] == "weather":
                        official = resolve_weather_from_noaa(payload["event_identity"], client)
                    concordant = None
                    if official and official.get("status") == "resolved":
                        concordant = official["outcome"] == outcome
                    self.ledger.append(
                        "forecast_resolution",
                        {
                            "snapshot_key": key,
                            "event_group_id": payload["event_group_id"],
                            "venue": payload["venue"],
                            "market_id": payload["market_id"],
                            "outcome": outcome,
                            "venue_status": status,
                            "venue_result": result,
                            "closing_market_implied_prob": closing_probability,
                            "closing_price_source": closing_source,
                            "closing_price_observed_at": closing_observed_at,
                            "resolved_at": _now(),
                            "resolution_authority": payload["resolution_source"],
                            "resolution_rule_hash": payload["resolution_rule_hash"],
                            "evidence": "finalized venue result under the precommitted resolution rule",
                            "official_source_check": official,
                            "official_source_concordant": concordant,
                        },
                    )
                    resolved_keys.add(key)
                    resolved += 1
                except Exception as exc:  # a per-market outage must not abort the queue
                    # Snapshots created before venue_resolution_id was added
                    # only retain a condition id for these venues. Preserve
                    # them, but do not retry an unusable identifier forever.
                    if payload["venue"] in {"polymarket", "limitless"} and "venue_resolution_id" not in payload:
                        unsupported += 1
                    else:
                        errors += 1
                        label = f"{payload.get('venue', 'unknown')}:{type(exc).__name__}"
                        error_breakdown[label] = error_breakdown.get(label, 0) + 1
        finally:
            if own_client:
                client.close()
        return {"resolved": resolved, "pending": pending, "unsupported_venue": unsupported,
                "errors": errors, "error_breakdown": error_breakdown,
                "ledger": self.ledger.verify()}

    def verify_official_sources(self, client: httpx.Client | None = None) -> dict[str, Any]:
        """Retry official outcome checks independently of venue resolution.

        Official daily summaries commonly appear after a venue finalizes.  Keeping
        this as a separate append-only stage means a temporarily pending NOAA row
        is retried on every evidence run without rewriting the venue resolution.
        """
        own_client = client is None
        client = client or httpx.Client(timeout=20)
        precommits = {r.payload["snapshot_key"]: r.payload for r in self._records("forecast_precommit")}
        resolutions = {r.payload["snapshot_key"]: r.payload for r in self._records("forecast_resolution")}
        verified = {
            r.payload["snapshot_key"]
            for r in self._records("official_source_verification")
            if r.payload.get("status") == "resolved"
        }
        checked = resolved = pending = unsupported = errors = 0
        error_breakdown: dict[str, int] = {}
        official_cache: dict[str, dict[str, Any]] = {}
        try:
            for key, venue_resolution in resolutions.items():
                forecast = precommits.get(key)
                if not forecast or forecast.get("domain") != "weather" or key in verified:
                    continue
                checked += 1
                try:
                    identity = forecast["event_identity"]
                    identity_key = ":".join(str(identity.get(k) or "") for k in
                                            ("station_ghcnd_id", "target_date", "metric"))
                    official = official_cache.get(identity_key)
                    if official is None:
                        official = resolve_weather_from_noaa(identity, client)
                        official_cache[identity_key] = official
                    elif official.get("status") == "resolved":
                        official = dict(official)
                        official["outcome"] = int(event_happened(
                            official["observed_value"], identity.get("strike_type"),
                            identity.get("floor_strike"), identity.get("cap_strike")))
                    status = official.get("status")
                    if status == "pending":
                        pending += 1
                        continue
                    if status != "resolved":
                        unsupported += 1
                        continue
                    concordant = int(official["outcome"]) == int(venue_resolution["outcome"])
                    self.ledger.append("official_source_verification", {
                        "snapshot_key": key,
                        "event_group_id": forecast["event_group_id"],
                        "family": forecast["family"],
                        "market_id": forecast["market_id"],
                        "venue": forecast["venue"],
                        "venue_outcome": venue_resolution["outcome"],
                        "official_outcome": official["outcome"],
                        "status": "resolved",
                        "concordant": concordant,
                        "checked_at": _now(),
                        "official_source_check": official,
                    })
                    verified.add(key)
                    resolved += 1
                except Exception as exc:
                    errors += 1
                    label = type(exc).__name__
                    error_breakdown[label] = error_breakdown.get(label, 0) + 1
        finally:
            if own_client:
                client.close()
        return {"checked": checked, "resolved": resolved, "pending": pending,
                "unsupported": unsupported, "errors": errors, "error_breakdown": error_breakdown,
                "ledger": self.ledger.verify()}

    def report(self) -> dict[str, Any]:
        precommits = {row.payload["snapshot_key"]: row.payload for row in self._records("forecast_precommit")}
        resolutions = {row.payload["snapshot_key"]: row.payload for row in self._records("forecast_resolution")}
        verifications = {
            row.payload["snapshot_key"]: row.payload
            for row in self._records("official_source_verification")
            if row.payload.get("status") == "resolved"
        }
        scored: list[CalibrationRecord] = []
        scored_payloads = []
        for key, resolution in resolutions.items():
            forecast = precommits.get(key)
            if forecast is None:
                continue
            scored.append(
                CalibrationRecord(
                    domain=forecast["domain"], venue=forecast["venue"], market_id=forecast["market_id"],
                    question=forecast["question"], decision_timestamp=forecast["forecast_created_at"],
                    resolution_timestamp=resolution["resolved_at"], oracle_prob=forecast["oracle_prob"],
                    outcome=resolution["outcome"], bucket=probability_bucket(forecast["oracle_prob"], .1),
                    source_run=forecast["event_group_id"], source_available_at=forecast["forecast_created_at"],
                    target_date=str(forecast["event_identity"].get("target_date") or forecast["resolution_time"] or ""),
                )
            )
            scored_payloads.append({"forecast": forecast, "resolution": resolution})
        family_groups: dict[str, set[str]] = {}
        family_rows: dict[str, int] = {}
        family_scored: dict[str, list[CalibrationRecord]] = {}
        weather_concordance: dict[str, dict[str, bool]] = {}
        for record, row in zip(scored, scored_payloads):
            family = row["forecast"]["family"]
            family_groups.setdefault(family, set()).add(row["forecast"]["event_group_id"])
            family_rows[family] = family_rows.get(family, 0) + 1
            family_scored.setdefault(family, []).append(record)
            verification = verifications.get(row["forecast"]["snapshot_key"])
            concordant = (verification.get("concordant") if verification
                          else row["resolution"].get("official_source_concordant"))
            if concordant is not None:
                group = row["forecast"]["event_group_id"]
                family_checks = weather_concordance.setdefault(family, {})
                family_checks[group] = family_checks.get(group, True) and bool(concordant)

        # Prospective evidence is always broken out by the exact model version
        # that produced the precommit. This is the source used by versioned API
        # routes; aggregate contract rows must never masquerade as current-model
        # proof.
        model_evidence: dict[str, dict[str, Any]] = {}
        precommit_counts: dict[tuple[str, str], int] = {}
        precommit_band_counts: dict[tuple[str, str], dict[str, int]] = {}
        for forecast in precommits.values():
            key = (str(forecast.get("family") or "unknown"),
                   str(forecast.get("model_version") or "unknown"))
            precommit_counts[key] = precommit_counts.get(key, 0) + 1
            try:
                band = probability_bucket(float(forecast["oracle_prob"]), .1)
                bands = precommit_band_counts.setdefault(key, {})
                bands[band] = bands.get(band, 0) + 1
            except (KeyError, TypeError, ValueError):
                pass
        grouped_pairs: dict[tuple[str, str], list[tuple[CalibrationRecord, dict[str, Any]]]] = {}
        for record, row in zip(scored, scored_payloads):
            forecast = row["forecast"]
            key = (str(forecast.get("family") or "unknown"),
                   str(forecast.get("model_version") or "unknown"))
            grouped_pairs.setdefault(key, []).append((record, row))
        for key in sorted(set(precommit_counts) | set(grouped_pairs)):
            family, version = key
            pairs = grouped_pairs.get(key, [])
            records = [pair[0] for pair in pairs]
            rows = [pair[1] for pair in pairs]
            checks: dict[str, bool] = {}
            for row in rows:
                forecast = row["forecast"]
                verification = verifications.get(forecast["snapshot_key"])
                concordant = (verification.get("concordant") if verification
                              else row["resolution"].get("official_source_concordant"))
                if concordant is not None:
                    group = forecast["event_group_id"]
                    checks[group] = checks.get(group, True) and bool(concordant)
            resolved_rows = len(rows)
            precommitted_rows = precommit_counts.get(key, 0)
            breakdown = calibration_breakdown(records, width=.1) if records else None
            model_evidence.setdefault(family, {})[version] = {
                "evidence_type": "prospective_exact_model_version",
                "model_version": version,
                "precommitted_contract_rows": precommitted_rows,
                "resolved_contract_rows": resolved_rows,
                "unresolved_contract_rows": max(0, precommitted_rows - resolved_rows),
                "precommitted_by_probability_band": precommit_band_counts.get(key, {}),
                "independent_event_groups": len({
                    row["forecast"]["event_group_id"] for row in rows
                }),
                "calibration": breakdown["overall"] if breakdown else None,
                "calibration_by_probability_band": breakdown["by_probability_band"] if breakdown else {},
                "official_source_checks": len(checks),
                "official_source_concordance_rate": (
                    sum(checks.values()) / len(checks) if checks else None
                ),
                "probability_band_gate": _band_gate(records),
                "market_and_paper_performance": _market_performance(rows),
                "drift_monitoring": _segment_drift(rows) if family == "weather.temperature" else None,
            }

        # Weather v3's fixed transform was selected from v2 evidence. Publish
        # that development evidence, but label it retrospective and never add
        # its groups to v3's prospective promotion count.
        retrospective_validation: dict[str, Any] = {}
        source_pairs = grouped_pairs.get(("weather.temperature", WEATHER_V3_SOURCE_MODEL), [])
        if source_pairs:
            source_records = [pair[0] for pair in source_pairs]
            transformed_records = [replace(
                record,
                oracle_prob=power_transform(record.oracle_prob, WEATHER_V3_CALIBRATION_GAMMA),
                bucket=probability_bucket(
                    power_transform(record.oracle_prob, WEATHER_V3_CALIBRATION_GAMMA), .1
                ),
            ) for record in source_records]
            original = calibration_breakdown(source_records, width=.1)["overall"]
            transformed = calibration_breakdown(transformed_records, width=.1)["overall"]
            walk_forward = grouped_walk_forward(source_records)
            market_rows = [pair[1] for pair in source_pairs
                           if _float_or_none(pair[1]["forecast"].get("market_implied_prob")) is not None]
            market_brier = (sum(
                (row["forecast"]["market_implied_prob"] - row["resolution"]["outcome"]) ** 2
                for row in market_rows
            ) / len(market_rows)) if market_rows else None
            target_model = WEATHER_PRODUCTION_MODEL
            retrospective_validation["weather.temperature"] = {
                "evidence_type": "retrospective_model_development",
                "target_model_version": target_model,
                "source_model_version": WEATHER_V3_SOURCE_MODEL,
                "method": "power_transform",
                "gamma": WEATHER_V3_CALIBRATION_GAMMA,
                "independent_event_groups": len({r.source_run for r in source_records}),
                "contract_rows": len(source_records),
                "original_calibration": original,
                "transformed_calibration": transformed,
                "market_brier": market_brier,
                "transformed_oracle_brier_advantage": (
                    market_brier - transformed["brier_score"] if market_brier is not None else None
                ),
                "grouped_walk_forward": {k: v for k, v in walk_forward.items() if k != "folds"},
                "counts_toward_prospective_promotion": False,
                "paper_strategy_recomputed_for_target_model": False,
                "note": "supports the calibration design but does not replace prospective exact-version resolutions",
            }
        promotion = {}
        for family in sorted(set(family_rows) | {"weather.temperature"}):
            target_model = MODEL_VERSIONS.get(family)
            selected_pairs = [(record, row) for record, row in zip(scored, scored_payloads)
                              if row["forecast"]["family"] == family and
                              (target_model is None or row["forecast"].get("model_version") == target_model)]
            selected_records = [pair[0] for pair in selected_pairs]
            selected_rows = [pair[1] for pair in selected_pairs]
            groups = len({row["forecast"]["event_group_id"] for row in selected_rows})
            family_report = calibration_breakdown(selected_records, width=.1)["overall"] if selected_records else None
            checks = {}
            for row in selected_rows:
                verification = verifications.get(row["forecast"]["snapshot_key"])
                concordant = verification.get("concordant") if verification else row["resolution"].get("official_source_concordant")
                if concordant is not None:
                    group = row["forecast"]["event_group_id"]
                    checks[group] = checks.get(group, True) and bool(concordant)
            concordance_rate = sum(checks.values()) / len(checks) if checks else None
            checkpoint = next((n for n in CHECKPOINTS if groups < n), None)
            band_gate = _band_gate(selected_records)
            performance = _market_performance(selected_rows)
            drift = _segment_drift(selected_rows) if family == "weather.temperature" else None
            criteria = {
                "independent_groups_at_least_30": groups >= 30,
                "brier_score_at_most_0_20": bool(family_report and family_report["brier_score"] <= .20),
                "max_calibration_gap_at_most_0_15": bool(family_report and family_report["max_calibration_gap"] <= .15),
                "official_source_concordance_at_least_0_95": bool(concordance_rate is not None and concordance_rate >= .95),
                "all_adequately_sampled_bands_pass": band_gate["all_adequately_sampled_bands_pass"],
                "beats_market_brier": bool(performance["oracle_brier_advantage"] is not None and performance["oracle_brier_advantage"] > 0),
                "closing_price_group_coverage_at_least_0_80": (
                    performance["closing_price_group_coverage"] >= MIN_CLOSING_PRICE_GROUP_COVERAGE
                ),
                "beats_closing_market_brier": bool(
                    performance.get("closing_oracle_brier_advantage") is not None and
                    performance["closing_oracle_brier_advantage"] > 0
                ),
                "paper_return_positive_after_costs": performance["paper_strategy"]["positive_after_fees_and_spread"],
                "no_drift_alerts": bool(drift is None or drift["passes"]),
            }
            crossed = [n for n in CHECKPOINTS if groups >= n]
            checkpoint_reviews = []
            group_times: dict[str, str] = {}
            for row in selected_rows:
                group_times.setdefault(row["forecast"]["event_group_id"], row["forecast"]["forecast_created_at"])
            ordered_groups = [group for group, _ in sorted(group_times.items(), key=lambda item: item[1])]
            for checkpoint_size in crossed:
                allowed = set(ordered_groups[:checkpoint_size])
                checkpoint_pairs = [pair for pair in selected_pairs if pair[1]["forecast"]["event_group_id"] in allowed]
                checkpoint_records = [pair[0] for pair in checkpoint_pairs]
                checkpoint_rows = [pair[1] for pair in checkpoint_pairs]
                checkpoint_reviews.append({
                    "checkpoint": checkpoint_size,
                    "contract_rows": len(checkpoint_rows),
                    "calibration": calibration_breakdown(checkpoint_records, width=.1)["overall"],
                    "probability_band_gate": _band_gate(checkpoint_records),
                    "market_and_paper_performance": _market_performance(checkpoint_rows),
                })
            promotion[family] = {
                "model_version": target_model or "unversioned-family",
                "independent_event_groups": groups,
                "resolved_contract_rows": len(selected_rows),
                "minimum_groups_for_experimental_micro_execution": 30,
                "calibration": family_report,
                "official_source_checks": len(checks),
                "official_source_concordance_rate": concordance_rate,
                "probability_band_gate": band_gate,
                "market_and_paper_performance": performance,
                "drift_monitoring": drift,
                "criteria": criteria,
                "eligible": bool(crossed and all(criteria.values())),
                "execution_interlock": "unlocked" if crossed and all(criteria.values()) else "locked",
                "fixed_checkpoints": list(CHECKPOINTS),
                "crossed_checkpoints": crossed,
                "checkpoint_reviews": checkpoint_reviews,
                "last_reassessed_checkpoint": crossed[-1] if crossed else None,
                "next_checkpoint": checkpoint,
                "note": "promotion occurs only at fixed checkpoints and requires every criterion",
            }
        independent_groups = len({r.source_run for r in scored})
        weather_records = [
            record for record, row in zip(scored, scored_payloads)
            if row["forecast"]["family"] == "weather.temperature" and
            row["forecast"].get("model_version") == WEATHER_PRODUCTION_MODEL
        ]
        weather_recalibration = None
        if weather_records:
            weather_report = calibration_breakdown(weather_records, width=.1)
            band_diagnostics = sorted(({
                "band": row["bucket"], "contract_rows": row["count"],
                "mean_predicted": row["mean_predicted"], "actual_hit_rate": row["actual_hit_rate"],
                "calibration_gap": abs(row["mean_predicted"] - row["actual_hit_rate"]),
            } for row in weather_report["overall"]["reliability"]),
                key=lambda row: row["calibration_gap"], reverse=True)
            walk_forward = grouped_walk_forward(weather_records)
            candidate = fit_power_recalibration(weather_records)
            weather_recalibration = {
                "diagnosis": band_diagnostics,
                "grouped_walk_forward": walk_forward,
                "candidate_power_transform": {k: v for k, v in candidate.items() if k != "details"},
                "production_status": (
                    "eligible_candidate" if walk_forward.get("eligible") and walk_forward.get("improved")
                    else "diagnostic_only_not_applied"
                ),
                "safety_note": "never apply an in-sample correction without improvement on later independent event groups",
            }
        return {
            "created_at": _now(),
            "independent_resolved_event_groups": independent_groups,
            "primary_evidence_unit": "independent_event_group",
            "precommitted_forecasts": len(precommits),
            "resolved_contract_rows": len(scored),
            "unresolved_contract_rows": len(precommits) - len(resolutions),
            # Compatibility aliases; public displays use the explicit contract-row names above.
            "resolved_forecasts": len(scored),
            "unresolved_forecasts": len(precommits) - len(resolutions),
            "calibration": calibration_breakdown(scored, width=.1) if scored else None,
            "weather_recalibration": weather_recalibration,
            "model_evidence": model_evidence,
            "retrospective_validation": retrospective_validation,
            "promotion_readiness": promotion,
            "ledger_verification": self.ledger.verify(),
            "selection_policy": "all priced scan records are precommitted; losses and non-actionable forecasts are retained",
        }


def write_report(report: dict[str, Any], json_path: str | Path = DEFAULT_REPORT,
                 md_path: str | Path = DEFAULT_REPORT_MD) -> None:
    json_path, md_path = Path(json_path), Path(md_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_tmp, md_tmp = json_path.with_suffix(".json.tmp"), md_path.with_suffix(".md.tmp")
    json_tmp.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    lines = ["# Real-World Odds Oracle Calibration Evidence", "", f"- Created: {report['created_at']}",
             f"- **Independent resolved events (primary evidence): {report['independent_resolved_event_groups']}**",
             f"- Resolved contract rows (correlated thresholds): {report['resolved_contract_rows']}",
             f"- Precommitted contract rows: {report['precommitted_forecasts']}", "",
             "## Promotion readiness", ""]
    for family, row in report["promotion_readiness"].items():
        lines.append(f"- {family}: {row['independent_event_groups']}/30 independent events; eligible={row['eligible']}")
    md_tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_tmp.replace(json_path)
    md_tmp.replace(md_path)


def write_backlog(backlog: dict[str, Any], path: str | Path = DEFAULT_BACKLOG) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(backlog, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def run_daily(store: EvidenceStore) -> dict[str, Any]:
    scan = scan_opportunities()
    collected = store.collect_scan(scan)
    resolved = store.resolve_pending()
    verified = store.verify_official_sources()
    report = store.report()
    write_report(report)
    backlog = store.backlog(
        family="weather.temperature",
        model_version=WEATHER_PRODUCTION_MODEL,
        latest_report=report,
    )
    write_backlog(backlog)
    return {"collected": collected, "resolved": resolved, "official_verification": verified,
            "report": report, "backlog": backlog}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Precommit, resolve, and score oracle evidence")
    parser.add_argument("action", choices=("backlog", "collect", "resolve", "report", "run"), default="run", nargs="?")
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--family", default="weather.temperature")
    parser.add_argument("--model-version", default=WEATHER_PRODUCTION_MODEL)
    parser.add_argument("--latest-report", default=str(DEFAULT_REPORT))
    parser.add_argument("--max-report-age-hours", type=float, default=7.0)
    parser.add_argument("--output", help="optional path for the derived backlog JSON artifact")
    args = parser.parse_args(argv)
    store = EvidenceStore(args.ledger)
    if args.action == "backlog":
        try:
            latest_report = json.loads(Path(args.latest_report).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            latest_report = None
        result = store.backlog(
            family=args.family or None,
            model_version=args.model_version or None,
            latest_report=latest_report,
            max_report_age_hours=args.max_report_age_hours,
        )
        if args.output:
            write_backlog(result, args.output)
    elif args.action == "collect":
        result = store.collect_scan(scan_opportunities())
    elif args.action == "resolve":
        result = store.resolve_pending()
    elif args.action == "report":
        result = store.report(); write_report(result)
    else:
        result = run_daily(store)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
