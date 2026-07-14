"""Append-only market quote capture, with a targeted final-hour refresh path."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from rwoo.evidence import _prospective_eligible, _quote_before_cutoff
from rwoo.identity import MODEL_VERSIONS
from rwoo.readers import kalshi, limitless, polymarket
from rwoo.receipts import AppendOnlyLedger, hash_hex

DEFAULT_SCAN = Path(os.environ.get(
    "RWOO_OPPORTUNITY_SCAN_PATH", "data/public/opportunity_scan_latest.json",
))
DEFAULT_LEDGER = Path(os.environ.get(
    "RWOO_EVIDENCE_LEDGER_PATH", "data/receipts/forecast_evidence.jsonl",
))
NEAR_CLOSE_SECONDS = 60 * 60
MAX_SCAN_AGE_SECONDS = 45 * 60


def _dt(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if 0 <= result <= 1 else None


def _raw_market(canonical) -> dict[str, Any]:
    if canonical.venue in {"kalshi", "limitless"}:
        return canonical.raw.get("market", {})
    return canonical.raw


def _last_trade(venue: str, raw: dict[str, Any]) -> float | None:
    keys = ("last_price_dollars", "last_price") if venue == "kalshi" else (
        "lastTradePrice", "lastPrice", "price",
    )
    for key in keys:
        value = _number(raw.get(key))
        if value is not None:
            return value
    return None


def _depth(venue: str, raw: dict[str, Any], orderbook: dict[str, Any] | None) -> dict[str, Any]:
    if orderbook:
        return {"available": True, "source": f"{venue} public orderbook depth=1", "top_levels": orderbook}
    liquidity = raw.get("liquidityNum") or raw.get("liquidity")
    return {
        "available": liquidity is not None,
        "source": f"{venue} reported liquidity" if liquidity is not None else f"{venue} depth unavailable",
        "reported_liquidity": liquidity,
    }


def _live_quote(row: dict[str, Any], client: httpx.Client) -> dict[str, Any] | None:
    venue, market_id = row["venue"], row["market_id"]
    orderbook = None
    if venue == "kalshi":
        canonical = kalshi.fetch_canonical_market(market_id, client=client)
        orderbook = kalshi.fetch_orderbook(market_id, depth=1, client=client)
    elif venue == "polymarket":
        canonical = polymarket.fetch_canonical_market(
            str(row.get("venue_resolution_id") or market_id), client=client,
        )
    elif venue == "limitless":
        identifier = str(row.get("venue_resolution_id") or market_id)
        canonical = limitless.fetch_canonical_market(identifier, client=client)
        if canonical is not None:
            orderbook = limitless.fetch_orderbook(identifier, client=client)
    else:
        return None
    if canonical is None or str(canonical.market_status or "").lower() not in {"", "open", "active"}:
        return None
    bid = _number(round(canonical.implied_prob - canonical.spread / 2, 6))
    ask = _number(round(canonical.implied_prob + canonical.spread / 2, 6))
    if bid is None or ask is None or bid > ask:
        return None
    raw = _raw_market(canonical)
    return {
        "observed_at": canonical.fetched_at, "yes_bid": bid, "yes_ask": ask,
        "market_implied_prob": (bid + ask) / 2, "spread": ask - bid,
        "last_trade": _last_trade(venue, raw), "depth": _depth(venue, raw, orderbook),
        "raw_response_hash": hash_hex({"market": raw, "orderbook": orderbook}),
        "raw_response_hash_scope": "venue market response plus depth-one orderbook when available",
        "quote_source": "targeted final-hour venue quote",
    }


def _scan_quote(row: dict[str, Any]) -> dict[str, Any] | None:
    execution = row.get("execution") or {}
    bid = _number(execution.get("yes_bid"))
    ask = _number(execution.get("yes_ask"))
    if bid is None or ask is None or bid > ask:
        implied = _number(row.get("implied_prob"))
        spread = _number(row.get("spread"))
        if implied is None or spread is None:
            return None
        bid, ask = implied - spread / 2, implied + spread / 2
    if not 0 <= bid <= ask <= 1:
        return None
    return {
        "observed_at": row.get("fetched_at"), "yes_bid": bid, "yes_ask": ask,
        "market_implied_prob": (bid + ask) / 2, "spread": ask - bid,
        "last_trade": None, "depth": {"available": False, "source": "scanner artifact"},
        "raw_response_hash": hash_hex(row),
        "raw_response_hash_scope": "normalized_scan_record",
        "quote_source": "scheduled 30-minute scanner quote",
    }


def _bucket(observed_at: str, interval_minutes: int) -> str:
    observed = _dt(observed_at)
    if observed is None:
        return "invalid"
    minute = observed.minute - observed.minute % interval_minutes
    return observed.replace(minute=minute, second=0, microsecond=0).isoformat()


def capture_quotes(
    *, scan: dict[str, Any], ledger: AppendOnlyLedger, mode: str,
    now: datetime | None = None,
    live_fetcher: Callable[[dict[str, Any], httpx.Client], dict[str, Any] | None] = _live_quote,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    created = _dt(scan.get("created_at"))
    if created is None or not 0 <= (now - created).total_seconds() <= MAX_SCAN_AGE_SECONDS:
        return {"captured": 0, "eligible": 0, "errors": 0, "refused": "scan artifact is missing or stale"}
    records = ledger.read_records()
    precommits: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in records:
        if record.record_type != "forecast_precommit":
            continue
        payload = record.payload
        key = (str(payload.get("venue")), str(payload.get("market_id")), str(payload.get("model_version")))
        if key not in precommits or str(payload.get("forecast_created_at", "")) > str(precommits[key].get("forecast_created_at", "")):
            precommits[key] = payload
    existing = {
        record.payload.get("quote_key") for record in records
        if record.record_type == "market_quote_snapshot"
    }
    pending: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []
    eligible = duplicates = errors = cutoff_rejected = 0
    error_breakdown: dict[str, int] = {}
    client = httpx.Client(timeout=20)
    try:
        for row in scan.get("top") or []:
            expected_model = MODEL_VERSIONS.get(str(row.get("family") or ""))
            key = (str(row.get("venue")), str(row.get("market_id")), str(row.get("model_version")))
            precommit = precommits.get(key)
            close = _dt(row.get("trading_close_time"))
            if (row.get("oracle_prob") is None or precommit is None or expected_model != row.get("model_version")
                    or str(row.get("market_status") or "").lower() not in {"", "open", "active"}
                    or close is None or close <= now or not _prospective_eligible(row)[0]):
                continue
            seconds_to_close = (close - now).total_seconds()
            if mode == "near-close" and seconds_to_close > NEAR_CLOSE_SECONDS:
                continue
            eligible += 1
            try:
                quote = live_fetcher(row, client) if mode == "near-close" else _scan_quote(row)
                if quote is None or not _quote_before_cutoff(
                    {**quote, "trading_close_time": row.get("trading_close_time")}, precommit,
                ):
                    cutoff_rejected += 1
                    continue
                interval = 5 if mode == "near-close" else 30
                quote_key = ":".join((row["venue"], row["market_id"], row["model_version"], mode,
                                      _bucket(str(quote["observed_at"]), interval)))
                if quote_key in existing:
                    duplicates += 1
                    continue
                payload = {
                    **quote, "quote_key": quote_key,
                    "forecast_snapshot_key": precommit.get("snapshot_key"),
                    "event_group_id": row.get("event_group_id"), "venue": row["venue"],
                    "market_id": row["market_id"], "model_version": row["model_version"],
                    "trading_close_time": row.get("trading_close_time"),
                    "resolution_time": row.get("resolution_time"),
                    "capture_mode": mode,
                }
                pending.append(("market_quote_snapshot", payload, None))
                existing.add(quote_key)
            except Exception as exc:  # one venue outage must not abort every market
                errors += 1
                label = f"{row.get('venue', 'unknown')}:{type(exc).__name__}"
                error_breakdown[label] = error_breakdown.get(label, 0) + 1
    finally:
        client.close()
    ledger.append_many(pending)
    return {
        "captured": len(pending), "eligible": eligible, "duplicates": duplicates,
        "cutoff_rejected": cutoff_rejected, "errors": errors,
        "error_breakdown": error_breakdown,
        "ledger": ledger.verify(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture append-only pre-close market quotes")
    parser.add_argument("--mode", choices=("regular", "near-close"), required=True)
    parser.add_argument("--scan", default=str(DEFAULT_SCAN))
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    args = parser.parse_args(argv)
    try:
        scan = json.loads(Path(args.scan).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"captured": 0, "errors": 1, "refused": type(exc).__name__}, sort_keys=True))
        return 1
    result = capture_quotes(scan=scan, ledger=AppendOnlyLedger(args.ledger), mode=args.mode)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not result.get("errors") and not result.get("refused") else 1


if __name__ == "__main__":
    raise SystemExit(main())
