# Real-World Odds Oracle

**The calibration oracle for data-resolvable prediction markets — the true odds, proven.**

An OKX AI Agent Service Provider (ASP) that agents and individuals pay to call
before acting on a data-resolvable prediction market. The product is a paid
decision API, not a custodial trading bot. Given a market, it:

1. **Reads the market** — extracts the implied probability (bid/ask midpoint,
   not last trade) and the *exact* resolution rule + settlement source + time.
2. **Computes an independent probability** — deterministically from real-world
   sources, with an uncertainty interval, explicit model version, and a
   transparent explanation of source/model disagreement.
3. **Computes the edge** — `oracle_prob − implied_prob`, qualified against its
   own uncertainty and the market's trading friction; refuses to call an edge
   that isn't beyond both.
4. **Attaches its calibration record** — a public, tamper-proof, append-only
   track record proving past probabilities came true at the stated rates.
5. **Returns a hash-committed receipt** — anchored on X Layer mainnet, so no
   one (including the builder) can rewrite history after the fact.

No forecast is guaranteed to win. High confidence is earned through
precommitted, independently resolved calibration evidence; model agreement by
itself is not presented as proof of accuracy.

Flagship domain: **weather** (least-covered, most-differentiated). Volume
domains: **economics** and **sports**.

## Product surface

The listing leads with three paid services:

1. **`rwoo.check_market`** — probability, interval, model version, confidence,
   executable-price EV, explanation trace, and tamper-evident receipt.
2. **`rwoo.cross_venue_edge`** — compares candidate-equivalent contracts and
   refuses to call a price difference arbitrage unless resolution authority,
   time, event semantics, and YES orientation match.
3. **`rwoo.get_calibration`** — the public precommitted track record by domain,
   family, model version, probability band, and independent event count.

The same signed verdict can later feed an approval-gated execution adapter.
Execution is optional proof that the oracle is operationally useful: callers
never need to surrender custody, and funded execution remains disabled until
the relevant family passes fixed evidence gates.

## Live evidence and promotion policy

`rwoo.evidence` runs every six hours in production. It precommits every priced
forecast, resolves finalized Kalshi, Polymarket, and Limitless contracts,
checks supported US weather outcomes directly against NOAA NCEI station
observations, and publishes grouped calibration reports. Multiple strikes on
one event share one `event_group_id` and cannot inflate sample size.

Weather is reviewed only at 30, 100, 250, and 500 independently resolved
events. The first gate requires at least 30 groups, Brier score <=0.20, maximum
calibration gap <=0.15, NOAA concordance >=95%, and a separate correctness and
risk review. Economics and each sports family are promoted separately. See
`docs/EVIDENCE_AND_EXECUTION.md` for the operating policy.

For the exact checklist to follow after the callable ASP/frontend build returns,
see `docs/POST_ASP_HANDOFF.md`.

## The Deterministic-Core Law

Every probability this project emits is computed by deterministic code
operating on real data. A language model is used *only* to understand/route a
market question and to narrate results in prose — never to produce, adjust,
or "sanity-check" the probability number itself. This is proven, not claimed:
see Phase 3's Gate 3, which reproduces a probability with the LLM completely
disconnected from the call path.

## Status

This build is phased, with a human-readable verification gate at the end of
each phase (see `docs/VERIFICATION_LEDGER.md` for every external fact this
project depends on, and how it was verified). Currently: **live opportunity
scanner complete** on top of Phase 6/7 hardening (foundations, market readers,
the weather engine, edge computation with its reproducibility proof, the
restraint layer, economics/sports engines, no-lookahead calibration,
tamper-evident receipts with a real corrected X Layer mainnet anchor,
receipt-backed daily proof loop, and a ranked cost-aware scan across live
markets). The scanner now keeps a broad market inventory across venues and
records a coverage state for every included weather/economics/sports market:
`actionable`, `wait`, `model_missing`, `parse_missing`, `source_missing`, or
`fee_missing`.

