"""Truthful coverage metadata for weather/commodity market expansion."""
from __future__ import annotations

from collections import Counter
from typing import Any

from rwoo.identity import MODEL_VERSIONS


EXPANSION_COVERAGE = [
    {
        "market": "Atlantic seasonal storm counts",
        "family": "weather.hurricane_season",
        "availability": "live_signal_candidate",
        "market_shapes": ["named storms above threshold", "hurricanes above threshold", "major hurricanes above threshold"],
        "model_version": MODEL_VERSIONS["weather.hurricane_season"],
        "data_sources": ["NOAA CPC Atlantic seasonal outlook", "NHC current-season summary"],
        "limitations": "Only structured NOAA-resolved Atlantic count thresholds are priced. Landfall, category-at-landfall, damage, and individual-storm paths are not inferred from this model.",
    },
    {
        "market": "Henry Hub natural gas",
        "family": "energy.henry_hub_spot",
        "availability": "live_signal_candidate",
        "market_shapes": ["calendar-year daily spot-price maximum above threshold"],
        "model_version": MODEL_VERSIONS["energy.henry_hub_spot"],
        "data_sources": ["EIA Henry Hub DHHNGSP official series via FRED public mirror"],
        "limitations": "Only EIA-resolved annual-high thresholds are priced. Futures, weekly/monthly extrema, and unrelated gas-price definitions remain gated until separately validated.",
    },
    {
        "market": "Other energy prices",
        "family": "energy.commodity_price",
        "availability": "source_gated",
        "market_shapes": [],
        "model_version": MODEL_VERSIONS["energy.commodity_price"],
        "data_sources": [],
        "limitations": "WTI, Brent, retail gasoline, Pyth, ICE, and other price contracts are classified and measured but refused until their exact settlement feed and history adapter are approved.",
    },
    {
        "market": "Agriculture prices and reports",
        "family": "agriculture.commodity_price",
        "availability": "source_gated",
        "market_shapes": [],
        "model_version": MODEL_VERSIONS["agriculture.commodity_price"],
        "data_sources": [],
        "limitations": "Corn, wheat, soybeans, cattle, coffee, cocoa, and sugar are classified but not priced without the contract's exact approved feed. A USDA model is activated only for a verified recurring open USDA-resolved contract shape.",
    },
]


def expansion_scan_summary(scan: dict[str, Any] | None) -> dict[str, Any]:
    rows = [row for row in ((scan or {}).get("top") or [])
            if row.get("family") in {item["family"] for item in EXPANSION_COVERAGE}]
    statuses = Counter(str(row.get("coverage_status") or "unknown") for row in rows)
    families = Counter(str(row.get("family") or "unknown") for row in rows)
    return {
        "scan_created_at": (scan or {}).get("created_at"),
        "rows": len(rows),
        "actionable_rows": sum(bool(row.get("actionable")) for row in rows),
        "by_family": dict(sorted(families.items())),
        "by_coverage_status": dict(sorted(statuses.items())),
        "dynamically_discovered_series": (scan or {}).get("dynamically_discovered_expansion_series", []),
        "unsupported_market_telemetry": (scan or {}).get("unsupported_market_telemetry", []),
    }
