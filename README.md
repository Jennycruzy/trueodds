# Real-World Odds Oracle

**Independent weather, commodity, economic-data, and sports probabilities for real-money decisions.**

Real-World Odds Oracle is a live, agent-callable intelligence API built around
four real-world domains: **weather**, **commodities**, **economic data**, and **sports**. It
turns forecast models, official releases, observation stations, rating systems,
and tournament simulations into independent probabilities that agents can
compare with live market prices before committing real money.

Weather is the flagship: station-bound temperature and precipitation forecasts
are modeled independently and resolved against authoritative observations.
Economic-data services cover scheduled releases such as CPI, GDP, employment,
payrolls, rates, and supported recession structures. Sports services cover
supported tournament, team, and match structures using explicit rating systems
and deterministic simulation. Prediction markets are where these probabilities
are priced and acted upon; they are not a substitute for the underlying
weather, commodity, economic, or sports analysis.

- Public site: <https://trueodd.xyz>
- API: <https://api.trueodd.xyz>
- Interactive API documentation: <https://api.trueodd.xyz/docs>
- OpenAPI schema: <https://api.trueodd.xyz/openapi.json>
- Service catalog: <https://api.trueodd.xyz/v1/service-metadata>
- Public calibration: <https://api.trueodd.xyz/v1/calibration>

The product is designed for real-money decision workflows. It does not confuse
a model probability with a guaranteed outcome: every verdict carries the
information an agent needs to decide whether an apparent edge survives model
uncertainty, executable prices, spread, fees, source freshness, and evidence
quality.

## Four real-world intelligence domains

The service combines four independently modeled capabilities in one API:

1. **Weather** — station-bound daily high/low and precipitation probabilities
   derived from multiple forecast models and checked against NOAA observations,
   plus NOAA-resolved Atlantic seasonal storm-count thresholds.
2. **Commodities** — EIA-resolved Henry Hub annual-high thresholds backed by
   official daily history; other energy and agriculture contracts are measured
   but remain source-gated until their exact settlement feed is approved.
3. **Economic data** — CPI, GDP, labor, rates, and recession structures tied to
   official release definitions and forward-looking official sources where
   available.
4. **Sports** — structured tournament and match probabilities from explicit
   rating systems and deterministic simulation rather than generated guesses.

The durable advantage is the shared architecture across all three domains:
independent models, exact outcome-rule binding, authoritative sources,
fail-closed coverage, cost-aware edges, continuous resolution, public
calibration, and verifiable receipts.

## What an agent receives

For a supported weather, commodity, economic-release, or sports event, the oracle
returns:

- independent YES probability;
- probability interval and confidence;
- deterministic model version;
- source freshness and model-disagreement trace;
- market-implied probability from executable bid/ask data;
- candidate side (`YES` or `NO`);
- entry-price basis;
- estimated spread and venue fees;
- expected profit per contract and expected return on cost;
- actionable, wait, or refused status with an explicit reason;
- family/model/band calibration context;
- promotion and execution-eligibility state;
- hash-chained decision receipt.

Unsupported, ambiguous, stale, or insufficiently sourced markets are refused.
Unknown inputs never silently become a zero probability.

## Agent services

### `rwoo.best_signals` / `rwoo_best_signals`

Request ranked opportunities using natural language. This is the primary command
for an agent looking for signals.

```http
POST /v1/signals
Content-Type: application/json

{"message":"Give me the best weather signals now","limit":5}
```

The command returns only currently open candidates that pass freshness,
trading-close, executable-quote, spread, and exact-model checks. A valid empty
result uses `status: "no_signal"`.

### `rwoo.check_market`

Evaluate one supported market.

```http
POST /v1/check-market
Content-Type: application/json

{
  "market": {
    "venue": "kalshi",
    "market_id": "<market-id>"
  }
}
```

The response contains the forecast, market comparison, execution economics,
calibration scope, request ID, and receipt reference. Idempotency and client
request IDs are supported through headers.

```bash
curl -sS https://api.trueodd.xyz/v1/check-market \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: agent-example-001' \
  -H 'Idempotency-Key: market-check-001' \
  -d '{"market":{"venue":"kalshi","market_id":"<market-id>"}}'
```

### `rwoo.cross_venue_edge`

Compare two candidate-equivalent contracts.

```http
POST /v1/cross-venue-edge
Content-Type: application/json

{
  "left": {"venue": "kalshi", "market_id": "<left-id>"},
  "right": {"venue": "polymarket", "market_id": "<right-id>"}
}
```

Only exact agreement on event semantics, resolution authority, resolution
time, and YES orientation can qualify. Similar titles are not enough. Results
remain subject to fill, custody, venue, cancellation, and settlement risk.

