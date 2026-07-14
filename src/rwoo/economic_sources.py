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
import math
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import wraps

import httpx

_SOURCE_CACHE: ContextVar[dict | None] = ContextVar("rwoo_source_cache", default=None)


@contextmanager
def source_cache_scope():
    """Reuse immutable source snapshots only inside one coherent scan."""
    token = _SOURCE_CACHE.set({})
    try:
        yield
    finally:
        _SOURCE_CACHE.reset(token)


def scan_cached(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        cache = _SOURCE_CACHE.get()
        if cache is None:
            return func(*args, **kwargs)
        key = (func.__name__, args, tuple(sorted(kwargs.items())))
        if key not in cache:
            cache[key] = func(*args, **kwargs)
        return cache[key]
    return wrapper

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
FRED_FED_TARGET_UPPER_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU"
FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
GDPNOW_WORKBOOK_URL = (
    "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/cqer/"
    "researchcq/gdpnow/GDPTrackingModelDataAndForecasts.xlsx"
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


@scan_cached
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


@scan_cached
def fetch_spf_release_dates() -> dict[tuple[int, int], date]:
    return parse_spf_release_dates(_get_with_retry(SPF_RELEASE_DATES_URL).text)


@scan_cached
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


# --------------------------------------------------------------------------
# Cleveland Fed year-over-year nowcasts (headline/core CPI annual markets).
# Table location and column order verified live 2026-07-09 on the official
# inflation-nowcasting page (same page the MoM reader already parses).
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ClevelandYoyNowcast:
    year: int
    month: int
    cpi_yoy: float
    core_cpi_yoy: float
    pce_yoy: float
    core_pce_yoy: float
    updated: str


@scan_cached
def fetch_cleveland_yoy_nowcasts() -> list[ClevelandYoyNowcast]:
    text = _get_with_retry(CLEVELAND_NOWCAST_URL).text
    plain = html.unescape(re.sub(r"<[^>]+>", " ", text))
    plain = re.sub(r"\s+", " ", plain)
    start = plain.find("Inflation, year-over-year percent change")
    if start == -1:
        raise RuntimeError("could not find Cleveland Fed year-over-year nowcast table")
    end = plain.find("Note:", start)
    table = plain[start:end] if end != -1 else plain[start:start + 2000]

    rows: list[ClevelandYoyNowcast] = []
    pattern = re.compile(
        r"\b("
        + "|".join(m.title() for m in _MONTHS)
        + r")\s+(\d{4})\s*([-+]?\d+\.\d+)\s+([-+]?\d+\.\d+)\s+"
        r"([-+]?\d+\.\d+)\s+([-+]?\d+\.\d+)\s+(\d{2}/\d{2})"
    )
    for match in pattern.finditer(table):
        month_name, year, cpi, core_cpi, pce, core_pce, updated = match.groups()
        rows.append(
            ClevelandYoyNowcast(
                year=int(year),
                month=_MONTHS[month_name.lower()],
                cpi_yoy=float(cpi),
                core_cpi_yoy=float(core_cpi),
                pce_yoy=float(pce),
                core_pce_yoy=float(core_pce),
                updated=updated,
            )
        )
    if not rows:
        raise RuntimeError("Cleveland Fed YoY nowcast table parsed but no monthly rows were found")
    return rows


# --------------------------------------------------------------------------
# SPF density variables beyond PRCCPI: PRGDP, PRUNEMP, RECESS.
#
# Bin ranges are quoted verbatim from the official SPF documentation PDF
# (Tables 7 and 9, "2024:Q2 to Present" columns), downloaded and read
# 2026-07-09. Rows from surveys before 2024:Q2 use DIFFERENT bins, so the
# readers below only return rows from the current bin era — using an old row
# against the new bins would silently answer the wrong question.
# --------------------------------------------------------------------------

SPF_CURRENT_BIN_ERA_START: tuple[int, int] = (2024, 2)

# Table 7, PRGDP, 2024:Q2 to present: annual-average over annual-average
# real GDP growth, 11 bins per target year, 4 target years.
SPF_PRGDP_BINS: list[tuple[float | None, float | None, str]] = [
    (9.0, None, "9.0+"),
    (7.0, 8.9, "7.0 to 8.9"),
    (5.5, 6.9, "5.5 to 6.9"),
    (4.0, 5.4, "4.0 to 5.4"),
    (2.5, 3.9, "2.5 to 3.9"),
    (1.5, 2.4, "1.5 to 2.4"),
    (0.0, 1.4, "0.0 to 1.4"),
    (-1.5, -0.1, "-1.5 to -0.1"),
    (-3.0, -1.6, "-3.0 to -1.6"),
    (-5.1, -3.1, "-5.1 to -3.1"),
    (None, -5.1, "<-5.1"),
]

# Table 9, PRUNEMP, 2024:Q2 to present: annual-average unemployment level,
# 10 bins per target year, 4 target years.
SPF_PRUNEMP_BINS: list[tuple[float | None, float | None, str]] = [
    (9.9, None, ">= 9.9"),
    (8.3, 9.8, "8.3 to 9.8"),
    (7.2, 8.2, "7.2 to 8.2"),
    (6.1, 7.1, "6.1 to 7.1"),
    (5.5, 6.0, "5.5 to 6.0"),
    (4.9, 5.4, "4.9 to 5.4"),
    (4.3, 4.8, "4.3 to 4.8"),
    (3.7, 4.2, "3.7 to 4.2"),
    (3.1, 3.6, "3.1 to 3.6"),
    (None, 3.1, "<3.1"),
]

_SPF_SHEETS = {
    "PRGDP": ("xl/worksheets/sheet1.xml", 11, 4),
    "PRUNEMP": ("xl/worksheets/sheet3.xml", 10, 4),
}

_SPF_WORKBOOK_CACHE: dict[str, bytes] = {}


def _spf_workbook() -> bytes:
    if "prob" not in _SPF_WORKBOOK_CACHE:
        _SPF_WORKBOOK_CACHE["prob"] = _get_with_retry(SPF_PROBABILITY_URL, timeout=45).content
    return _SPF_WORKBOOK_CACHE["prob"]


@scan_cached
def fetch_spf_density_rows(variable: str) -> list[SpfProbabilityRow]:
    """Density rows for PRGDP or PRUNEMP, current bin era only.

    horizon is 'year_1' (survey year) through 'year_4'.
    """
    sheet_path, bins_per_year, target_years = _SPF_SHEETS[variable]
    release_dates = fetch_spf_release_dates()
    rows = _xlsx_sheet_rows(_spf_workbook(), sheet_path)
    out: list[SpfProbabilityRow] = []
    for raw in rows[1:]:
        if len(raw) < 2 + bins_per_year:
            continue
        try:
            survey_year, survey_quarter = int(float(raw[0])), int(float(raw[1]))
        except ValueError:
            continue
        if (survey_year, survey_quarter) < SPF_CURRENT_BIN_ERA_START:
            continue
        release = release_dates.get((survey_year, survey_quarter))
        if release is None:
            continue
        for year_offset in range(target_years):
            offset = 2 + year_offset * bins_per_year
            values = raw[offset:offset + bins_per_year]
            if len(values) < bins_per_year or any(v in {"", "#N/A"} for v in values):
                continue
            try:
                probabilities = [float(v) / 100.0 for v in values]
            except ValueError:
                continue
            if sum(probabilities) <= 0:
                continue
            out.append(
                SpfProbabilityRow(
                    survey_year=survey_year,
                    survey_quarter=survey_quarter,
                    target_year=survey_year + year_offset,
                    horizon=f"year_{year_offset + 1}",
                    probabilities=probabilities,
                    source_available_at=release.isoformat(),
                )
            )
    return out


def latest_spf_density_for_target(variable: str, target_year: int) -> SpfProbabilityRow | None:
    rows = [row for row in fetch_spf_density_rows(variable) if row.target_year == target_year]
    return max(rows, key=lambda row: (row.survey_year, row.survey_quarter), default=None)


@dataclass(frozen=True)
class SpfRecessRow:
    survey_year: int
    survey_quarter: int
    probabilities: list[float]  # decline in real GDP: survey quarter, +1 .. +4
    source_available_at: str


@scan_cached
def fetch_spf_recess_rows() -> list[SpfRecessRow]:
    """The SPF 'anxious index': mean probability of a DECLINE in real GDP in
    the survey quarter and each of the next four quarters (RECESS1..RECESS5)."""
    release_dates = fetch_spf_release_dates()
    rows = _xlsx_sheet_rows(_spf_workbook(), "xl/worksheets/sheet6.xml")
    out: list[SpfRecessRow] = []
    for raw in rows[1:]:
        if len(raw) < 7:
            continue
        try:
            survey_year, survey_quarter = int(float(raw[0])), int(float(raw[1]))
        except ValueError:
            continue
        release = release_dates.get((survey_year, survey_quarter))
        if release is None:
            continue
        values = raw[2:7]
        if any(v in {"", "#N/A"} for v in values):
            continue
        try:
            probabilities = [float(v) / 100.0 for v in values]
        except ValueError:
            continue
        out.append(
            SpfRecessRow(
                survey_year=survey_year,
                survey_quarter=survey_quarter,
                probabilities=probabilities,
                source_available_at=release.isoformat(),
            )
        )
    return out


def event_probability_from_bins(
    probabilities: list[float],
    bins: list[tuple[float | None, float | None, str]],
    strike_type: str,
    floor_strike,
    cap_strike,
) -> tuple[float, float, float]:
    """(strict, midpoint, generous) event probability from a binned density.

    strict counts only bins that lie ENTIRELY inside the event; generous also
    counts every bin that overlaps it at all; midpoint assumes uniform mass
    within each partially-overlapping bin. The strict/generous pair is an
    honest uncertainty band that costs no invented distributional assumption.
    Open-ended bins are treated as 3 percentage points wide for the uniform
    midpoint split — disclosed, and irrelevant to strict/generous.
    """
    def bin_bounds(low, high):
        if low is None:
            return (high - 3.0, high)
        if high is None:
            return (low, low + 3.0)
        return (low, high)

    def event_bounds():
        if strike_type == "greater":
            return (float(floor_strike), math.inf)
        if strike_type == "less":
            return (-math.inf, float(cap_strike))
        if strike_type == "between":
            return (float(floor_strike), float(cap_strike))
        raise ValueError(f"Unknown strike_type: {strike_type!r}")

    event_low, event_high = event_bounds()
    strict = generous = midpoint = 0.0
    total = sum(probabilities)
    if total <= 0:
        raise ValueError("empty SPF density")
    for probability, (low, high, _label) in zip(probabilities, bins):
        b_low, b_high = bin_bounds(low, high)
        overlap_low = max(b_low, event_low)
        overlap_high = min(b_high, event_high)
        if overlap_high <= overlap_low:
            continue
        generous += probability
        fraction = (overlap_high - overlap_low) / (b_high - b_low)
        midpoint += probability * min(1.0, fraction)
        if b_low >= event_low and b_high <= event_high:
            strict += probability
    return strict / total, midpoint / total, generous / total


# --------------------------------------------------------------------------
# Fed funds target range (FRED public CSV) + FOMC meeting calendar.
# --------------------------------------------------------------------------


@scan_cached
def fetch_fred_series(series_id: str) -> list[tuple[date, float]]:
    """A FRED public no-key CSV series (fredgraph.csv). FRED mirrors official
    BLS/Fed series; used for series whose BLS flat files are hundreds of MB.
    CSV shape verified live 2026-07-09 with DFEDTARU."""
    text = _get_with_retry(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}", timeout=45).text
    out: list[tuple[date, float]] = []
    for line in text.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) != 2 or parts[1] in ("", "."):
            continue
        out.append((date.fromisoformat(parts[0]), float(parts[1])))
    if not out:
        raise RuntimeError(f"FRED {series_id} returned no usable rows")
    return out


def fetch_fed_target_upper() -> list[tuple[date, float]]:
    """Daily upper limit of the federal funds target range (FRED DFEDTARU)."""
    return fetch_fred_series("DFEDTARU")


_FOMC_MONTH_RE = "|".join(m.title() for m in _MONTHS)


def parse_fomc_meeting_dates(page_html: str) -> list[date]:
    """Decision dates (the final day of each scheduled meeting) parsed from
    the official FOMC calendar page. Handles 'January 27-28' and
    'April 30-May 1' spellings inside each year's panel."""
    plain = html.unescape(re.sub(r"<[^>]+>", " ", page_html))
    plain = re.sub(r"\s+", " ", plain)
    meetings: list[date] = []
    year_blocks = re.split(r"(\d{4}) FOMC Meetings", plain)
    for idx in range(1, len(year_blocks), 2):
        year = int(year_blocks[idx])
        block = year_blocks[idx + 1]
        for match in re.finditer(
            rf"\b({_FOMC_MONTH_RE})\s+(\d{{1,2}})\s*[-–]\s*(?:({_FOMC_MONTH_RE})\s+)?(\d{{1,2}})",
            block,
        ):
            start_month, _start_day, end_month, end_day = match.groups()
            month_name = end_month or start_month
            try:
                meetings.append(date(year, _MONTHS[month_name.lower()], int(end_day)))
            except ValueError:
                continue
    # The page lists some years in more than one panel with slightly
    # different spellings; a scheduled meeting is unique per (year, month),
    # so keep the latest parsed day for each.
    by_month: dict[tuple[int, int], date] = {}
    for meeting in meetings:
        key = (meeting.year, meeting.month)
        if key not in by_month or meeting > by_month[key]:
            by_month[key] = meeting
    return sorted(by_month.values())


@scan_cached
def fetch_fomc_meeting_dates() -> list[date]:
    return parse_fomc_meeting_dates(_get_with_retry(FOMC_CALENDAR_URL, timeout=45).text)


# --------------------------------------------------------------------------
# Atlanta Fed GDPNow current-quarter nowcast.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GdpNowcast:
    quarter_label: str  # e.g. '2026Q2'
    latest: float  # latest GDPNow real GDP growth nowcast, QoQ SAAR percent
    path_values: list[float]  # the quarter's full nowcast evolution
    latest_date: str


_GDPNOW_CACHE: dict[str, GdpNowcast] = {}


@dataclass(frozen=True)
class GdpNowHistoricalForecast:
    forecast_date: date
    quarter_label: str
    nowcast: float
    advance_estimate: float
    publication_date: date


def _excel_serial_to_date(serial: float) -> date:
    return date(1899, 12, 30) + timedelta(days=int(serial))


@scan_cached
def fetch_gdpnow_current() -> GdpNowcast:
    """Latest GDPNow nowcast from the official tracking workbook's
    TrackingHistory sheet (row layout verified live 2026-07-09: header
    'Date | Major Releases | GDP | ...', one row per model run)."""
    if "current" in _GDPNOW_CACHE:
        return _GDPNOW_CACHE["current"]
    content = _get_with_retry(GDPNOW_WORKBOOK_URL, timeout=90).content
    zf = zipfile.ZipFile(io.BytesIO(content))
    book = ET.fromstring(zf.read("xl/workbook.xml"))
    sheet_names = [
        s.attrib.get("name")
        for s in book.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet")
    ]
    sheet_index = sheet_names.index("TrackingHistory") + 1
    rows = _xlsx_sheet_rows(content, f"xl/worksheets/sheet{sheet_index}.xml")
    header = rows[0]
    gdp_col = next(i for i, name in enumerate(header) if name.strip().upper() == "GDP")
    path: list[tuple[date, float]] = []
    for raw in rows[1:]:
        if len(raw) <= gdp_col or raw[gdp_col] in ("", "#N/A"):
            continue
        try:
            run_date = _excel_serial_to_date(float(raw[0]))
            value = float(raw[gdp_col])
        except (ValueError, TypeError):
            continue
        # The sheet's GDP column carries dollar-LEVEL rows (tens of millions)
        # in a separate block above the growth-rate tracking rows (verified
        # live 2026-07-09). Only QoQ SAAR growth-rate rows belong in the
        # nowcast path; no real SAAR print has ever approached ±30.
        if abs(value) >= 30:
            continue
        path.append((run_date, value))
    if not path:
        raise RuntimeError("GDPNow TrackingHistory sheet had no usable nowcast rows")
    path.sort()
    latest_date, latest = path[-1]
    # GDPNow keeps tracking a quarter until that quarter's BEA advance
    # estimate (~30 days after quarter end), so runs in early July still
    # track Q2. The quarter containing (run date - 30 days) is therefore the
    # tracked quarter across the whole cycle.
    anchor = latest_date - timedelta(days=30)
    quarter = (anchor.month - 1) // 3 + 1
    label = f"{anchor.year}Q{quarter}"
    nowcast = GdpNowcast(
        quarter_label=label,
        latest=latest,
        path_values=[v for _d, v in path],
        latest_date=latest_date.isoformat(),
    )
    _GDPNOW_CACHE["current"] = nowcast
    return nowcast


@scan_cached
def fetch_gdpnow_track_record() -> list[GdpNowHistoricalForecast]:
    """Official real-time GDPNow forecasts paired with BEA advance estimates."""
    content = _get_with_retry(GDPNOW_WORKBOOK_URL, timeout=90).content
    zf = zipfile.ZipFile(io.BytesIO(content))
    book = ET.fromstring(zf.read("xl/workbook.xml"))
    names = [s.attrib.get("name") for s in book.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet")]
    rows = _xlsx_sheet_rows(content, f"xl/worksheets/sheet{names.index('TrackRecord') + 1}.xml")
    header = rows[0]
    indexes = {name: header.index(name) for name in (
        "Forecast Date", "Quarter being forecasted", "GDP Nowcast",
        "Advance Estimate From BEA", "Publication Date of Advance Estimate",
    )}
    out = []
    for raw in rows[1:]:
        try:
            forecast_date = _excel_serial_to_date(float(raw[indexes["Forecast Date"]]))
            quarter_date = _excel_serial_to_date(float(raw[indexes["Quarter being forecasted"]]))
            nowcast = float(raw[indexes["GDP Nowcast"]])
            actual = float(raw[indexes["Advance Estimate From BEA"]])
            publication = _excel_serial_to_date(float(raw[indexes["Publication Date of Advance Estimate"]]))
        except (IndexError, TypeError, ValueError):
            continue
        quarter = (quarter_date.month - 1) // 3 + 1
        if forecast_date >= publication:
            continue
        out.append(GdpNowHistoricalForecast(forecast_date, f"{quarter_date.year}Q{quarter}", nowcast, actual, publication))
    if len(out) < 100:
        raise RuntimeError(f"GDPNow TrackRecord returned only {len(out)} usable historical forecasts")
    return out


@scan_cached
def fetch_gdpnow_tracking_archives() -> list[tuple[date, str, float]]:
    """Parse the workbook's transposed most-recent archived quarter path."""
    content = _get_with_retry(GDPNOW_WORKBOOK_URL, timeout=90).content
    zf = zipfile.ZipFile(io.BytesIO(content)); book = ET.fromstring(zf.read("xl/workbook.xml"))
    names = [s.attrib.get("name") for s in book.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet")]
    rows = _xlsx_sheet_rows(content, f"xl/worksheets/sheet{names.index('TrackingArchives') + 1}.xml")
    dates = [_excel_serial_to_date(float(x)) for x in rows[0] if x]
    title = next((x for x in rows[1] if "for " in x), "")
    match = re.search(r"for (\d{4})q([1-4])", title, re.I)
    gdp = next((r[2:] for r in rows if len(r) > 2 and r[0] == "GDP" and r[1] == "GDP Nowcast"), [])
    if not match or not gdp:
        raise RuntimeError("GDPNow TrackingArchives quarter/GDP row not found")
    label = f"{match.group(1)}Q{match.group(2)}"
    return [(d, label, float(v)) for d, v in zip(dates, gdp) if v not in ("", "#N/A")]
