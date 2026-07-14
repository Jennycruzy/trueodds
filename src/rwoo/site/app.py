"""Public site FastAPI app (separate from the paid API).

Served at the site hostname; the paid API lives at api.<domain>. All pages are
rendered from live artifacts at request time. This app is read-only: it never
prices a market or takes a payment — the playground calls the paid API in the
browser, and no wallet key is ever collected.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from rwoo.api.config import Settings, get_settings
from rwoo.api import services
from rwoo.api.receipt_store import DecisionReceiptStore
from rwoo.identity import MODEL_VERSIONS, model_version
from rwoo.expansion_coverage import EXPANSION_COVERAGE, expansion_scan_summary
from rwoo.scanner import ECONOMICS_SERIES, SPORTS_SERIES, WEATHER_SERIES
from rwoo.site import content
from rwoo.sports_coverage import SPORTS_COVERAGE, sports_scan_summary

_HERE = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(_HERE / "templates"))

NAV = [
    ("/", "Overview"),
    ("/markets", "Coverage"),
    ("/calibration", "Calibration"),
    ("/receipts", "Receipts"),
    ("/docs", "Docs"),
    ("/playground", "Playground"),
    ("/methodology", "Methodology"),
    ("/status", "Status"),
]

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


# ------------------------------ data loaders ------------------------------


def _scan(settings: Settings) -> dict[str, Any] | None:
    return services.load_json_artifact(settings.opportunity_scan_path)


def _calibration(settings: Settings) -> dict[str, Any] | None:
    return services.load_json_artifact(settings.calibration_report_path)


def _live_example(scan: dict[str, Any] | None) -> dict[str, Any] | None:
    """Pick one real, priced scan record for the landing hero — preferring an
    actionable, higher-confidence record. Never fabricated; None if the scan
    has no priced record yet."""
    if not scan:
        return None
    priced = [r for r in scan.get("top", []) if r.get("oracle_prob") is not None]
    if not priced:
        return None
    priced.sort(key=lambda r: (1 if r.get("actionable") else 0, r.get("confidence") or 0.0), reverse=True)
    record = dict(priced[0])
    record["model_version"] = model_version(record.get("family", ""))
    return record


def _evidence_summary(settings: Settings) -> dict[str, Any]:
    report = _calibration(settings)
    store = DecisionReceiptStore(settings.decision_ledger_path)
    return {
        "report": report,
        "report_available": report is not None,
        "decision_ledger": store.verify(),
    }


# ------------------------------ app factory -------------------------------


def create_site(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title=content.SITE_NAME, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

    @app.middleware("http")
    async def _headers(request: Request, call_next):
        response = await call_next(request)
        for key, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response

    def ctx(request: Request, active: str, **extra) -> dict[str, Any]:
        base = {
            "request": request,
            "settings": settings,
            "site_name": content.SITE_NAME,
            "tagline": content.TAGLINE,
            "disclaimer": content.DISCLAIMER,
            "nav": NAV,
            "active": active,
            "execution_enabled": False,
            "support_email": settings.support_email,
            "api_base": settings.api_base_url.rstrip("/"),
            "public_base": settings.public_base_url.rstrip("/"),
        }
        base.update(extra)
        return base

    def render(request: Request, template: str, active: str, **extra) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(request, template, ctx(request, active, **extra))

    # ------------------------------ pages ------------------------------
    @app.get("/", response_class=HTMLResponse)
    async def landing(request: Request):
        scan = _scan(settings)
        evidence = _evidence_summary(settings)
        return render(
            request, "index.html", "/",
            services=content.SERVICES,
            workflow=content.WORKFLOW_STEPS,
            law=content.DETERMINISTIC_LAW,
            supported=content.SUPPORTED_DOMAINS,
            deferred=content.DEFERRED_DOMAINS,
            equivalence=content.EQUIVALENCE_CLASSES,
            cross_venue_risk=content.CROSS_VENUE_RISK,
            example=_live_example(scan),
            scan=scan,
            evidence=evidence,
        )

    @app.get("/docs", response_class=HTMLResponse)
    async def docs(request: Request):
        scan = _scan(settings)
        return render(
            request, "docs.html", "/docs",
            services=content.SERVICES,
            errors=content.ERROR_TABLE,
            examples=content.code_examples(settings.api_base_url.rstrip("/")),
            changelog=content.CHANGELOG,
            model_versions=MODEL_VERSIONS,
            sports_coverage=SPORTS_COVERAGE,
            sports_scan=sports_scan_summary(scan),
            expansion_coverage=EXPANSION_COVERAGE,
            expansion_scan=expansion_scan_summary(scan),
        )

    @app.get("/playground", response_class=HTMLResponse)
    async def playground(request: Request):
        return render(request, "playground.html", "/playground", services=content.SERVICES)

    @app.get("/calibration", response_class=HTMLResponse)
    async def calibration(request: Request):
        report = _calibration(settings)
        summary = services.build_calibration(report=report)
        return render(request, "calibration.html", "/calibration", report=report, summary=summary)

    @app.get("/markets", response_class=HTMLResponse)
    async def markets(request: Request):
        scan = _scan(settings)
        return render(
            request, "markets.html", "/markets",
            scan=scan,
            supported=content.SUPPORTED_DOMAINS,
            deferred=content.DEFERRED_DOMAINS,
            series={"weather": WEATHER_SERIES, "economics": ECONOMICS_SERIES, "sports": SPORTS_SERIES},
            venues=["kalshi", "polymarket", "limitless"],
            sports_coverage=SPORTS_COVERAGE,
            sports_scan=sports_scan_summary(scan),
            expansion_coverage=EXPANSION_COVERAGE,
            expansion_scan=expansion_scan_summary(scan),
        )

    @app.get("/receipts", response_class=HTMLResponse)
    async def receipts(request: Request):
        store = DecisionReceiptStore(settings.decision_ledger_path)
        return render(request, "receipts.html", "/receipts",
                      ledger=store.verify(), law=content.DETERMINISTIC_LAW)

    @app.get("/methodology", response_class=HTMLResponse)
    async def methodology(request: Request):
        return render(request, "methodology.html", "/methodology",
                      law=content.DETERMINISTIC_LAW,
                      supported=content.SUPPORTED_DOMAINS,
                      deferred=content.DEFERRED_DOMAINS)

    @app.get("/status", response_class=HTMLResponse)
    async def status(request: Request):
        evidence = _evidence_summary(settings)
        scan = _scan(settings)
        return render(request, "status.html", "/status", evidence=evidence, scan=scan)

    @app.get("/privacy", response_class=HTMLResponse)
    async def privacy(request: Request):
        return render(request, "privacy.html", "/privacy", legal_entity=settings.legal_entity)

    @app.get("/terms", response_class=HTMLResponse)
    async def terms(request: Request):
        return render(request, "terms.html", "/terms", legal_entity=settings.legal_entity)

    # ------------------------- ops / SEO -------------------------
    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"status": "ok"}

    @app.get("/robots.txt", include_in_schema=False, response_class=PlainTextResponse)
    async def robots():
        return f"User-agent: *\nAllow: /\nSitemap: {settings.public_base_url.rstrip('/')}/sitemap.xml\n"

    @app.get("/sitemap.xml", include_in_schema=False)
    async def sitemap():
        base = settings.public_base_url.rstrip("/")
        paths = ["/", "/markets", "/calibration", "/receipts", "/docs", "/playground",
                 "/methodology", "/status", "/privacy", "/terms"]
        urls = "".join(f"<url><loc>{base}{p}</loc></url>" for p in paths)
        xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
        return Response(content=xml, media_type="application/xml")

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon():
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
            '<rect width="32" height="32" rx="6" fill="#0b0b0b"/>'
            '<circle cx="16" cy="16" r="9" fill="none" stroke="#3987e5" stroke-width="2.5"/>'
            '<line x1="16" y1="16" x2="16" y2="8.5" stroke="#fcfcfb" stroke-width="2.5" stroke-linecap="round"/>'
            '<line x1="16" y1="16" x2="21" y2="19" stroke="#fcfcfb" stroke-width="2.5" stroke-linecap="round"/>'
            "</svg>"
        )
        return Response(content=svg, media_type="image/svg+xml")

    return app


app = create_site()
