# Build Gaps And Sequencing

Last updated: 2026-07-09

This file records incomplete work that must not be forgotten between phases.
It is intentionally blunt: if a component is not complete, it stays listed
until a verification gate proves otherwise.

## Sequencing Decision

Phase 6, pre-listing hardening, and the live opportunity scanner are now
**complete**: economics produces a real forward-looking-source probability and
a real Brier score, sports includes multi-source deterministic tournament
simulators, primary-source checks are wired, the daily proof loop produces
receipt-backed artifacts, and Phase 8 scans live markets for cost-adjusted
opportunities. Limitless has been added to the scanner as a read-only venue,
with grouped markets flattened and unsupported weather/economics/sports shapes
included explicitly as non-actionable records. The scanner now also reads
broad active batches from Kalshi and paginated Polymarket batches instead of
only the original hand-picked weather/CPI/World Cup paths.
Only after these gates pass should OKX.AI listing/service registration/payment
work resume.

Recommended order (updated):

1. ~~Before Phase 6, clean up quick primary-source verification gaps~~ — done.
2. ~~Phase 6: receipts, append-only ledger, tamper evidence, X Layer anchoring~~ — done, including a corrected anchor after catching a false positive in the verifier (see docs/VERIFICATION_LEDGER.md §16.1).
3. ~~Pre-listing hardening: economics, sports, primary sources, daily proof loop~~ — done; `python3 verify.py --phase 7` passes.
4. ~~Live opportunity scanner: broad cost-aware scan across supported markets~~ — done; `python3 verify.py --phase 8` passes and `data/public/opportunity_scan_latest.*` is generated. Limitless is read-only in this scanner; no Limitless execution is wired.
5. OKX.AI ASP listing, service registration, Payment SDK, a real pay-per-call round trip.
6. Funded execution path: credentials, risk limits, dry-run/live switch, order placement, and post-trade receipts.
7. Public calibration page and distribution surfaces.

## Immediate Checklist

Do before starting Phase 6:

- [x] Try to verify Kalshi's primary fee schedule directly.
- [x] Try to verify the primary OKX AI Genesis hackathon rules, deadline, and
      Google submission form.
- [x] Update `docs/VERIFICATION_LEDGER.md` with either successful primary
      evidence or a precise blocked/not-found finding.

Do in Phase 6:

- [x] Add append-only local calibration/receipt ledger.
- [x] Add receipt hash generation for verdict/calibration records.
- [x] Add hash-chain or equivalent tamper detection.
- [x] Add a tamper test to the verification harness.
- [x] Verify X Layer RPC path.
- [x] Verify the OKX Agentic Wallet transaction-signing flow for anchoring a
      real commitment on X Layer mainnet.
- [x] Anchor a real commitment on X Layer mainnet and print the
      transaction/explorer evidence.
- [x] Switch the local hash algorithm to real keccak256 (was sha3_256 — a
      different algorithm despite the similar name).
- [x] Fix a genuine false positive in the anchor verifier: this Agentic
      Wallet is an ERC-4337 smart account, so an outer bundler-transaction
      receipt status of "0x1" does NOT prove our inner UserOperation
      executed — it can succeed at the outer level while the inner call
      reverts. `verify_anchor_transaction()` now decodes the EntryPoint's
      `UserOperationEvent` and requires `success == true` explicitly. This
      caught and invalidated the first anchor attempt, which had silently
      reverted. See docs/VERIFICATION_LEDGER.md §16.1 for the full account.

Phase 6 status: **complete.** `python3 verify.py --phase 6` passes every
check, including a real, correctly-verified X Layer mainnet anchor
transaction (0x655d283549f0e809985a7fa401b1a8a14b6ad1419e3ebd15dd57424950c53ef2).
`data/anchors/phase6_anchor.json` and `data/receipts/phase6_anchor.jsonl` are
now tracked in git so any future drift between the anchored hash and the
ledger's actual content is visible in a diff, not silent.

## Gaps Closed By Pre-Listing Hardening

### Production economics model and calibration

Current status: complete for pre-listing hardening.

