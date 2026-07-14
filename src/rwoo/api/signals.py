"""Conversational delivery over precomputed, precommitted scan artifacts."""
from __future__ import annotations

from datetime import datetime, timezone
import base64
import json
from typing import Any

from rwoo.api.errors import OracleError
from rwoo.identity import MODEL_VERSIONS

SERVICE = "rwoo.best_signals"
_DOMAINS = ("weather", "economics", "sports", "commodities")
_VENUES = ("kalshi", "polymarket", "limitless")
_DAILY_WEATHER_FAMILIES = {"weather.temperature", "weather.precipitation"}


def _dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _daily_weather_event_elapsed(row: dict[str, Any], now: datetime) -> bool:
    if row.get("family") not in _DAILY_WEATHER_FAMILIES:
        return False
    identity = row.get("event_identity") or {}
    value = identity.get("target_date")
    if not isinstance(value, str) or len(value) < 10:
        return False
    try:
        target = datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return False
    # UTC is intentionally conservative for US-local weather: immediately
    # after 00:00 UTC we may suppress a still-running local day, but we never
    # advertise a forecast after that target date has unquestionably elapsed.
    return now.date() > target


_SPORT_FAMILY_ALIASES = {
    "sports.world_cup": ("world cup", "fifa"),
    "sports.nba": ("basketball", "nba"),
    "sports.tennis": ("tennis", "wimbledon", "atp", "wta"),
    "sports.mlb": ("baseball", "mlb", "world series"),
    "sports.nhl": ("hockey", "nhl"),
    "sports.esports": ("esports", "e-sports", "counter-strike", "league of legends"),
}

_MARKET_FAMILY_ALIASES = {
    "weather.hurricane_season": ("hurricane", "named storm", "tropical storm", "major storm"),
    "energy.henry_hub_spot": ("henry hub", "natural gas", "eia energy"),
    "agriculture.commodity_price": ("agriculture", "corn", "wheat", "soybean", "cattle", "coffee", "cocoa", "sugar"),
}


def _intent(message: str) -> tuple[str | None, str | None, str | None]:
    text = message.lower()
    domain = next((value for value in _DOMAINS if value in text), None)
    venue = next((value for value in _VENUES if value in text), None)
    family_aliases = {**_SPORT_FAMILY_ALIASES, **_MARKET_FAMILY_ALIASES}
    family = next((family for family, aliases in family_aliases.items()
                   if any(alias in text for alias in aliases)), None)
    if family in _SPORT_FAMILY_ALIASES or any(word in text for word in ("sport", "soccer", "football")):
        domain = "sports"
    elif family == "weather.hurricane_season":
        domain = "weather"
    elif family in {"energy.henry_hub_spot", "agriculture.commodity_price"} or "energy" in text:
        domain = "commodities"
    return domain, venue, family


def _evidence(report: dict[str, Any] | None, family: str, version: str) -> dict[str, Any]:
    if not report:
        return {"eligible": False, "prospective_groups": 0, "retrospective": None}
    row = (report.get("promotion_readiness") or {}).get(family) or {}
    # Evidence belongs to the exact deployed model. Older report formats did
    # not carry model_version, so they cannot establish current-model proof.
    if row.get("model_version") != version:
        eligible, count = False, 0
    else:
        eligible = bool(row.get("eligible"))
        count = int(row.get("independent_event_groups") or 0)
    retrospective = (report.get("retrospective_validation") or {}).get(family)
    if not retrospective or retrospective.get("target_model_version") != version:
        retrospective = None
    return {"eligible": eligible, "prospective_groups": count, "retrospective": retrospective}


def _encode_cursor(offset: int, scan_created_at: str) -> str:
    raw = json.dumps({"offset": offset, "scan_created_at": scan_created_at}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str | None, scan_created_at: str) -> int:
    if not cursor:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        value = json.loads(raw)
        offset = int(value["offset"])
        if offset < 0 or value["scan_created_at"] != scan_created_at:
            raise ValueError
        return offset
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OracleError("INVALID_REQUEST", "signal cursor is invalid or belongs to an older scan") from exc


