"""Structured, brand-level content shared across pages.

Prose that is genuinely static (workflow, the Deterministic-Core Law, coverage
posture, error meanings, code examples) lives here so templates stay layout.
Anything that is a *measured value* is never here — those come from the live
artifacts at request time.
"""
from __future__ import annotations

SITE_NAME = "Real-World Odds Oracle"
TAGLINE = "The true odds, proven."
DISCLAIMER = "Probabilities are estimates, not guarantees. No forecast is guaranteed to win."

WORKFLOW_STEPS = [
    ("Read the rule", "Bind the exact resolution rule, settlement source, resolution time, entity/location, strike, and which side YES prices. If any of these can't be bound, the oracle refuses rather than guesses."),
    ("Compute the probability", "A deterministic engine — never an LLM — produces the independent probability from real-world sources, with an uncertainty interval and an explicit model version."),
    ("Compare price and cost", "Read the executable bid/ask (not last trade), estimate venue fees, and compute net expected value. An edge is only called actionable if it clears both the oracle's own uncertainty and real trading friction."),
    ("Explain the uncertainty", "Surface source and model disagreement, the model range, and the largest outlier — so the confidence is legible, not asserted."),
    ("Commit a receipt", "Hash-commit the decision into an append-only, tamper-evident ledger, linked by request id. A receipt exists whether the market resolves or not."),
    ("Resolve and calibrate", "When the market settles, record the outcome against the precommitted forecast and update the public calibration record — losses kept, not hidden."),
]

SERVICES = [
    {
        "name": "rwoo.best_signals",
        "underscore": "rwoo_best_signals",
        "path": "/v1/signals",
        "method": "POST",
        "paid": True,
        "blurb": "Natural-language command returning ranked, currently open signals after freshness, close-time, executable-price, spread, model-version, and evidence checks.",
    },
    {
        "name": "rwoo.check_market",
        "underscore": "rwoo_check_market",
        "path": "/v1/check-market",
        "method": "POST",
        "paid": True,
        "blurb": "Independent probability, uncertainty interval, model version, confidence, executable-price EV, model-disagreement explanation, and a tamper-evident receipt for one supported market.",
    },
    {
        "name": "rwoo.cross_venue_edge",
        "underscore": "rwoo_cross_venue_edge",
        "path": "/v1/cross-venue-edge",
        "method": "POST",
        "paid": True,
        "blurb": "Conservative cross-venue equivalence and executable complementary edge. Only exact equivalence is actionable, and it is never called risk-free.",
    },
    {
        "name": "rwoo.get_calibration",
        "underscore": "rwoo_get_calibration",
        "path": "/v1/calibration",
        "method": "GET",
        "paid": False,
        "blurb": "The public, precommitted calibration record by domain, family, model version, and probability band — with independent event counts always shown.",
    },
]

DETERMINISTIC_LAW = [
    "Deterministic code produces every probability.",
    "An LLM may route and narrate, but may not create, alter, veto, or sanity-check a probability.",
    "Unsupported or ambiguous markets fail closed.",
    "Unknown entities never silently become probability zero.",
    "Every result identifies its model version.",
    "Every successful or refused decision remains auditable.",
    "Model agreement is not automatically empirical calibration confidence.",
    "Missing data stays missing, not zero.",
    "The evidence and receipt ledgers are append-only.",
]

EQUIVALENCE_CLASSES = [
    ("exact_equivalent", "Rule, settlement authority, resolution time, and YES orientation all match. Only this class can be actionable."),
    ("candidate_needs_rule_review", "Titles align but at least one binding is unverified. Not tradeable as arbitrage."),
    ("related_not_equivalent", "Same topic, materially different contract."),
    ("not_equivalent", "Different events."),
]

CROSS_VENUE_RISK = ("Complementary executable-price edge, subject to fill, custody, "
                    "venue, cancellation, and settlement risk.")

SUPPORTED_DOMAINS = [
    ("Weather", "Daily temperature maxima/minima and precipitation for verified stations, plus NOAA-resolved Atlantic seasonal named-storm, hurricane, and major-hurricane count thresholds.", "supported"),
    ("Economics", "Headline & core CPI, GDP, unemployment, payrolls, Fed rate decisions, and recession-quarter nowcasts against official releases.", "supported"),
    ("Sports", "World Cup winner and stage-of-elimination markets currently produce candidates. Tennis, MLB, and club-soccer match engines are conditional; NBA, NHL, esports, props, and unsupported outrights fail closed as detailed below.", "partial"),
    ("Energy", "EIA-resolved Henry Hub annual-high thresholds are priced from official daily history. Other energy price definitions remain source-gated.", "partial"),
    ("Agriculture", "Agricultural markets are classified and measured, but exact price-feed and USDA report shapes remain source-gated until verified open contracts exist.", "discovery"),
]

