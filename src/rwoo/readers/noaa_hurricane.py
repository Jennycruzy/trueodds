"""Official NOAA Atlantic seasonal-outlook reader."""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone

import httpx

OUTLOOK_URL = "https://www.cpc.ncep.noaa.gov/products/outlooks/hurricane.shtml"
SEASON_URL = "https://www.nhc.noaa.gov/data/tcr/index.php"
USER_AGENT = "TrueOdd/1.0 (+https://trueodd.xyz/methodology)"


def _plain(page: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page))).strip()


def parse_atlantic_outlook(page: str) -> dict:
    text = _plain(page)
    year_match = re.search(r"(20\d{2}) North Atlantic Hurricane Season Outlook", text, re.I)
    if not year_match:
        raise ValueError("NOAA Atlantic outlook year was not found")
    ranges = {}
    patterns = {
        "named_storms": r"(\d+)\s*[-–]\s*(\d+)\s+Named Storms",
        "hurricanes": r"(\d+)\s*[-–]\s*(\d+)\s+Hurricanes",
        "major_hurricanes": r"(\d+)\s*[-–]\s*(\d+)\s+Major Hurricanes",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.I)
        if not match:
            raise ValueError(f"NOAA Atlantic outlook {key} range was not found")
        ranges[key] = [int(match.group(1)), int(match.group(2))]
    coverage = re.search(r"(\d+)% probability for each", text, re.I)
    issued = re.search(r"Issued:\s*(\d{1,2}\s+[A-Za-z]+\s+20\d{2})", text, re.I)
    issued_text = issued.group(1) if issued else None
    issued_month = None
    if issued_text:
        try:
            issued_month = datetime.strptime(issued_text, "%d %B %Y").month
        except ValueError:
            pass
    return {
        "year": int(year_match.group(1)),
        "ranges": ranges,
        "range_probability": (int(coverage.group(1)) / 100) if coverage else 0.70,
        "issued": issued_text,
        # NOAA's May outlook precedes the season; its early-August update is a
        # forecast of the seasonal total with activity-to-date incorporated.
        "includes_season_to_date": bool(issued_month and issued_month >= 7),
        "source_url": OUTLOOK_URL,
    }


def parse_current_counts(page: str) -> dict:
    # Bind to the NHC summary table by its three headers, then read the first
    # three data cells.  Comparisons with normal are nested inside each cell,
    # so parsing the flattened page can accidentally bind those values.
    summary = re.search(r"North\s+Atlantic\s+Summary\s+as\s+of", page, re.I)
    table_html = ""
    if summary:
        start = page.rfind("<table", 0, summary.start())
        end = page.find("</table>", summary.end())
        if start >= 0 and end >= 0:
            table_html = page[start:end + len("</table>")]
    headers_present = all(
        re.search(pattern, table_html, re.I | re.S)
        for pattern in (r"Named\s+Storms", r">\s*Hurricanes\s*<", r"Major\s+Hurricanes")
    )
    body = re.search(r"<tbody\b[^>]*>(.*?)</tbody>", table_html, re.I | re.S) if headers_present else None
    row = re.search(r"<tr\b[^>]*>(.*?)</tr>", body.group(1), re.I | re.S) if body else None
    cells = re.findall(r"<td\b[^>]*>\s*(\d+)", row.group(1), re.I | re.S) if row else []
    if len(cells) < 3:
        return {"named_storms": 0, "hurricanes": 0, "major_hurricanes": 0, "parsed": False}
    return {
        "named_storms": int(cells[0]), "hurricanes": int(cells[1]),
        "major_hurricanes": int(cells[2]), "parsed": True,
    }


def fetch_atlantic_outlook(client: httpx.Client | None = None) -> dict:
    own = client is None
    client = client or httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT})
    try:
        response = client.get(OUTLOOK_URL)
        response.raise_for_status()
        outlook = parse_atlantic_outlook(response.text)
        season = client.get(SEASON_URL, params={"season": outlook["year"]})
        if season.is_success:
            outlook["observed"] = parse_current_counts(season.text)
        else:
            outlook["observed"] = {"named_storms": 0, "hurricanes": 0, "major_hurricanes": 0, "parsed": False}
        outlook["fetched_at"] = datetime.now(timezone.utc).isoformat()
        return outlook
    finally:
        if own:
            client.close()
