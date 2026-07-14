"""Runtime configuration for the ASP.

Every public URL, allowed origin, trusted host, ledger path, and listing field
is derived from environment variables so nothing about a specific deployment
(domain name, VPS IP, wallet, price) is baked into code. The defaults are
deliberately local-only placeholders; production values come from the operator
via the environment (see docs/EVIDENCE_AND_EXECUTION.md and the deploy/ tree).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value is not None and value != "" else default


def _env_list(name: str, default: str) -> list[str]:
    raw = _env(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # Canonical public URLs — generated, never hardcoded elsewhere.
    public_base_url: str = field(default_factory=lambda: _env("RWOO_PUBLIC_BASE_URL", "http://localhost:8000"))
    api_base_url: str = field(default_factory=lambda: _env("RWOO_API_BASE_URL", "http://localhost:8000"))
    docs_url: str = field(default_factory=lambda: _env("RWOO_DOCS_URL", "http://localhost:8000/docs"))
    calibration_url: str = field(default_factory=lambda: _env("RWOO_CALIBRATION_URL", "http://localhost:8000/calibration"))
    receipts_url: str = field(default_factory=lambda: _env("RWOO_RECEIPTS_URL", "http://localhost:8000/receipts"))
    support_email: str = field(default_factory=lambda: _env("RWOO_SUPPORT_EMAIL", "support@example.invalid"))
    # Legal identity for privacy/terms — an operator input; empty until supplied
    # so the pages honestly show a pending state rather than inventing an entity.
    legal_entity: str = field(default_factory=lambda: _env("RWOO_LEGAL_ENTITY", ""))

    # Security surfaces.
    allowed_origins: list[str] = field(default_factory=lambda: _env_list("RWOO_ALLOWED_ORIGINS", "http://localhost:8000"))
    trusted_hosts: list[str] = field(default_factory=lambda: _env_list("RWOO_TRUSTED_HOSTS", "localhost,127.0.0.1,testserver"))

    # Artifact + ledger paths (repo-relative defaults).
    opportunity_scan_path: Path = field(default_factory=lambda: Path(_env("RWOO_OPPORTUNITY_SCAN_PATH", "data/public/opportunity_scan_latest.json")))
    calibration_report_path: Path = field(default_factory=lambda: Path(_env("RWOO_CALIBRATION_REPORT_PATH", "data/public/calibration_report_latest.json")))
    evidence_ledger_path: Path = field(default_factory=lambda: Path(_env("RWOO_EVIDENCE_LEDGER_PATH", "data/receipts/forecast_evidence.jsonl")))
    decision_ledger_path: Path = field(default_factory=lambda: Path(_env("RWOO_DECISION_LEDGER_PATH", "data/receipts/decision_receipts.jsonl")))

    # Request handling limits.
    max_body_bytes: int = field(default_factory=lambda: _env_int("RWOO_MAX_BODY_BYTES", 32_768))
    upstream_timeout_seconds: float = field(default_factory=lambda: _env_float("RWOO_UPSTREAM_TIMEOUT_SECONDS", 20.0))
    signal_scan_max_age_minutes: int = field(default_factory=lambda: _env_int("RWOO_SIGNAL_SCAN_MAX_AGE_MINUTES", 45))
    signal_min_close_lead_minutes: int = field(default_factory=lambda: _env_int("RWOO_SIGNAL_MIN_CLOSE_LEAD_MINUTES", 60))
    signal_max_spread: float = field(default_factory=lambda: _env_float("RWOO_SIGNAL_MAX_SPREAD", 0.12))

    # Payment configuration lives in rwoo.api.payment.PaymentConfig (its own
    # env surface). It is off by default and MUST NOT be enabled without an
    # operator-approved recipient, network, asset, decimals, and price.

    def verification_url(self, record_hash: str) -> str:
        return f"{self.api_base_url.rstrip('/')}/v1/receipts/{record_hash}/verify"


_SETTINGS: Settings | None = None


def get_settings() -> Settings:
    """Process-wide settings singleton (read once at startup)."""
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = Settings()
    return _SETTINGS


def reset_settings_for_test(settings: Settings | None = None) -> None:
    """Test hook — replace or clear the cached settings."""
    global _SETTINGS
    _SETTINGS = settings
