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

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from rwoo.api import API_VERSION
from rwoo.api.config import Settings, get_settings
from rwoo.api.errors import OracleError
from rwoo.api.market_fetch import SUPPORTED_VENUES, fetch_canonical
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
    CrossVenueRequest,
    CrossVenueResponse,
    ErrorEnvelope,
    SignalRequest,
    SignalResponse,
)
from rwoo.api import services
from rwoo.api.signals import SERVICE as SIGNAL_SERVICE, rank_signals
from rwoo.identity import MODEL_VERSIONS
from rwoo.expansion_coverage import EXPANSION_COVERAGE, expansion_scan_summary
from rwoo.scanner import ECONOMICS_SERIES, SPORTS_SERIES, WEATHER_SERIES, evaluate_market
from rwoo.sports_coverage import SPORTS_COVERAGE, sports_scan_summary

REQUEST_ID_HEADER = "X-Request-ID"
IDEMPOTENCY_HEADER = "Idempotency-Key"

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
    "rwoo.best_signals": "Ranked conversational signals filtered for freshness, trading close, executable quotes, spread, model consistency, and evidence.",
    "rwoo.check_market": "Independent probability, interval, executable-price EV, why-trace, and receipt for one market.",
    "rwoo.cross_venue_edge": "Conservative cross-venue equivalence and executable complementary edge with risk disclosure.",
}


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
    app.state.fetch_market = fetch_market
    app.state.evaluate = evaluate
    app.state.payment_config = payment_config
    app.state.payment_verifier = payment_verifier if payment_verifier is not None else select_verifier(payment_config)
    app.state.replay_store = ReplayStore()

    if payment_config.enabled and payment_config.mode == "facilitator":
        _install_official_x402(app, payment_config)

    # --- middleware (added last runs first / outermost) ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", REQUEST_ID_HEADER, IDEMPOTENCY_HEADER, "X-PAYMENT", "PAYMENT-SIGNATURE"],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

    @app.middleware("http")
    async def _request_context(request: Request, call_next):
        rid = request.headers.get(REQUEST_ID_HEADER) or f"req_{uuid.uuid4().hex}"
        request.state.request_id = rid

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > settings.max_body_bytes:
                    return _error_response(
                        OracleError("INVALID_REQUEST", "request body exceeds the size limit"), rid
                    )
            except ValueError:
                return _error_response(OracleError("INVALID_REQUEST", "invalid Content-Length"), rid)

        try:
            response = await call_next(request)
        except OracleError as exc:
            return _error_response(exc, rid)
        except Exception:  # never leak a stack trace
            return _error_response(OracleError("INTERNAL_ERROR", "internal error"), rid)

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

    facilitator = _SafeOKXFacilitator(raw_facilitator)
    server = x402ResourceServer(facilitator)
    server.register(config.network, ExactEvmScheme())

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
    # ------------------------- paid services -------------------------
    async def _best_signals(request: Request, body: SignalRequest):
        payload = body.model_dump()
        enforce_payment(request, SIGNAL_SERVICE, payload)
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
        return {
            "request_id": request.state.request_id, "service": SIGNAL_SERVICE,
            "status": "ok" if ranked["signals"] else "no_signal",
            "created_at": datetime.now(timezone.utc).isoformat(),
            **ranked,
        }

    @app.post(
        "/v1/signals", response_model=SignalResponse,
        responses={402: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}},
        tags=["services"], summary="Best Signals — ranked natural-language opportunities",
        operation_id="rwoo_best_signals",
    )
    async def best_signals(request: Request, body: SignalRequest):
        return await _best_signals(request, body)

    @app.get("/v1/signals", response_model=SignalResponse, tags=["services"],
             summary="Best Signals (GET form for x402 discovery clients)",
             operation_id="rwoo_best_signals_get")
    async def best_signals_get(request: Request, message: str = "Give me the best signals now",
                               limit: int = 5, min_minutes_to_close: int | None = None,
                               cursor: str | None = None):
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
        responses={402: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}},
        tags=["services"],
        summary="Price and compare one supported market",
        operation_id="rwoo_check_market",
    )
    async def check_market(request: Request, body: CheckMarketRequest):
        rid = request.state.request_id
        idem = request.headers.get(IDEMPOTENCY_HEADER)
        if idem:
            cached = request.app.state.idempotency.get(idem)
            if cached is not None:  # retry: return cached, never re-charge
                return cached
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
        if idem:
            request.app.state.idempotency.put(idem, result)
        return result

    @app.post(
        "/v1/cross-venue-edge",
        response_model=CrossVenueResponse,
        responses={402: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}},
        tags=["services"],
        summary="Compare two candidate-equivalent contracts across venues",
        operation_id="rwoo_cross_venue_edge",
    )
    async def cross_venue(request: Request, body: CrossVenueRequest):
        rid = request.state.request_id
        idem = request.headers.get(IDEMPOTENCY_HEADER)
        if idem:
            cached = request.app.state.idempotency.get(idem)
            if cached is not None:  # retry: return cached, never re-charge
                return cached
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
        if idem:
            request.app.state.idempotency.put(idem, result)
        return result

    @app.get("/v1/calibration", tags=["calibration"], summary="Public calibration summary")
    async def calibration_all(request: Request, probability_band: str | None = None):
        report = services.load_json_artifact(settings.calibration_report_path)
        return services.build_calibration(report=report, probability_band=probability_band)

    @app.get("/v1/calibration/{family}", tags=["calibration"])
    async def calibration_family(family: str, request: Request, probability_band: str | None = None):
        report = services.load_json_artifact(settings.calibration_report_path)
        return services.build_calibration(report=report, family=family, probability_band=probability_band)

    @app.get("/v1/calibration/{family}/{model_version}", tags=["calibration"])
    async def calibration_family_model(family: str, model_version: str, request: Request,
                                       probability_band: str | None = None):
        report = services.load_json_artifact(settings.calibration_report_path)
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
        checks = _readiness_checks(request.app.state.receipt_store, settings)
        ready = all(c["ok"] for c in checks.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ready" if ready else "not_ready", "checks": checks},
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

        def svc(identifier, endpoint, description, payment_capable):
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
                "description": description,
                "paid": paid,
                # Price is only populated once an operator sets it via env; it is
                # never hardcoded.
                "price_atomic": price if paid else None,
            }

        ready, missing = config.settlement_readiness()
        return {
            "name": "Real-World Odds Oracle",
            "tagline": "The true odds, proven.",
            "api_base_url": settings.api_base_url,
            "docs_url": settings.docs_url,
            "openapi_url": f"{settings.api_base_url.rstrip('/')}/openapi.json",
            "support_email": settings.support_email,
            "execution_enabled": False,
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
                "pending_operator_config": missing,
            },
            "services": [
                svc("rwoo.best_signals", "/v1/signals",
                    _SERVICE_DESCRIPTION["rwoo.best_signals"], True),
                svc("rwoo.check_market", "/v1/check-market",
                    _SERVICE_DESCRIPTION["rwoo.check_market"], True),
                svc("rwoo.cross_venue_edge", "/v1/cross-venue-edge",
                    _SERVICE_DESCRIPTION["rwoo.cross_venue_edge"], True),
                svc("rwoo.get_calibration", "/v1/calibration",
                    "Public precommitted calibration record by family, model version, and probability band.", False),
            ],
        }

    @app.get("/v1/supported-markets", tags=["ops"], summary="Coverage: venues, families, series")
    async def supported_markets():
        scan = services.load_json_artifact(settings.opportunity_scan_path)
        return {
            "venues": list(SUPPORTED_VENUES),
            "registered_model_families": sorted(MODEL_VERSIONS.keys()),
            "families": sorted(MODEL_VERSIONS.keys()),
            "model_versions": MODEL_VERSIONS,
            "sports_families_currently_producing_candidates": ["sports.world_cup"],
            "sports_coverage": SPORTS_COVERAGE,
            "current_sports_scan": sports_scan_summary(scan),
            "expanded_market_coverage": EXPANSION_COVERAGE,
            "current_expansion_scan": expansion_scan_summary(scan),
            "kalshi_series": {
                "weather": WEATHER_SERIES,
                "economics": ECONOMICS_SERIES,
                "sports": SPORTS_SERIES,
                "expansion": (scan or {}).get("dynamically_discovered_expansion_series", []),
            },
            "note": "Registered model families are not a promise of a current signal. Expansion series are discovered from venue settlement metadata on every scan; unsupported or unbindable markets fail closed, never to a silent zero.",
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
            "execution_enabled": False,
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


def _readiness_checks(receipt_store: DecisionReceiptStore, settings: Settings) -> dict[str, Any]:
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
