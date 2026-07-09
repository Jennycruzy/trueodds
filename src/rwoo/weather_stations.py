"""Kalshi weather-series -> physical station registry.

Coordinates are the official NOAA GHCND registry locations for the station
each series' settlement source actually names. Getting the wrong point on the
map is the single easiest way to answer the wrong question — this table
exists so that mistake can't happen silently.

How entries are verified (2026-07-09, extending the 2026-07-08 originals):

1. Each Kalshi event exposes `settlement_sources` naming an official NWS
   Climatological Report URL of the form
   `forecast.weather.gov/product.php?...&issuedby=<CODE>`. That CODE is the
   NWS CLI station identifier the market settles against — read live for
   every series below, not assumed.
2. The CODE is mapped to its GHCND station id, and lat/lon are taken from
   NOAA's own station registry file
   https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt
   (the registry line is quoted in each entry's `source`).

Never add a series here without both steps.
"""
from dataclasses import dataclass

GHCND_REGISTRY_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt"


@dataclass(frozen=True)
class Station:
    name: str
    lat: float
    lon: float
    ghcnd_id: str
    source: str


# NWS CLI `issuedby` code -> verified station. Registry lines quoted verbatim
# from ghcnd-stations.txt on 2026-07-09.
STATIONS_BY_CODE: dict[str, Station] = {
    "NYC": Station(
        name="NY City Central Park, NY US",
        lat=40.7789,
        lon=-73.9692,
        ghcnd_id="GHCND:USW00094728",
        source=f"{GHCND_REGISTRY_URL} — 'USW00094728  40.7789  -73.9692 ... NY NY CITY CNTRL PARK'",
    ),
    "MDW": Station(
        name="Chicago Midway Airport, IL US",
        lat=41.7842,
        lon=-87.7553,
        ghcnd_id="GHCND:USW00014819",
        source=f"{GHCND_REGISTRY_URL} — 'USW00014819  41.7842  -87.7553 ... IL CHICAGO MIDWAY AP'",
    ),
    "LAX": Station(
        name="Los Angeles International Airport, CA US",
        lat=33.9381,
        lon=-118.3867,
        ghcnd_id="GHCND:USW00023174",
        source=f"{GHCND_REGISTRY_URL} — 'USW00023174  33.9381 -118.3867 ... CA LOS ANGELES INTL AP'",
    ),
    "MIA": Station(
        name="Miami International Airport, FL US",
        lat=25.7881,
        lon=-80.3169,
        ghcnd_id="GHCND:USW00012839",
        source=f"{GHCND_REGISTRY_URL} — 'USW00012839  25.7881  -80.3169 ... FL MIAMI INTL AP'",
    ),
    "DEN": Station(
        name="Denver International Airport, CO US",
        lat=39.8467,
        lon=-104.6561,
        ghcnd_id="GHCND:USW00003017",
        source=f"{GHCND_REGISTRY_URL} — 'USW00003017  39.8467 -104.6561 ... CO DENVER INTL AP'",
    ),
    "SEA": Station(
        name="Seattle-Tacoma International Airport, WA US",
        lat=47.4447,
        lon=-122.3144,
        ghcnd_id="GHCND:USW00024233",
        source=f"{GHCND_REGISTRY_URL} — 'USW00024233  47.4447 -122.3144 ... WA SEATTLE TACOMA AP'",
    ),
    "DFW": Station(
        name="Dallas-Fort Worth Airport, TX US",
        lat=32.8975,
        lon=-97.0219,
        ghcnd_id="GHCND:USW00003927",
        source=f"{GHCND_REGISTRY_URL} — 'USW00003927  32.8975  -97.0219 ... TX DAL-FTW WSCMO AP'",
    ),
    "AUS": Station(
        name="Austin Bergstrom International Airport, TX US",
        lat=30.1831,
        lon=-97.6800,
        ghcnd_id="GHCND:USW00013904",
        source=f"{GHCND_REGISTRY_URL} — 'USW00013904  30.1831  -97.6800 ... TX AUSTIN BERGSTROM INTL AP'",
    ),
    "LAS": Station(
        name="Las Vegas McCarran International Airport, NV US",
        lat=36.0719,
        lon=-115.1633,
        ghcnd_id="GHCND:USW00023169",
        source=f"{GHCND_REGISTRY_URL} — 'USW00023169  36.0719 -115.1633 ... NV MCCARRAN INTL AP'",
    ),
    "OKC": Station(
        name="Oklahoma City Will Rogers World Airport, OK US",
        lat=35.3883,
        lon=-97.6003,
        ghcnd_id="GHCND:USW00013967",
        source=f"{GHCND_REGISTRY_URL} — 'USW00013967  35.3883  -97.6003 ... OK OKLAHOMA CY WILL ROGERS WORLD'",
    ),
    "SFO": Station(
        name="San Francisco International Airport, CA US",
        lat=37.6197,
        lon=-122.3656,
        ghcnd_id="GHCND:USW00023234",
        source=f"{GHCND_REGISTRY_URL} — 'USW00023234  37.6197 -122.3656 ... CA SAN FRANCISCO INTL AP'",
    ),
    "BOS": Station(
        name="Boston Logan International Airport, MA US",
        lat=42.3606,
        lon=-71.0097,
        ghcnd_id="GHCND:USW00014739",
        source=f"{GHCND_REGISTRY_URL} — 'USW00014739  42.3606  -71.0097 ... MA BOSTON'",
    ),
    "PHL": Station(
        name="Philadelphia International Airport, PA US",
        lat=39.8733,
        lon=-75.2269,
        ghcnd_id="GHCND:USW00013739",
        source=f"{GHCND_REGISTRY_URL} — 'USW00013739  39.8733  -75.2269 ... PA PHILA INTL AP'",
    ),
    "PHX": Station(
        name="Phoenix Sky Harbor Airport, AZ US",
        lat=33.4278,
        lon=-112.0036,
        ghcnd_id="GHCND:USW00023183",
        source=f"{GHCND_REGISTRY_URL} — 'USW00023183  33.4278 -112.0036 ... AZ PHOENIX AP'",
    ),
    "DCA": Station(
        name="Washington Reagan National Airport, VA US",
        lat=38.8472,
        lon=-77.0344,
        ghcnd_id="GHCND:USW00013743",
        source=f"{GHCND_REGISTRY_URL} — 'USW00013743  38.8472  -77.0344 ... VA WASHINGTON REAGAN NATL AP'",
    ),
    "ATL": Station(
        name="Atlanta Hartsfield-Jackson International Airport, GA US",
        lat=33.6297,
        lon=-84.4422,
        ghcnd_id="GHCND:USW00013874",
        source=f"{GHCND_REGISTRY_URL} — 'USW00013874  33.6297  -84.4422 ... GA ATLANTA HARTSFIELD-JACKSON INT'",
    ),
    "SAT": Station(
        name="San Antonio International Airport, TX US",
        lat=29.5442,
        lon=-98.4839,
        ghcnd_id="GHCND:USW00012921",
        source=f"{GHCND_REGISTRY_URL} — 'USW00012921  29.5442  -98.4839 ... TX SAN ANTONIO INTL AP'",
    ),
    "MSY": Station(
        name="New Orleans International Airport, LA US",
        lat=29.9975,
        lon=-90.2778,
        ghcnd_id="GHCND:USW00012916",
        source=f"{GHCND_REGISTRY_URL} — 'USW00012916  29.9975  -90.2778 ... LA NEW ORLEANS AP'",
    ),
    "MSP": Station(
        name="Minneapolis-St Paul International Airport, MN US",
        lat=44.8853,
        lon=-93.2314,
        ghcnd_id="GHCND:USW00014922",
        source=f"{GHCND_REGISTRY_URL} — 'USW00014922  44.8853  -93.2314 ... MN MINNEAPOLIS-ST PAUL INTL AP'",
    ),
    "HOU": Station(
        name="Houston William P Hobby Airport, TX US",
        lat=29.6458,
        lon=-95.2822,
        ghcnd_id="GHCND:USW00012918",
        source=f"{GHCND_REGISTRY_URL} — 'USW00012918  29.6458  -95.2822 ... TX HOUSTON WILLIAM P HOBBY AP'",
    ),
}

