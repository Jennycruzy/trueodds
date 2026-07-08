# Credits

Real-World Odds Oracle's engines, data model, calibration methodology, and
receipt scheme are original work. The following third-party services and
libraries are used as building blocks.

## Data sources (free/public APIs, called directly — not vendored code)

- **[Open-Meteo](https://open-meteo.com/)** — multi-model weather forecast API (ECMWF, GFS, ICON, and others). Keyless, CC-BY-4.0 attributed data.
- **[NWS / weather.gov](https://www.weather.gov/documentation/services-web-api)** — US authoritative forecast and climatological report data. Public domain (US government work).
- **[Meteostat](https://meteostat.net/)** — historical weather observations, used for calibration backtests.
- **[NASA POWER](https://power.larc.nasa.gov/)** — climatological baselines.
- **[Kalshi](https://kalshi.com/)** — regulated US prediction market; public market-data API.
- **[Polymarket](https://polymarket.com/)** — on-chain prediction market; Gamma and CLOB public APIs.

## Planned libraries (to be added as implementation proceeds, with versions pinned in requirements.txt)

- **FastAPI** (MIT) — backend API framework.
- **httpx** (BSD-3-Clause) — async HTTP client for data workers.
- **pydantic** (MIT) — data validation / canonical market schema.
- **web3.py** (MIT) — X Layer (EVM) transaction signing for receipt anchoring.

This file will be updated as each phase adds a new dependency. No open-source
project is copied wholesale; only stated libraries/APIs are used as building
blocks, per the project's Forbidden Actions §3.6.
