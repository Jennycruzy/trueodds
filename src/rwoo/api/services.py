"""Service orchestration and response assembly.

Assembly is deterministic and side-effect free apart from committing a receipt:
it never invents a probability, never overrides an engine refusal, and turns a
`ScanRecord` (or its absence) into the documented response shape. The engine
functions in `rwoo.scanner`/`rwoo.edge`/`rwoo.cross_venue` remain the sole
source of every number.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable

from rwoo.api.config import Settings
from rwoo.api.errors import OracleError
from rwoo.api.receipt_store import DecisionReceiptStore, request_hash
from rwoo.calibration import probability_bucket
from rwoo.coverage import classify_market_shape
from rwoo.cross_venue import cross_venue_edge
from rwoo.identity import model_version
from rwoo.receipts import hash_hex

# Coverage status -> stable refusal reason code. These are honest "cannot price
# this safely" outcomes returned as HTTP 200 status="refused".
_COVERAGE_REFUSAL = {
    "unsupported_domain": "UNSUPPORTED_MARKET",
    "source_missing": "UNSUPPORTED_MARKET",
    "parse_missing": "ENTITY_UNBOUND",
    "model_missing": "MODEL_MISSING",
}

CHECK_MARKET_SERVICE = "rwoo.check_market"
CROSS_VENUE_SERVICE = "rwoo.cross_venue_edge"
CALIBRATION_SERVICE = "rwoo.get_calibration"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json_artifact(path) -> dict[str, Any] | None:
    """Read a public JSON artifact, tolerating a missing or corrupt file."""
    try:
        from pathlib import Path

        p = Path(path)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ------------------------------ check market ------------------------------


def _calibration_context(report: dict[str, Any] | None, family: str, oracle_prob: float | None,
                         model_ver: str) -> dict[str, Any]:
    band = probability_bucket(oracle_prob, 0.1) if oracle_prob is not None else None
    scope = {"family": family, "model_version": model_ver, "probability_band": band}
    if not report:
        return {
            "status": "accumulating",
            "scope": scope,
            "independent_resolved_events": 0,
            "next_checkpoint": 30,
            "promotion_eligible": False,
            "criteria": {},
        }
    promotion = (report.get("promotion_readiness") or {}).get(family)
    if not promotion:
        exact = (((report.get("model_evidence") or {}).get(family) or {}).get(model_ver) or {})
        return {
            "status": "accumulating",
            "scope": scope,
            "independent_resolved_events": int(exact.get("independent_event_groups") or 0),
            "next_checkpoint": 30,
            "promotion_eligible": False,
            "criteria": {},
        }
    if promotion.get("model_version") != model_ver:
        exact = (((report.get("model_evidence") or {}).get(family) or {}).get(model_ver) or {})
        return {
            "status": "accumulating", "scope": scope,
            "independent_resolved_events": int(exact.get("independent_event_groups") or 0),
            "next_checkpoint": 30, "promotion_eligible": False, "criteria": {},
        }
    events = int(promotion.get("independent_event_groups") or 0)
    eligible = bool(promotion.get("eligible"))
    return {
        "status": "promotion_eligible" if eligible else "accumulating",
        "scope": scope,
        "independent_resolved_events": events,
        "next_checkpoint": promotion.get("next_checkpoint"),
        "promotion_eligible": eligible,
        "criteria": promotion.get("criteria") or {},
    }


def _forecast_block(record) -> dict[str, Any]:
    why = record.why or {}
    model_probs = why.get("model_probabilities") or {}
    agreement = {
        "available": bool(model_probs),
        "model_count": why.get("model_count"),
        "range": why.get("model_range"),
        "median": why.get("median_model_probability"),
        "largest_outlier": why.get("largest_outlier"),
    }
    interval = None
    if record.prob_low is not None and record.prob_high is not None:
        interval = [record.prob_low, record.prob_high]
    return {
        "event_group_id": record.event_group_id,
        "domain": record.domain,
        "family": record.family,
        "model_version": record.model_version,
        "oracle_probability": record.oracle_prob,
        "probability_interval": interval,
        "confidence": record.confidence,
        "model_agreement": agreement,
    }


def _comparison_block(record, market) -> dict[str, Any]:
    execution = record.execution or {}
    gross_edge = abs(record.edge_points) if record.edge_points is not None else None
    return {
        "market_probability": market.implied_prob,
        "yes_bid": execution.get("yes_bid"),
        "yes_ask": execution.get("yes_ask"),
        "spread": market.spread,
        "side": record.side,
        "gross_edge": gross_edge,
        "estimated_fees": execution.get("estimated_fee_per_contract"),
        "expected_profit_per_contract": execution.get("expected_profit_per_contract"),
        "expected_return_on_cost": execution.get("expected_return_on_cost"),
        "actionable": bool(record.actionable),
        "reason": record.reason,
    }


def _why_block(record, market) -> dict[str, Any]:
    why = record.why or {}
    limitations: list[str] = list(why.get("limitations") or [])
    if not (why.get("model_probabilities")):
        limitations.append("no component model ensemble was exposed; confidence rests on the engine's documented source path")
    if not record.actionable and record.reason:
        limitations.append(record.reason)
    return {
        "summary": why.get("summary"),
        "method": record.method or why.get("method"),
        "sources": why.get("sources") or {},
        "source_freshness": {"market_fetched_at": market.fetched_at},
        "model_probabilities": why.get("model_probabilities") or {},
        "limitations": limitations,
    }


def _refusal_reason(market, record) -> tuple[str, str, str | None]:
    """Return (reason_code, explanation, missing_capability) for a market that
    could not be priced."""
    if record is not None and record.reason:
        # An engine ran but declined to emit a probability.
        return "MODEL_MISSING", record.reason, record.missing or None
    coverage = classify_market_shape(market)
    code = _COVERAGE_REFUSAL.get(coverage.status, "UNSUPPORTED_MARKET")
    return code, coverage.reason or "market shape is not supported by any wired engine", coverage.reason


def assemble_check_market(
    *,
    request_id: str,
    market,
    record,
    calibration_report: dict[str, Any] | None,
    include,
    settings: Settings,
    receipt_store: DecisionReceiptStore,
    request_payload: dict[str, Any],
    payment_reference: str | None = None,
) -> dict[str, Any]:
    created_at = _now()
    priced = record is not None and record.oracle_prob is not None
    market_block = {
        "venue": market.venue,
        "market_id": market.market_id,
        "question": market.question,
        "yes_subtitle": market.yes_subtitle,
        "resolution_time": market.resolution_time,
        "resolution_source": market.resolution_source,
        "resolution_rule_hash": hash_hex(market.resolution_rule),
    }
    response: dict[str, Any] = {
        "request_id": request_id,
        "service": CHECK_MARKET_SERVICE,
        "status": "priced" if priced else "refused",
        "created_at": created_at,
        "market": market_block,
    }

    if priced:
        family = record.family
        response["forecast"] = _forecast_block(record)
        response["market_comparison"] = _comparison_block(record, market)
        if include.why_trace:
            response["why"] = _why_block(record, market)
        if include.calibration:
            response["calibration"] = _calibration_context(
                calibration_report, family, record.oracle_prob, record.model_version
            )
        receipt_probability: Any = record.oracle_prob
        family_for_scope = family
    else:
        reason_code, explanation, missing = _refusal_reason(market, record)
        family_for_scope = record.family if record is not None else classify_market_shape(market).family
        response["reason_code"] = reason_code
        response["explanation"] = explanation
        response["missing_capability"] = missing
        if include.calibration:
            response["calibration"] = _calibration_context(
                calibration_report, family_for_scope, None, model_version(family_for_scope)
            )
        receipt_probability = {"refused": True, "reason_code": reason_code}

    if include.receipt:
        response["receipt"] = _commit_check_receipt(
            request_id=request_id,
            market=market,
            record=record,
            response=response,
            receipt_probability=receipt_probability,
            family=family_for_scope,
            settings=settings,
            receipt_store=receipt_store,
            request_payload=request_payload,
            payment_reference=payment_reference,
        )
    return response


def _commit_check_receipt(*, request_id, market, record, response, receipt_probability, family,
                          settings, receipt_store, request_payload, payment_reference=None) -> dict[str, Any]:
    forecast = response.get("forecast") or {}
    comparison = response.get("market_comparison") or {}
    calibration = response.get("calibration") or {}
    payload = {
        "request_id": request_id,
        "service": CHECK_MARKET_SERVICE,
        "request_hash": request_hash(request_payload),
        "venue": market.venue,
        "market_id": market.market_id,
        "event_group_id": record.event_group_id if record is not None else None,
        "resolution_rule_hash": hash_hex(market.resolution_rule),
        "model_version": record.model_version if record is not None else model_version(family),
        "probability": receipt_probability,
        "probability_interval": forecast.get("probability_interval"),
        "confidence": forecast.get("confidence"),
        "economics": {
            "market_probability": comparison.get("market_probability"),
            "side": comparison.get("side"),
            "gross_edge": comparison.get("gross_edge"),
            "estimated_fees": comparison.get("estimated_fees"),
            "expected_profit_per_contract": comparison.get("expected_profit_per_contract"),
            "actionable": comparison.get("actionable", False),
        },
        "why_summary": (response.get("why") or {}).get("summary"),
        "calibration_scope": calibration.get("scope"),
        "source_freshness": {"market_fetched_at": market.fetched_at},
        "created_at": response["created_at"],
        "payment_reference": payment_reference,
    }
    committed = receipt_store.commit(payload)
    return {
        "record_hash": committed.record_hash,
        "chain_hash": committed.chain_hash,
        "sequence": committed.sequence,
        "verification_url": settings.verification_url(committed.record_hash),
    }


def run_check_market(
    *,
    request_id: str,
    venue: str,
    market_id: str,
    include,
    settings: Settings,
    receipt_store: DecisionReceiptStore,
    request_payload: dict[str, Any],
    fetch_market: Callable,
    evaluate,
    payment_reference: str | None = None,
) -> dict[str, Any]:
    market = fetch_market(venue, market_id)
    record = evaluate(market)
    calibration_report = load_json_artifact(settings.calibration_report_path)
    return assemble_check_market(
        request_id=request_id,
        market=market,
        record=record,
        calibration_report=calibration_report,
        include=include,
        settings=settings,
        receipt_store=receipt_store,
        request_payload=request_payload,
        payment_reference=payment_reference,
    )


# ----------------------------- cross venue --------------------------------


def _market_facet(market) -> dict[str, Any]:
    return {
        "venue": market.venue,
        "market_id": market.market_id,
        "question": market.question,
        "yes_subtitle": market.yes_subtitle,
        "resolution_source": market.resolution_source,
        "resolution_time": market.resolution_time,
        "resolution_rule_hash": hash_hex(market.resolution_rule),
    }


def assemble_cross_venue(
    *,
    request_id: str,
    left,
    right,
    include,
    settings: Settings,
    receipt_store: DecisionReceiptStore,
    request_payload: dict[str, Any],
    payment_reference: str | None = None,
) -> dict[str, Any]:
    result = cross_venue_edge(left, right)
    created_at = _now()
    equivalence = result["equivalence"]
    response: dict[str, Any] = {
        "request_id": request_id,
        "service": CROSS_VENUE_SERVICE,
        "status": "evaluated",
        "created_at": created_at,
        "left": _market_facet(left),
        "right": _market_facet(right),
        "equivalence": equivalence,
        "edge": result.get("edge"),
        "actionable": bool(result.get("actionable")),
        "reason": result.get("reason"),
        "risk_disclosure": result.get(
            "risk_disclosure",
            "Complementary executable-price edge, subject to fill, custody, venue, "
            "cancellation, and settlement risk.",
        ),
    }
    if include.receipt:
        payload = {
            "request_id": request_id,
            "service": CROSS_VENUE_SERVICE,
            "request_hash": request_hash(request_payload),
            "left": {"venue": left.venue, "market_id": left.market_id,
                     "resolution_rule_hash": hash_hex(left.resolution_rule)},
            "right": {"venue": right.venue, "market_id": right.market_id,
                      "resolution_rule_hash": hash_hex(right.resolution_rule)},
            "equivalence_classification": equivalence.get("classification"),
            "actionable": bool(result.get("actionable")),
            "edge": result.get("edge"),
            "created_at": created_at,
            "payment_reference": payment_reference,
        }
        committed = receipt_store.commit(payload)
        response["receipt"] = {
            "record_hash": committed.record_hash,
            "chain_hash": committed.chain_hash,
            "sequence": committed.sequence,
            "verification_url": settings.verification_url(committed.record_hash),
        }
    return response


def run_cross_venue(
    *,
    request_id: str,
    left_ref,
    right_ref,
    include,
    settings: Settings,
    receipt_store: DecisionReceiptStore,
    request_payload: dict[str, Any],
    fetch_market: Callable,
    payment_reference: str | None = None,
) -> dict[str, Any]:
    left = fetch_market(left_ref.venue, left_ref.market_id)
    right = fetch_market(right_ref.venue, right_ref.market_id)
    if left.venue == right.venue:
        raise OracleError(
            "INVALID_REQUEST",
            "cross-venue edge requires two different venues",
        )
    return assemble_cross_venue(
        request_id=request_id,
        left=left,
        right=right,
        include=include,
        settings=settings,
        receipt_store=receipt_store,
        request_payload=request_payload,
        payment_reference=payment_reference,
    )


# ----------------------------- calibration --------------------------------


def build_calibration(
    *,
    report: dict[str, Any] | None,
    family: str | None = None,
    model_version_filter: str | None = None,
    probability_band: str | None = None,
) -> dict[str, Any]:
    created_at = _now()
    if not report:
        return {
            "service": CALIBRATION_SERVICE,
            "status": "insufficient_evidence",
            "created_at": created_at,
            "report_available": False,
            "message": "no calibration report has been generated yet; evidence is still accumulating",
            "precommitted_forecasts": 0,
            "resolved_forecasts": 0,
            "independent_resolved_event_groups": 0,
            "families": {},
        }
    promotion = report.get("promotion_readiness") or {}
    all_model_evidence = report.get("model_evidence") or {}
    retrospective = report.get("retrospective_validation") or {}
    if family is not None:
        promotion = {family: promotion[family]} if family in promotion else {}
    families: dict[str, Any] = {}
    scoped_model_evidence: dict[str, Any] = {}
    if model_version_filter:
        candidate_families = [family] if family is not None else sorted(all_model_evidence)
        for fam in candidate_families:
            row = (all_model_evidence.get(fam) or {}).get(model_version_filter)
            if row is None:
                continue
            scoped_row = dict(row)
            if probability_band:
                band_calibration = (row.get("calibration_by_probability_band") or {}).get(probability_band)
                band_gate = next((item for item in
                                  (row.get("probability_band_gate") or {}).get("bands", [])
                                  if item.get("bucket") == probability_band), None)
                precommitted = int((row.get("precommitted_by_probability_band") or {}).get(probability_band, 0))
                resolved = int((band_calibration or {}).get("count") or 0)
                scoped_row.update({
                    "precommitted_contract_rows": precommitted,
                    "resolved_contract_rows": resolved,
                    "unresolved_contract_rows": max(0, precommitted - resolved),
                    "independent_event_groups": int((band_gate or {}).get("independent_event_groups") or 0),
                    "calibration": band_calibration,
                    "selected_probability_band": probability_band,
                })
            scoped_model_evidence.setdefault(fam, {})[model_version_filter] = scoped_row
            families[fam] = scoped_row
            current = promotion.get(fam) or {}
            if current.get("model_version") == model_version_filter:
                families[fam] = {**scoped_row, "promotion_readiness": current}
    else:
        families = dict(promotion)
        scoped_model_evidence = {
            fam: versions for fam, versions in all_model_evidence.items()
            if family is None or fam == family
        }
    scoped_retro = {
        fam: row for fam, row in retrospective.items()
        if (family is None or fam == family) and
        (model_version_filter is None or model_version_filter in {
            row.get("target_model_version"), row.get("source_model_version")
        })
    }
    selected_rows = [row for versions in scoped_model_evidence.values() for row in versions.values()]
    scoped_precommitted = sum(int(row.get("precommitted_contract_rows") or 0) for row in selected_rows)
    scoped_resolved = sum(int(row.get("resolved_contract_rows") or 0) for row in selected_rows)
    scoped_groups = sum(int(row.get("independent_event_groups") or 0) for row in selected_rows)
    exact_calibration = selected_rows[0].get("calibration") if len(selected_rows) == 1 else None
    return {
        "service": CALIBRATION_SERVICE,
        "status": "ok",
        "created_at": created_at,
        "report_available": True,
        "report_created_at": report.get("created_at"),
        "precommitted_forecasts": scoped_precommitted if model_version_filter else report.get("precommitted_forecasts", 0),
        "resolved_forecasts": scoped_resolved if model_version_filter else report.get("resolved_forecasts", 0),
        "unresolved_forecasts": (scoped_precommitted - scoped_resolved) if model_version_filter else report.get("unresolved_forecasts", 0),
        "independent_resolved_event_groups": scoped_groups if model_version_filter else report.get("independent_resolved_event_groups", 0),
        "calibration": exact_calibration if model_version_filter else report.get("calibration"),
        "families": families,
        "model_evidence": scoped_model_evidence,
        "retrospective_validation": scoped_retro,
        "ledger_verification": report.get("ledger_verification"),
        "selection_policy": report.get("selection_policy"),
        "filters": {
            "family": family,
            "model_version": model_version_filter,
            "probability_band": probability_band,
        },
        "warning": "band and family hit rates are evidence only with their displayed independent sample counts",
    }