### `rwoo.get_calibration`

Read the public evidence record.

```bash
curl -sS https://api.trueodd.xyz/v1/calibration
curl -sS https://api.trueodd.xyz/v1/calibration/weather.temperature
```

The report exposes independent event counts, correlated contract-row counts,
Brier scores, reliability bands, official-source concordance, market
benchmarking, cost-adjusted performance, drift monitoring, fixed-checkpoint
reviews, and the execution interlock.

## Domain coverage

### Weather — flagship

The weather engine supports registered US observation stations and binds the
venue series to a station, target date, metric, and strike before computing a
probability.

- multi-model forecast ensemble;
- daily maximum and minimum temperature;
- precipitation paths where the market rule is supported;
- explicit ensemble disagreement and uncertainty interval;
- station-specific identity carried into the receipt;
- NOAA NCEI Daily Summaries outcome verification;
- v3 power recalibration derived from grouped walk-forward evidence;
- drift monitoring by station, metric, horizon, and warm/cool season.

The current production model is
`weather-ensemble-v3-power-calibrated`. Results from earlier weather versions
cannot promote v3.

Structured Atlantic-season count contracts are a separate family,
`weather.hurricane_season`. Their ranges and stated coverage are parsed from the
current NOAA CPC outlook and reconciled with the live NHC season summary. A May
preseason outlook is conditioned on observed season-to-date activity; an August
update, which already incorporates the season to date, is not conditioned a
second time.
Only NOAA-resolved named-storm, hurricane, and major-hurricane count thresholds
are accepted; landfall, damage, and individual-storm contracts are not silently
treated as equivalent.

### Energy and agriculture

`energy.henry_hub_spot` prices structured EIA-resolved calendar-year Henry Hub
daily-maximum thresholds. It uses the EIA DHHNGSP series through FRED's public
mirror, first checks the full contract-year observed maximum, and then compares
an unhit threshold with independent same-calendar-date historical remaining-year
maximum ratios from full and recent official history. The corrected model is
`henry-hub-seasonal-annual-max-v2`.

Other energy prices (`energy.commodity_price`) and agricultural prices
(`agriculture.commodity_price`) are discovered, classified, and included in
unsupported-market telemetry, but remain `source_gated`. In particular, the
service does not substitute an unrelated public quote for an ICE, Pyth, AAA, or
other contract-specific settlement feed. A USDA report model will be enabled
only when an actual recurring open USDA-resolved contract shape is verified;
the API does not advertise a fabricated USDA product merely because USDA data
exists.

Natural-language family filters include:

```json
{"message":"Give me the best hurricane signals now","limit":5}
{"message":"Give me the best Henry Hub natural gas signals now","limit":5}
{"message":"Give me the best agriculture signals now","limit":5}
```

The third request currently returns `no_signal` rather than substituting another
commodity family.

### Economic data

Economic engines are bound to official definitions and release schedules.
Implemented paths include:

- headline and core CPI bins and thresholds;
- quarterly and annual GDP structures;
- unemployment and payroll markets;
- constrained Fed target-range paths;
- single-quarter real-GDP-decline recession structures.

Sources include BLS releases and history, Cleveland Fed nowcasts,
Philadelphia Fed Survey of Professional Forecasters distributions, Atlanta
Fed GDPNow, FRED series, and other explicit official inputs. NBER declaration
markets, unsupported non-US releases, PPI, or rate paths lacking an adequate
forward distribution fail closed instead of borrowing an unrelated proxy.

### Sports

Sports coverage is exposed per family at `GET /v1/supported-markets`; a
registered model identifier is not treated as proof that a current signal is
available.

| Sport / family | Availability | Supported market shape | Data and boundary |
|---|---|---|---|
| FIFA World Cup (`sports.world_cup`) | Live signal candidates | 2026 national-team winner; stage of elimination | Official FIFA inputs, World Football Elo, deterministic 48-team simulation. Props, top scorer, goals, and exact matchup outcomes are unsupported. |
| Tennis (`sports.tennis`) | Conditional engine; no qualifying current scan rows | Head-to-head match winner with exact YES binding | Ultimate Tennis Statistics Elo. Tournament winner outrights lack a wired draw/bracket simulation. |
| MLB / baseball (`sports.mlb`) | Conditional engine; no qualifying current scan rows | Head-to-head game winner with exact YES binding | Official MLB completed-game results and current-season Elo; no pitcher/lineup adjustment. Champion outrights are unsupported. |
| Club soccer (`sports.club_soccer`) | Conditional engine; no qualifying current scan rows | Head-to-head match winner with exact YES binding | ClubElo; unsuitable draw/home-field structures fail closed. |
| NBA / basketball (`sports.nba`) | Conditional engine; no qualifying current scan rows | Head-to-head game winner with exact YES binding | ESPN season point differential. Champion futures remain model-missing. |
| NHL / hockey (`sports.nhl`) | Unsupported; fails closed | None | Discovered champion futures have no approved champion model. |
| Esports (`sports.esports`) | Unsupported; fails closed | None | No approved source and model are wired. |