What exists: the live core-CPI economics engine now combines official BLS
history with official forward-looking Cleveland Fed monthly CPI/core-CPI
nowcasts and Philadelphia Fed SPF PRCCPI probability distributions. The BLS
API is still tried first, but the official BLS flat-file mirror is now used as
a quota-free fallback, so a full economics calibration run is no longer allowed
to pass by claiming the unauthenticated BLS quota blocked it.

Backtest evidence: `python3 verify.py --phase 5` now builds 1,427 economics
calibration records: 27 real settled Kalshi CPI markets plus 1,400 official
SPF probability-bin records scored against realized BLS Q4/Q4 core CPI. It
prints an economics reliability curve and Brier score (`0.0550` in the latest
run) and demonstrates deterministic recalibration only after measuring
miscalibration.

Gate evidence: `python3 verify.py --phase 7` verifies the official Cleveland
Fed and Philadelphia Fed sources, proves the live engine includes those
forward-looking sources, and fails if economics does not produce real records
and a Brier score.

### Production sports model and calibration

Current status: complete for pre-listing hardening; still improvable later.

What exists: a conservative World Cup baseline using live World Football Elo
ratings plus the official FIFA/Coca-Cola Men's World Ranking. Each source
family feeds deterministic rank/rating transforms and a deterministic 48-team
tournament simulator. The calibration backtest remains real: Euro 2024 and
Copa America 2024 are scored using self-computed historical Elo ratings
replayed from real match history as of the market decision date.

Future improvement: add independent projection-market/bookmaker/projection
sources beyond ranking systems, injury/lineup adjustments, qualification/draw
state, and more resolved tournaments as reliable market history becomes
available.

### Primary Kalshi fee schedule PDF

Current status: complete for pre-listing hardening; one workspace fetch
constraint remains documented.

What exists: the official Kalshi Help Center fee article is reachable and
links the fee-schedule PDF. Browser retrieval of the PDF verified the primary
formula (`0.07 * C * P * (1-P)` for taker fees, with multiplier `M`); the
official Kalshi API independently exposes `fee_type: "quadratic"` and
`fee_multiplier: 1`. The pre-listing gate now checks the Help Center link,
the official API fields, and the direct PDF fetch outcome.

Known infrastructure constraint:

`https://kalshi.com/docs/kalshi-fee-schedule.pdf` still returns HTTP 429 from
this workspace even with browser-like headers. Gate 7 does not pretend the
workspace downloaded the PDF; it passes only if the official Help Center link,
API corroboration, and explicit PDF fetch status are all verified.

### Primary hackathon rules and submission form

Current status: complete.

The primary OKX Build X page and official Google Form are verified in
`docs/VERIFICATION_LEDGER.md`; `python3 verify.py --phase 7` checks the OKX
Build X primary page before listing work can proceed.

### OKX payment settlement token

Current status: unresolved.

What exists: conflicting sources mention USDT/USDG/USDC on X Layer.

Why incomplete: only a real Payment SDK funded call can settle the discrepancy.

Not covered by Phase 6 or pre-listing hardening; this belongs to the later
listing/payment phase.

Completion criteria:

- Run a real funded OKX payment flow.
- Record actual settlement token and rail.
- Update service pricing accordingly.

### Funded execution path

Current status: not built.

What exists: `src/rwoo/scanner.py` finds and ranks actionable cost-adjusted
candidates from broad live Kalshi/Polymarket markets and read-only Limitless
market data. It writes JSON/Markdown artifacts and Phase 8 proves the scanner
runs. `src/rwoo/coverage.py` assigns every included market a family, shape,
and coverage status (`actionable`, `wait`, `model_missing`, `parse_missing`,
`source_missing`, `fee_missing`, or `unsupported_domain`). Unsupported
weather/economics/sports shapes are included as non-actionable records instead
of disappearing into skip counts.

Why incomplete: no exchange credential flow, wallet approval flow, order
placement API, max-size/risk-limit policy, or post-trade receipt is wired.
Limitless specifically still needs exact fee calculation from its dynamic CLOB
fee rules/profile fields before any Limitless edge can be actionable. The
scanner says what the engine would trade; it does not spend funds.

Completion criteria:

