"""Stage 3 — compute and qualify the edge. Deterministic; no LLM.

edge_points = oracle_prob - implied_prob. On its own that number is
meaningless — it has to clear the oracle's own uncertainty band AND the
market's real trading friction before it's called actionable. This module
enforces the restraint layer described in the founding spec §9: when either
check fails, the honest answer is "no clear edge," not a confident verdict.

Constants used here are cited, not invented:
  - 0.07 is Kalshi's own published taker-fee rate: fee = ceil(fee_multiplier
    * 0.07 * contracts * price * (1-price)) per contract. Cross-referenced
    against multiple independent secondary sources and corroborated by
    Kalshi's own live API fields (`fee_type: "quadratic"` — P*(1-P) is
    quadratic in P — and `fee_multiplier`, the M term). The primary PDF
    (kalshi.com/docs/kalshi-fee-schedule.pdf) returned a bot-checkpoint page
    when fetched directly rather than the document itself — that gap is
    disclosed here and in docs/VERIFICATION_LEDGER.md, not papered over.
  - Polymarket's fee schedule has not been verified at all. Friction there
    uses the real quoted spread only; the missing fee term is a stated gap,
    not a guessed number standing in for real data.
"""
from datetime import datetime, timezone

KALSHI_TAKER_FEE_RATE = 0.07
DEFAULT_MAX_DATA_AGE_HOURS = 24.0
DEFAULT_MIN_CONFIDENCE = 0.55


def kalshi_taker_fee(price: float, fee_multiplier: float = 1.0) -> float:
    """Fee per $1-notional contract, in probability-point-equivalent units."""
    return fee_multiplier * KALSHI_TAKER_FEE_RATE * price * (1 - price)


def estimate_friction(market, fee_multiplier: float = 1.0) -> dict:
    half_spread = market.spread / 2
    if market.venue == "kalshi":
        fee = kalshi_taker_fee(market.implied_prob, fee_multiplier)
        method = "half the live bid/ask spread + Kalshi's published taker fee (0.07 * P * (1-P))"
    else:
        fee = 0.0
        method = (
            f"half the live bid/ask spread only — {market.venue}'s fee schedule is not yet "
            "verified (a disclosed gap, not a guessed fee)"
        )
    return {
        "half_spread": half_spread,
        "fee": fee,
        "total_friction": half_spread + fee,
        "method": method,
    }


def compute_edge(market, engine_result: dict, fee_multiplier: float = 1.0) -> dict:
    """market: a CanonicalMarket. engine_result: a Stage 2 engine's output
    dict (must carry oracle_prob, confidence, and ideally prob_low/prob_high
    for the uncertainty-band check)."""
    now = datetime.now(timezone.utc)

    if engine_result.get("refused") or engine_result.get("oracle_prob") is None:
        return {
            "actionable": False,
            "side": None,
            "edge_points": None,
            "reason": f"engine refused to produce a probability: {engine_result.get('reason', 'no reason given')}",
        }

    oracle_prob = engine_result["oracle_prob"]
    confidence = engine_result.get("confidence")
    prob_low = engine_result.get("prob_low")
    prob_high = engine_result.get("prob_high")

    implied = market.implied_prob
    edge_points = oracle_prob - implied
    side = "YES" if edge_points > 0 else "NO"
    friction = estimate_friction(market, fee_multiplier)

    base = {
        "side": side,
        "edge_points": edge_points,
        "confidence": confidence,
        "uncertainty_band": [prob_low, prob_high] if prob_low is not None else None,
        "friction": friction,
    }

    # Check 1 — is the market still forecastable, i.e. has resolution already passed?
    if market.resolution_time:
        try:
            resolution_dt = datetime.fromisoformat(market.resolution_time.replace("Z", "+00:00"))
            if resolution_dt < now:
                return {
                    **base,
                    "actionable": False,
                    "reason": "market's resolution time has already passed — cannot forecast the past",
                }
        except ValueError:
            pass  # unparseable resolution_time is a Stage-1 data-quality issue, not this check's job

    # Check 2 — is the underlying data fresh enough to trust?
    freshness = engine_result.get("data_freshness")
    if freshness:
        try:
            freshness_dt = datetime.fromisoformat(str(freshness).replace("Z", "+00:00"))
            age_hours = (now - freshness_dt).total_seconds() / 3600
            if age_hours > DEFAULT_MAX_DATA_AGE_HOURS:
                return {
                    **base,
                    "actionable": False,
                    "reason": (
                        f"data stale — source data was fetched {age_hours:.1f} hours ago, beyond "
                        f"the {DEFAULT_MAX_DATA_AGE_HOURS:.0f}-hour limit"
                    ),
                }
        except ValueError:
            return {
                **base,
                "actionable": False,
                "reason": "data freshness timestamp is unparseable — cannot certify source recency",
            }

    # Check 3 — do the sources/models agree enough to call an edge?
    if confidence is not None and confidence < DEFAULT_MIN_CONFIDENCE:
        return {
            **base,
            "actionable": False,
            "reason": (
                f"confidence low — sources/models disagree or are too thin "
                f"(confidence {confidence:.4f} < {DEFAULT_MIN_CONFIDENCE:.2f})"
            ),
        }

    # Check 4 — is the edge beyond the oracle's own uncertainty?
    if prob_low is not None and prob_high is not None and prob_low <= implied <= prob_high:
        return {
            **base,
            "actionable": False,
            "reason": (
                f"within noise — the market's implied probability {implied:.4f} falls inside "
                f"the oracle's own uncertainty band [{prob_low:.4f}, {prob_high:.4f}]"
            ),
        }

    # Check 5 — is the edge beyond real trading friction?
    if abs(edge_points) <= friction["total_friction"]:
        return {
            **base,
            "actionable": False,
            "reason": (
                f"smaller than trading cost — edge of {abs(edge_points):.4f} does not exceed "
                f"estimated friction of {friction['total_friction']:.4f} ({friction['method']})"
            ),
        }

    return {
        **base,
        "actionable": True,
        "reason": "edge exceeds both the oracle's own uncertainty band and estimated trading friction",
    }