The Best Signals command understands sport-specific requests. For example,
`{"message":"Give me the best World Cup signals now"}` filters to
`sports.world_cup`, while a basketball request returns `no_signal` instead of
substituting another sport or domain.

## Real-money decision discipline

An apparent edge is not actionable merely because
`oracle_probability != market_probability`. It must survive:

1. exact market-rule, source, time, entity, strike, and YES-side binding;
2. valid and sufficiently fresh source data;
3. minimum model agreement;
4. the oracle's own probability interval;
5. executable bid/ask pricing rather than last-trade price;
6. spread and quantified venue fees;
7. positive net expected value;
8. family- and model-specific evidence status.

Kalshi uses its published quadratic taker-fee formula. Limitless uses a
conservative bound derived from its published taker-fee table until an exact
execution fee is available. Missing fee information is disclosed and can
force refusal.

The API can be called by agents operating real-money strategies today. The
oracle's own funded order path remains independently gated; callers retain
responsibility for their orders, custody, sizing, venue access, and losses.

## Evidence, calibration, and promotion

The production evidence loop runs every six hours:

1. collect every priced supported forecast;
2. append a pre-resolution market quote snapshot;
3. commit the probability, model version, rule hash, source, interval, market
   price, side, and execution economics;
4. resolve finalized Kalshi, Polymarket, and Limitless contracts;
5. retry supported NOAA outcome verification until official data arrives;
6. preserve the latest genuine pre-resolution quote as a closing benchmark;
7. regenerate public calibration and promotion reports.

Multiple strike contracts for one underlying location/date/metric or sporting
event remain visible, but they share an independent event-group identity and
cannot inflate the primary evidence count.

Weather v3 is reassessed at fixed checkpoints of 30, 100, 250, and 500
independent resolved events. Promotion requires all applicable controls:

- at least 30 independent v3 events;
- Brier score at most `0.20`;
- maximum calibration gap at most `0.15`;
- NOAA/venue concordance at least `95%`;
- every probability band with at least 30 independent groups within the
  calibration-gap limit;
- oracle Brier score better than the recorded market benchmark;
- positive cost-adjusted strategy result after entry price, spread, and fees;
- no adequately sampled station, metric, horizon, or weather-regime drift
  alert;
- valid evidence ledger.

Evidence gates are not weakened to force a launch result. A failure keeps the
family locked and becomes a diagnostic input for the next model version.

## Funded execution interlock

The repository contains an auditable trade lifecycle, but it does not store
venue keys or autonomously submit orders. A funded trade precommit is rejected
unless the operator explicitly enables execution and the current family report
passes every gate.

Additional controls include:

- report age limited to 12 hours, otherwise automatic re-lock;
- append-only operator kill switch;
- explicit operator approval ID;
- limit orders only;
- one position per independent event;
- mandatory correlation-group identity and exposure ceiling;
- checkpoint-tier position, daily exposure, and trailing-seven-day loss caps;
- genuine venue order ID required before a fill can be recorded;
- duplicate-fill and duplicate-settlement rejection;
- realized P&L calculated from recorded fills, fees, and official settlement.

| Passed checkpoint | Maximum position | Correlated exposure | Daily exposure | Trailing 7-day loss |
| ---: | ---: | ---: | ---: | ---: |
| 30 | $5 | $5 | $15 | $25 |
| 100 | $10 | $15 | $30 | $50 |
| 250 | $20 | $30 | $60 | $100 |
| 500 | $50 | $75 | $150 | $250 |

These values are hard ceilings. An operator or integrating agent can impose
smaller limits.

## Deterministic-Core Law

Every probability is produced by deterministic code operating on identified
data. A language model may classify a request or narrate a result, but it may
not create, alter, veto, or “sanity-check” a probability.

The project enforces these invariants:

- missing data remains missing, never zero;
- unsupported markets fail closed;
- model agreement is not presented as empirical calibration;
- each successful or refused decision is auditable;
- model changes receive a new version;
- earlier-version results cannot validate a later version;
- losses and non-actionable forecasts remain in the evidence record;
- evidence and decision ledgers are append-only and hash chained.

## Receipts and integrity

Receipts use canonical JSON and keccak256 in an append-only hash chain. Each
record commits its sequence, type, payload, creation time, previous hash, and
record hash. Verification detects deletion, mutation, insertion, or reordering.

