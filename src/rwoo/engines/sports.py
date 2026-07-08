"""Phase 4 sports engine.

The first supported sports market is a FIFA World Cup outright market such as
"Will Spain win the 2026 FIFA World Cup?". It blends live World Football Elo
Ratings with the official FIFA/Coca-Cola Men's World Ranking and converts those
source families to transparent tournament-winning baselines.

This is still deliberately conservative: it does not yet condition on the final
draw, player injuries, or lineup news. The goal is an honest end-to-end sports
path with more than one independent ranking source plus restraint.
"""
from __future__ import annotations

import math
import random
import re
import statistics
import time
from datetime import datetime, timezone
from unicodedata import combining, normalize

import httpx

ELO_BASE = "https://www.eloratings.net"
WORLD_TSV_URL = f"{ELO_BASE}/World.tsv"
TEAM_NAMES_URL = f"{ELO_BASE}/en.teams.tsv"
FIFA_RANKINGS_URL = "https://api.fifa.com/api/v3/rankings"
USER_AGENT = "Mozilla/5.0 rwoo-verifier/1.0"
_TEAM_NAMES_CACHE: dict[str, str] | None = None
_WORLD_ELO_CACHE: list[dict] | None = None
_FIFA_RANKINGS_CACHE: list[dict] | None = None


def _get_with_retry(
    url: str,
    params: dict | None = None,
    timeout: float = 25,
    attempts: int = 3,
) -> httpx.Response:
    last_exc = None
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(1, attempts + 1):
        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts:
                time.sleep(1.5 * attempt)
    raise last_exc


def _normal_name(name: str) -> str:
    decomposed = normalize("NFKD", name)
    ascii_name = "".join(ch for ch in decomposed if not combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", ascii_name.lower()).strip()


def _localized_description(values: list[dict] | None) -> str:
    if not values:
        return ""
    for item in values:
        if item.get("Locale", "").lower().startswith("en") and item.get("Description"):
            return item["Description"]
    return values[0].get("Description", "")


def fetch_team_names() -> dict[str, str]:
    global _TEAM_NAMES_CACHE
    if _TEAM_NAMES_CACHE is not None:
        return dict(_TEAM_NAMES_CACHE)
    text = _get_with_retry(TEAM_NAMES_URL).text
    names: dict[str, str] = {}
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) >= 2:
            names[fields[0]] = fields[1]
    _TEAM_NAMES_CACHE = dict(names)
    return names


def fetch_world_elo_ratings() -> list[dict]:
    global _WORLD_ELO_CACHE
    if _WORLD_ELO_CACHE is not None:
        return [dict(row) for row in _WORLD_ELO_CACHE]
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
    _WORLD_ELO_CACHE = [dict(row) for row in ratings]
    return ratings


def fetch_fifa_rankings(count: int = 211) -> list[dict]:
    global _FIFA_RANKINGS_CACHE
    if _FIFA_RANKINGS_CACHE is not None:
        return [dict(row) for row in _FIFA_RANKINGS_CACHE]
    data = _get_with_retry(
        FIFA_RANKINGS_URL,
        params={"gender": 1, "count": count, "language": "en"},
    ).json()
    rankings = []
    for row in data.get("Results", []):
        team = _localized_description(row.get("TeamName"))
        points_raw = row.get("DecimalTotalPoints") or row.get("TotalPoints")
        if not team or points_raw is None:
            continue
        rankings.append(
            {
                "rank": int(row["Rank"]),
                "code": row.get("IdCountry"),
                "team": team,
                "rating": float(points_raw),
                "pub_date": row.get("PubDate"),
            }
        )
    if len(rankings) < 20:
        raise RuntimeError(f"FIFA rankings returned only {len(rankings)} teams")
    rankings = sorted(rankings, key=lambda r: r["rank"])
    _FIFA_RANKINGS_CACHE = [dict(row) for row in rankings]
    return rankings


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


def _match_win_probability(team_a: dict, team_b: dict) -> float:
    return 1.0 / (1.0 + 10 ** (-(team_a["rating"] - team_b["rating"]) / 400.0))


def _play_match(team_a: dict, team_b: dict, rng: random.Random) -> dict:
    return team_a if rng.random() < _match_win_probability(team_a, team_b) else team_b


def _simulate_group(group: list[dict], rng: random.Random) -> list[dict]:
    points = {team["key"]: 0 for team in group}
    strength_tiebreak = {team["key"]: team["rating"] for team in group}
    for i, team_a in enumerate(group):
        for team_b in group[i + 1:]:
            winner = _play_match(team_a, team_b, rng)
            points[winner["key"]] += 3
    return sorted(group, key=lambda team: (points[team["key"]], strength_tiebreak[team["key"]]), reverse=True)


def _simulate_world_cup_once(field: list[dict], rng: random.Random) -> str:
    groups = [field[i:i + 4] for i in range(0, 48, 4)]
    top_two = []
    thirds = []
    for group in groups:
        ranked = _simulate_group(group, rng)
        top_two.extend(ranked[:2])
        thirds.append(ranked[2])
    qualifiers = top_two + sorted(thirds, key=lambda team: team["rating"], reverse=True)[:8]
    bracket = sorted(qualifiers, key=lambda team: team["rating"], reverse=True)
    while len(bracket) > 1:
        next_round = []
        for i in range(0, len(bracket), 2):
            next_round.append(_play_match(bracket[i], bracket[-(i + 1)], rng))
        bracket = next_round
    return bracket[0]["key"]


