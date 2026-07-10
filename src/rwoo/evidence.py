"""Continuous precommitted forecast evidence and resolution pipeline."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from rwoo.calibration import CalibrationRecord, calibration_breakdown, probability_bucket
from rwoo.receipts import AppendOnlyLedger, hash_hex
from rwoo.scanner import scan_opportunities
from rwoo.official_outcomes import resolve_weather_from_noaa

DEFAULT_LEDGER = Path("data/receipts/forecast_evidence.jsonl")
DEFAULT_REPORT = Path("data/public/calibration_report_latest.json")
DEFAULT_REPORT_MD = Path("data/public/calibration_report_latest.md")
KALSHI_MARKET_URL = "https://api.elections.kalshi.com/trade-api/v2/markets/{market_id}"
POLYMARKET_URL = "https://gamma-api.polymarket.com/markets/{market_id}"
LIMITLESS_URL = "https://api.limitless.exchange/markets/{market_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _day(timestamp: str) -> str:
    return timestamp[:10]


class EvidenceStore:
    def __init__(self, path: str | Path = DEFAULT_LEDGER):
        self.ledger = AppendOnlyLedger(path)

    def _records(self, record_type: str | None = None):
        rows = self.ledger.read_records()
        return [row for row in rows if record_type is None or row.record_type == record_type]

    def collect_scan(self, scan: dict[str, Any]) -> dict[str, Any]:
        existing = {
            row.payload["snapshot_key"]
            for row in self._records("forecast_precommit")
            if "snapshot_key" in row.payload
        }
        appended = skipped = 0
        for record in scan["top"]:
            if record.get("oracle_prob") is None:
                continue
            forecast_at = record["fetched_at"]
            snapshot_key = ":".join(
                (record["venue"], record["market_id"], record["model_version"], _day(forecast_at))
            )
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
                "actionable": record["actionable"],
                "side": record["side"],
                "execution": record.get("execution"),
                "why": record.get("why"),
            }
            self.ledger.append("forecast_precommit", payload)
            existing.add(snapshot_key)
            appended += 1
        return {"appended": appended, "duplicates_skipped": skipped, "ledger": self.ledger.verify()}

    def resolve_pending(self, client: httpx.Client | None = None) -> dict[str, Any]:
        own_client = client is None
        client = client or httpx.Client(timeout=20)
        precommits = self._records("forecast_precommit")
        resolved_keys = {row.payload["snapshot_key"] for row in self._records("forecast_resolution")}
        resolved = pending = unsupported = errors = 0
        try:
            for row in precommits:
                payload = row.payload
                key = payload["snapshot_key"]
                if key in resolved_keys:
                    continue
                try:
                    venue = payload["venue"]
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
                except Exception:  # a per-market outage must not abort the queue
                    # Snapshots created before venue_resolution_id was added
                    # only retain a condition id for these venues. Preserve
                    # them, but do not retry an unusable identifier forever.
                    if payload["venue"] in {"polymarket", "limitless"} and "venue_resolution_id" not in payload:
                        unsupported += 1
                    else:
                        errors += 1
        finally:
            if own_client:
                client.close()
        return {"resolved": resolved, "pending": pending, "unsupported_venue": unsupported,
                "errors": errors, "ledger": self.ledger.verify()}

    def report(self) -> dict[str, Any]:
        precommits = {row.payload["snapshot_key"]: row.payload for row in self._records("forecast_precommit")}
        resolutions = {row.payload["snapshot_key"]: row.payload for row in self._records("forecast_resolution")}
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
        weather_concordance: dict[str, list[bool]] = {}
        for record, row in zip(scored, scored_payloads):
            family = row["forecast"]["family"]
            family_groups.setdefault(family, set()).add(row["forecast"]["event_group_id"])
            family_rows[family] = family_rows.get(family, 0) + 1
            family_scored.setdefault(family, []).append(record)
            concordant = row["resolution"].get("official_source_concordant")
            if concordant is not None:
                weather_concordance.setdefault(family, []).append(bool(concordant))
        promotion = {}
        for family in sorted(set(family_rows) | {"weather.temperature"}):
            groups = len(family_groups.get(family, set()))
            family_report = calibration_breakdown(family_scored[family], width=.1)["overall"] if family_scored.get(family) else None
            checks = weather_concordance.get(family, [])
            concordance_rate = sum(checks) / len(checks) if checks else None
            checkpoint = next((n for n in (30, 100, 250, 500) if groups < n), None)
            criteria = {
                "independent_groups_at_least_30": groups >= 30,
                "brier_score_at_most_0_20": bool(family_report and family_report["brier_score"] <= .20),
                "max_calibration_gap_at_most_0_15": bool(family_report and family_report["max_calibration_gap"] <= .15),
                "official_source_concordance_at_least_0_95": bool(concordance_rate is not None and concordance_rate >= .95),
            }
            promotion[family] = {
                "independent_event_groups": groups,
                "resolved_contract_rows": family_rows.get(family, 0),
                "minimum_groups_for_experimental_micro_execution": 30,
                "calibration": family_report,
                "official_source_checks": len(checks),
                "official_source_concordance_rate": concordance_rate,
                "criteria": criteria,
                "eligible": all(criteria.values()),
                "fixed_checkpoints": [30, 100, 250, 500],
                "next_checkpoint": checkpoint,
                "note": "promotion occurs only at fixed checkpoints and requires every criterion",
            }
        return {
            "created_at": _now(),
            "precommitted_forecasts": len(precommits),
            "resolved_forecasts": len(scored),
            "unresolved_forecasts": len(precommits) - len(resolutions),
            "independent_resolved_event_groups": len({r.source_run for r in scored}),
            "calibration": calibration_breakdown(scored, width=.1) if scored else None,
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
             f"- Precommitted forecasts: {report['precommitted_forecasts']}",
             f"- Resolved forecasts: {report['resolved_forecasts']}",
             f"- Independent resolved events: {report['independent_resolved_event_groups']}", "",
             "## Promotion readiness", ""]
    for family, row in report["promotion_readiness"].items():
        lines.append(f"- {family}: {row['independent_event_groups']}/30 independent events; eligible={row['eligible']}")
    md_tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_tmp.replace(json_path)
    md_tmp.replace(md_path)


def run_daily(store: EvidenceStore) -> dict[str, Any]:
    scan = scan_opportunities()
    collected = store.collect_scan(scan)
    resolved = store.resolve_pending()
    report = store.report()
    write_report(report)
    return {"collected": collected, "resolved": resolved, "report": report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Precommit, resolve, and score oracle evidence")
    parser.add_argument("action", choices=("collect", "resolve", "report", "run"), default="run", nargs="?")
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    args = parser.parse_args(argv)
    store = EvidenceStore(args.ledger)
    if args.action == "collect":
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