STATION_TIMEZONES: dict[str, str] = {
    "NYC": "America/New_York",
    "MIA": "America/New_York",
    "BOS": "America/New_York",
    "PHL": "America/New_York",
    "DCA": "America/New_York",
    "ATL": "America/New_York",
    "MDW": "America/Chicago",
    "DFW": "America/Chicago",
    "AUS": "America/Chicago",
    "OKC": "America/Chicago",
    "SAT": "America/Chicago",
    "MSY": "America/Chicago",
    "MSP": "America/Chicago",
    "HOU": "America/Chicago",
    "DEN": "America/Denver",
    "PHX": "America/Phoenix",  # Arizona does not observe DST
    "LAX": "America/Los_Angeles",
    "SFO": "America/Los_Angeles",
    "SEA": "America/Los_Angeles",
    "LAS": "America/Los_Angeles",
}


@dataclass(frozen=True)
class SeriesSpec:
    metric: str  # Open-Meteo daily variable name
    station_code: str  # NWS CLI issuedby code, read live from settlement_sources


# Every series' issuedby code was read live from its Kalshi event
# settlement_sources on 2026-07-09 (see module docstring for the method).
SERIES: dict[str, SeriesSpec] = {
    # Daily high temperature
    "KXHIGHNY": SeriesSpec("temperature_2m_max", "NYC"),
    "KXHIGHCHI": SeriesSpec("temperature_2m_max", "MDW"),
    "KXHIGHLAX": SeriesSpec("temperature_2m_max", "LAX"),
    "KXHIGHMIA": SeriesSpec("temperature_2m_max", "MIA"),
    "KXHIGHDEN": SeriesSpec("temperature_2m_max", "DEN"),
    "KXHIGHTSEA": SeriesSpec("temperature_2m_max", "SEA"),
    "KXHIGHTDAL": SeriesSpec("temperature_2m_max", "DFW"),
    "KXHIGHAUS": SeriesSpec("temperature_2m_max", "AUS"),
    "KXHIGHTLV": SeriesSpec("temperature_2m_max", "LAS"),
    "KXHIGHTOKC": SeriesSpec("temperature_2m_max", "OKC"),
    "KXHIGHTSFO": SeriesSpec("temperature_2m_max", "SFO"),
    "KXHIGHTBOS": SeriesSpec("temperature_2m_max", "BOS"),
    "KXHIGHPHIL": SeriesSpec("temperature_2m_max", "PHL"),
    "KXHIGHTPHX": SeriesSpec("temperature_2m_max", "PHX"),
    "KXHIGHTDC": SeriesSpec("temperature_2m_max", "DCA"),
    "KXHIGHTATL": SeriesSpec("temperature_2m_max", "ATL"),
    "KXHIGHTSATX": SeriesSpec("temperature_2m_max", "SAT"),
    "KXHIGHTNOLA": SeriesSpec("temperature_2m_max", "MSY"),
    "KXHIGHTMIN": SeriesSpec("temperature_2m_max", "MSP"),
    "KXHIGHTHOU": SeriesSpec("temperature_2m_max", "HOU"),
    # Daily low temperature
    "KXLOWTNYC": SeriesSpec("temperature_2m_min", "NYC"),
    "KXLOWTCHI": SeriesSpec("temperature_2m_min", "MDW"),
    "KXLOWTLAX": SeriesSpec("temperature_2m_min", "LAX"),
    "KXLOWTMIA": SeriesSpec("temperature_2m_min", "MIA"),
    "KXLOWTDEN": SeriesSpec("temperature_2m_min", "DEN"),
    "KXLOWTPHX": SeriesSpec("temperature_2m_min", "PHX"),
    "KXLOWTOKC": SeriesSpec("temperature_2m_min", "OKC"),
    "KXLOWTAUS": SeriesSpec("temperature_2m_min", "AUS"),
    "KXLOWTHOU": SeriesSpec("temperature_2m_min", "HOU"),
    "KXLOWTATL": SeriesSpec("temperature_2m_min", "ATL"),
    "KXLOWTDAL": SeriesSpec("temperature_2m_min", "DFW"),
    "KXLOWTDC": SeriesSpec("temperature_2m_min", "DCA"),
    "KXLOWTPHIL": SeriesSpec("temperature_2m_min", "PHL"),
    "KXLOWTLV": SeriesSpec("temperature_2m_min", "LAS"),
    "KXLOWTSATX": SeriesSpec("temperature_2m_min", "SAT"),
    "KXLOWTSEA": SeriesSpec("temperature_2m_min", "SEA"),
    "KXLOWTBOS": SeriesSpec("temperature_2m_min", "BOS"),
    "KXLOWTSFO": SeriesSpec("temperature_2m_min", "SFO"),
    "KXLOWTNOLA": SeriesSpec("temperature_2m_min", "MSY"),
    "KXLOWTMIN": SeriesSpec("temperature_2m_min", "MSP"),
}

# Legacy views: series ticker -> Station / timezone. Kept because parsers and
# backtests address stations by series ticker.
STATIONS: dict[str, Station] = {
    series: STATIONS_BY_CODE[spec.station_code] for series, spec in SERIES.items()
}
WEATHER_TIMEZONES: dict[str, str] = {
    series: STATION_TIMEZONES[spec.station_code] for series, spec in SERIES.items()
}


def station_for_series(series_ticker: str) -> Station:
    if series_ticker not in STATIONS:
        raise KeyError(
            f"No verified station coordinates for series '{series_ticker}'. "
            "Add and verify one in weather_stations.py before using this series "
            "— never guess a station's lat/lon."
        )
    return STATIONS[series_ticker]


def metric_for_series(series_ticker: str) -> str | None:
    spec = SERIES.get(series_ticker)
    return spec.metric if spec else None