Receipt lookup and verification are available through the API. X Layer anchor
verification additionally checks the inner ERC-4337 operation rather than
treating an outer bundler receipt as sufficient proof.

## Opportunity scanner

The scanner pulls broad live inventories from Kalshi, Polymarket, and
Limitless, evaluates supported markets, and publishes ranked JSON and Markdown
artifacts under `data/public/`.

Every included market receives an honest coverage state:

- `actionable`;
- `wait`;
- `model_missing`;
- `parse_missing`;
- `source_missing`;
- `fee_missing`.

Visibility is not presented as model support. Unsupported records remain in
coverage diagnostics so development priorities follow actual market supply.

## Local setup

Python 3.12 is used in production.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python -m unittest discover -q
```

Run the scanner and evidence loop:

```bash
PYTHONPATH=src python -m rwoo.scanner --write --top 30
PYTHONPATH=src python -m rwoo.evidence run
```

Run individual verification phases:

```bash
python3 verify.py --phase 0
python3 verify.py --phase 1
python3 verify.py --phase 2
python3 verify.py --phase 3
python3 verify.py --phase 4
python3 verify.py --phase 5
python3 verify.py --phase 6
python3 verify.py --phase 7
python3 verify.py --phase 8
python3 verify.py --phase 9
```

These phases exercise live sources where required and print explicit
acceptance results. Tests under `tests/` remain deterministic and network-free.

## Production architecture

```text
Venue readers ──> canonical market + exact resolution rule
                         │
Domain router ──> deterministic weather/commodity/economics/sports engine
                         │
                  probability + interval
                         │
Executable quote ──> spread + fee + net edge qualification
                         │
                   agent API response
                         │
             decision receipt + evidence precommit
                         │
Venue settlement + official outcome verification
                         │
Calibration + benchmark + drift + promotion report
                         │
                  execution interlock
```

Production uses hardened systemd services bound to localhost behind nginx:

- `rwoo-api.service` — FastAPI decision service;
- `rwoo-site.service` — public product site;
- `rwoo-scan.timer` — live market scan every 30 minutes;
- `rwoo-evidence.timer` — evidence and resolution cycle every six hours.

Public traffic is HTTPS-only. Application ports are not exposed publicly.

## Repository map

- `src/rwoo/readers/` — Kalshi, Polymarket, and Limitless readers.
- `src/rwoo/engines/weather.py` — weather ensemble and v3 recalibration.
- `src/rwoo/engines/economics.py` — official economic-data models.
- `src/rwoo/engines/sports.py` — sports ratings and simulations.
- `src/rwoo/parsers.py` — structured market-rule parsing.
- `src/rwoo/coverage.py` — coverage classification and refusal states.
- `src/rwoo/edge.py` — executable-price and trading-cost qualification.
- `src/rwoo/evidence.py` — precommitment, resolution, benchmarking, drift,
  calibration, and promotion.
- `src/rwoo/official_outcomes.py` — NOAA authoritative outcome checks.
- `src/rwoo/calibration.py` — Brier, reliability, and grouped walk-forward
  utilities.
- `src/rwoo/cross_venue.py` — exact-equivalence and complementary-edge checks.
- `src/rwoo/receipts.py` — canonical commitments and hash-chain verification.
- `src/rwoo/trades.py` — approval, limits, kill switch, fills, settlement, and
  realized P&L.
- `src/rwoo/api/` — public API, schemas, payment gate, and receipts.
- `src/rwoo/site/` — public web application.
- `deploy/systemd/` — production timer and service definitions.
- `docs/EVIDENCE_AND_EXECUTION.md` — evidence and funded-execution policy.
- `docs/VERIFICATION_LEDGER.md` — external assumptions and verification record.
- `verify.py` — phased live verification harness.

## Current operating state

- Public site and API are live.
- Weather v3 is producing forecasts and accumulating independently resolved
  evidence.
- Scanner and evidence timers are active.
- Public calibration and ledger verification are available.
- Funded execution inside this repository is locked until the model-specific
  gates pass and the operator explicitly enables it.
- External agents may call the API for real-money decision workflows now; they
  remain responsible for independent risk controls and all resulting orders.

## Important limitation

Probabilities are estimates, not promises. No model can guarantee a market
outcome or profit. Data errors, venue outages, liquidity, slippage, model
misspecification, correlated exposure, rule interpretation, settlement, and
custody can all produce losses. The purpose of this build is to make those
risks measurable, visible, and enforceable rather than hiding them behind a
confident number.

## License and attribution

Licensed under MIT. See `LICENSE` and `CREDITS.md` for source and dependency
attribution.
