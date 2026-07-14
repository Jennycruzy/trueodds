"""Read-only live release audit for scan coverage and energy validation."""
from __future__ import annotations

import json

from rwoo import economic_sources
from rwoo.engines.energy import backtest_henry_hub_annual_high
from rwoo.scanner import EXPANSION_FAMILIES, scan_opportunities


def main() -> int:
    scan = scan_opportunities()
    energy_rows = [row for row in scan["top"] if row.get("family") == "energy.henry_hub_spot"]
    thresholds = sorted({
        float((row.get("event_identity") or {})["floor_strike"])
        for row in energy_rows
        if (row.get("event_identity") or {}).get("floor_strike") is not None
    })
    history = economic_sources.fetch_fred_series("DHHNGSP")
    backtest = backtest_henry_hub_annual_high(
        history, thresholds=thresholds or [4.0, 5.0, 6.0, 8.0, 10.0],
    )
    output = {
        "scan": {
            key: scan.get(key) for key in (
                "created_at", "markets_seen", "markets_evaluated", "markets_included",
                "markets_included_unsupported", "markets_skipped", "actionable_count",
                "dynamically_discovered_expansion_series", "expansion_family_counts",
                "coverage_status_counts", "errors",
            )
        },
        "expansion_rows": [
            {key: row.get(key) for key in (
                "venue", "market_id", "question", "family", "shape", "coverage_status",
                "oracle_prob", "prob_low", "prob_high", "actionable", "reason", "model_version",
            )}
            for row in scan["top"] if row.get("family") in EXPANSION_FAMILIES
        ],
        "henry_hub_backtest": {key: value for key, value in backtest.items() if key != "rows"},
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if not scan["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