- Add dry-run and live modes with explicit risk limits.
- Wire authenticated exchange/order APIs only after credentials are approved.
- Record every submitted order and fill as a receipt.
- Make live mode impossible without explicit operator configuration.

### Limitless venue expansion

Current status: read-only scanned venue.

What exists: `src/rwoo/readers/limitless.py` reads public active/search/detail
market data, flattens grouped markets, maps `tradePrices` to bid/ask-like
spread, records collateral/fee metadata in `raw`, and classifies Limitless
markets into weather/economics/sports/other. Phase 8 now checks that Limitless
was read live, grouped children were flattened, unsupported domain shapes were
included as non-actionable records, and no Limitless record is actionable
while the exact fee term is not computed.

Known support boundary:

- Weather remains the flagship domain, but the 2026-07-09 Limitless live scan
  did not expose a true parseable weather market. Limitless weather markets
  should be added before sports breadth whenever a market gives station/source,
  date, metric, strike, and settlement source clearly enough to feed
  `engines/weather.py`.
- Economics Limitless markets exist, including headline CPI, GDP, recession,
  and Fed-rate shapes. The current engine now prices US annual headline-CPI
  bins from official BLS all-items CPI-U history, but Limitless records remain
  non-actionable until exact Limitless fees are wired. Non-US CPI sources,
  monthly headline-CPI bins, GDP, Fed-rate, recession, and PPI markets still
  need matching engines/sources.
- Sports Limitless markets are broad. The current supported sports engine is
  2026 FIFA World Cup national-team outright winner only. NBA/NHL/EPL/tennis,
  esports, props, stages, exact matchups, and player-stat markets need their
  own deterministic source/model paths before they can be actionable, but they
  are still included in the scan inventory.

Completion criteria:

- Add a Limitless weather parser once a live Limitless weather market provides
  structured-enough settlement fields, and prove it with Phase 8 or a new gate.
- Add exact Limitless fee calculation from official fee/profile/order rules.
- Add new deterministic economics/sports engines before widening Limitless
  actionable support beyond US headline CPI and World Cup outright shapes.

### Broad venue coverage and engine expansion

Current status: inventory layer started; many engines still missing.

What exists: broad market ingestion is now the scanner's default direction.
Kalshi active markets are cursor-paginated, Polymarket Gamma markets are
offset-paginated, and Limitless active/search markets are flattened. Domain
markets are included with explicit family/shape/status metadata even when no
probability engine exists.

Known gap: broad inclusion is not the same as broad pricing. The next engine
work should be added family by family, with verification per family:

- Weather: parse any venue's location/date/metric/strike into the existing
  weather engine before widening sports. The structured parser layer exists
  for Kalshi high-temperature markets and recognizes low/rain/snow/wind as
  explicit missing metric families; fixing weather coverage remains the
  priority whenever a real non-Kalshi weather market is available.
- Economics: US annual headline CPI is now priced from BLS CPI-U history.
  Headline CPI monthly, non-US CPI, GDP, Fed-rate path/decision, recession,
  PPI, and labor markets each still need source-backed engines.
- Sports: tennis match/tournament, NBA/NHL futures, soccer club outrights,
  esports, World Cup stages/props, and player props each need their own source
  and model path.

Completion criteria:

- Add a Phase 9 coverage gate proving broad ingestion across all venues.
- Require every weather/economics/sports market to be included or produce a
  structured item-level error.
- Require every included domain market to carry family, shape, coverage status,
  and missing capability text when not priced.
- Add at least one new engine family per phase, starting with weather when a
  parseable market is present, then GDP/Fed.

### Public calibration page

Current status: daily proof loop built; full public calibration page still open.

What exists: `src/rwoo/daily.py` creates a real daily proof receipt, verifies
the ledger, and emits public JSON/Markdown artifacts generated from the same
committed record. Phase 7 fails if this loop cannot run.

Why still open: there is not yet a hosted public calibration page reading from
the same calibration store.

Not covered by Phase 6/7/8; covered later after the scanner/listing path.

Completion criteria:

- Build a live public page from the calibration store.
- Show Brier score, reliability curve, call log, misses, and receipt hashes.
- Prove the page updates from data, not hardcoded HTML.
