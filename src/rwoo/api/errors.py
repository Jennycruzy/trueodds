"""Stable error taxonomy and JSON error shape.

Every error the API can return has a stable machine code from ERROR_CODES.
`OracleError` carries the code, an HTTP status, and a safe public message; the
handlers in app.py turn it (and framework/validation errors) into the single
JSON error envelope. No stack trace, upstream body, secret, or private payment
field is ever placed in a response.
"""
from __future__ import annotations

from typing import Any

# Stable error codes (also the documented set in the spec). The HTTP status is
# how the transport signals the class of failure; the `code` is what agents
# branch on.
ERROR_CODES: dict[str, int] = {
    "INVALID_REQUEST": 400,
    "IDEMPOTENCY_CONFLICT": 409,
    "MARKET_NOT_FOUND": 404,
    "UNSUPPORTED_VENUE": 400,
    "UNSUPPORTED_MARKET": 422,
    "ENTITY_UNBOUND": 422,
    "YES_SIDE_UNBOUND": 422,
    "SOURCE_UNAVAILABLE": 503,
    "SOURCE_STALE": 422,
    "SOURCE_CONFLICT": 422,
    "MODEL_MISSING": 422,
    "FEE_UNKNOWN": 422,
    "RATE_LIMITED": 429,
    "PAYMENT_REQUIRED": 402,
    "PAYMENT_INVALID": 402,
    "PAYMENT_REPLAYED": 402,
    "UPSTREAM_TIMEOUT": 504,
    "INTERNAL_ERROR": 500,
    "NOT_FOUND": 404,
    "SERVICE_NOT_FOUND": 404,
    "SIGNALS_UNAVAILABLE": 503,
    "SIGNALS_STALE": 503,
    "INVALID_EXECUTION": 400,
    "EXECUTION_NOT_FOUND": 404,
    "EXECUTION_DISABLED": 423,
    "INVALID_EXECUTION_STATE": 409,
    "RISK_LIMIT_EXCEEDED": 422,
    "APPROVAL_REQUIRED": 403,
    "INVALID_VENUE_RESPONSE": 502,
}

# Codes that a check-market/cross-venue call surfaces as a *refused* decision
# (HTTP 200, status="refused") rather than a transport error. These are honest
# "cannot safely price this" outcomes, not malformed requests.
REFUSAL_CODES = {
    "UNSUPPORTED_MARKET",
    "ENTITY_UNBOUND",
    "YES_SIDE_UNBOUND",
    "SOURCE_STALE",
    "SOURCE_CONFLICT",
    "MODEL_MISSING",
    "FEE_UNKNOWN",
}


class OracleError(Exception):
    """A request-level error with a stable code. `http_status` overrides the
    default from ERROR_CODES when a specific case needs a different status."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if code not in ERROR_CODES:
            code = "INTERNAL_ERROR"
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status or ERROR_CODES[code]
        self.details = details or {}

    def to_body(self, request_id: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "error": {
                "code": self.code,
                "message": self.message,
            },
            "request_id": request_id,
        }
        if self.details:
            body["error"]["details"] = self.details
        return body
