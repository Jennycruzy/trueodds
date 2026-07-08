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
project depends on, and how it was verified). Currently: **Phase 3 complete** (foundations, market readers, the weather engine, and the edge computation with its reproducibility proof).

## Reproduce every claim

Every number in this project traces to a real run. To check Phase 0's claims
yourself:

```bash
pip install -r requirements.txt
python3 verify.py --phase 0   # foundations: live Open-Meteo, Kalshi, Polymarket calls
python3 verify.py --phase 1   # market readers: canonical objects from live markets
python3 verify.py --phase 2   # weather engine: multi-model consensus + confidence
python3 verify.py --phase 3   # edge computation + a live reproducibility proof
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
  - `edge.py` — Stage 3: edge = oracle_prob - implied_prob, qualified against
    the oracle's own uncertainty band and real trading friction (Kalshi's
    published fee formula + the live spread). Refuses non-actionable edges.
  - (restraint layer, calibration record, receipts, econ/sports engines — later phases)
- `CREDITS.md` — attribution for third-party data sources and libraries.
- `LICENSE` — MIT.
