"""Deterministic domain routing — keyword/category rules, never an LLM.

This only sorts a market into weather/economics/sports/commodities/other so Stage 2 can
pick an engine; it is not a probability and has no bearing on the
Deterministic-Core Law either way, but it is kept rule-based for the same
reason everything else is: reproducibility. Given the same market object,
this function always returns the same domain.
"""
import re

# Kalshi exposes an explicit, clean category string per event/series.
# Verified live 2026-07-08 (docs/VERIFICATION_LEDGER.md) against
# GET /trade-api/v2/series — the full real category list returned was:
# ['Climate and Weather', 'Commodities', 'Companies', 'Crypto', 'Economics',
#  'Education', 'Elections', 'Entertainment', 'Exotics', 'Financials',
#  'Health', 'Mentions', 'Politics', 'Science and Technology', 'Social',
#  'Sports', 'Transportation', 'World']
KALSHI_CATEGORY_MAP = {
    "Climate and Weather": "weather",
    "Economics": "economics",
    "Financials": "economics",
    "Commodities": "commodities",
    "Sports": "sports",
}

_WEATHER_KEYWORDS = (
    "temperature", "high temp", "low temp", "rainfall", "rain", "snow",
    "snowfall", "hurricane", "hurricanes", "storm", "storms", "wind speed", "heat wave", "weather",
)
_ECON_KEYWORDS = (
    "cpi", "inflation", "gdp", "unemployment", "jobs report", "nonfarm",
    "fed ", "federal reserve", "interest rate", "fomc", "recession",
)
_SPORTS_KEYWORDS = (
    "vs.", "vs ", "wins the", "championship", "playoff", "world cup",
    "super bowl", "nba", "nfl", "mlb", "nhl", "ncaa",
)
_COMMODITY_KEYWORDS = (
    "wti", "brent crude", "brent oil", "brent price", "brent futures",
    "crude oil", "natural gas", "henry hub", "gasoline",
    "heating oil", "corn price", "wheat price", "soybean", "live cattle",
    "coffee price", "cocoa price", "sugar price",
)


def classify_kalshi(category: str | None, question: str) -> str:
    if category and category in KALSHI_CATEGORY_MAP:
        return KALSHI_CATEGORY_MAP[category]
    return _classify_by_keywords(question)


def classify_polymarket(tag_labels: list[str], question: str) -> str:
    lowered = {t.lower() for t in tag_labels}
    if lowered & {"weather", "climate"}:
        return "weather"
    if lowered & {"economy", "economics", "finance", "fed", "inflation"}:
        return "economics"
    if lowered & {"sports", "nba", "nfl", "mlb", "nhl", "soccer", "football"}:
        return "sports"
    if lowered & {"commodities", "commodity", "oil", "natural gas", "agriculture"}:
        return "commodities"
    return _classify_by_keywords(question)


def classify_limitless(categories: list[str], tags: list[str], question: str, description: str = "") -> str:
    labels = {str(item).lower() for item in categories + tags}
    text = f"{question} {description}".lower()

    if labels & {
        "sports",
        "football",
        "soccer",
        "nba",
        "nfl",
        "mlb",
        "nhl",
        "tennis",
        "esports",
    }:
        return "sports"

    if labels & {"weather", "climate"} or _contains_any_keyword(text, _WEATHER_KEYWORDS):
        return "weather"

    if labels & {"commodities", "commodity", "oil & gas", "agriculture"} or _contains_any_keyword(text, _COMMODITY_KEYWORDS):
        return "commodities"

    # Limitless has many crypto/equity/commodity Up/Down markets. Those are
    # deliberately not routed into the economics engine unless the rule text
    # itself is macroeconomic.
    if (
        labels & {"economy", "economics"}
        or "inflation" in text
        or "consumer price index" in text
        or "producer price index" in text
        or "gross domestic product" in text
        or _contains_any_keyword(text, _ECON_KEYWORDS)
    ):
        return "economics"

    # Avoid treating price-oracle events as macro markets just because they
    # mention oil, gold, equities, or crypto. A future price-source engine can
    # opt these in explicitly.
    if labels & {
        "crypto",
        "bitcoin",
        "ethereum",
        "daily",
        "hourly",
        "minutely",
        "5 min",
        "15 min",
        "indexes",
        "weekly",
    }:
        return "other"

    return _classify_by_keywords(question)


def _classify_by_keywords(question: str) -> str:
    q = question.lower()
    if _contains_any_keyword(q, _WEATHER_KEYWORDS):
        return "weather"
    if _contains_any_keyword(q, _ECON_KEYWORDS):
        return "economics"
    if _contains_any_keyword(q, _SPORTS_KEYWORDS):
        return "sports"
    if _contains_any_keyword(q, _COMMODITY_KEYWORDS):
        return "commodities"
    return "other"


def _contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    for keyword in keywords:
        kw = keyword.strip().lower()
        if " " in kw or not kw.isalnum():
            if kw in text:
                return True
        elif re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", text):
            return True
    return False
