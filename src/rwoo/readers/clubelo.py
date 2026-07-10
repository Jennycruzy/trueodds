"""Club soccer ratings from ClubElo's public dated CSV endpoint."""
import csv
from datetime import date
from io import StringIO
import httpx

_CACHE = {}


def fetch_club_elo(as_of: date | None = None) -> list[dict]:
    as_of = as_of or date.today()
    key = as_of.isoformat()
    if key in _CACHE:
        return [dict(x) for x in _CACHE[key]]
    response = httpx.get(f"http://api.clubelo.com/{key}", timeout=30, follow_redirects=True)
    response.raise_for_status()
    rows = []
    for row in csv.DictReader(StringIO(response.text)):
        try:
            rows.append({"name": row["Club"], "country": row.get("Country"), "rating": float(row["Elo"])})
        except (KeyError, TypeError, ValueError):
            continue
    if len(rows) < 100:
        raise RuntimeError(f"ClubElo returned only {len(rows)} usable clubs")
    _CACHE[key] = rows
    return [dict(x) for x in rows]
