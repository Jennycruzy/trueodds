"""FastAPI application factory for the Real-World Odds Oracle ASP.

The app is a thin, secure transport over the deterministic core. It adds a
request id to every call, restricts origins/hosts, caps body size, never caches
priced responses, hides stack traces, and returns one stable JSON error shape.
The three paid services and the read-only supporting endpoints all delegate to
`rwoo.api.services`, which delegates every probability to the engines.

Payment (OKX Agent Payments / x402 402 flow) is enforced by `enforce_payment`
per protected service (see rwoo.api.payment). It is a no-op while disabled and
fails CLOSED if enabled before the settlement path is fully configured, so a
paid endpoint can never be served for free and a dev stub can never be reached
in production by accident.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import os
import uuid
from datetime import datetime, timezone
from typing import Any
from weakref import WeakValueDictionary

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from rwoo.api import API_VERSION
from rwoo.api.config import Settings, get_settings
from rwoo.api.errors import OracleError
from rwoo.api.market_fetch import SUPPORTED_VENUES, discover_live_candidates, fetch_canonical
from rwoo.api import payment as payment_mod
from rwoo.api.payment import (
    PaymentConfig,
    PaymentError,
    PaymentRequired,
    ReplayStore,
    build_challenge,
    select_verifier,
    validate_startup,
    verify_payment,
)
from rwoo.api.receipt_store import DecisionReceiptStore, IdempotencyCache, request_hash
from rwoo.api.schemas import (
    CheckMarketRequest,
    CheckMarketResponse,
    CalibrationResponse,
    CrossVenueRequest,
    CrossVenueResponse,
    ErrorEnvelope,
    MarketCandidatesResponse,
    SignalRequest,
    SignalResponse,
    PrepareExecutionRequest,
    SubmitExecutionRequest,
    SubmitSignedExecutionRequest,
    ExecutionResponse,
)
from rwoo.api import services
from rwoo.api.signals import SERVICE as SIGNAL_SERVICE, rank_signals
from rwoo.identity import MODEL_VERSIONS
from rwoo.expansion_coverage import (
    ACTIVE_EXPANSION_COVERAGE,
    INTERNAL_DISCOVERY_COVERAGE,
    expansion_scan_summary,
)
from rwoo.scanner import ECONOMICS_SERIES, SPORTS_SERIES, WEATHER_SERIES, evaluate_market
from rwoo.sports_coverage import SPORTS_COVERAGE, sports_scan_summary
from rwoo.execution import ExecutionCoordinator, ExecutionError, ExecutionStore
from rwoo.adapters.polymarket import COLLATERAL, funding_routes
from rwoo.signed_relay import (
    decode_signed_order,
    relay_signed_order,
    validate_signed_order_matches_intent,
)

REQUEST_ID_HEADER = "X-Request-ID"
IDEMPOTENCY_HEADER = "Idempotency-Key"
IDEMPOTENCY_REPLAY_HEADER = "X-Idempotent-Replay"

_IDEMPOTENT_ROUTES = {
    ("POST", "/"),
    ("GET", "/v1/signals"),
    ("POST", "/v1/signals"),
    ("POST", "/v1/check-market"),
    ("POST", "/v1/cross-venue-edge"),
    ("POST", "/v1/executions/prepare"),
    ("POST", "/v1/executions/{intent_id}/submit-signed"),
}

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def _request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    return rid or request.headers.get(REQUEST_ID_HEADER) or f"req_{uuid.uuid4().hex}"


_SERVICE_DESCRIPTION = {
    "rwoo.best_signals": "Ranks open Kalshi, Polymarket, and Limitless opportunities across supported weather, economics, Henry Hub natural gas, and sports markets after freshness, price, spread, model, and evidence checks.",
    "rwoo.check_market": "Evaluates one supported weather, economics, Henry Hub, or sports market on Kalshi, Polymarket, or Limitless, returning probability, uncertainty, executable-price EV, source trace, calibration, and a receipt.",
    "rwoo.cross_venue_edge": "Compares equivalent contracts across Kalshi, Polymarket, and Limitless; verifies event rules, resolution authority, timing, and YES orientation; then reports conservative executable edge and risk.",
}

_PROBABILITY_BANDS = tuple(f"{index / 10:.1f}-{(index + 1) / 10:.1f}" for index in range(10))


def _execution_client_package(intent: dict[str, Any], settings: Settings) -> dict[str, Any]:
    base_url = settings.api_base_url.rstrip("/")
    submit_url = f"{base_url}/v1/executions/{intent['intent_id']}/submit-signed"
    return {
        "mode": "caller_side_signed",
        "custody": "caller keeps signing authority and funds; ASP receives only signed order bytes and L2 headers",
        "target_collateral": {
            "chain": "eip155:137",
            **COLLATERAL,
        },
        "wallet_backends": [
            {
                "id": "okx_agentic_wallet",
                "status": "funding_ready_order_signing_adapter_pending",
                "auth": "email_or_api_key_session",
                "requires_private_key_env": False,
                "capabilities": [
                    "evm_address",
                    "evm_contract_call",
                    "evm_token_transfer",
                    "cross_chain_execute",
                    "eip712_sign_message",
                ],
                "note": (
                    "normal ASP agents can use an authenticated OKX Agentic Wallet "
                    "session for funding; Polymarket POLY_1271 order signing still "
                    "needs a verified Agentic Wallet signer adapter"
                ),
            },
            {
                "id": "local_private_key",
                "status": "executable",
                "auth": "local_env_private_key",
                "requires_private_key_env": True,
                "capabilities": [
                    "evm_address",
                    "evm_contract_call",
                    "evm_token_transfer",
                    "polymarket_l2_headers",
                    "poly_1271_order_sign",
                ],
                "note": "developer fallback used by the live spike and offline tests",
            },
        ],
        "funding_routes": funding_routes(),
        "submit_signed": {
            "method": "POST",
            "url": submit_url,
            "body": {"body_base64": "<exact Polymarket /order bytes>", "headers": "<caller L2 headers>"},
        },
        "helper": {
            "package": "scripts/polymarket_agent_helper.py",
            "one_flow_local_key": (
                "python scripts/polymarket_agent_helper.py --intent-file <prepared.json> "
                f"--asp-url {base_url} --wallet-backend local-private-key --execute"
            ),
            "funding_plan_agentic_wallet": (
                "python scripts/polymarket_agent_helper.py --intent-file <prepared.json> "
                "--wallet-backend okx-agentic-wallet --funding-plan --source-asset xlayer-usdt"
            ),
            "local_secret_boundary": "private key material, if any exists, stays inside the caller-side wallet backend",
        },
    }


def _enrich_execution(intent: dict[str, Any], settings: Settings) -> dict[str, Any]:
    enriched = copy.deepcopy(intent)
    if enriched.get("venue") == "polymarket":
        enriched["client_execution"] = _execution_client_package(enriched, settings)
    return enriched


def _validate_calibration_scope(
    report: dict[str, Any] | None,
    *,
    family: str | None,
    model_version: str | None,
    probability_band: str | None,
) -> None:
    if probability_band is not None and probability_band not in _PROBABILITY_BANDS:
        raise OracleError(
            "INVALID_REQUEST",
            f"unknown probability_band {probability_band!r}",
            details={"available_probability_bands": list(_PROBABILITY_BANDS)},
        )
    if family is None:
        return
    report = report or {}
    evidence = report.get("model_evidence") or {}
    promotion = report.get("promotion_readiness") or {}
    retrospective = report.get("retrospective_validation") or {}
    available_families = sorted(set(MODEL_VERSIONS) | set(evidence) | set(promotion) | set(retrospective))
    if family not in available_families:
        raise OracleError(
            "NOT_FOUND",
            f"unknown calibration family {family!r}",
            details={"available_families": available_families},
        )
    if model_version is None:
        return
    versions = set((evidence.get(family) or {}).keys())
    if family in MODEL_VERSIONS:
        versions.add(MODEL_VERSIONS[family])
    retrospective_row = retrospective.get(family) or {}
    versions.update(
        value for value in (
            retrospective_row.get("target_model_version"),
            retrospective_row.get("source_model_version"),
        ) if value
    )
    if model_version not in versions:
        raise OracleError(
            "NOT_FOUND",
            f"unknown model version {model_version!r} for family {family!r}",
            details={"family": family, "available_model_versions": sorted(versions)},
        )


def enforce_payment(request: Request, service: str, payload: dict[str, Any]) -> str | None:
    """Enforce the OKX Agent Payments 402 flow for a protected service.

    Returns a payment reference to embed in the decision receipt, or None when
    payments are disabled (free deployment). Raises PaymentRequired (402
    challenge) when no payment is presented, or PaymentError on a bad payment.
    """
    config: PaymentConfig = request.app.state.payment_config
    if not config.enabled:
        return None
    # The official middleware has already verified and settled facilitator
    # payments before the request can reach this handler.
    if config.mode == "facilitator":
        return None
    resource = request.url.path
    req_hash = request_hash(payload)
    x_payment = request.headers.get(payment_mod.X_PAYMENT_HEADER)
    if not x_payment:
        challenge = build_challenge(
            config, service, resource, req_hash,
            description=_SERVICE_DESCRIPTION.get(service, service),
        )
        raise PaymentRequired(challenge)
    result = verify_payment(
        config=config,
        verifier=request.app.state.payment_verifier,
        replay_store=request.app.state.replay_store,
        service=service,
        resource=resource,
        request_hash=req_hash,
        x_payment=x_payment,
    )
    if result.settlement is not None:
        # Surfaced to the caller as the PAYMENT-RESPONSE header by the middleware.
        request.state.payment_response = payment_mod.encode_payment_header(result.settlement)
    return result.payment_reference


def create_app(
    settings: Settings | None = None,
    *,
    fetch_market=fetch_canonical,
    evaluate=evaluate_market,
    payment_config: PaymentConfig | None = None,
    payment_verifier=None,
    execution_adapter=None,
) -> FastAPI:
    settings = settings or get_settings()
    payment_config = payment_config if payment_config is not None else PaymentConfig.from_env()
    validate_startup(payment_config)  # fail closed if enabled but unsafe/incomplete

    app = FastAPI(
        title="Real-World Odds Oracle API",
        version=API_VERSION,
        description=(
            "The true odds, proven. A paid, evidence-backed decision oracle for "
            "data-resolvable prediction markets. Every probability is produced by a "
            "deterministic engine; the API reads a market, compares it to the "
            "independent probability net of uncertainty and cost, and commits a "
            "tamper-evident receipt."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact=(
            {"name": "Real-World Odds Oracle", "email": settings.support_email}
            if not settings.support_email.endswith(".invalid") else None
        ),
        license_info={"name": "See repository LICENSE"},
    )

    app.state.settings = settings
    app.state.receipt_store = DecisionReceiptStore(settings.decision_ledger_path)
    app.state.idempotency = IdempotencyCache()
    app.state.idempotency_locks = WeakValueDictionary()
    app.state.fetch_market = fetch_market
    app.state.evaluate = evaluate
    app.state.payment_config = payment_config
    app.state.payment_verifier = payment_verifier if payment_verifier is not None else select_verifier(payment_config)
    app.state.replay_store = ReplayStore()
    app.state.execution = ExecutionCoordinator(
        ExecutionStore(settings.execution_db_path),
        mode=settings.execution_mode,
        adapter=execution_adapter,
        max_order_usd=settings.execution_max_order_usd,
    )

    if payment_config.enabled and payment_config.mode == "facilitator":
        _install_official_x402(app, payment_config)

    # --- middleware (added last runs first / outermost) ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", REQUEST_ID_HEADER, IDEMPOTENCY_HEADER, "X-PAYMENT", "PAYMENT-SIGNATURE"],
        expose_headers=[
            REQUEST_ID_HEADER,
            IDEMPOTENCY_REPLAY_HEADER,
            "PAYMENT-REQUIRED",
            payment_mod.PAYMENT_RESPONSE_HEADER,
            "WWW-Authenticate",
        ],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

    @app.middleware("http")
    async def _request_context(request: Request, call_next):
        rid = request.headers.get(REQUEST_ID_HEADER) or f"req_{uuid.uuid4().hex}"
        if len(rid) > 200 or not rid.isascii() or any(ord(char) < 32 for char in rid):
            rid = f"req_{uuid.uuid4().hex}"
        request.state.request_id = rid

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                parsed_length = int(content_length)
                if parsed_length < 0 or parsed_length > settings.max_body_bytes:
                    return _error_response(
                        OracleError("INVALID_REQUEST", "request body exceeds the size limit"), rid
                    )
            except ValueError:
                return _error_response(OracleError("INVALID_REQUEST", "invalid Content-Length"), rid)

        try:
            # Enforce the real body size as well as Content-Length so chunked
            # requests cannot bypass the application limit. Starlette caches
            # this body for FastAPI's downstream parser.
            raw_body = await request.body()
            if len(raw_body) > settings.max_body_bytes:
                return _error_response(
                    OracleError("INVALID_REQUEST", "request body exceeds the size limit"), rid
                )

            idem = request.headers.get(IDEMPOTENCY_HEADER)
            idempotent_route = (request.method.upper(), request.url.path) in _IDEMPOTENT_ROUTES
            if idem and idempotent_route:
                if len(idem) > 200 or not idem.isascii() or any(ord(char) < 33 for char in idem):
                    raise OracleError(
                        "INVALID_REQUEST",
                        "Idempotency-Key must be 1-200 visible ASCII characters without spaces",
                    )
                fingerprint = hashlib.sha256(b"\0".join([
                    request.method.upper().encode("ascii"),
                    request.url.path.encode("utf-8"),
                    request.url.query.encode("utf-8"),
                    raw_body,
                    # Bind a paid cached deliverable to the exact payment
                    # credential as well as its request. Idempotency keys are
                    # not authentication tokens and may be observable in logs.
                    (
                        request.headers.get("PAYMENT-SIGNATURE")
                        or request.headers.get(payment_mod.X_PAYMENT_HEADER)
                        or ""
                    ).encode("utf-8"),
                ])).hexdigest()
                lock = request.app.state.idempotency_locks.get(idem)
                if lock is None:
                    lock = asyncio.Lock()
                    request.app.state.idempotency_locks[idem] = lock
                async with lock:
                    try:
                        cached = request.app.state.idempotency.get(idem, fingerprint)
                    except ValueError as exc:
                        raise OracleError(
                            "IDEMPOTENCY_CONFLICT",
                            "Idempotency-Key is already bound to a different request",
                            details={"action": "use a new Idempotency-Key for the changed request"},
                        ) from exc
                    if cached is not None:
                        request.state.idempotency_replay = True
                        headers = dict(cached["headers"])
                        headers[IDEMPOTENCY_REPLAY_HEADER] = "true"
                        response = Response(
                            content=cached["body"],
                            status_code=cached["status_code"],
                            headers=headers,
                            media_type=cached.get("media_type"),
                        )
                    else:
                        response = await call_next(request)
                        if 200 <= response.status_code < 300:
                            response_body = b"".join([chunk async for chunk in response.body_iterator])
                            cached_response = {
                                "body": response_body,
                                "status_code": response.status_code,
                                "headers": {**dict(response.headers), REQUEST_ID_HEADER: rid},
                                "media_type": response.media_type,
                            }
                            request.app.state.idempotency.put(idem, fingerprint, cached_response)
                            response = Response(
                                content=response_body,
                                status_code=response.status_code,
                                headers=dict(response.headers),
                                media_type=response.media_type,
                                background=response.background,
                            )
            else:
                response = await call_next(request)
        except OracleError as exc:
            return _error_response(exc, rid)
        except Exception:  # never leak a stack trace
            return _error_response(OracleError("INTERNAL_ERROR", "internal error"), rid)

        if not getattr(request.state, "idempotency_replay", False):
            response.headers[REQUEST_ID_HEADER] = rid
        for key, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        payment_response = getattr(request.state, "payment_response", None)
        if payment_response:
            response.headers[payment_mod.PAYMENT_RESPONSE_HEADER] = payment_response
        # Never cache priced responses or any API result.
        if request.url.path.startswith("/v1") or request.url.path in {"/health", "/healthz"}:
            response.headers["Cache-Control"] = "no-store"
        return response

    _register_exception_handlers(app)
    _register_routes(app, settings)
    _install_custom_openapi(app, settings)
    return app


def _error_response(exc: OracleError, request_id: str) -> JSONResponse:
    resp = JSONResponse(status_code=exc.http_status, content=exc.to_body(request_id))
    resp.headers[REQUEST_ID_HEADER] = request_id
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _install_official_x402(app: FastAPI, config: PaymentConfig) -> None:
    """Install the upstream x402 v2 verify+settle middleware for live mode."""
    try:
        from x402.http import (
            OKXAuthConfig,
            OKXFacilitatorClient,
            OKXFacilitatorConfig,
            PaymentOption,
        )
        from x402.http.facilitator_client_base import FacilitatorResponseError
        from x402.http.middleware.fastapi import PaymentMiddlewareASGI
        from x402.http.okx_facilitator_client import OKXFacilitatorResponseError
        from x402.http.types import RouteConfig
        from x402.mechanisms.evm.exact.server import ExactEvmScheme
        from x402.schemas import AssetAmount
        from x402.server import x402ResourceServer
    except ImportError as exc:
        raise RuntimeError("live payments require the pinned OKX x402 seller SDK") from exc

    if not str(config.network).startswith("eip155:"):
        raise RuntimeError("live x402 EVM network must use a CAIP-2 eip155:<chain-id> identifier")
    raw_facilitator = OKXFacilitatorClient(OKXFacilitatorConfig(
        auth=OKXAuthConfig(
            api_key=str(config.okx_api_key),
            secret_key=str(config.okx_secret_key),
            passphrase=str(config.okx_passphrase),
        ),
        base_url=str(config.facilitator_url),
        sync_settle=True,
    ))

    class _SafeOKXFacilitator:
        """Normalize an upstream OKX SDK error-type mismatch for middleware.

        Version 0.1.1 raises ``OKXFacilitatorResponseError`` while its FastAPI
        middleware catches only ``FacilitatorResponseError``. Translate that
        narrow case so expired/invalid credentials or facilitator downtime
        produce a controlled 502 rather than an application 500.
        """

        def __init__(self, client):
            self._client = client

        @staticmethod
        def _normalized(exc: Exception) -> FacilitatorResponseError:
            return FacilitatorResponseError("OKX payment facilitator is unavailable")

        def get_supported(self):
            try:
                return self._client.get_supported()
            except OKXFacilitatorResponseError as exc:
                raise self._normalized(exc) from exc

        async def verify(self, payload, requirements):
            try:
                return await self._client.verify(payload, requirements)
            except OKXFacilitatorResponseError as exc:
                raise self._normalized(exc) from exc

        async def verify_signature(self, payload, requirements=None):
            try:
                return await self._client.verify_signature(payload, requirements)
            except OKXFacilitatorResponseError as exc:
                raise self._normalized(exc) from exc

        async def settle(self, payload, requirements):
            try:
                return await self._client.settle(payload, requirements)
            except OKXFacilitatorResponseError as exc:
                raise self._normalized(exc) from exc

        async def get_settle_status(self, tx_hash):
            """Proxy timeout recovery required by the upstream x402 server.

            OKX may submit the transfer successfully but initially return a timeout
            while it waits for confirmation. The resource server then polls this
            method before deciding whether to release the buffered deliverable.
            """
            try:
                return await self._client.get_settle_status(tx_hash)
            except OKXFacilitatorResponseError as exc:
                raise self._normalized(exc) from exc

    facilitator = _SafeOKXFacilitator(raw_facilitator)
    server = x402ResourceServer(facilitator)
    server.register(config.network, ExactEvmScheme())

    def current_market_refs() -> list[dict[str, str]]:
        """Current retrievable IDs for copy-ready Bazaar request examples."""
        settings: Settings = app.state.settings
        if not _opportunity_scan_check(settings)["ok"]:
            return []
        scan = services.load_json_artifact(settings.opportunity_scan_path) or {}
        ranked_refs: list[tuple[int, dict[str, str]]] = []
        seen: set[tuple[str, str]] = set()
        for row in scan.get("top") or []:
            venue = str(row.get("venue") or "").strip().lower()
            market_id = str(row.get("market_id") or "").strip()
            status = str(row.get("market_status") or "").strip().lower()
            key = (venue, market_id)
            if venue not in SUPPORTED_VENUES or not market_id or key in seen:
                continue
            if status and status not in {"active", "open", "funded"}:
                continue
            seen.add(key)
            # Prefer rows the latest scan found actionable, while retaining
            # open rows as a fallback when no actionable row exists for a venue.
            priority = 0 if row.get("actionable") is True or row.get("coverage_status") == "actionable" else 1
            ranked_refs.append((priority, {"venue": venue, "market_id": market_id}))
        ranked_refs.sort(key=lambda item: item[0])
        return [ref for _, ref in ranked_refs]

    def current_body_example(service: str, request_model) -> dict[str, Any]:
        example = copy.deepcopy(
            request_model.model_config.get("json_schema_extra", {}).get("example", {})
        )
        refs = current_market_refs()
        if service == services.CHECK_MARKET_SERVICE and refs:
            example["market"] = refs[0]
        elif service == services.CROSS_VENUE_SERVICE:
            pair = next(
                ((left, right) for left in refs for right in refs if left["venue"] != right["venue"]),
                None,
            )
            if pair:
                example["left"], example["right"] = pair
        return example

    def compact_body_schema(service: str, request_model) -> dict[str, Any]:
        """Keep Bazaar discovery below common 4 KiB proxy header buffers."""
        if service == SIGNAL_SERVICE:
            return request_model.model_json_schema()
        venue_ref = {
            "type": "object",
            "properties": {
                "venue": {"type": "string", "enum": list(SUPPORTED_VENUES)},
                "market_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 256,
                    "description": (
                        "Exact venue ID. Polymarket accepts numeric, 0x condition, market slug, "
                        "or single-market event slug."
                    ),
                },
            },
            "required": ["venue", "market_id"],
            "additionalProperties": False,
        }
        include = {
            "type": "object",
            "properties": {
                "why_trace": {"type": "boolean"},
                "calibration": {"type": "boolean"},
                "receipt": {"type": "boolean"},
            },
            "additionalProperties": False,
        }
        if service == services.CHECK_MARKET_SERVICE:
            return {
                "type": "object",
                "properties": {"market": venue_ref, "include": include},
                "required": ["market"],
                "additionalProperties": False,
            }
        return {
            "type": "object",
            "properties": {"left": venue_ref, "right": venue_ref, "include": include},
            "required": ["left", "right"],
            "additionalProperties": False,
        }

    def discovery_extension(method: str, service: str) -> dict[str, Any]:
        """Describe paid request and response shapes inside the x402 challenge.

        Review clients probe before they know our OpenAPI contract. The Bazaar extension
        gives them the exact body/query schema needed for the paid replay instead of forcing
        them to guess and receive a post-payment validation error.
        """
        output_example = {
            SIGNAL_SERVICE: {
                "request_id": "req_example",
                "service": SIGNAL_SERVICE,
                "status": "ok",
                "created_at": "2026-07-14T00:00:00+00:00",
                "answer": "Ranked currently open signals.",
                "signals": [],
                "filters": {},
                "pagination": {},
                "receipt": {"record_hash": "0" * 64},
            },
            services.CHECK_MARKET_SERVICE: {
                "request_id": "req_example",
                "service": services.CHECK_MARKET_SERVICE,
                "status": "priced",
                "created_at": "2026-07-14T00:00:00+00:00",
                "market": {},
                "receipt": {"record_hash": "0" * 64},
            },
            services.CROSS_VENUE_SERVICE: {
                "request_id": "req_example",
                "service": services.CROSS_VENUE_SERVICE,
                "status": "evaluated",
                "created_at": "2026-07-14T00:00:00+00:00",
                "left": {},
                "right": {},
                "equivalence": {},
                "actionable": False,
                "receipt": {"record_hash": "0" * 64},
            },
        }[service]
        if service == SIGNAL_SERVICE and method == "GET":
            input_info = {
                "type": "http",
                "method": "GET",
                "queryParams": {"message": "Give me the best signals now", "limit": 5},
            }
            input_properties = {
                "type": {"type": "string", "const": "http"},
                "method": {"type": "string", "enum": ["GET", "HEAD", "DELETE"]},
                "queryParams": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "minLength": 3, "maxLength": 500},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                        "min_minutes_to_close": {
                            "type": ["integer", "null"], "minimum": 5, "maximum": 10080,
                        },
                        "cursor": {"type": ["string", "null"], "minLength": 8, "maxLength": 500},
                    },
                    "additionalProperties": False,
                },
            }
            required_input = ["type", "method"]
        else:
            request_model = {
                SIGNAL_SERVICE: SignalRequest,
                services.CHECK_MARKET_SERVICE: CheckMarketRequest,
                services.CROSS_VENUE_SERVICE: CrossVenueRequest,
            }[service]
            body_example = current_body_example(service, request_model)
            input_info = {
                "type": "http", "method": method, "bodyType": "json", "body": body_example,
            }
            input_properties = {
                "type": {"type": "string", "const": "http"},
                "method": {"type": "string", "enum": ["POST", "PUT", "PATCH"]},
                "bodyType": {"type": "string", "enum": ["json", "form-data", "text"]},
                "body": compact_body_schema(service, request_model),
            }
            required_input = ["type", "method", "bodyType", "body"]

        # Bazaar discovery is an x402 extension, not a payment primitive. Build its
        # documented JSON shape directly so the pinned OKX seller SDK remains the
        # only runtime dependency; newer optional x402 helper packages are unnecessary.
        return {"bazaar": {
            "info": {
                "input": input_info,
                "output": {"type": "json", "example": output_example},
            },
            "schema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "input": {
                        "type": "object", "properties": input_properties,
                        "required": required_input, "additionalProperties": False,
                    },
                    "output": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            # Keep PAYMENT-REQUIRED compact enough for standard
                            # reverse-proxy/client header limits. The concrete
                            # deliverable example is above; only the request
                            # schema must be exhaustive for paid replay.
                            "example": {"type": "object"},
                        },
                        "required": ["type"],
                    },
                },
                "required": ["input"],
            },
        }}

    routes = {}
    for method, path, service in (
        ("POST", "/v1/signals", SIGNAL_SERVICE),
        ("GET", "/v1/signals", SIGNAL_SERVICE),
        ("POST", "/", SIGNAL_SERVICE),
        ("POST", "/v1/check-market", services.CHECK_MARKET_SERVICE),
        ("POST", "/v1/cross-venue-edge", services.CROSS_VENUE_SERVICE),
    ):
        routes[f"{method} {path}"] = RouteConfig(
            accepts=[PaymentOption(
                scheme=config.scheme,
                pay_to=str(config.recipient),
                price=AssetAmount(
                    amount=str(config.price_for(service)), asset=str(config.asset),
                    extra={
                        "name": config.asset_name or "token",
                        "version": config.asset_version,
                        "decimals": config.asset_decimals,
                    },
                ),
                network=config.network,
                max_timeout_seconds=config.max_timeout_seconds,
            )],
            mime_type="application/json",
            description=_SERVICE_DESCRIPTION[service],
            extensions=discovery_extension(method, service),
        )
    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(OracleError)
    async def _oracle_error(request: Request, exc: OracleError):
        return _error_response(exc, _request_id(request))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        details = [
            {"loc": [str(p) for p in err.get("loc", [])], "msg": err.get("msg"), "type": err.get("type")}
            for err in exc.errors()
        ]
        error = OracleError("INVALID_REQUEST", "request failed schema validation", details={"errors": details})
        return _error_response(error, _request_id(request))

    @app.exception_handler(PaymentRequired)
    async def _payment_required(request: Request, exc: PaymentRequired):
        rid = _request_id(request)
        resp = JSONResponse(status_code=402, content=exc.challenge)
        for key, value in exc.headers.items():
            resp.headers[key] = value
        resp.headers[REQUEST_ID_HEADER] = rid
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.exception_handler(PaymentError)
    async def _payment_error(request: Request, exc: PaymentError):
        return _error_response(OracleError(exc.code, exc.message), _request_id(request))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        return _error_response(OracleError("INTERNAL_ERROR", "internal error"), _request_id(request))


def _register_routes(app: FastAPI, settings: Settings) -> None:
    def _execution_call(call):
        try:
            return call()
        except ExecutionError as exc:
            raise OracleError(exc.code, str(exc)) from exc

    # ------------------------- paid services -------------------------
    async def _best_signals(request: Request, body: SignalRequest):
        payload = body.model_dump()
        payment_reference = enforce_payment(request, SIGNAL_SERVICE, payload)
        scan = services.load_json_artifact(settings.opportunity_scan_path)
        calibration = services.load_json_artifact(settings.calibration_report_path)
        ranked = rank_signals(
            scan=scan, calibration=calibration, message=body.message, limit=body.limit,
            now=datetime.now(timezone.utc),
            max_age_minutes=settings.signal_scan_max_age_minutes,
            min_close_minutes=body.min_minutes_to_close or settings.signal_min_close_lead_minutes,
            max_spread=settings.signal_max_spread,
            cursor=body.cursor,
        )
        result = {
            "request_id": request.state.request_id, "service": SIGNAL_SERVICE,
            "status": "ok" if ranked["signals"] else "no_signal",
            "created_at": datetime.now(timezone.utc).isoformat(),
            **ranked,
        }
        committed = request.app.state.receipt_store.commit({
            "request_id": request.state.request_id,
            "service": SIGNAL_SERVICE,
            "request_hash": request_hash(payload),
            "result_status": result["status"],
            "signal_count": len(ranked["signals"]),
            "signals": [{
                key: signal.get(key) for key in (
                    "venue", "market_id", "family", "side", "oracle_probability",
                    "probability_interval", "market_probability", "spread", "entry_price",
                    "expected_profit_per_contract", "model_version", "signal_expires_at",
                )
            } for signal in ranked["signals"]],
            "scan_timestamp": (scan or {}).get("created_at"),
            "created_at": result["created_at"],
            "payment_reference": payment_reference,
        })
        result["receipt"] = {
            "record_hash": committed.record_hash,
            "chain_hash": committed.chain_hash,
            "sequence": committed.sequence,
            "verification_url": settings.verification_url(committed.record_hash),
        }
        return result

    @app.post(
        "/v1/signals", response_model=SignalResponse,
        responses={
            400: {"model": ErrorEnvelope, "description": "Invalid request"},
            402: {"description": "x402 payment challenge (see PAYMENT-REQUIRED header) or payment error"},
            409: {"model": ErrorEnvelope, "description": "Idempotency key reused for a different request or payment"},
            503: {"model": ErrorEnvelope, "description": "Signal scan unavailable or stale"},
        },
        tags=["services"], summary="Best Signals — ranked natural-language opportunities",
        operation_id="rwoo_best_signals",
    )
    async def best_signals(request: Request, body: SignalRequest):
        return await _best_signals(request, body)

    @app.get("/v1/signals", response_model=SignalResponse, tags=["services"],
             responses={
                 400: {"model": ErrorEnvelope, "description": "Invalid query parameters"},
                 402: {"description": "x402 payment challenge (see PAYMENT-REQUIRED header) or payment error"},
                 409: {"model": ErrorEnvelope, "description": "Idempotency key reused for a different request or payment"},
                 503: {"model": ErrorEnvelope, "description": "Signal scan unavailable or stale"},
             },
             summary="Best Signals (GET form for x402 discovery clients)",
             operation_id="rwoo_best_signals_get")
    async def best_signals_get(
        request: Request,
        message: str = Query(default="Give me the best signals now", min_length=3, max_length=500),
        limit: int = Query(default=5, ge=1, le=10),
        min_minutes_to_close: int | None = Query(default=None, ge=5, le=10080),
        cursor: str | None = Query(default=None, min_length=8, max_length=500),
    ):
        body = SignalRequest(message=message, limit=limit, min_minutes_to_close=min_minutes_to_close,
                             cursor=cursor)
        return await _best_signals(request, body)

    # Compatibility for agent clients that POST their text envelope to the
    # advertised base resource. It delegates to exactly the same service.
    @app.post("/", response_model=SignalResponse, include_in_schema=False)
    async def root_agent_request(request: Request, body: SignalRequest):
        return await _best_signals(request, body)

    @app.post(
        "/v1/check-market",
        response_model=CheckMarketResponse,
        responses={
            400: {"model": ErrorEnvelope, "description": "Invalid request or unsupported venue"},
            402: {"description": "x402 payment challenge (see PAYMENT-REQUIRED header) or payment error"},
            409: {"model": ErrorEnvelope, "description": "Idempotency key reused for a different request or payment"},
            404: {"model": ErrorEnvelope, "description": "Market not found; may include candidate market IDs"},
            422: {"model": ErrorEnvelope, "description": "Market cannot be safely evaluated"},
            429: {"model": ErrorEnvelope, "description": "Upstream rate limited"},
            503: {"model": ErrorEnvelope, "description": "Venue upstream unavailable"},
            504: {"model": ErrorEnvelope, "description": "Venue upstream timed out"},
        },
        tags=["services"],
        summary="Price and compare one supported market",
        description=(
            "The JSON body must contain `market` as an object: "
            "`{\"market\": {\"venue\": \"polymarket\", \"market_id\": \"<id-or-slug>\"}}`. "
            "Polymarket supports numeric Gamma IDs, condition IDs, market slugs, and "
            "single-market event slugs. Unknown slugs return HTTP 404 and may include candidates."
        ),
        operation_id="rwoo_check_market",
    )
    async def check_market(request: Request, body: CheckMarketRequest):
        rid = request.state.request_id
        payload = body.model_dump()
        payment_reference = enforce_payment(request, services.CHECK_MARKET_SERVICE, payload)
        result = services.run_check_market(
            request_id=rid,
            venue=body.market.venue,
            market_id=body.market.market_id,
            include=body.include,
            settings=settings,
            receipt_store=request.app.state.receipt_store,
            request_payload=payload,
            fetch_market=request.app.state.fetch_market,
            evaluate=request.app.state.evaluate,
            payment_reference=payment_reference,
        )
        return result

    @app.post(
        "/v1/cross-venue-edge",
        response_model=CrossVenueResponse,
        responses={
            400: {"model": ErrorEnvelope, "description": "Invalid request or unsupported venue"},
            402: {"description": "x402 payment challenge (see PAYMENT-REQUIRED header) or payment error"},
            409: {"model": ErrorEnvelope, "description": "Idempotency key reused for a different request or payment"},
            404: {"model": ErrorEnvelope, "description": "One market was not found; may include candidates"},
            422: {"model": ErrorEnvelope, "description": "Markets cannot be safely compared"},
            429: {"model": ErrorEnvelope, "description": "Upstream rate limited"},
            503: {"model": ErrorEnvelope, "description": "Venue upstream unavailable"},
            504: {"model": ErrorEnvelope, "description": "Venue upstream timed out"},
        },
        tags=["services"],
        summary="Compare two candidate-equivalent contracts across venues",
        description=(
            "`left` and `right` must each be objects containing `venue` and `market_id`, "
            "and the venues must differ. Use GET `/v1/market-candidates` to obtain current IDs."
        ),
        operation_id="rwoo_cross_venue_edge",
    )
    async def cross_venue(request: Request, body: CrossVenueRequest):
        rid = request.state.request_id
        payload = body.model_dump()
        payment_reference = enforce_payment(request, services.CROSS_VENUE_SERVICE, payload)
        result = services.run_cross_venue(
            request_id=rid,
            left_ref=body.left,
            right_ref=body.right,
            include=body.include,
            settings=settings,
            receipt_store=request.app.state.receipt_store,
            request_payload=payload,
            fetch_market=request.app.state.fetch_market,
            payment_reference=payment_reference,
        )
        return result

    @app.post(
        "/v1/executions/prepare", response_model=ExecutionResponse, tags=["execution"],
        summary="Durably prepare and risk-check a Polymarket limit-order intent",
        responses={409: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}},
    )
    async def prepare_execution(request: Request, body: PrepareExecutionRequest):
        key = request.headers.get(IDEMPOTENCY_HEADER)
        if not key:
            raise OracleError("INVALID_EXECUTION", "Idempotency-Key is required for execution preparation")
        receipt = request.app.state.receipt_store.find(body.decision_receipt_hash)
        if receipt is None:
            raise OracleError("INVALID_EXECUTION", "decision receipt was not found")
        decision = receipt.payload
        economics = decision.get("economics") or {}
        if (
            decision.get("service") != services.CHECK_MARKET_SERVICE
            or economics.get("actionable") is not True
            or decision.get("venue") != body.venue
            or decision.get("market_id") != body.market_id
            or decision.get("event_group_id") != body.event_group_id
            or economics.get("side") != body.side
        ):
            raise OracleError(
                "INVALID_EXECUTION",
                "execution intent does not match an actionable check-market decision receipt",
            )
        intent, _ = _execution_call(lambda: request.app.state.execution.prepare(body.model_dump(), key))
        return _enrich_execution(intent, settings)

    @app.post(
        "/v1/executions/{intent_id}/submit", response_model=ExecutionResponse, tags=["execution"],
        summary="Submit a prepared intent when the funded execution interlock is unlocked",
        responses={403: {"model": ErrorEnvelope}, 423: {"model": ErrorEnvelope}},
    )
    async def submit_execution(intent_id: str, request: Request, body: SubmitExecutionRequest):
        intent = _execution_call(lambda: request.app.state.execution.submit(
            intent_id, body.operator_approval_id,
        ))
        return _enrich_execution(intent, settings)

    @app.post(
        "/v1/executions/{intent_id}/submit-signed", response_model=ExecutionResponse, tags=["execution"],
        summary="Relay a caller-signed Polymarket order without receiving a private key",
        responses={409: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}, 502: {"model": ErrorEnvelope}},
    )
    async def submit_signed_execution(intent_id: str, request: Request, body: SubmitSignedExecutionRequest):
        payload = _execution_call(lambda: decode_signed_order(body.body_base64, body.headers))
        intent = request.app.state.execution.store.get(intent_id)
        if intent is None:
            raise OracleError("EXECUTION_NOT_FOUND", "execution intent was not found")
        _execution_call(lambda: validate_signed_order_matches_intent(intent, payload))
        intent = _execution_call(lambda: request.app.state.execution.submit_signed(
            intent_id,
            payload.body_hash,
            lambda _intent: relay_signed_order(payload),
        ))
        return _enrich_execution(intent, settings)

    @app.get(
        "/v1/executions/{intent_id}", response_model=ExecutionResponse, tags=["execution"],
        summary="Inspect durable execution state and its transition history",
    )
    async def get_execution(intent_id: str, request: Request):
        intent = request.app.state.execution.store.get(intent_id)
        if intent is None:
            raise OracleError("EXECUTION_NOT_FOUND", "execution intent was not found")
        return _enrich_execution(intent, settings)

    @app.post(
        "/v1/executions/{intent_id}/cancel", response_model=ExecutionResponse, tags=["execution"],
        summary="Cancel an unsubmitted intent or request venue cancellation",
    )
    async def cancel_execution(intent_id: str, request: Request):
        intent = _execution_call(lambda: request.app.state.execution.cancel(intent_id))
        return _enrich_execution(intent, settings)

    @app.post(
        "/v1/executions/{intent_id}/reconcile", response_model=ExecutionResponse, tags=["execution"],
        summary="Resolve an ambiguous or nonterminal order state from the venue",
    )
    async def reconcile_execution(intent_id: str, request: Request):
        intent = _execution_call(lambda: request.app.state.execution.reconcile(intent_id))
        return _enrich_execution(intent, settings)

    @app.get(
        "/v1/calibration", response_model=CalibrationResponse,
        tags=["calibration"], summary="Public calibration summary",
        operation_id="rwoo_get_calibration",
    )
    async def calibration_all(request: Request, probability_band: str | None = None):
        report = services.load_json_artifact(settings.calibration_report_path)
        _validate_calibration_scope(
            report, family=None, model_version=None, probability_band=probability_band,
        )
        return services.build_calibration(report=report, probability_band=probability_band)

    @app.get(
        "/v1/calibration/{family}", response_model=CalibrationResponse, tags=["calibration"],
        responses={404: {"model": ErrorEnvelope, "description": "Unknown calibration family"}},
        operation_id="rwoo_get_calibration_family",
    )
    async def calibration_family(family: str, request: Request, probability_band: str | None = None):
        report = services.load_json_artifact(settings.calibration_report_path)
        _validate_calibration_scope(
            report, family=family, model_version=None, probability_band=probability_band,
        )
        return services.build_calibration(report=report, family=family, probability_band=probability_band)

    @app.get(
        "/v1/calibration/{family}/{model_version}",
        response_model=CalibrationResponse,
        tags=["calibration"],
        responses={404: {"model": ErrorEnvelope, "description": "Unknown family or model version"}},
        operation_id="rwoo_get_calibration_model",
    )
    async def calibration_family_model(family: str, model_version: str, request: Request,
                                       probability_band: str | None = None):
        report = services.load_json_artifact(settings.calibration_report_path)
        _validate_calibration_scope(
            report, family=family, model_version=model_version, probability_band=probability_band,
        )
        return services.build_calibration(
            report=report, family=family, model_version_filter=model_version,
            probability_band=probability_band,
        )

    # ------------------------- supporting endpoints -------------------------
    @app.get("/healthz", tags=["ops"], summary="Cheap liveness check")
    async def healthz():
        return {"status": "ok", "version": API_VERSION}

    @app.get("/health", tags=["ops"], summary="Compatibility liveness check")
    async def health():
        return {"status": "ok", "version": API_VERSION}

    @app.get("/readyz", tags=["ops"], summary="Readiness: engine, ledger, paths, artifacts")
    async def readyz(request: Request):
        checks = _readiness_checks(
            request.app.state.receipt_store,
            settings,
            request.app.state.payment_config,
        )
        ready = all(c["ok"] for c in checks.values() if c.get("required", True))
        degraded = ready and any(not c["ok"] for c in checks.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "degraded" if degraded else ("ready" if ready else "not_ready"),
                "checks": checks,
            },
        )

    @app.get("/version", tags=["ops"])
    async def version():
        return {
            "api_version": API_VERSION,
            "git_sha": os.environ.get("RWOO_GIT_SHA", "unknown"),
            "model_versions": MODEL_VERSIONS,
        }

    @app.get("/v1/service-metadata", tags=["ops"], summary="ASP service catalog")
    async def service_metadata(request: Request):
        config: PaymentConfig = request.app.state.payment_config

        def svc(identifier, endpoint, description, payment_capable, methods):
            price = config.price_for(identifier)
            paid = bool(payment_capable and config.enabled and price is not None)
            return {
                "identifier": identifier,
                "underscore_identifier": identifier.replace(".", "_"),
                "command": identifier.replace(".", "_"),
                "display_name": {
                    "rwoo.best_signals": "Best Signals",
                    "rwoo.check_market": "Check Market",
                    "rwoo.cross_venue_edge": "Cross-Venue Edge",
                    "rwoo.get_calibration": "Get Calibration",
                }.get(identifier, identifier),
                "endpoint": f"{settings.api_base_url.rstrip('/')}{endpoint}",
                "methods": methods,
                "description": description,
                "paid": paid,
                # Price is only populated once an operator sets it via env; it is
                # never hardcoded.
                "price_atomic": price if paid else None,
            }

        ready, missing = config.settlement_readiness()
        operational_checks = _readiness_checks(request.app.state.receipt_store, settings, config)
        core_ready = all(
            check["ok"] for check in operational_checks.values() if check.get("required", True)
        )
        signal_scan_ready = operational_checks.get("paid_signal_scan", {"ok": True})["ok"]
        return {
            "name": "Real-World Odds Oracle",
            "tagline": "The true odds, proven.",
            "api_base_url": settings.api_base_url,
            "docs_url": settings.docs_url,
            "openapi_url": f"{settings.api_base_url.rstrip('/')}/openapi.json",
            "support_email": settings.support_email,
            "execution_enabled": request.app.state.execution.live_enabled,
            "execution": {
                "mode": request.app.state.execution.mode,
                "prepare_available": True,
                "live_submission_available": request.app.state.execution.live_enabled,
                "max_order_usd": str(request.app.state.execution.max_order),
                "endpoints": {
                    "prepare": f"{settings.api_base_url.rstrip('/')}/v1/executions/prepare",
                    "inspect": f"{settings.api_base_url.rstrip('/')}/v1/executions/{{intent_id}}",
                    "submit": f"{settings.api_base_url.rstrip('/')}/v1/executions/{{intent_id}}/submit",
                    "cancel": f"{settings.api_base_url.rstrip('/')}/v1/executions/{{intent_id}}/cancel",
                    "reconcile": f"{settings.api_base_url.rstrip('/')}/v1/executions/{{intent_id}}/reconcile",
                },
            },
            "payment": {
                "protocol": "OKX Agent Payments (x402)",
                "x402_version": 2,
                "enabled": config.enabled,
                "mode": config.mode,
                "scheme": config.scheme,
                "network": config.network,
                "asset": config.asset,
                "asset_name": config.asset_name,
                "asset_version": config.asset_version,
                "asset_decimals": config.asset_decimals,
                "recipient": config.recipient,
                "settlement_ready": ready,
                "operational_ready": core_ready,
                "readiness_url": f"{settings.api_base_url.rstrip('/')}/readyz",
                "pending_operator_config": missing,
            },
            "services": [
                svc("rwoo.best_signals", "/v1/signals",
                    _SERVICE_DESCRIPTION["rwoo.best_signals"], True, ["GET", "POST"]),
                svc("rwoo.check_market", "/v1/check-market",
                    _SERVICE_DESCRIPTION["rwoo.check_market"], True, ["POST"]),
                svc("rwoo.cross_venue_edge", "/v1/cross-venue-edge",
                    _SERVICE_DESCRIPTION["rwoo.cross_venue_edge"], True, ["POST"]),
                svc("rwoo.get_calibration", "/v1/calibration",
                    "Returns exact-version calibration for supported weather, economics, Henry Hub, and sports families, including independent resolution counts, probability-band results, and checkpoint status.",
                    False, ["GET"]),
            ],
            "service_readiness": {
                "rwoo.best_signals": {
                    "ready": signal_scan_ready,
                    "detail": operational_checks.get("paid_signal_scan", {}).get("detail"),
                },
                "rwoo.check_market": {"ready": core_ready},
                "rwoo.cross_venue_edge": {"ready": core_ready},
                "rwoo.get_calibration": {"ready": True},
            },
        }

    @app.get(
        "/v1/market-candidates",
        response_model=MarketCandidatesResponse,
        tags=["ops"],
        summary="Current market identifiers for check-market and cross-venue requests",
    )
    async def market_candidates(
        venue: str | None = Query(default=None, max_length=32),
        query: str | None = Query(default=None, max_length=200),
        limit: int = Query(default=10, ge=1, le=20),
    ):
        normalized_venue = venue.strip().lower() if venue else None
        if normalized_venue and normalized_venue not in SUPPORTED_VENUES:
            raise OracleError(
                "UNSUPPORTED_VENUE",
                f"venue {normalized_venue!r} is not supported; supported venues are {', '.join(SUPPORTED_VENUES)}",
            )
        scan_check = _opportunity_scan_check(settings)
        if not scan_check["ok"]:
            candidates, live_errors = await discover_live_candidates(
                venue=normalized_venue,
                query=query,
                limit=limit,
            )
            if not candidates and live_errors and len(live_errors) == (
                1 if normalized_venue else len(SUPPORTED_VENUES)
            ):
                raise OracleError(
                    "SOURCE_UNAVAILABLE",
                    "live market discovery is temporarily unavailable",
                    details={
                        "scan": scan_check,
                        "venue_errors": live_errors,
                        "retryable": True,
                        "action": "retry later or submit a known exact venue market_id",
                    },
                )
            return {
                "scan_created_at": None,
                "venue": normalized_venue,
                "query": query,
                "candidates": candidates,
                "count": len(candidates),
                "source": "live_venue_fallback",
                "freshness_status": "live",
                "note": "Live venue discovery was used because the scan artifact was stale; use IDs exactly as returned.",
            }
        terms = [term for term in (query or "").lower().replace("-", " ").split() if term]
        scan = services.load_json_artifact(settings.opportunity_scan_path) or {}
        candidates: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for row in scan.get("top") or []:
            row_venue = str(row.get("venue") or "").lower()
            row_id = str(row.get("market_id") or "")
            status = str(row.get("market_status") or "").lower()
            haystack = f"{row_id} {row.get('question') or ''} {row.get('family') or ''}".lower()
            key = (row_venue, row_id)
            if not row_id or key in seen:
                continue
            if row_venue not in SUPPORTED_VENUES:
                continue
            if normalized_venue and row_venue != normalized_venue:
                continue
            if status and status not in {"active", "open", "funded"}:
                continue
            if terms and not all(term in haystack for term in terms):
                continue
            seen.add(key)
            candidates.append({
                "venue": row_venue,
                "market_id": row_id,
                "question": row.get("question"),
                "family": row.get("family"),
                "market_status": row.get("market_status"),
                "trading_close_time": row.get("trading_close_time"),
            })
            if len(candidates) >= limit:
                break
        return {
            "scan_created_at": scan.get("created_at"),
            "venue": normalized_venue,
            "query": query,
            "candidates": candidates,
            "count": len(candidates),
            "source": "opportunity_scan",
            "freshness_status": "fresh",
            "note": "Use venue and market_id exactly as returned; availability and quotes can change.",
        }

    @app.get("/v1/supported-markets", tags=["ops"], summary="Coverage: venues, families, series")
    async def supported_markets():
        scan = services.load_json_artifact(settings.opportunity_scan_path)
        public_families = {
            family: version for family, version in MODEL_VERSIONS.items()
            if family not in {"energy.commodity_price", "agriculture.commodity_price"}
        }
        return {
            "venues": list(SUPPORTED_VENUES),
            "registered_model_families": sorted(MODEL_VERSIONS.keys()),
            "families": sorted(public_families.keys()),
            "model_versions": public_families,
            "sports_families_currently_producing_candidates": ["sports.world_cup"],
            "sports_coverage": SPORTS_COVERAGE,
            "current_sports_scan": sports_scan_summary(scan),
            "expanded_market_coverage": ACTIVE_EXPANSION_COVERAGE,
            "internal_discovery_telemetry": {
                "not_product_capabilities": True,
                "coverage": INTERNAL_DISCOVERY_COVERAGE,
            },
            "current_expansion_scan": expansion_scan_summary(scan),
            "kalshi_series": {
                "weather": WEATHER_SERIES,
                "economics": ECONOMICS_SERIES,
                "sports": SPORTS_SERIES,
                "expansion": (scan or {}).get("dynamically_discovered_expansion_series", []),
            },
            "note": "Families lists active public coverage. Internal discovery telemetry is measured for research only and is not a product capability until its exact settlement source is integrated.",
        }

    @app.get("/v1/evidence/status", tags=["ops"], summary="Evidence ledger + calibration status")
    async def evidence_status(request: Request):
        report = services.load_json_artifact(settings.calibration_report_path)
        ledger_ok = request.app.state.receipt_store.verify()
        return {
            "calibration_report_available": report is not None,
            "report_created_at": (report or {}).get("created_at"),
            "precommitted_forecasts": (report or {}).get("precommitted_forecasts", 0),
            "resolved_forecasts": (report or {}).get("resolved_forecasts", 0),
            "independent_resolved_event_groups": (report or {}).get("independent_resolved_event_groups", 0),
            "decision_ledger_verification": ledger_ok,
            "execution_enabled": request.app.state.execution.live_enabled,
            "execution_mode": request.app.state.execution.mode,
        }

    @app.get("/v1/receipts/{record_hash}", tags=["receipts"], summary="Fetch a decision receipt")
    async def get_receipt(record_hash: str, request: Request):
        record = request.app.state.receipt_store.find(record_hash)
        if record is None:
            raise OracleError("NOT_FOUND", f"no receipt with record_hash {record_hash!r}")
        return {
            "sequence": record.sequence,
            "record_type": record.record_type,
            "payload": record.payload,
            "created_at": record.created_at,
            "prev_hash": record.prev_hash,
            "record_hash": record.record_hash,
            "chain_hash": record.chain_hash,
            "hash_algorithm": record.hash_algorithm,
            "verification_url": settings.verification_url(record.record_hash),
        }

    @app.get("/v1/receipts/{record_hash}/verify", tags=["receipts"], summary="Verify a receipt against the chain")
    async def verify_receipt(record_hash: str, request: Request):
        store = request.app.state.receipt_store
        record = store.find(record_hash)
        if record is None:
            raise OracleError("NOT_FOUND", f"no receipt with record_hash {record_hash!r}")
        ledger = store.verify()
        return {
            "record_hash": record_hash,
            "found": True,
            "sequence": record.sequence,
            "ledger_valid": ledger.get("valid", False),
            "ledger_head_hash": ledger.get("head_hash"),
            "record_count": ledger.get("record_count"),
            "hash_algorithm": record.hash_algorithm,
        }


def _opportunity_scan_check(settings: Settings) -> dict[str, Any]:
    path = settings.opportunity_scan_path
    scan = services.load_json_artifact(path)
    if scan is None:
        return {
            "ok": False,
            "detail": "opportunity scan is missing or invalid JSON",
            "path": str(path),
        }
    created_at = scan.get("created_at")
    try:
        created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return {"ok": False, "detail": "opportunity scan has an invalid created_at"}
    age_minutes = (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds() / 60
    if age_minutes < -5:
        return {
            "ok": False,
            "detail": "opportunity scan timestamp is in the future",
            "scan_created_at": created_at,
        }
    if age_minutes > settings.signal_scan_max_age_minutes:
        return {
            "ok": False,
            "detail": "opportunity scan is stale",
            "scan_created_at": created_at,
            "age_minutes": round(age_minutes, 1),
            "max_age_minutes": settings.signal_scan_max_age_minutes,
        }
    return {
        "ok": True,
        "scan_created_at": created_at,
        "age_minutes": round(max(0.0, age_minutes), 1),
    }


def _readiness_checks(
    receipt_store: DecisionReceiptStore,
    settings: Settings,
    payment_config: PaymentConfig | None = None,
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    # engine import
    try:
        from rwoo import scanner  # noqa: F401

        checks["engine_import"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        checks["engine_import"] = {"ok": False, "detail": type(exc).__name__}
    # ledger readable + valid
    try:
        verification = receipt_store.verify()
        checks["decision_ledger"] = {"ok": bool(verification.get("valid", True))}
    except Exception as exc:  # noqa: BLE001
        checks["decision_ledger"] = {"ok": False, "detail": type(exc).__name__}
    # writable path for the ledger
    try:
        parent = settings.decision_ledger_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        checks["writable_paths"] = {"ok": os.access(parent, os.W_OK)}
    except Exception as exc:  # noqa: BLE001
        checks["writable_paths"] = {"ok": False, "detail": type(exc).__name__}
    # artifact integrity: a present-but-corrupt report is not ready; missing is fine
    report_path = settings.calibration_report_path
    if report_path.exists():
        checks["calibration_report"] = {"ok": services.load_json_artifact(report_path) is not None}
    else:
        checks["calibration_report"] = {"ok": True, "detail": "absent; evidence accumulating"}
    # A paid Best Signals route cannot fulfill its advertised response without
    # a recent scan. Check this only when that paid service is enabled so a
    # check-market-only/local deployment is not incorrectly marked unavailable.
    if (
        payment_config is not None
        and payment_config.enabled
        and payment_config.price_for(SIGNAL_SERVICE) is not None
    ):
        checks["paid_signal_scan"] = {
            **_opportunity_scan_check(settings),
            "required": False,
            "service": SIGNAL_SERVICE,
        }
    return checks


def _install_custom_openapi(app: FastAPI, settings: Settings) -> None:
    from fastapi.openapi.utils import get_openapi

    def custom_openapi():
        if app.openapi_schema:
            app.openapi_schema["servers"] = [{"url": settings.api_base_url}]
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            contact=app.contact,
        )
        schema["servers"] = [{"url": settings.api_base_url}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[assignment]


# A module-level app for `uvicorn rwoo.api.app:app`.
app = create_app()