The calibration backtest code keeps full/no-cap paths, but the human-readable
gate uses explicit runtime controls where live APIs are slow or quota-limited:
- **Weather** can run across all 5 verified stations against every real
  settled Kalshi market, bounded only by Open-Meteo's real archived-forecast
  window. `verify.py --phase 5` defaults to 5 real records per station
  (25 total) with progress output and a raw-response cache so the judge-facing
  gate does not look frozen. Set `RWOO_WEATHER_GATE_RECORDS_PER_SERIES=0` for
  the full no-cap run.
- **Economics** scores every real settled core-CPI market using the actual
  BLS release-date schedule (not calendar month), adds official Philadelphia
  Fed SPF probability distributions for historical calibration, and uses the
  official BLS flat-file mirror as a quota-free fallback when the BLS API is
  unavailable. The live economics engine now also consumes official
  forward-looking Cleveland Fed nowcasts plus SPF density data for core CPI,
  and official BLS all-items CPI-U annual history for US headline-CPI annual
  bins.
- **Sports** scores every real per-team market from two real, resolved
  tournaments (Euro 2024, Copa América 2024) using a self-computed Elo rating
  history replayed from 49,506 real historical matches, because no public API
  provides national-team ratings by arbitrary past date. The live sports
  engine now blends World Football Elo with the official FIFA/Coca-Cola Men's
  World Ranking and includes deterministic 48-team tournament simulators for
  both source families.
- **Opportunity scanning** pulls broad live batches from Kalshi, Polymarket,
  and Limitless, runs the supported deterministic engines, applies uncertainty
  and real trading-friction checks, ranks actionable candidates, and emits
  JSON/Markdown artifacts under `data/public/`. Weather/economics/sports
  markets without a matching engine are still included as explicit
  non-actionable records with family/shape/status fields. Unrelated
  `other`/price-oracle noise remains skipped. Limitless taker fees are charged
  as the conservative upper bound of the venue's official published buy-fee
  table (an upper bound can only under-call an edge, never over-call it), so a
  Limitless edge can qualify as actionable; the exact per-order fee is only
  returned per executed order and is reconciled at execution time, not in the
  scanner.

## Reproduce every claim

Every number in this project traces to a real run. To check Phase 0's claims
yourself:

```bash
pip install -r requirements.txt
python3 verify.py --phase 0   # foundations: live Open-Meteo, Kalshi, Polymarket calls
python3 verify.py --phase 1   # market readers: canonical objects from live markets
python3 verify.py --phase 2   # weather engine: multi-model consensus + confidence
python3 verify.py --phase 3   # edge computation + a live reproducibility proof
python3 verify.py --phase 4   # restraint layer + live BLS economics and Elo sports baselines
python3 verify.py --phase 5   # calibration backtest: weather/economics/sports scored
python3 verify.py --phase 6   # receipts, tamper test, real X Layer mainnet anchor
python3 verify.py --phase 7   # pre-listing hardening: economics/sports/primary-source/daily-loop gate
python3 verify.py --phase 8   # live opportunity scanner: broad, cost-aware batch scan
python3 verify.py --phase 9   # broad family coverage + honest refusal paths
PYTHONPATH=src python3 -m rwoo.scanner --write --top 20
PYTHONPATH=src python3 -m rwoo.evidence run
```

Both make live network calls and print the real responses plus a
plain-English PASS/FAIL for each acceptance criterion — nothing is a fixture
or a canned pass.

## Repo layout

- `verify.py` — the verification harness; one gate per build phase.
- `docs/VERIFICATION_LEDGER.md` — every external fact (API shapes, OKX
  integration mechanics, chain facts) verified live, with evidence and dates.