def _tournament_simulator_probability(target: dict, ratings: list[dict], simulations: int = 4000) -> float:
    """Deterministic Monte Carlo approximation for a 48-team World Cup.

    The 2026 final field and draw are not fully known at model runtime, so this
    simulates a transparent top-48 ranking field. If the requested team is outside
    the top 48, it replaces the weakest seed so the probability remains defined
    and openly conservative.
    """
    field = [_sim_team(r) for r in ratings[:48]]
    target_key = _normal_name(target["team"])
    if all(r["key"] != target_key for r in field):
        field[-1] = _sim_team(target)
    rng = random.Random(20260708)
    wins = 0
    for _ in range(simulations):
        if _simulate_world_cup_once(field, rng) == target_key:
            wins += 1
    return wins / simulations


def _sim_team(row: dict) -> dict:
    out = dict(row)
    out["key"] = _normal_name(row["team"])
    return out


def _find_target(country: str, ratings: list[dict], code: str | None = None) -> dict | None:
    wanted = _normal_name(country)
    aliases = {
        "usa": "united states",
        "united states of america": "united states",
        "england": "england",
    }
    wanted = aliases.get(wanted, wanted)
    for row in ratings:
        row_name = aliases.get(_normal_name(row["team"]), _normal_name(row["team"]))
        if row_name == wanted:
            return row
    if code:
        return next((row for row in ratings if row.get("code") == code), None)
    return None


def compute_world_cup_probability(question: str) -> dict:
    country = parse_world_cup_country(question)
    ratings = fetch_world_elo_ratings()
    fifa_rankings = fetch_fifa_rankings()
    target = _find_target(country, ratings)
    fifa_target = _find_target(country, fifa_rankings, code=target.get("code") if target else None)
    if not target or not fifa_target:
        return {
            "oracle_prob": None,
            "confidence": 0.0,
            "prob_low": None,
            "prob_high": None,
            "per_source_values": {
                "country": country,
                "elo_ratings_count": len(ratings),
                "fifa_rankings_count": len(fifa_rankings),
                "matched_elo": bool(target),
                "matched_fifa": bool(fifa_target),
            },
            "method": "unsupported_country_or_market",
            "data_freshness": datetime.now(timezone.utc).isoformat(),
            "base_rate": None,
            "refused": True,
            "reason": f"could not match {country!r} to both Elo and FIFA team names",
        }

    # Restrict closed-form baselines to the top 64 teams because the 2026
    # tournament field is 48 teams and many long-tail Elo teams are not
    # realistic entrants. The simulator itself uses a 48-team field.
    field = ratings[:64]
    softmax_prob = _softmax_probability(target, field, scale=115.0)
    rank_decay_prob = _rank_decay_probability(target, field)
    simulator_prob = _tournament_simulator_probability(target, ratings)
    fifa_field = fifa_rankings[:64]
    fifa_softmax_prob = _softmax_probability(fifa_target, fifa_field, scale=70.0)
    fifa_rank_decay_prob = _rank_decay_probability(fifa_target, fifa_field)
    fifa_simulator_prob = _tournament_simulator_probability(fifa_target, fifa_rankings)
    model_probs = {
        "elo_rating_softmax_top64": softmax_prob,
        "elo_rank_decay_top64": rank_decay_prob,
        "elo_48_team_tournament_simulator": simulator_prob,
        "fifa_points_softmax_top64": fifa_softmax_prob,
        "fifa_rank_decay_top64": fifa_rank_decay_prob,
        "fifa_48_team_tournament_simulator": fifa_simulator_prob,
    }
    oracle_prob = statistics.fmean(model_probs.values())
    prob_low = min(model_probs.values())
    prob_high = max(model_probs.values())
    raw_agreement = 1.0 - (prob_high - prob_low)
    confidence = min(0.78, max(0.0, raw_agreement))

    return {
        "oracle_prob": oracle_prob,
        "confidence": confidence,
        "prob_low": prob_low,
        "prob_high": prob_high,
        "per_model_prob": model_probs,
        "per_source_values": {
            "sources": [
                "World Football Elo Ratings",
                "FIFA/Coca-Cola Men's World Ranking",
            ],
            "country": country,
            "elo": {
                "source": "World Football Elo Ratings",
                "target_rank": target["rank"],
                "target_rating": target["rating"],
                "ratings_count": len(ratings),
                "top_8": [(r["rank"], r["team"], r["rating"]) for r in ratings[:8]],
            },
            "fifa": {
                "source": "FIFA/Coca-Cola Men's World Ranking",
                "publication_date": fifa_target.get("pub_date"),
                "target_rank": fifa_target["rank"],
                "target_points": fifa_target["rating"],
                "rankings_count": len(fifa_rankings),
                "top_8": [(r["rank"], r["team"], r["rating"]) for r in fifa_rankings[:8]],
            },
            "tournament_state": {
                "conditioned_on_actual_draw": False,
                "draw_state_source": "not integrated; 2026 final draw/state feed is still absent from this engine",
                "injury_lineup_source": "not integrated; no official team injury/lineup feed is wired",
            },
        },
        "method": (
            "World Football Elo plus official FIFA/Coca-Cola rankings -> top-64 rating/rank baselines "
            "and deterministic 48-team tournament simulators; confidence capped because draw state, "
            "injuries, lineups, and independent bookmaker/projection ensembles are not yet integrated"
        ),
        "data_freshness": datetime.now(timezone.utc).isoformat(),
        "base_rate": softmax_prob,
        "refused": False,
    }
