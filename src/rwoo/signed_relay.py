"""Caller-signed Polymarket order relay.

The ASP never receives a private key here. A caller signs locally, sends the
exact serialized CLOB body plus caller-computed L2 headers, and this module
checks that the signed order matches the prepared intent before relaying the
original bytes unchanged.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

import httpx

from rwoo.execution import ExecutionError, VenueResult, canonical

CLOB_ORDER_URL = "https://clob.polymarket.com/order"
BASE_UNITS = Decimal("1000000")
REQUIRED_POLY_HEADERS = (
    "POLY_ADDRESS",
    "POLY_API_KEY",
    "POLY_PASSPHRASE",
    "POLY_SIGNATURE",
    "POLY_TIMESTAMP",
)


@dataclass(frozen=True)
class SignedOrderPayload:
    body_bytes: bytes
    body_hash: str
    headers: dict[str, str]
    parsed: dict[str, Any]


def decode_signed_order(body_base64: str, headers: dict[str, str]) -> SignedOrderPayload:
    try:
        body_bytes = base64.b64decode(body_base64, validate=True)
    except Exception as exc:
        raise ExecutionError("INVALID_EXECUTION", "signed order body must be base64") from exc
    if not body_bytes:
        raise ExecutionError("INVALID_EXECUTION", "signed order body is empty")
    try:
        parsed = json.loads(body_bytes)
    except json.JSONDecodeError as exc:
        raise ExecutionError("INVALID_EXECUTION", "signed order body is not JSON") from exc
    if not isinstance(parsed, dict):
        raise ExecutionError("INVALID_EXECUTION", "signed order body must be a JSON object")
    normalized_headers = {str(k).upper(): str(v) for k, v in headers.items()}
    missing = [name for name in REQUIRED_POLY_HEADERS if not normalized_headers.get(name)]
    if missing:
        raise ExecutionError("INVALID_EXECUTION", f"missing Polymarket headers: {', '.join(missing)}")
    return SignedOrderPayload(
        body_bytes=body_bytes,
        body_hash=hashlib.sha256(body_bytes).hexdigest(),
        headers={name: normalized_headers[name] for name in REQUIRED_POLY_HEADERS},
        parsed=parsed,
    )


def validate_signed_order_matches_intent(intent: dict[str, Any], payload: SignedOrderPayload) -> None:
    order = payload.parsed.get("order")
    if not isinstance(order, dict):
        raise ExecutionError("SIGNED_ORDER_MISMATCH", "signed payload is missing order object")
    if str(payload.parsed.get("orderType") or intent.get("time_in_force")) != intent.get("time_in_force"):
        raise ExecutionError("SIGNED_ORDER_MISMATCH", "signed order time_in_force does not match intent")
    _require_equal(order, "tokenId", intent["token_id"])
    _require_equal(order, "side", "BUY")
    _require_equal(order, "signatureType", 3)
    maker = str(order.get("maker") or "")
    signer = str(order.get("signer") or "")
    if not maker or maker.lower() != signer.lower():
        raise ExecutionError("SIGNED_ORDER_MISMATCH", "POLY_1271 order must use deposit wallet as maker and signer")
    if not str(order.get("signature") or "").startswith("0x"):
        raise ExecutionError("SIGNED_ORDER_MISMATCH", "signed order is missing a signature")
    price = Decimal(intent["price"])
    quantity = Decimal(intent["quantity"])
    expected_maker = _base_units(price * quantity)
    expected_taker = _base_units(quantity)
    _require_equal(order, "makerAmount", expected_maker)
    _require_equal(order, "takerAmount", expected_taker)
    expiration = str(order.get("expiration", "0"))
    if not expiration.isdigit():
        raise ExecutionError("SIGNED_ORDER_MISMATCH", "signed order expiration must be numeric")


def relay_signed_order(payload: SignedOrderPayload, *, post: Callable[..., Any] | None = None) -> VenueResult:
    post = post or _post_to_polymarket
    response = post(CLOB_ORDER_URL, headers=payload.headers, content=payload.body_bytes)
    status_code = getattr(response, "status_code", 200)
    try:
        data = response.json()
    except Exception as exc:
        raise ExecutionError("VENUE_RELAY_FAILED", "Polymarket returned a non-JSON response") from exc
    if status_code >= 500:
        raise RuntimeError(f"Polymarket relay status {status_code}")
    if status_code >= 400 or data.get("success") is False or data.get("error"):
        message = str(data.get("error") or data.get("errorMsg") or f"Polymarket rejected order with HTTP {status_code}")
        return VenueResult(state="REJECTED", message=message)
    order_id = data.get("orderID") or data.get("orderId")
    if not order_id:
        raise ExecutionError("INVALID_VENUE_RESPONSE", "Polymarket accepted response without order id")
    return VenueResult(state="OPEN", venue_order_id=str(order_id), message=str(data.get("status") or "live"))


def _post_to_polymarket(url: str, *, headers: dict[str, str], content: bytes):
    with httpx.Client(timeout=20) as client:
        return client.post(url, headers=headers, content=content)


def _require_equal(container: dict[str, Any], field: str, expected: Any) -> None:
    if str(container.get(field)) != str(expected):
        raise ExecutionError("SIGNED_ORDER_MISMATCH", f"signed order {field} does not match prepared intent")


def _base_units(amount: Decimal) -> str:
    scaled = amount * BASE_UNITS
    if scaled != scaled.to_integral_value():
        raise ExecutionError("INVALID_EXECUTION", f"{canonical(amount)} does not convert to exact base units")
    return str(int(scaled))
