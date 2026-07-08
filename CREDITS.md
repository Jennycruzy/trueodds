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
- **[Bureau of Labor Statistics public API](https://www.bls.gov/developers/)** and **[BLS time-series flat files](https://download.bls.gov/pub/time.series/cu/)** — official seasonally adjusted core CPI history for the economics engine and backtest. The API is tried first; the official flat-file mirror is used as the quota-free fallback.
- **[Federal Reserve Bank of Cleveland Inflation Nowcasting](https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting)** — official CPI/core-CPI monthly nowcast input for the live economics engine.
- **[Federal Reserve Bank of Philadelphia Survey of Professional Forecasters](https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/survey-of-professional-forecasters)** — official PRCCPI probability distributions and SPF release-date data for economics calibration.
- **[World Football Elo Ratings](https://www.eloratings.net/)** — public national-team Elo ratings TSV data for the sports engine's live (current-ratings) path.
- **[FIFA/Coca-Cola Men's World Ranking](https://inside.fifa.com/fifa-world-ranking/men)** — official national-team ranking/points source for the sports engine's live multi-source World Cup path.
- **[martj42/international_results](https://github.com/martj42/international_results)** (public domain / CC0-style open data) — real historical international football match results, 1872-present, used to self-compute a dated Elo rating history for the sports calibration backtest (no public API provides national-team Elo by arbitrary past date; verified and disclosed in `docs/VERIFICATION_LEDGER.md` §19).
- **[BLS CPI release schedule](https://www.bls.gov/schedule/news_release/cpi.htm)** — primary CPI publication-date source, now reachable with a normal User-Agent and verified by the pre-listing hardening gate.

## Libraries (versions pinned in requirements.txt)

- **httpx** (BSD-3-Clause) — HTTP client for all data workers.
- **pycryptodome** (BSD/public-domain components) — real keccak256 hashing for receipt commitments.

## Not yet added (originally anticipated, not used so far)

- FastAPI, pydantic, web3.py — the build hasn't needed a web framework, schema-validation library, or a Python EVM-signing library yet (X Layer transactions go through the OKX Agentic Wallet CLI, not a local signer). Will be added here the moment any of them is actually used, not before.

This file will be updated as each phase adds a new dependency. No open-source
project is copied wholesale; only stated libraries/APIs are used as building
blocks, per the project's Forbidden Actions §3.6.
