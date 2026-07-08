"""Official economics forecast/source readers.

The live economics engine uses Cleveland Fed nowcasts for current CPI/core CPI
month-over-month forecasts, while the calibration layer uses Philadelphia Fed
SPF probability distributions for historical, dated professional forecast
probabilities. Both readers are deterministic parsers over official public
sources; neither invents a probability.
"""
from __future__ import annotations

import html
import io
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime

import httpx

CLEVELAND_NOWCAST_URL = "https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting"
SPF_PROBABILITY_URL = (
    "https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/"
    "survey-of-professional-forecasters/historical-data/prob.xlsx?sc_lang=en"
    "&hash=2FCC8CA15B8202406A2204EC1777EFAF"
)
SPF_RELEASE_DATES_URL = (
    "https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/"
    "survey-of-professional-forecasters/spf-release-dates.txt?sc_lang=en"
)

USER_AGENT = "Mozilla/5.0 (compatible; rwoo-verifier/1.0)"
_XLSX_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


@dataclass(frozen=True)
class ClevelandNowcast:
    year: int
    month: int
    cpi_mom: float
    core_cpi_mom: float
    pce_mom: float
    core_pce_mom: float
    updated: str


@dataclass(frozen=True)
class SpfProbabilityRow:
    survey_year: int
    survey_quarter: int
    target_year: int
    horizon: str
    probabilities: list[float]
    source_available_at: str


def _get_with_retry(url: str, timeout: float = 30, attempts: int = 3) -> httpx.Response:
    last_exc = None
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(1, attempts + 1):
        try:
            resp = httpx.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts:
                time.sleep(1.5 * attempt)
    raise last_exc


def fetch_cleveland_nowcasts() -> list[ClevelandNowcast]:
    """Parse the official Cleveland Fed daily nowcasting page.

    Returns the month-over-month table. The page also contains y/y and quarterly
    tables; this reader deliberately extracts only the monthly rows needed for
    Kalshi core-CPI MoM markets.
    """
    text = _get_with_retry(CLEVELAND_NOWCAST_URL).text
    plain = html.unescape(re.sub(r"<[^>]+>", " ", text))
    plain = re.sub(r"\s+", " ", plain)
    start = plain.find("Inflation, month-over-month percent change")
    end = plain.find("Inflation, year-over-year percent change")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError("could not find Cleveland Fed month-over-month nowcast table")
    table = plain[start:end]

    rows: list[ClevelandNowcast] = []
    pattern = re.compile(
        r"\b("
        + "|".join(m.title() for m in _MONTHS)
        + r")\s+(\d{4})\s*([-+]?\d+\.\d+)\s+([-+]?\d+\.\d+)\s+"
        r"([-+]?\d+\.\d+)\s+([-+]?\d+\.\d+)\s+(\d{2}/\d{2})"
    )
    for match in pattern.finditer(table):
        month_name, year, cpi, core_cpi, pce, core_pce, updated = match.groups()
        rows.append(
            ClevelandNowcast(
                year=int(year),
                month=_MONTHS[month_name.lower()],
                cpi_mom=float(cpi),
                core_cpi_mom=float(core_cpi),
                pce_mom=float(pce),
                core_pce_mom=float(core_pce),
                updated=updated,
            )
        )
    if not rows:
        raise RuntimeError("Cleveland Fed nowcast table parsed but no monthly rows were found")
    return rows