def rank_signals(*, scan: dict[str, Any] | None, calibration: dict[str, Any] | None,
                 message: str, limit: int, now: datetime, max_age_minutes: int,
                 min_close_minutes: int, max_spread: float, cursor: str | None = None) -> dict[str, Any]:
    if not scan:
        raise OracleError("SIGNALS_UNAVAILABLE", "no opportunity scan is available", http_status=503)
    created = _dt(scan.get("created_at"))
    age_minutes = ((now - created).total_seconds() / 60) if created else float("inf")
    if age_minutes < 0 or age_minutes > max_age_minutes:
        raise OracleError("SIGNALS_STALE", "the latest opportunity scan is stale; no signal was returned", http_status=503)

    domain, venue, family = _intent(message)
    accepted: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    for row in scan.get("top") or []:
        reason = None
        close = _dt(row.get("trading_close_time"))
        minutes = ((close - now).total_seconds() / 60) if close else None
        status = str(row.get("market_status") or "").lower()
        execution = row.get("execution") or {}
        version = str(row.get("model_version") or "")
        expected_version = MODEL_VERSIONS.get(str(row.get("family") or ""))
        if not row.get("actionable"):
            reason = "not_actionable"
        elif domain and row.get("domain") != domain:
            reason = "domain"
        elif family and row.get("family") != family:
            reason = "family"
        elif venue and row.get("venue") != venue:
            reason = "venue"
        elif status and status not in {"open", "active"}:
            reason = "closed_or_inactive"
        elif _daily_weather_event_elapsed(row, now):
            reason = "event_elapsed"
        elif close is None:
            reason = "unknown_trading_close"
        elif minutes is None or minutes < min_close_minutes:
            reason = "near_close"
        elif float(row.get("spread") or 0) <= 0 or float(row.get("spread") or 0) > max_spread:
            reason = "spread"
        elif execution.get("entry_price") is None or execution.get("expected_profit_per_contract") is None:
            reason = "no_executable_quote"
        elif expected_version is None or version != expected_version:
            reason = "model_version_drift"
        if reason:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue

        evidence = _evidence(calibration, str(row.get("family")), version)
        eligible = bool(evidence["eligible"])
        independent = int(evidence["prospective_groups"])
        retrospective = evidence["retrospective"]
        accepted.append({
            "rank": 0,
            "venue": row.get("venue"), "market_id": row.get("market_id"),
            "question": row.get("question"), "domain": row.get("domain"),
            "family": row.get("family"), "side": row.get("side"),
            "oracle_probability": row.get("oracle_prob"),
            "probability_interval": [row.get("prob_low"), row.get("prob_high")],
            "market_probability": row.get("implied_prob"), "spread": row.get("spread"),
            "entry_price": execution.get("entry_price"),
            "expected_profit_per_contract": execution.get("expected_profit_per_contract"),
            "net_edge": row.get("net_edge_points"), "confidence": row.get("confidence"),
            "trading_close_time": row.get("trading_close_time"),
            "minutes_to_trading_close": round(minutes, 1), "model_version": version,
            "promotion_eligible": eligible, "independent_resolved_events": independent,
            "retrospective_validation": ({
                "source_model_version": retrospective.get("source_model_version"),
                "independent_event_groups": retrospective.get("independent_event_groups"),
                "contract_rows": retrospective.get("contract_rows"),
                "transformed_brier_score": (retrospective.get("transformed_calibration") or {}).get("brier_score"),
                "walk_forward_improved": (retrospective.get("grouped_walk_forward") or {}).get("improved"),
                "counts_toward_prospective_promotion": False,
            } if retrospective else None),
            "execution_recommended": eligible,
            "risk_label": "validated" if eligible else "experimental_current_model",
            "sizing_scope": "one_contract_only; displayed top-of-book does not prove larger depth",
        })

        scan_expiry = created.timestamp() + max_age_minutes * 60
        close_expiry = close.timestamp() - min_close_minutes * 60
        accepted[-1].update({
            "quote_timestamp": row.get("fetched_at"),
            "source_timestamp": row.get("source_timestamp"),
            "scan_timestamp": scan.get("created_at"),
            "signal_expires_at": datetime.fromtimestamp(min(scan_expiry, close_expiry), timezone.utc).isoformat(),
        })

    accepted.sort(key=lambda x: (bool(x["promotion_eligible"]), float(x["net_edge"] or -1), float(x["confidence"] or 0)), reverse=True)
    offset = _decode_cursor(cursor, str(scan.get("created_at") or ""))
    total_accepted = len(accepted)
    accepted = accepted[offset:offset + limit]
    next_offset = offset + len(accepted)
    next_cursor = _encode_cursor(next_offset, str(scan.get("created_at") or "")) if next_offset < total_accepted else None
    for index, signal in enumerate(accepted, offset + 1):
        signal["rank"] = index
    if accepted:
        answer = f"Found {len(accepted)} currently open signal{'s' if len(accepted) != 1 else ''} after tradability checks."
    else:
        answer = "No signal currently passes the freshness, trading-close, quote, spread, and model-version gates."
    return {
        "answer": answer, "signals": accepted,
        "filters": {"domain": domain, "venue": venue, "family": family,
                    "scan_age_minutes": round(age_minutes, 1),
                    "min_minutes_to_close": min_close_minutes, "max_spread": max_spread,
                    "rejected": rejected},
        "pagination": {"cursor": cursor, "next_cursor": next_cursor,
                       "returned": len(accepted), "total_matching": total_accepted},
        "evidence_notice": "Signals are delivered when tradability gates pass. Retrospective model-development evidence is disclosed separately; only prospective exact-version evidence can unlock execution recommendations.",
    }
