"""Truthful sports capability metadata and live-scan summaries.

Registered model identifiers are not the same thing as a currently usable
signal.  This module keeps that distinction explicit for agents and humans.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from rwoo.identity import MODEL_VERSIONS


SPORTS_COVERAGE = [
    {
        "sport": "FIFA World Cup",
        "family": "sports.world_cup",
        "availability": "live_signal_candidate",
        "market_shapes": ["2026 national-team winner", "stage of elimination"],
        "model_version": MODEL_VERSIONS["sports.world_cup"],
        "data_sources": ["official FIFA calendar/rankings", "World Football Elo"],
        "limitations": "Props, top scorer, goals, and exact matchup outcomes are not priced. Signals remain experimental unless exact-version prospective evidence is promotion-eligible.",
    },
    {
        "sport": "Tennis",
        "family": "sports.tennis",
        "availability": "conditional_engine",
        "market_shapes": ["head-to-head match winner with exact YES-side binding"],
        "model_version": MODEL_VERSIONS["sports.tennis"],
        "data_sources": ["Ultimate Tennis Statistics Elo"],
        "limitations": "No qualifying markets in the current scan. Tournament outrights are unsupported because no draw/bracket simulation is wired.",
    },
    {
        "sport": "MLB / baseball",
        "family": "sports.mlb",
        "availability": "conditional_engine",
        "market_shapes": ["head-to-head game winner with exact YES-side binding"],
        "model_version": MODEL_VERSIONS["sports.mlb"],
        "data_sources": ["official MLB Stats API completed-game results"],
        "limitations": "No qualifying markets in the current scan. The current-season Elo model has no pitcher or lineup adjustment; World Series/champion outrights are unsupported.",
    },
    {
        "sport": "Club soccer",
        "family": "sports.club_soccer",
        "availability": "conditional_engine",
        "market_shapes": ["head-to-head match winner with exact YES-side binding"],
        "model_version": MODEL_VERSIONS["sports.club_soccer"],
        "data_sources": ["ClubElo"],
        "limitations": "No qualifying markets in the current scan. Draw and home-field effects are not modeled, so ambiguous or unsuitable contracts fail closed.",
    },
    {
        "sport": "NBA / basketball",
        "family": "sports.nba",
        "availability": "conditional_engine",
        "market_shapes": ["head-to-head game winner with exact YES-side binding"],
        "model_version": MODEL_VERSIONS["sports.nba"],
        "data_sources": ["ESPN season point differential (engine input)"],
        "limitations": "The conservative head-to-head parser and engine are wired. Champion futures remain model-missing; basketball requests return no_signal when no qualifying head-to-head row exists.",
    },
    {
        "sport": "NHL / hockey",
        "family": "sports.nhl",
        "availability": "unsupported_fails_closed",
        "market_shapes": [],
        "model_version": None,
        "data_sources": [],
        "limitations": "Current champion futures are visible in scans but no approved champion model is wired.",
    },
    {
        "sport": "Esports",
        "family": "sports.esports",
        "availability": "unsupported_fails_closed",
        "market_shapes": [],
        "model_version": None,
        "data_sources": [],
        "limitations": "Markets may be discovered, but no approved source and probability model are wired.",
    },
]


def sports_scan_summary(scan: dict[str, Any] | None) -> dict[str, Any]:
    """Return measured sports counts from the current scan artifact."""
    rows = [row for row in ((scan or {}).get("top") or []) if row.get("domain") == "sports"]
    families = Counter(str(row.get("family") or "sports.unclassified") for row in rows)
    statuses = Counter(str(row.get("coverage_status") or ("actionable" if row.get("actionable") else "not_actionable")) for row in rows)
    venues = Counter(str(row.get("venue") or "unknown") for row in rows)
    return {
        "scan_created_at": (scan or {}).get("created_at"),
        "sports_rows": len(rows),
        "actionable_rows": sum(bool(row.get("actionable")) for row in rows),
        "by_family": dict(sorted(families.items())),
        "by_coverage_status": dict(sorted(statuses.items())),
        "by_venue": dict(sorted(venues.items())),
    }
