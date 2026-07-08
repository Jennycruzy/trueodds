# Real-World Odds Oracle

**The calibration oracle for data-resolvable prediction markets — the true odds, proven.**

An OKX AI Agent Service Provider (ASP) that other agents pay to call before
betting a data-resolvable prediction market. Given a market, it:

1. **Reads the market** — extracts the implied probability (bid/ask midpoint,
   not last trade) and the *exact* resolution rule + settlement source + time.
2. **Computes the true probability** — independently, from multiple real-world
   data sources, with confidence derived from how much those sources agree.
3. **Computes the edge** — `oracle_prob − implied_prob`, qualified against its
   own uncertainty and the market's trading friction; refuses to call an edge
   that isn't beyond both.
4. **Attaches its calibration record** — a public, tamper-proof, append-only
   track record proving past probabilities came true at the stated rates.
5. **Returns a hash-committed receipt** — anchored on X Layer mainnet, so no
   one (including the builder) can rewrite history after the fact.

Flagship domain: **weather** (least-covered, most-differentiated). Volume
domains: **economics** and **sports**.

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
markets).

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
  forward-looking Cleveland Fed nowcasts plus SPF density data.
- **Sports** scores every real per-team market from two real, resolved
  tournaments (Euro 2024, Copa América 2024) using a self-computed Elo rating
  history replayed from 49,506 real historical matches, because no public API
  provides national-team ratings by arbitrary past date. The live sports
  engine now blends World Football Elo with the official FIFA/Coca-Cola Men's
  World Ranking and includes deterministic 48-team tournament simulators for
  both source families.
- **Opportunity scanning** pulls batches from live Kalshi and Polymarket
  markets, runs the supported deterministic engines, applies uncertainty and
  real trading-friction checks, ranks actionable candidates, and emits
  JSON/Markdown artifacts under `data/public/`.

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
PYTHONPATH=src python3 -m rwoo.scanner --write --top 20
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
  - `readers/kalshi.py`, `readers/polymarket.py` — Stage 1 market readers.
  - `weather_stations.py` — verified station registry (Kalshi series -> lat/lon).
  - `engines/weather.py` — Stage 2 weather engine: multi-model ensemble
    consensus + confidence, plus a NASA POWER historical base rate. No LLM
    anywhere in this path — verified by an AST import check in the harness.
  - `economic_sources.py` — official Cleveland Fed nowcast and Philadelphia
    Fed SPF probability-distribution readers.
  - `engines/economics.py` — official-history baseline plus official
    forward-looking Cleveland Fed/SPF inputs for core-CPI markets.
  - `engines/sports.py` — World Football Elo + official FIFA ranking baselines
    plus deterministic 48-team tournament simulators.
  - `edge.py` — Stage 3: edge = oracle_prob - implied_prob, qualified against
    the oracle's own uncertainty band, source freshness, source/model agreement,
    and real trading friction (Kalshi's published fee formula + the live
    spread). Refuses non-actionable edges.
  - `calibration.py` — Brier score, reliability buckets, and transparent
    recalibration utilities.
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
  - `xlayer.py` — X Layer RPC verification and on-chain anchor verification
    (decodes the ERC-4337 `UserOperationEvent` to confirm the inner call
    actually succeeded — an outer bundler-transaction receipt status alone is
    not sufficient proof, learned the hard way; see Ledger §16.1).
  - (OKX listing, funded trade/payment execution, public pages — later phases)
- `CREDITS.md` — attribution for third-party data sources and libraries.
- `LICENSE` — MIT.
