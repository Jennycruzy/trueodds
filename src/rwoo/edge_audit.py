"""Read-only structural audit for large actionable edges in a scan artifact."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

from rwoo.identity import MODEL_VERSIONS


DEFAULT_SCAN = Path(os.environ.get(
    "RWOO_OPPORTUNITY_SCAN_PATH", "data/public/opportunity_scan_latest.json",
))
DEFAULT_AUDIT = Path(os.environ.get(
    "RWOO_EDGE_AUDIT_PATH", str(DEFAULT_SCAN.with_name("opportunity_scan_edge_audit_latest.json")),
))
TOLERANCE = 1e-6


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _close(left: float | None, right: float | None) -> bool:
    return left is not None and right is not None and math.isclose(
        left, right, rel_tol=TOLERANCE, abs_tol=TOLERANCE,
    )


def audit_edge(row: dict[str, Any]) -> list[str]:
    """Return structural inconsistencies without recalculating model odds."""
    issues: list[str] = []
    execution = row.get("execution") or {}
    oracle = _number(row.get("oracle_prob"))
    implied = _number(row.get("implied_prob"))
    spread = _number(row.get("spread"))
    low = _number(row.get("prob_low"))
    high = _number(row.get("prob_high"))
    fee = _number(execution.get("estimated_fee_per_contract"))
    side = row.get("side")

    for name, value in (("oracle_prob", oracle), ("implied_prob", implied), ("spread", spread)):
        if value is None or not 0 <= value <= 1:
            issues.append(f"{name} is missing, non-finite, or outside [0, 1]")
    if low is None or high is None or not 0 <= low <= high <= 1:
        issues.append("probability interval is missing or invalid")
    if oracle is None or implied is None or spread is None:
        return issues

    expected_side = "YES" if oracle > implied else "NO"
    if side != expected_side:
        issues.append(f"side is {side!r}; expected {expected_side} from oracle-versus-market direction")
    if execution.get("side") not in {None, side}:
        issues.append("execution side disagrees with scan side")

    yes_bid = max(0.0, implied - spread / 2)
    yes_ask = min(1.0, implied + spread / 2)
    expected_entry = yes_ask if side == "YES" else 1.0 - yes_bid
    expected_side_probability = oracle if side == "YES" else 1.0 - oracle
    execution_bid = _number(execution.get("yes_bid"))
    execution_ask = _number(execution.get("yes_ask"))
    entry = _number(execution.get("entry_price"))
    side_probability = _number(execution.get("side_probability"))
    expected_profit = _number(execution.get("expected_profit_per_contract"))
    net_edge = _number(row.get("net_edge_points"))
    if not _close(execution_bid, yes_bid):
        issues.append("YES bid is inconsistent with the canonical midpoint and spread")
    if not _close(execution_ask, yes_ask):
        issues.append("YES ask is inconsistent with the canonical midpoint and spread")
    if not _close(entry, expected_entry):
        issues.append("entry price is inconsistent with the selected side's executable ask")
    if not _close(side_probability, expected_side_probability):
        issues.append("side probability is inconsistent with oracle probability and selected side")
    if fee is None or fee < 0:
        issues.append("estimated fee is missing or negative")
    else:
        calculated_profit = expected_side_probability - expected_entry - fee
        if not _close(expected_profit, calculated_profit):
            issues.append("expected profit is inconsistent with probability, entry price, and fee")
        if not _close(net_edge, calculated_profit):
            issues.append("net edge is inconsistent with executable expected profit")

    expected_model = MODEL_VERSIONS.get(str(row.get("family") or ""))
    if expected_model is None or row.get("model_version") != expected_model:
        issues.append("model version does not match the registered production family version")
    identity = row.get("event_identity") or {}
    if row.get("family") == "weather.temperature":
        for field in ("target_date", "metric", "station_ghcnd_id", "strike_type"):
            if identity.get(field) in {None, ""}:
                issues.append(f"weather event identity is missing {field}")
        if identity.get("floor_strike") is None and identity.get("cap_strike") is None:
            issues.append("weather event identity is missing both strike bounds")
    return issues


def audit_scan(scan: dict[str, Any], *, limit: int = 30) -> dict[str, Any]:
    actionable = [row for row in scan.get("top") or [] if row.get("actionable")]
    ranked = sorted(
        actionable,
        key=lambda row: abs(_number(row.get("net_edge_points")) or -1),
        reverse=True,
    )[:limit]
    rows = []
    for row in ranked:
        issues = audit_edge(row)
        rows.append({
            "venue": row.get("venue"),
            "market_id": row.get("market_id"),
            "family": row.get("family"),
            "side": row.get("side"),
            "oracle_prob": row.get("oracle_prob"),
            "market_prob": row.get("implied_prob"),
            "net_edge": row.get("net_edge_points"),
            "quote_timestamp": row.get("fetched_at"),
            "source_timestamp": row.get("source_timestamp"),
            "trading_close_time": row.get("trading_close_time"),
            "issue_count": len(issues),
            "issues": issues,
        })
    failures = sum(bool(row["issues"]) for row in rows)
    return {
        "scan_created_at": scan.get("created_at"),
        "actionable_rows": len(actionable),
        "audited_rows": len(rows),
        "structural_failures": failures,
        "status": "pass" if failures == 0 else "fail",
        "scope": (
            "structural consistency only; this does not prove source semantics, "
            "forecast accuracy, liquidity, or future profitability"
        ),
        "rows": rows,
    }


def write_audit(audit: dict[str, Any], path: str | Path = DEFAULT_AUDIT) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit the largest actionable scan edges without writing state")
    parser.add_argument("--scan", default=str(DEFAULT_SCAN))
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--output", help="optional path for the derived audit JSON artifact")
    args = parser.parse_args(argv)
    try:
        scan = json.loads(Path(args.scan).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "reason": type(exc).__name__}, sort_keys=True))
        return 1
    result = audit_scan(scan, limit=max(1, args.limit))
    if args.output:
        write_audit(result, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