# Philadelphia Fed SPF PRCCPI bins, Table 8 in SPF documentation:
# fourth-quarter over fourth-quarter core CPI inflation, current year bins
# 1..10 and next year bins 11..20.
SPF_PRCCPI_BINS: list[tuple[float | None, float | None, str]] = [
    (4.0, None, "4.0 or more"),
    (3.5, 3.9, "3.5 to 3.9"),
    (3.0, 3.4, "3.0 to 3.4"),
    (2.5, 2.9, "2.5 to 2.9"),
    (2.0, 2.4, "2.0 to 2.4"),
    (1.5, 1.9, "1.5 to 1.9"),
    (1.0, 1.4, "1.0 to 1.4"),
    (0.5, 0.9, "0.5 to 0.9"),
    (0.0, 0.4, "0.0 to 0.4"),
    (None, 0.0, "will decline"),
]


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    out = []
    for item in root.findall("a:si", _XLSX_NS):
        parts = [node.text or "" for node in item.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")]
        out.append("".join(parts))
    return out


def _cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    value = cell.find("a:v", _XLSX_NS)
    if value is None:
        return ""
    text = value.text or ""
    if cell.attrib.get("t") == "s":
        return shared_strings[int(text)]
    return text


def _xlsx_sheet_rows(content: bytes, sheet_path: str) -> list[list[str]]:
    zf = zipfile.ZipFile(io.BytesIO(content))
    shared_strings = _shared_strings(zf)
    sheet = ET.fromstring(zf.read(sheet_path))
    rows = []
    for row in sheet.findall(".//a:row", _XLSX_NS):
        values = [_cell_text(cell, shared_strings) for cell in row.findall("a:c", _XLSX_NS)]
        rows.append(values)
    return rows


def parse_spf_release_dates(text: str) -> dict[tuple[int, int], date]:
    release_dates: dict[tuple[int, int], date] = {}
    current_year: int | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or not re.match(r"^(\d{4}\s+)?Q[1-4]\b", line):
            continue
        match = re.match(r"^(?:(\d{4})\s+)?Q([1-4])\s+\S+\*?\s+(\d{1,2}/\d{1,2}/\d{2})\*?", line)
        if not match:
            continue
        year_text, quarter_text, release_text = match.groups()
        if year_text:
            current_year = int(year_text)
        if current_year is None:
            continue
        month, day, yy = [int(part) for part in release_text.split("/")]
        year = 1900 + yy if yy >= 68 else 2000 + yy
        release_dates[(current_year, int(quarter_text))] = date(year, month, day)
    return release_dates


def fetch_spf_release_dates() -> dict[tuple[int, int], date]:
    return parse_spf_release_dates(_get_with_retry(SPF_RELEASE_DATES_URL).text)


def fetch_spf_prccpi_rows() -> list[SpfProbabilityRow]:
    """Official Philadelphia Fed SPF PRCCPI probability rows.

    Each workbook row contains 10 current-year and 10 next-year probabilities.
    Values are percentages in the workbook; this function returns probabilities
    in [0, 1].
    """
    workbook = _get_with_retry(SPF_PROBABILITY_URL, timeout=45).content
    release_dates = fetch_spf_release_dates()
    rows = _xlsx_sheet_rows(workbook, "xl/worksheets/sheet4.xml")
    out: list[SpfProbabilityRow] = []
    for raw in rows[1:]:
        if len(raw) < 22:
            continue
        try:
            survey_year, survey_quarter = int(float(raw[0])), int(float(raw[1]))
        except ValueError:
            continue
        release = release_dates.get((survey_year, survey_quarter))
        if release is None:
            continue
        for offset, horizon in ((2, "current_year"), (12, "next_year")):
            values = raw[offset:offset + 10]
            if any(v in {"", "#N/A"} for v in values):
                continue
            try:
                probabilities = [float(v) / 100.0 for v in values]
            except ValueError:
                continue
            if sum(probabilities) <= 0:
                continue
            target_year = survey_year if horizon == "current_year" else survey_year + 1
            out.append(
                SpfProbabilityRow(
                    survey_year=survey_year,
                    survey_quarter=survey_quarter,
                    target_year=target_year,
                    horizon=horizon,
                    probabilities=probabilities,
                    source_available_at=release.isoformat(),
                )
            )
    return out


def spf_bin_contains(bin_index: int, annual_core_cpi_q4q4: float) -> bool:
    low, high, _label = SPF_PRCCPI_BINS[bin_index]
    if low is None:
        return annual_core_cpi_q4q4 < high
    if high is None:
        return annual_core_cpi_q4q4 >= low
    return low <= annual_core_cpi_q4q4 <= high


def annual_core_bin_to_monthly_midpoint(bin_index: int) -> float:
    low, high, _label = SPF_PRCCPI_BINS[bin_index]
    if low is None:
        annual = -0.25
    elif high is None:
        annual = low + 0.25
    else:
        annual = (low + high) / 2
    return (((1 + annual / 100.0) ** (1 / 12)) - 1) * 100


def event_probability_from_spf_monthly_equivalent(
    probabilities: list[float], strike_type: str, floor_strike, cap_strike
) -> float:
    """Approximate a monthly core-CPI event from SPF annual Q4/Q4 density.

    The approximation is disclosed in engine output. Cleveland Fed monthly
    nowcasts, when available, carry the direct month-specific signal; SPF adds
    an independent professional-forecast regime prior.
    """
    hits = 0.0
    for idx, probability in enumerate(probabilities):
        monthly = annual_core_bin_to_monthly_midpoint(idx)
        if strike_type == "greater" and monthly > float(floor_strike):
            hits += probability
        elif strike_type == "less" and monthly < float(cap_strike):
            hits += probability
        elif strike_type == "between" and float(floor_strike) <= monthly <= float(cap_strike):
            hits += probability
    total = sum(probabilities)
    return hits / total if total else 0.0


def latest_spf_row_for_target(target_year: int) -> SpfProbabilityRow | None:
    rows = [row for row in fetch_spf_prccpi_rows() if row.target_year == target_year]
    return max(rows, key=lambda row: (row.survey_year, row.survey_quarter), default=None)
