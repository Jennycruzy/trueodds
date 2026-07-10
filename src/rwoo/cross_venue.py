"""Conservative cross-venue equivalence and executable edge detection.

Similar titles are only candidates.  An executable cross-venue edge is
reported solely when event wording, settlement source, and resolution time
normalize identically.  This intentionally under-matches rather than selling
a false arbitrage caused by different contract rules.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

from rwoo.edge import estimate_friction


def _normalize(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def equivalence_assessment(left, right) -> dict[str, Any]:
    checks = {
        "different_venues": left.venue != right.venue,
        "question": _normalize(left.question) == _normalize(right.question),
        "resolution_source": bool(_normalize(left.resolution_source))
        and _normalize(left.resolution_source) == _normalize(right.resolution_source),
        "resolution_time": bool(left.resolution_time)
        and left.resolution_time == right.resolution_time,
        "yes_orientation": _normalize(left.yes_subtitle or "yes")
        == _normalize(right.yes_subtitle or "yes"),
    }
    exact = all(checks.values())
    if exact:
        classification = "exact_equivalent"
    elif checks["different_venues"] and checks["question"]:
        classification = "candidate_needs_rule_review"
    else:
        classification = "not_equivalent"
    return {
        "classification": classification,
        "checks": checks,
        "safe_for_cross_venue_edge": exact,
        "reason": (
            "normalized question, settlement authority, resolution time, and YES orientation match"
            if exact
            else "contract equivalence is not proven; no arbitrage claim is permitted"
        ),
    }


def _quotes(market) -> dict[str, float]:
    yes_bid = max(0.0, market.implied_prob - market.spread / 2)
    yes_ask = min(1.0, market.implied_prob + market.spread / 2)
    return {"yes_bid": yes_bid, "yes_ask": yes_ask, "no_bid": 1 - yes_ask, "no_ask": 1 - yes_bid}


def cross_venue_edge(left, right) -> dict[str, Any]:
    equivalence = equivalence_assessment(left, right)
    base = {
        "markets": [
            {"venue": left.venue, "market_id": left.market_id, "question": left.question},
            {"venue": right.venue, "market_id": right.market_id, "question": right.question},
        ],
        "equivalence": equivalence,
    }
    if not equivalence["safe_for_cross_venue_edge"]:
        return {**base, "actionable": False, "edge": None, "reason": equivalence["reason"]}

    lq, rq = _quotes(left), _quotes(right)
    candidates = []
    for yes_market, no_market, yq, nq in ((left, right, lq, rq), (right, left, rq, lq)):
        yes_friction = estimate_friction(yes_market, side="YES")
        no_friction = estimate_friction(no_market, side="NO")
        entry_cost = yq["yes_ask"] + nq["no_ask"]
        fees = yes_friction["fee"] + no_friction["fee"]
        total_cost = entry_cost + fees
        candidates.append(
            {
                "buy_yes": {"venue": yes_market.venue, "market_id": yes_market.market_id, "price": yq["yes_ask"]},
                "buy_no": {"venue": no_market.venue, "market_id": no_market.market_id, "price": nq["no_ask"]},
                "entry_cost": entry_cost,
                "estimated_fees": fees,
                "total_cost": total_cost,
                "locked_payout": 1.0,
                "net_edge": 1.0 - total_cost,
            }
        )
    best = max(candidates, key=lambda row: row["net_edge"])
    actionable = best["net_edge"] > 0
    return {
        **base,
        "actionable": actionable,
        "edge": best,
        "alternatives": candidates,
        "reason": (
            "executable complementary asks plus estimated fees are below the $1 locked payout"
            if actionable
            else "no positive executable cross-venue edge after asks and estimated fees"
        ),
        "risk_disclosure": (
            "Locked payout assumes both orders fill and both venues settle identically; execution, custody, "
            "venue, cancellation, and settlement risks remain."
        ),
    }


def find_cross_venue_edges(markets: Iterable) -> list[dict[str, Any]]:
    groups: dict[str, list] = {}
    for market in markets:
        groups.setdefault(_normalize(market.question), []).append(market)
    results = []
    for group in groups.values():
        for index, left in enumerate(group):
            for right in group[index + 1:]:
                if left.venue == right.venue:
                    continue
                result = cross_venue_edge(left, right)
                if result["equivalence"]["classification"] != "not_equivalent":
                    results.append(result)
    return sorted(results, key=lambda row: (row["actionable"], (row.get("edge") or {}).get("net_edge", -1)), reverse=True)
