"""Current-season MLB team Elo replay from the official StatsAPI."""
from datetime import date
import httpx

URL = "https://statsapi.mlb.com/api/v1/schedule"
_CACHE = None


def fetch_team_elo(season: int | None = None) -> dict:
    global _CACHE
    season = season or date.today().year
    if _CACHE and _CACHE["season"] == season:
        return _CACHE
    response = httpx.get(URL, params={"sportId": 1, "season": season, "gameType": "R", "hydrate": "team"}, timeout=45)
    response.raise_for_status()
    data = response.json()
    ratings, games = {}, 0
    for day in data.get("dates", []):
        for game in day.get("games", []):
            if game.get("status", {}).get("abstractGameState") != "Final":
                continue
            home, away = game["teams"]["home"], game["teams"]["away"]
            hn, an = home["team"]["name"], away["team"]["name"]
            ratings.setdefault(hn, 1500.0); ratings.setdefault(an, 1500.0)
            expected = 1 / (1 + 10 ** (-(ratings[hn] + 24 - ratings[an]) / 400))
            actual = 1.0 if home.get("isWinner") else 0.0
            delta = 20 * (actual - expected)
            ratings[hn] += delta; ratings[an] -= delta; games += 1
    if len(ratings) < 25 or games < 100:
        raise RuntimeError(f"MLB StatsAPI returned only {len(ratings)} teams/{games} completed games")
    _CACHE = {"season": season, "games": games, "teams": [{"name": n, "rating": r} for n, r in ratings.items()]}
    return _CACHE