DEFERRED_DOMAINS = [
    "Markets whose resolution rule, source, time, entity, strike, or YES side cannot be bound.",
    "Venues whose fee schedule is not yet verified (edge is disclosed, never guessed).",
    "Anything requiring subjective judgement rather than a data source.",
]

# HTTP error taxonomy, described for humans. Kept in sync with rwoo.api.errors.
ERROR_TABLE = [
    ("INVALID_REQUEST", 400, "Body failed schema validation or exceeded limits."),
    ("MARKET_NOT_FOUND", 404, "The venue has no such market id."),
    ("UNSUPPORTED_VENUE", 400, "Venue is not one of kalshi, polymarket, limitless."),
    ("UNSUPPORTED_MARKET", 422, "No wired engine covers this market shape (refusal)."),
    ("ENTITY_UNBOUND", 422, "The entity/location/strike could not be bound (refusal)."),
    ("YES_SIDE_UNBOUND", 422, "Which side YES prices could not be determined (refusal)."),
    ("SOURCE_UNAVAILABLE", 503, "A required upstream source could not be reached."),
    ("SOURCE_STALE", 422, "Source data is older than the freshness limit (refusal)."),
    ("SOURCE_CONFLICT", 422, "Sources disagree beyond tolerance (refusal)."),
    ("MODEL_MISSING", 422, "The engine declined to emit a probability (refusal)."),
    ("FEE_UNKNOWN", 422, "The venue fee term is not quantified (refusal)."),
    ("RATE_LIMITED", 429, "Too many requests, or an upstream rate limit."),
    ("PAYMENT_REQUIRED", 402, "A paid endpoint was called without payment (x402 challenge)."),
    ("PAYMENT_INVALID", 402, "The presented payment failed verification."),
    ("PAYMENT_REPLAYED", 402, "The payment nonce was already used."),
    ("UPSTREAM_TIMEOUT", 504, "An upstream source timed out."),
    ("INTERNAL_ERROR", 500, "An unexpected error (no stack trace is exposed)."),
]

CHANGELOG = [
    ("v1.0.0", "ASP surface: Best Signals plus three supporting services, receipts, calibration evidence, and the OKX Agent Payments (x402) 402 flow. Funded execution remains disabled."),
]


def code_examples(api_base: str) -> dict[str, str]:
    """Client snippets, generated against the configured API base URL. No
    signatures or secrets appear — the payment payload is produced by the
    caller's own wallet/agent, never here."""
    body = '{"message":"Give me the best weather signals now","limit":5}'
    return {
        "curl": (
            f"curl -sS -X POST {api_base}/v1/signals \\\n"
            f"  -H 'Content-Type: application/json' \\\n"
            f"  -d '{body}'\n"
            f"# A paid deployment answers 402 with a PAYMENT-REQUIRED header;\n"
            f"# have the agent wallet sign it, then re-send the identical body\n"
            f"# with PAYMENT-SIGNATURE to receive 200."
        ),
        "python": (
            "import httpx\n\n"
            f'BASE = "{api_base}"\n'
            'req = {"message": "Give me the best weather signals now", "limit": 5}\n'
            'r = httpx.post(f"{BASE}/v1/signals", json=req, timeout=30)\n'
            "if r.status_code == 402:\n"
            "    challenge = r.headers['PAYMENT-REQUIRED']\n"
            "    # Agent wallet signs the challenge; retry the identical body\n"
            "    # with the resulting PAYMENT-SIGNATURE header.\n"
            "print(r.json())"
        ),
        "typescript": (
            f'const BASE = "{api_base}";\n'
            'const req = { message: "Give me the best weather signals now", limit: 5 };\n'
            'const r = await fetch(`${BASE}/v1/signals`, {\n'
            '  method: "POST",\n'
            '  headers: { "Content-Type": "application/json" },\n'
            "  body: JSON.stringify(req),\n"
            "});\n"
            "// On 402, read PAYMENT-REQUIRED, sign with the agent wallet,\n"
            "// then retry the identical body with PAYMENT-SIGNATURE.\n"
            "console.log(await r.json());"
        ),
        "agent_json": body,
    }
