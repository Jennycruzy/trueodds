"""Phase 4 sports engine.

The first supported sports market is a FIFA World Cup outright market such as
"Will Spain win the 2026 FIFA World Cup?". It uses the live World Football Elo
Ratings TSV files as a deterministic public rating source and converts ratings
to two transparent tournament-winning baselines.

This is deliberately conservative: both baselines come from one rating source,
so confidence is capped. The goal in Phase 4 is an honest end-to-end sports
path plus restraint, not a production World Cup simulator.
"""
from __future__ import annotations

import math
import re
import statistics
import time
from datetime import datetime, timezone

import httpx

ELO_BASE = "https://www.eloratings.net"
WORLD_TSV_URL = f"{ELO_BASE}/World.tsv"
TEAM_NAMES_URL = f"{ELO_BASE}/en.teams.tsv"


def _get_with_retry(url: str, timeout: float = 25, attempts: int = 3) -> httpx.Response:
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            resp = httpx.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts:
                time.sleep(1.5 * attempt)
    raise last_exc


def fetch_team_names() -> dict[str, str]:
    text = _get_with_retry(TEAM_NAMES_URL).text
    names: dict[str, str] = {}
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) >= 2:
            names[fields[0]] = fields[1]
    return names


def fetch_world_elo_ratings() -> list[dict]:
    names = fetch_team_names()
    text = _get_with_retry(WORLD_TSV_URL).text
    ratings = []
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) < 4:
            continue
        code = fields[2]
        ratings.append(
            {
                "rank": int(fields[1]),
                "code": code,
                "team": names.get(code, code),
                "rating": int(fields[3]),
            }
        )
    if len(ratings) < 20:
        raise RuntimeError(f"World Football Elo returned only {len(ratings)} ratings")
    return ratings


def parse_world_cup_country(question: str) -> str:
    match = re.search(r"Will (.+?) win the 2026 FIFA World Cup\\?", question)
    if not match:
        raise ValueError(f"Unsupported sports question shape: {question!r}")
    return match.group(1).strip()


def _softmax_probability(target: dict, ratings: list[dict], scale: float) -> float:
    top = max(r["rating"] for r in ratings)
    weights = [math.exp((r["rating"] - top) / scale) for r in ratings]
    target_weight = math.exp((target["rating"] - top) / scale)
    return target_weight / sum(weights)


def _rank_decay_probability(target: dict, ratings: list[dict], decay: float = 0.88) -> float:
    weights = [decay ** (r["rank"] - 1) for r in ratings]
    return (decay ** (target["rank"] - 1)) / sum(weights)


def compute_world_cup_probability(question: str) -> dict:
    country = parse_world_cup_country(question)
    ratings = fetch_world_elo_ratings()
    target = next((r for r in ratings if r["team"].lower() == country.lower()), None)
    if not target:
        return {
            "oracle_prob": None,
            "confidence": 0.0,
            "prob_low": None,
            "prob_high": None,
            "per_source_values": {"country": country, "ratings_count": len(ratings)},
            "method": "unsupported_country_or_market",
            "data_freshness": datetime.now(timezone.utc).isoformat(),
            "base_rate": None,
            "refused": True,
            "reason": f"could not match {country!r} to a World Football Elo team name",
        }

    # Restrict to the top 64 teams because the 2026 tournament field is 48
    # teams and many long-tail Elo teams are not realistic entrants. The
    # method string states this modeling simplification openly.
    field = ratings[:64]
    softmax_prob = _softmax_probability(target, field, scale=115.0)
    rank_decay_prob = _rank_decay_probability(target, field)
    model_probs = {
        "elo_rating_softmax_top64": softmax_prob,
        "elo_rank_decay_top64": rank_decay_prob,
    }
    oracle_prob = statistics.fmean(model_probs.values())
    prob_low = min(model_probs.values())
    prob_high = max(model_probs.values())
    raw_agreement = 1.0 - (prob_high - prob_low)
    confidence = min(0.45, max(0.0, raw_agreement))

    return {
        "oracle_prob": oracle_prob,
        "confidence": confidence,
        "prob_low": prob_low,
        "prob_high": prob_high,
        "per_model_prob": model_probs,
        "per_source_values": {
            "source": "World Football Elo Ratings",
            "country": country,
            "target_rank": target["rank"],
            "target_rating": target["rating"],
            "ratings_count": len(ratings),
            "top_8": [(r["rank"], r["team"], r["rating"]) for r in ratings[:8]],
        },
        "method": (
            "World Football Elo current ratings -> top-64 field -> rating softmax and rank-decay "
            "outright baselines; confidence capped because this is one public rating source, not a full simulator"
        ),
        "data_freshness": datetime.now(timezone.utc).isoformat(),
        "base_rate": softmax_prob,
        "refused": False,
    }