- `src/rwoo/` — the engine, built out phase by phase:
  - `models.py` — the canonical market object.
  - `domain.py` — deterministic weather/economics/sports/other routing.
  - `parsers.py` — venue-agnostic structured parsers that convert included
    markets into engine inputs, with explicit missing reasons when a source,
    parser, or model is not yet wired.
  - `coverage.py` — deterministic family/shape/status coverage registry for
    included markets.
  - `readers/kalshi.py`, `readers/polymarket.py`, `readers/limitless.py` —
    Stage 1 market readers. Limitless flattens grouped markets but remains
    read-only.
  - `weather_stations.py` — verified station registry (Kalshi series -> lat/lon).
  - `engines/weather.py` — Stage 2 weather engine: multi-model ensemble
    consensus + confidence, plus a NASA POWER historical base rate. No LLM
    anywhere in this path — verified by an AST import check in the harness.
  - `economic_sources.py` — official Cleveland Fed nowcast and Philadelphia
    Fed SPF probability-distribution readers.
  - `engines/economics.py` — official-history baseline plus official
    forward-looking Cleveland Fed/SPF inputs for core-CPI markets, and BLS
    CPI-U paths for US headline-CPI (monthly + annual) bins. Also prices
    quarterly/annual GDP (Atlanta Fed GDPNow / Philadelphia Fed SPF),
    unemployment (U-3) and payrolls (FRED), Fed target range (only when no
    scheduled FOMC meeting remains before the target, else refuses), and
    single-quarter real-GDP-decline recession markets (SPF RECESS anxious
    index). NBER-style recession, non-US CPI, and PPI stay source_missing.
  - `engines/sports.py` — World Football Elo + official FIFA ranking baselines
    plus deterministic 48-team tournament simulators.
  - `edge.py` — Stage 3: edge = oracle_prob - implied_prob, qualified against
    the oracle's own uncertainty band, source freshness, source/model agreement,
    and real trading friction (Kalshi's published fee formula + the live
    spread). Limitless friction uses the live spread plus the conservative
    upper bound of Limitless's official published taker buy-fee table, so a
    Limitless edge is quantified and can be actionable; the exact per-order fee
    is an execution-time reconciliation. Refuses non-actionable edges.
  - `calibration.py` — Brier score, reliability buckets, and transparent
    recalibration utilities with domain/band breakdowns and sample counts.
  - `identity.py` — stable independent-event grouping and model versions.
  - `explanations.py` — deterministic why traces exposing model disagreement.
  - `cross_venue.py` — fail-closed contract-equivalence and executable edge analysis.
  - `evidence.py` — append-only precommitment, multi-venue resolution,
    calibration reports, and fixed promotion checkpoints.
  - `official_outcomes.py` — direct authoritative-source concordance checks,
    beginning with NOAA NCEI high/low observations.
  - `trades.py` — approval/fill/settlement/P&L receipts; it does not hold keys
    or submit orders.
  - `backtests/weather.py` — no-cap weather calibration backtest across all
    verified stations, using finalized Kalshi markets plus Open-Meteo Single
    Runs forecasts available before market open.
  - `backtests/economics.py` — no-cap core-CPI calibration backtest using the
    real BLS release-date schedule for a genuine no-lookahead cutoff.
  - `backtests/sports_elo.py` — self-computed historical Elo ratings replayed
    from a real 49,506-match public dataset (no public API gives national-team
    Elo by arbitrary past date).
  - `backtests/sports.py` — sports calibration backtest scoring real resolved
    Polymarket tournament markets against as-of-date self-computed ratings.
  - `receipts.py` — canonical JSON, real keccak256 commitments, and an
    append-only hash-chained ledger with a tamper test.
  - `daily.py` — receipt-backed daily proof loop and public JSON/Markdown
    artifact generation.
  - `scanner.py` — live opportunity scanner that ranks cost-adjusted
    actionable candidates and writes `data/public/opportunity_scan_latest.*`.
    It now reports venue/domain/family/status counts, included unsupported
    domain records, and skip reasons so market visibility does not masquerade
    as trade support.
  - `xlayer.py` — X Layer RPC verification and on-chain anchor verification
    (decodes the ERC-4337 `UserOperationEvent` to confirm the inner call
    actually succeeded — an outer bundler-transaction receipt status alone is
    not sufficient proof, learned the hard way; see Ledger §16.1).
  - (OKX listing, authenticated execution adapter, public UI — gated later work)
- `CREDITS.md` — attribution for third-party data sources and libraries.
- `LICENSE` — MIT.
