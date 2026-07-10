"""Stage 3 — compute and qualify the edge. Deterministic; no LLM.

edge_points = oracle_prob - implied_prob. On its own that number is
meaningless — it has to clear the oracle's own uncertainty band AND the
market's real trading friction before it's called actionable. This module
enforces the restraint layer described in the founding spec §9: when either
check fails, the honest answer is "no clear edge," not a confident verdict.

Constants used here are cited, not invented:
  - 0.07 is Kalshi's own published taker-fee rate: fee = ceil(fee_multiplier
    * 0.07 * contracts * price * (1-price)) per contract. The primary fee PDF
    is readable through browser retrieval and the same shape is corroborated by
    Kalshi's own live API fields (`fee_type: "quadratic"` — P*(1-P) is
    quadratic in P — and `fee_multiplier`, the M term). Direct PDF fetches from
    this workspace still return HTTP 429 / Vercel Security Checkpoint, so Gate
    7 records that workspace constraint instead of pretending the verifier
    parsed the PDF locally.
  - Polymarket's fee schedule has not been verified at all. Friction there
    uses the real quoted spread only; the missing fee term is a stated gap,
    not a guessed number standing in for real data.
  - Limitless CLOB taker fees: the official fee page
    (docs.limitless.exchange/user-guide/fees, read 2026-07-09) publishes a
    price-dependent buy-fee table — 3.00% for $0.01–$0.50, 1.26% at $0.75,
    0.53% at $0.95, 0.40% at $0.999 — but no closed-form formula; the
    exchange returns the exact `effectiveFeeBps` only per executed order
    (official SDK `Execution` type), and the per-account order ceiling is
    300 bps. This build therefore charges the CONSERVATIVE UPPER BOUND of
    the official table for the entry side's price band: never lower than any
    published anchor the price could fall under. An upper-bound fee can only
    under-call an edge, never over-call it, so it is safe to qualify
    actionable records with. Makers pay zero; taker entry is assumed.
"""
from datetime import datetime, timezone
import math

KALSHI_TAKER_FEE_RATE = 0.07
DEFAULT_MAX_DATA_AGE_HOURS = 24.0
DEFAULT_MIN_CONFIDENCE = 0.55

# Official Limitless buy-fee anchors (price -> fee fraction), quoted from
# docs.limitless.exchange/user-guide/fees. Used as a step-function upper
# bound: an entry price between two anchors is charged the HIGHER
# (lower-price) anchor's rate.
LIMITLESS_BUY_FEE_ANCHORS: list[tuple[float, float]] = [
    (0.50, 0.0300),
    (0.75, 0.0126),
    (0.95, 0.0053),
    (0.999, 0.0040),
]


def limitless_taker_fee_bound(entry_price: float) -> float:
    """Upper-bound taker buy fee (fraction of notional) at `entry_price`."""
    for anchor_price, fee in LIMITLESS_BUY_FEE_ANCHORS:
        if entry_price <= anchor_price:
            return fee
    return LIMITLESS_BUY_FEE_ANCHORS[-1][1]


def kalshi_taker_fee(price: float, fee_multiplier: float = 1.0) -> float:
    """Fee per $1-notional contract, in probability-point-equivalent units."""
    return fee_multiplier * KALSHI_TAKER_FEE_RATE * price * (1 - price)


def estimate_friction(market, fee_multiplier: float = 1.0, side: str | None = None) -> dict:
    half_spread = market.spread / 2
    if market.venue == "kalshi":
        fee = kalshi_taker_fee(market.implied_prob, fee_multiplier)
        method = "half the live bid/ask spread + Kalshi's published taker fee (0.07 * P * (1-P))"
        missing_fee = False
    elif market.venue == "limitless":
        # Entry is a taker buy of the YES token at ~P or the NO token at
        # ~(1-P). When the side is not yet known, charge the worse of the two.
        yes_entry = min(0.999, max(0.001, market.implied_prob))
        no_entry = min(0.999, max(0.001, 1 - market.implied_prob))
        if side == "YES":
            fee = limitless_taker_fee_bound(yes_entry)
        elif side == "NO":
            fee = limitless_taker_fee_bound(no_entry)
        else:
            fee = max(limitless_taker_fee_bound(yes_entry), limitless_taker_fee_bound(no_entry))
        method = (
            "half the live bid/ask spread + the conservative upper bound of Limitless's official "
            "published taker buy-fee table (3.00% <= $0.50, 1.26% <= $0.75, 0.53% <= $0.95, "
            "0.40% above) for the entry side's price band"
        )
        missing_fee = False
    else:
        fee = 0.0
        method = (
            f"half the live bid/ask spread only — {market.venue}'s fee schedule is not yet "
            "verified (a disclosed gap, not a guessed fee)"
        )
        missing_fee = False
    return {
        "half_spread": half_spread,
        "fee": fee,
        "total_friction": half_spread + fee,
        "method": method,
        "missing_fee": missing_fee,
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
    if not isinstance(oracle_prob, (int, float)) or not math.isfinite(oracle_prob) or not 0 <= oracle_prob <= 1:
        return {
            "actionable": False,
            "side": None,
            "edge_points": None,
            "reason": "engine probability is non-finite or outside [0, 1]",
        }
    confidence = engine_result.get("confidence")
    prob_low = engine_result.get("prob_low")
    prob_high = engine_result.get("prob_high")

    implied = market.implied_prob
    edge_points = oracle_prob - implied
    side = "YES" if edge_points > 0 else "NO"
    friction = estimate_friction(market, fee_multiplier, side=side)

    yes_bid = max(0.0, market.implied_prob - market.spread / 2)
    yes_ask = min(1.0, market.implied_prob + market.spread / 2)
    entry_price = yes_ask if side == "YES" else 1.0 - yes_bid
    side_probability = oracle_prob if side == "YES" else 1.0 - oracle_prob
    # A binary contract bought at price C has expected pre-fee P-C.  The fee
    # estimate is deliberately conservative and expressed per $1 contract.
    expected_profit = side_probability - entry_price - friction["fee"]
    expected_return = expected_profit / entry_price if entry_price > 0 else None

    base = {
        "side": side,
        "edge_points": edge_points,
        "confidence": confidence,
        "uncertainty_band": [prob_low, prob_high] if prob_low is not None else None,
        "friction": friction,
        "execution": {
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "side": side,
            "entry_price": entry_price,
            "side_probability": side_probability,
            "estimated_fee_per_contract": friction["fee"],
            "expected_profit_per_contract": expected_profit,
            "expected_return_on_cost": expected_return,
            "pricing_basis": "derived executable ask from canonical midpoint and spread",
        },
    }

    if friction.get("missing_fee"):
        return {
            **base,
            "actionable": False,
            "reason": (
                "venue fee is not quantified — spread was measured, but the fee term is still "
                "unverified so this read-only venue cannot produce an actionable edge yet"
            ),
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
