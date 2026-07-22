"""Pydantic request/response schemas.

Requests are strict (unknown fields rejected, types validated) so malformed
input fails fast with INVALID_REQUEST. Responses are documented models whose
optional fields default to null, so the deterministic assembly can never 500
on a field the engine legitimately did not produce (e.g. no model ensemble was
exposed). Venue is accepted as a plain string and validated in code so an
unknown venue becomes a stable UNSUPPORTED_VENUE rather than a schema error.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _OpenModel(BaseModel):
    # Response models tolerate extra keys and default everything optional.
    model_config = ConfigDict(extra="allow")


# ----------------------------- requests -----------------------------------


class MarketRef(_StrictModel):
    venue: str = Field(
        ...,
        min_length=1,
        examples=["polymarket"],
        description="Supported venue name: kalshi, polymarket, or limitless.",
    )
    market_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        examples=["fed-decision-in-october"],
        description=(
            "Venue-native identifier. For Polymarket, accepts a numeric Gamma market ID, "
            "a 0x-prefixed condition ID, an exact market slug, or a single-market event slug. "
            "Use GET /v1/market-candidates to discover current identifiers."
        ),
    )
    question: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Optional informational label for logs/clients. It is not used to resolve a market "
            "and never substitutes for the required exact market_id."
        ),
    )


class IncludeOptions(_StrictModel):
    why_trace: bool = True
    calibration: bool = True
    receipt: bool = True


class CheckMarketRequest(_StrictModel):
    market: MarketRef = Field(
        ...,
        description="Required market reference object with both venue and market_id.",
    )
    include: IncludeOptions = Field(default_factory=IncludeOptions)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "market": {
                    "venue": "polymarket",
                    "market_id": "<current-id-from-/v1/market-candidates>",
                },
                "include": {"why_trace": True, "calibration": True, "receipt": True},
            }
        },
    )


class VenueRef(_StrictModel):
    venue: str = Field(
        ..., min_length=1, max_length=32,
        description="Supported venue name: kalshi, polymarket, or limitless.",
    )
    market_id: str = Field(
        ..., min_length=1, max_length=256,
        description="Exact venue-native identifier; current IDs are available from /v1/market-candidates.",
    )


class CrossVenueRequest(_StrictModel):
    left: VenueRef
    right: VenueRef
    include: IncludeOptions = Field(default_factory=IncludeOptions)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "left": {"venue": "kalshi", "market_id": "<current-kalshi-id>"},
                "right": {"venue": "polymarket", "market_id": "<current-polymarket-id>"},
            }
        },
    )


class SignalRequest(_StrictModel):
    message: str = Field(..., min_length=3, max_length=500, examples=["Give me the best weather signals now"])
    limit: int = Field(default=5, ge=1, le=10)
    min_minutes_to_close: int | None = Field(default=None, ge=5, le=10080)
    cursor: str | None = Field(default=None, min_length=8, max_length=500)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {"message": "Give me the best weather signals now", "limit": 5}
        },
    )


class PrepareExecutionRequest(_StrictModel):
    venue: str = Field(default="polymarket", pattern="^polymarket$")
    market_id: str = Field(..., min_length=1, max_length=256)
    token_id: str = Field(..., min_length=1, max_length=256,
                          description="Venue-native outcome token identifier; never a wallet secret.")
    side: str = Field(..., pattern="^(YES|NO)$")
    price: str = Field(..., min_length=1, max_length=32,
                       description="Limit price as an exact decimal string between 0 and 1.")
    quantity: str = Field(..., min_length=1, max_length=32,
                          description="Contract quantity as an exact decimal string.")
    time_in_force: str = Field(default="GTC", pattern="^(GTC|GTD|FOK|FAK)$")
    event_group_id: str = Field(..., min_length=1, max_length=256)
    decision_receipt_hash: str = Field(..., min_length=32, max_length=128,
                                       description="Receipt for the actionable oracle decision authorizing this intent.")


class SubmitExecutionRequest(_StrictModel):
    operator_approval_id: str = Field(..., min_length=1, max_length=200)


# ----------------------------- responses ----------------------------------


class ReceiptRef(_OpenModel):
    record_hash: str | None = None
    chain_hash: str | None = None
    sequence: int | None = None
    verification_url: str | None = None


class ModelAgreement(_OpenModel):
    available: bool = False
    model_count: int | None = None
    range: list[float] | None = None
    median: float | None = None
    largest_outlier: dict[str, Any] | None = None


class Forecast(_OpenModel):
    event_group_id: str | None = None
    domain: str | None = None
    family: str | None = None
    model_version: str | None = None
    oracle_probability: float | None = None
    probability_interval: list[float | None] | None = None
    confidence: float | None = None
    model_agreement: ModelAgreement | None = None


class MarketComparison(_OpenModel):
    market_probability: float | None = None
    yes_bid: float | None = None
    yes_ask: float | None = None
    spread: float | None = None
    side: str | None = None
    gross_edge: float | None = None
    estimated_fees: float | None = None
    expected_profit_per_contract: float | None = None
    expected_return_on_cost: float | None = None
    actionable: bool = False
    reason: str | None = None


class WhyTrace(_OpenModel):
    summary: str | None = None
    method: str | None = None
    sources: dict[str, Any] = Field(default_factory=dict)
    source_freshness: dict[str, Any] = Field(default_factory=dict)
    model_probabilities: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)


class CalibrationContext(_OpenModel):
    status: str = "accumulating"
    scope: dict[str, Any] = Field(default_factory=dict)
    independent_resolved_events: int = 0
    next_checkpoint: int | None = None
    promotion_eligible: bool = False
    criteria: dict[str, Any] = Field(default_factory=dict)


class CheckMarketResponse(_OpenModel):
    request_id: str
    service: str
    status: str
    created_at: str
    market: dict[str, Any] = Field(default_factory=dict)
    forecast: Forecast | None = None
    market_comparison: MarketComparison | None = None
    why: WhyTrace | None = None
    calibration: CalibrationContext | None = None
    receipt: ReceiptRef | None = None
    reason_code: str | None = None
    explanation: str | None = None
    missing_capability: str | None = None


class CrossVenueResponse(_OpenModel):
    request_id: str
    service: str
    status: str
    created_at: str
    left: dict[str, Any] = Field(default_factory=dict)
    right: dict[str, Any] = Field(default_factory=dict)
    equivalence: dict[str, Any] = Field(default_factory=dict)
    edge: dict[str, Any] | None = None
    actionable: bool = False
    risk_disclosure: str | None = None
    reason: str | None = None
    receipt: ReceiptRef | None = None


class SignalResponse(_OpenModel):
    request_id: str
    service: str
    status: str
    created_at: str
    answer: str
    signals: list[dict[str, Any]] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    pagination: dict[str, Any] = Field(default_factory=dict)
    evidence_notice: str | None = None
    receipt: ReceiptRef | None = None


class CalibrationResponse(_OpenModel):
    service: str
    status: str
    created_at: str
    report_available: bool
    report_created_at: str | None = None
    message: str | None = None
    precommitted_forecasts: int = 0
    resolved_forecasts: int = 0
    unresolved_forecasts: int = 0
    independent_resolved_event_groups: int = 0
    calibration: Any | None = None
    families: dict[str, Any] = Field(default_factory=dict)
    model_evidence: dict[str, Any] = Field(default_factory=dict)
    retrospective_validation: dict[str, Any] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)
    warning: str | None = None


class MarketCandidatesResponse(_OpenModel):
    scan_created_at: str | None = None
    venue: str | None = None
    query: str | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    source: str
    freshness_status: str
    note: str


class ExecutionResponse(_OpenModel):
    intent_id: str
    state: str
    venue: str
    market_id: str
    token_id: str
    side: str
    price: str
    quantity: str
    notional: str
    order_type: str
    time_in_force: str
    event_group_id: str
    decision_receipt_hash: str | None = None
    venue_order_id: str | None = None
    filled_quantity: str = "0"
    average_fill_price: str | None = None
    last_error: str | None = None
    created_at: str
    updated_at: str
    events: list[dict[str, Any]] = Field(default_factory=list)


class ErrorEnvelope(_OpenModel):
    error: dict[str, Any]
    request_id: str
