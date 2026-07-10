"""Resilient dated ClubElo reader with auditable stale-snapshot fallback."""
import csv
import json
import time
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
import httpx

_CACHE = {}
_CIRCUIT_OPEN_UNTIL = 0.0
SNAPSHOT_DIR = Path(".cache/rwoo/clubelo")


def _parse(text: str, snapshot_date: date) -> list[dict]:
    rows = []
    age = max(0, (date.today() - snapshot_date).days)
    for row in csv.DictReader(StringIO(text)):
        try:
            rows.append({"name": row["Club"], "country": row.get("Country"), "rating": float(row["Elo"]),
                         "snapshot_date": snapshot_date.isoformat(), "source_age_days": age})
        except (KeyError, TypeError, ValueError):
            continue
    if len(rows) < 100:
        raise RuntimeError(f"ClubElo returned only {len(rows)} usable clubs")
    return rows


def _snapshot_path(day: date) -> Path:
    return SNAPSHOT_DIR / f"{day.isoformat()}.json"


def _store(day: date, rows: list[dict]) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    _snapshot_path(day).write_text(json.dumps({"snapshot_date": day.isoformat(), "rows": rows}, sort_keys=True), encoding="utf-8")


def _latest_snapshot(max_age_days: int) -> list[dict] | None:
    for path in sorted(SNAPSHOT_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8")); day = date.fromisoformat(data["snapshot_date"])
            if (date.today() - day).days <= max_age_days:
                return [{**row, "source_age_days": (date.today() - day).days} for row in data["rows"]]
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    return None


def fetch_club_elo(as_of: date | None = None, fallback_days: int = 3, max_stale_days: int = 14) -> list[dict]:
    global _CIRCUIT_OPEN_UNTIL
    requested = as_of or date.today(); key = requested.isoformat()
    if key in _CACHE:
        return [dict(x) for x in _CACHE[key]]
    if time.monotonic() < _CIRCUIT_OPEN_UNTIL:
        cached = _latest_snapshot(max_stale_days)
        if cached is not None:
            return cached
        raise RuntimeError("ClubElo circuit is open and no acceptable snapshot exists")
    errors = []
    for offset in range(fallback_days + 1):
        day = requested - timedelta(days=offset)
        for scheme in ("https", "http"):
            try:
                response = httpx.get(f"{scheme}://api.clubelo.com/{day.isoformat()}", timeout=3, follow_redirects=True)
                response.raise_for_status(); rows = _parse(response.text, day); _store(day, rows)
                _CACHE[key] = rows; return [dict(x) for x in rows]
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{scheme}/{day}: {exc}")
    _CIRCUIT_OPEN_UNTIL = time.monotonic() + 300
    cached = _latest_snapshot(max_stale_days)
    if cached is not None:
        return cached
    raise RuntimeError("ClubElo unavailable after bounded protocol/date fallback: " + "; ".join(errors[-3:]))
