"""Canonical market representation — the common shape every venue reader
normalizes into, per the founding spec's Stage 1 definition."""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CanonicalMarket:
    venue: str  # "kalshi" | "polymarket"
    market_id: str  # venue-native ticker / condition id
    question: str
    domain: str  # "weather" | "economics" | "sports" | "commodities" | "other"
    resolution_rule: str  # verbatim settlement rule text
    resolution_source: str  # named official source (e.g. "NWS Climatological Report")
    resolution_time: Optional[str]  # ISO8601 timestamp the market settles at/by
    implied_prob: float  # bid/ask midpoint, NOT last trade
    spread: float  # ask - bid, i.e. trading friction
    fetched_at: str  # ISO8601 timestamp this object was built
    # The venue-native label of the outcome `implied_prob` prices (e.g. the
    # player a Kalshi YES backs, a Polymarket groupItemTitle, a Limitless child
    # title). Head-to-head engines bind their probability to THIS side instead
    # of guessing from title word order; None when the venue exposes no label.
    yes_subtitle: Optional[str] = None
    # Distinct from resolution_time: this is the last instant at which the
    # venue says an order can be accepted.  Ranking against settlement time
    # caused near-close contracts to be advertised as tradable.
    trading_close_time: Optional[str] = None
    market_status: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def describe(self) -> str:
        """Plain-English rendering for the verification harness — no jargon."""
        lines = [
            f"[{self.venue.upper()}] {self.question}",
            f"  Market ID: {self.market_id}",
            f"  Domain: {self.domain}",
            f"  Resolves by: {self.resolution_time or 'unknown'}",
            f"  Resolution rule (verbatim): \"{self.resolution_rule}\"",
            f"  Settlement source: {self.resolution_source or 'not specified'}",
            f"  Implied probability (bid/ask midpoint): {self.implied_prob:.4f}",
            f"  Spread (trading friction): {self.spread:.4f}",
            f"  Fetched at: {self.fetched_at}",
        ]
        return "\n".join(lines)
