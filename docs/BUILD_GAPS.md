# Build Gaps And Sequencing

Last updated: 2026-07-12 (seventh session: SSH key-only access enabled and the
legacy public artifact server retired safely; sixth session: DOMAIN LIVE — trueodd.xyz purchased,
DNS set, and the ASP API + public site deployed to production over HTTPS with
Let's Encrypt certs on the shared VPS; fifth session: callable ASP HTTP API,
OKX Agent Payments x402 402 flow, and the public web frontend built + tested +
staged on the VPS; fourth session: recession-quarter routing wired + tested;
third session: parser tests, Phase 9 coverage gate, tennis/NBA sources,
head-to-head YES-side binding)

## 2026-07-11 Session — Production deployment on trueodd.xyz (LIVE, RESUME HERE)

The service is deployed and reachable over public HTTPS. Domain, DNS, systemd
services, nginx vhosts, and Let's Encrypt certs are all in place; 145 tests pass
on the box. Payments remain off (free mode). Remaining work is optional
hardening/product, not launch-blocking.

### Live production facts

- **Domain**: `trueodd.xyz` (Namecheap, BasicDNS). DNS: `A @` and `A api` ->
  `38.49.216.59`, `CNAME www -> trueodd.xyz`. Propagated and verified on public
  resolvers.
- **Site**: https://trueodd.xyz (+ www) — `rwoo.site.app:app`.
- **API**: https://api.trueodd.xyz — `rwoo.api.app:app`; `/docs`,
  `/openapi.json`, `/v1/service-metadata`, health/readiness all 200 externally.
  HTTP->HTTPS redirect enabled.
- **Certs**: separate Let's Encrypt certs for `trueodd.xyz`+`www` and
  `api.trueodd.xyz` (expire 2026-10-09); certbot auto-renew timer active;
  targeted `--dry-run` per cert passes.
- **Runtime**: two hardened systemd units (`User=rwoo`, localhost-bound behind
  nginx, auto-restart, ProtectSystem=strict):
  - `rwoo-api.service` -> `uvicorn rwoo.api.app:app` on `127.0.0.1:8090`
  - `rwoo-site.service` -> `uvicorn rwoo.site.app:app` on `127.0.0.1:8091`
- **Config**: `/etc/rwoo/rwoo.env` (root:root 0640, read by systemd). trueodd
  URLs; `RWOO_SUPPORT_EMAIL=jennyoliver630@gmail.com`;
  `RWOO_LEGAL_ENTITY=Jennycruzy`; artifact reads point at the live scan/evidence
  output in `/opt/rwoo/current/data`; decision receipts written to
  `/opt/rwoo/staging/data/receipts/decision_receipts.jsonl`. Payments OFF.
- **Code**: `/opt/rwoo/staging` fast-forwarded to `f3bb14a` (has site + api);
  its own venv has fastapi/uvicorn/jinja2/pycryptodome/httpx; 145 tests pass on
  the box.
- **nginx**: added only `trueodd` (site) and `trueodd-api` (API) vhosts —
  explicit `server_name`, no `default_server`, `underscores_in_headers on` and
  no caching on the API path to preserve x402/idempotency/request-id headers.
  The 9 other tenants were not modified and were re-verified healthy.
- **Not implemented**: no A2A (Agent2Agent) daemon or agent card — the surface
  is REST + x402 only (`/.well-known/agent.json` is 404 by design). Machine
  discovery is the REST `/v1/service-metadata` catalog.

### 2026-07-12 operational hardening completed

- Installed and verified a dedicated Ed25519 key for root administration.
- Root SSH remains allowed by public key only; password and
  keyboard-interactive SSH authentication are disabled. The root account
  password itself was not changed.
- Retired `rwoo-artifacts.service`: disabled and stopped after confirming that
  nginx, the API, site, scan timer, and evidence timer had no dependency on it.
- Removed the public `8088/tcp` UFW allowances for both IPv4 and IPv6. Ports
  8090 and 8091 remain localhost-only, and public site/API HTTPS health checks
  passed after the change.

### Remaining (optional / non-launch-blocking)

1. **Payments go-live**: still needs OKX network+asset+decimals, pay-to
   recipient, per-service prices, facilitator URL + verify schema. Until then
   the two paid services (`check-market`, `cross-venue-edge`) answer free; the
   `calibration` service is free by design (public track record).
2. **Support email** is a personal Gmail; swap for a dedicated address if wanted.
3. **A2A layer** if agent-ecosystem discovery is required (agent card +
   JSON-RPC adapter over the existing three services).
4. **OKX.AI listing package** can now be assembled from the live URLs. This is
   the immediate non-payment product step.

### Shared-box note (do NOT touch)

`concrete-academy` (upstream `:3003`) and `kairos-engine` (upstream `:3002`)
were already returning 502 before this session — their own backends are down,
unrelated to rwoo, and were left alone. No changes to the other tenants' nginx,
certs, ufw, docker, postgres, ollama, or pm2.

---

## 2026-07-10 Session — ASP API, payment flow, and public frontend (DEPLOYED 2026-07-11)

The software half of the ASP/listing program was built, tested, and staged this
session; it was **deployed to production on trueodd.xyz on 2026-07-11** (see the
LIVE section above). The build details below remain accurate.

### Done this session (145 tests pass: 94 existing + 23 API + 17 payment + 11 site)

- **Paid HTTP API** — `rwoo.api.app:app` (FastAPI). Three services:
  `POST /v1/check-market`, `POST /v1/cross-venue-edge`,
  `GET /v1/calibration[/{family}[/{model_version}]]`. Supporting endpoints:
  `/healthz`, `/readyz`, `/version`, `/v1/service-metadata`,
  `/v1/supported-markets`, `/v1/evidence/status`,
  `/v1/receipts/{hash}[/verify]`, `/openapi.json`, `/docs`, `/redoc`.
  Strict request schemas, stable error taxonomy, request-id propagation,
  body-size cap, restricted CORS + trusted hosts, security headers, no-store on
  results, no stack traces. Every probability still comes from
  `scanner.evaluate_market`; unsupported/unbindable markets fail closed with a
  stable refusal (never a silent zero). Decision receipts commit to an
  append-only keccak256-chained ledger; in-process idempotency. Single-market
  fetch-by-id helpers added to each reader (`fetch_canonical_market`).
- **Payment (OKX Agent Payments / x402)** — `rwoo.api.payment`. Unpaid protected
  request → 402 challenge (`x402Version` + `accepts`, `WWW-Authenticate:
  Payment`); identical body + `X-PAYMENT` → server-side verify → 200 with
  `PAYMENT-RESPONSE` and the payment reference linked into the receipt. Binds
  payment to service, request hash, amount, recipient, asset, network, expiry;
  rejects wrong-chain/token/recipient, insufficient, expired, replayed,
  malformed, and any secret key material. Prices/asset/network/recipient come
  ONLY from env; cryptographic settlement is delegated to an injected verifier
  (`FacilitatorVerifier` is structural, not exercised). Dev `StubVerifier`
  cannot run in production; an enabled-but-incomplete config fails closed at
  boot. **Disabled by default (free mode).**
- **Public frontend** — `rwoo.site.app:app` (separate FastAPI app, Jinja2). All
  10 pages (`/`, `/docs`, `/playground`, `/calibration`, `/markets`,
  `/receipts`, `/methodology`, `/status`, `/privacy`, `/terms`) + robots,
  sitemap, favicon. Every metric read live from the published artifacts and the
  receipt ledger; honest empty states; real (not hardcoded) live example
  verdict. Validated accessible palette, light/dark, reduced-motion, keyboard
  access. privacy/terms show operator-identity-pending until `RWOO_LEGAL_ENTITY`
  is set.
- **VPS staging (isolated)** — cloned to `/opt/rwoo/staging` as the `rwoo` user
  with its own venv; 145 tests pass on the box; API booted on `127.0.0.1:8090`
  only and shut down. The old artifact server (`rwoo-artifacts.service` on
  `:8088`) and all other tenants on the shared box were left untouched. Nothing
  is publicly exposed yet.

### Blocked — operator inputs still needed (do not guess) — RESOLVED 2026-07-11

(Historical. 1 domain -> trueodd.xyz; 2 support email -> jennyoliver630@gmail.com;
3 legal entity -> Jennycruzy; 4 payments still deferred (off); 5 root-password
rotation still outstanding.)

1. **Dedicated domain** (leaning `.xyz` or `.ai`) + DNS access. DNS: `A @` and
   `A api` → `38.49.216.59`, `CNAME www`.
2. **Support email** → `RWOO_SUPPORT_EMAIL`.
3. **Legal entity** for privacy/terms → `RWOO_LEGAL_ENTITY`.
4. **Payment go-live only:** approved network + asset + decimals, pay-to
   recipient/wallet, per-service prices, facilitator URL, and confirmation of
   the exact OKX facilitator verify/settle schema. Until then payments stay off.
5. **Security:** rotate the VPS root password (was shared in chat); prefer SSH
   keys.

### Next steps when the domain lands (deploy sequence) — EXECUTED 2026-07-11

(Historical record of the plan that was carried out. Steps 1-7 done; step 8
listing package is now assemblable. Deviations: apps run directly from
`/opt/rwoo/staging` with its own venv via new `rwoo-api`/`rwoo-site` units rather
than an atomic `staging -> current` promotion, so the live scan/evidence loop in
`current` was left untouched; the site reads live artifacts from
`/opt/rwoo/current/data` via absolute env paths. certbot used the `--nginx`
plugin, not webroot.)

1. Get domain + support email + Cloudflare yes/no (recommend BasicDNS first).
2. Set env for both apps: `RWOO_PUBLIC_BASE_URL=https://<domain>`,
   `RWOO_API_BASE_URL=https://api.<domain>`, `RWOO_DOCS_URL`,
   `RWOO_CALIBRATION_URL`, `RWOO_RECEIPTS_URL`, `RWOO_SUPPORT_EMAIL`,
   `RWOO_LEGAL_ENTITY`, `RWOO_ALLOWED_ORIGINS=https://<domain>`,
   `RWOO_TRUSTED_HOSTS=<domain>,api.<domain>`.
3. Two hardened systemd units (least-privilege, `rwoo` user, localhost bind):
   `uvicorn rwoo.api.app:app` (API) and `uvicorn rwoo.site.app:app` (site).
4. Isolated nginx vhosts: `<domain>` → site, `api.<domain>` → API. Preserve
   body, payment, request-id, idempotency headers; never cache paid responses or
   402 challenges; expose `/docs` + `/openapi.json`; no admin routes. Do not
   touch the other tenants' vhosts.
5. certbot: separate certs for root and `api.`; HTTP→HTTPS redirect; renewal
   dry-run must pass. Do not modify unrelated certs.
6. Promote `/opt/rwoo/staging` → `current` atomically with a timestamped
   rollback; keep `:8088` until the new stack is proven, then retire it.
7. External acceptance: root HTTPS, API metadata, health/readiness, OpenAPI/docs,
   correct unpaid 402 (once payments enabled), header preservation, closed
   internal ports (do not open 8090/8000 in ufw — nginx proxies from localhost),
   renewal dry-run, unrelated services healthy, mobile pages.
8. OKX.AI listing package: website, API base, docs, calibration, receipts,
   status, support URLs — copy-ready only after external tests pass.

### Do NOT in deployment

No funded execution. No exposing the API/site on the raw IP or a non-dedicated
domain. No changes to the other ~10 tenants on the shared VPS (nginx, certs,
ufw, docker, postgres, ollama, pm2). No enabling payments without every value in
item 4 above.



## 2026-07-10 Production evidence and oracle-product hardening

Completed:

- Unknown World Cup entities/regions fail closed instead of becoming false zeroes.
- Cross-venue comparison is first-class and requires proven contract equivalence.
- Priced verdicts include executable EV and deterministic why traces.
- Calibration splits by domain/probability band with visible sample counts.
- Stable event grouping, model versions, append-only precommitments,
  Kalshi/Polymarket/Limitless resolution, and NOAA high/low concordance run
  continuously every six hours.
- Reviews are fixed at 30/100/250/500 events. Weather's first gate requires
  Brier <=0.20, gap <=0.15, NOAA concordance >=95%, and safety review.
- Real-trade lifecycle receipts exist, but order submission remains disabled.
  The paid oracle is the product; execution is an optional gated consumer.
- Local and production suites contain 94 passing tests.

Immediate remaining work:

1. Accumulate evidence to the 30-event weather checkpoint.
2. Review results without moving the checkpoint.
3. Complete the hosted calibration UI and OKX ASP callable surface.
4. Submit the read-only paid oracle for OKX review without waiting for trading.
5. Only after a pass, add a disabled authenticated Kalshi adapter and approve
   micro-stake limits explicitly.

Operational handoff: `docs/POST_ASP_HANDOFF.md` separates the immediate ASP
launch/listing path from the time-dependent evidence path and is the starting
checklist when the callable API/frontend implementation returns.

## 2026-07-10 Session — tests, Phase 9 gate, tennis/NBA, YES-binding

Done this session (each verified live before commit):

- Parser unit tests (closes Remaining item 1): the first tests in the repo —
  stdlib `unittest`, run with `PYTHONPATH=src python3 -m unittest discover`.
  73 offline tests (as of the fourth session; +5 for recession routing)
  pin the family/shape/status contract of `parsers.py` across economics
  (Kalshi KXCPIYOY/KXECONSTATCPI/KXGDP/KXU3/KXPAYROLLS/KXFED and Limitless
  free-text CPI/GDP/Fed), World Cup stage titles, weather series/station
  routing, tennis head-to-head, coverage classifications, and the Elo /
  name-matching helpers. No network in the tests.
- Phase 9 coverage gate in `verify.py` (closes Remaining item 2): proves broad
  live ingestion across >=2 venues with per-record family/shape/status; prices
  at least one real record per newer engine family (weather low, monthly CPI,
  GDP, U-3, payrolls, World Cup stage, tennis) through the full
  `evaluate_market` path from live sources; and asserts honest restraint (a
  far-dated Fed market spanning a scheduled FOMC meeting is refused, the NBA
  champion outright stays model_missing, NBA head-to-head prices but stays
  below the actionable floor). `python3 verify.py --phase 9` passes.
- Tennis wired (was source_missing): `readers/tennis_uts.py` reads the Ultimate
  Tennis Statistics ELO_RANK table (HTTP 200, no key, verified live
  2026-07-10) — official ATP is 403 (Cloudflare) and the Sackmann CSV mirror
  404s from this workspace, so neither is usable here.
  `engines/sports.compute_tennis_match_probability` prices head-to-head via the
  existing Elo win expectation (single-source, confidence scales with
  rating-gap decisiveness, capped 0.68). Parser + scanner route tennis "A vs B"
  / "Will A beat B?" markets. Coverage: tennis head-to-head -> engine_available;
  tennis outright -> model_missing (source reachable, draw/bracket simulation
  not wired).
- NBA wired as priced-but-deferred (was source_missing): `readers/nba_espn.py`
  reads ESPN standings (HTTP 200, no key, verified 2026-07-10; merges both
  conference groups to 30 teams) — stats.nba.com times out and balldontlie is
  now key-gated. `engines/sports.compute_nba_match_probability` prices from
  season point differential (normal game-margin model, SD 12) with confidence
  HARD-CAPPED at 0.50, deliberately below the 0.55 actionable floor: NBA prices
  as information but never stakes on a single signal (refuses if a side has <10
  games). Coverage: NBA champion -> model_missing (ESPN reachable, champion
  simulation not wired).
- Head-to-head YES-side binding (hardening): added
  `CanonicalMarket.yes_subtitle`, populated by all three readers (Kalshi
  `yes_sub_title`, Polymarket `groupItemTitle`/`outcomes[0]`, Limitless
  flattened child `title`). The tennis parser no longer assumes the first-named
  player is YES; it binds YES to a specific player from `yes_subtitle` or the
  resolution rule, and returns parse_missing (non-actionable) when it cannot
  bind exactly one — so an inverted edge can never enter the actionable set.
  Proven end-to-end: the same matchup with YES bound to each side gives
  complementary probabilities. The `yes_subtitle` field now exists for any
  future head-to-head (NBA match, soccer).

## 2026-07-09 Engine-Breadth Session — done vs. remaining

Done this session (each verified live before commit):

- Weather: 40 Kalshi series (20 stations, daily high AND low) verified via
  live settlement-source `issuedby` codes + NOAA GHCND registry coordinates;
  engine now supports temperature_2m_min, precipitation_sum, snowfall_sum
  metrics (precip/snow have a documented 0.65 confidence cap; no live
  daily rain/snow markets existed to exercise them).
- Limitless fees: official published taker buy-fee table wired as a
  conservative upper bound in `edge.py`; priced Limitless records moved from
  `fee_missing` to `wait`/actionable-eligible. Phase 8 gate updated to assert
  the fee is QUANTIFIED (not the old fee-gap assertion).
- Economics engines added (`engines/economics.py`, sources in
  `economic_sources.py`): monthly headline CPI (BLS SA + Cleveland Fed MoM
  nowcast), annual headline CPI upgraded with Cleveland Fed YoY nowcast
  (history-only pricing had pointed the OPPOSITE way from the official
  nowcast on live June-2026 markets), quarterly GDP (Atlanta Fed GDPNow
  workbook; dollar-level rows filtered from the growth path), U-3 (FRED
  UNRATE empirical change distribution + SPF PRUNEMP annual density),
  payrolls (FRED PAYEMS, pandemic window excluded, history-only cap 0.50),
  Fed rates (FRED DFEDTARU + FOMC calendar; prices ONLY when no scheduled
  meeting remains before target, refuses otherwise — no futures source),
  recession-quarter (SPF RECESS anxious index; engine exists but is NOT yet
  routed by the scanner — no live market with a decline-in-quarter rule).
  SPF PRGDP/PRUNEMP bins quoted verbatim from the official documentation PDF
  (2024:Q2-era only).
- Sports: World Cup pricing now conditions on LIVE official FIFA bracket
  state (competition 17 / season 285023, verified live mid-tournament).
  Exact enumeration of the remaining bracket with live Elo; eliminated teams
  get deterministic 0/1. Stage-of-elimination engine + parsers for Kalshi
  KXWCSTAGEOFELIM and Limitless stage groups. This FIXED a real defect: the
  rankings-only model had called an actionable edge against France while
  France was alive in the semifinal bracket.
- Sports source assessment (recorded in coverage reasons): ATP 403,
  Sackmann CSV 404, stats.nba.com timeout -> tennis/NBA are source_missing;
  official NHL API verified reachable but offseason futures engine deferred
  (cannot honestly clear the 0.55 confidence floor).
- Ingestion: Kalshi reader has 429 backoff + throttled batch sweeps; every
  wired series family is swept completely; defaults raised (Kalshi census
  2000, Polymarket 2000, Limitless 1000). Full Kalshi universe measured at
  >600k open markets dominated by parlay/multigame series — full per-market
  enumeration is deliberately bounded, disclosed in the scan artifact's
  `ingestion_boundary` field.

Remaining (next session, in this order):

1. ~~Unit tests for `parsers.py` shapes~~ — DONE 2026-07-10: stdlib unittest
   tests (`PYTHONPATH=src python3 -m unittest discover`); see this session's
   notes.
2. ~~Phase 9 coverage gate in `verify.py`~~ — DONE 2026-07-10:
   `python3 verify.py --phase 9` passes. (Its tennis/NBA checks now assert the
   priced/deferred states, not the retired `source_missing` verdict.)
3. ~~Regenerate `data/public/opportunity_scan_latest.*` with a full scan and
   compare it with the 2026-07-09 morning artifact~~ — DONE 2026-07-10 in
   `9fac416`. The broader scan saw 5,495 markets vs. 2,163 and included 1,334
   vs. 915. `model_missing` fell 298 -> 249. Absolute `parse_missing` rose
   328 -> 365 because the wider Kalshi census explicitly included 39 more
   unsupported multigame/parlay records, but its share of included markets
   improved from 35.8% -> 27.4%; Limitless unknown-sports parse misses also
   fell 317 -> 308. This is broader honest inventory, not a parser regression.
4. ~~Update `docs/VERIFICATION_LEDGER.md` with this session's verified
   sources~~ — DONE 2026-07-10: ledger §23 records the 2026-07-09
   engine-breadth sources (NWS issuedby codes + NOAA GHCND registry, Cleveland
   MoM/YoY nowcast tables, SPF PRCCPI/PRGDP/PRUNEMP/RECESS sheets + doc-PDF
   bins, FRED DFEDTARU/UNRATE/PAYEMS CSVs, FOMC calendar, GDPNow
   TrackingHistory sheet, FIFA calendar/matches season 285023); §22 records the
   2026-07-10 tennis/NBA sources. (Limitless fee table is already in §21.)
5. ~~Re-run `python3 verify.py --phase 5/7/8` end to end~~ — DONE 2026-07-10:
   all three PASS. No regression from the yes_subtitle/tennis/NBA changes; two
   stale gate assertions were corrected for behavior the live state now
   exercises: phase 7's sports check accepts the in-tournament exact-bracket
   path (the WC is mid-knockout, so the engine conditions on real results
   instead of the pre-tournament simulator ensemble), and phase 8 requires
   real friction only on PRICED records (an honestly-refused GDP-Q3/Fed market
   has oracle_prob None and no friction, which is correct, not a cost gap).
6. ~~Economics backtests for the new families~~ — DONE 2026-07-10 for the
   defensible available evidence:
   annual GDP SPF calibration and explicitly history-only headline CPI
   monthly/annual baselines are wired, with per-record timestamp checks in
   Phase 5. These CPI baselines do NOT validate the Cleveland Fed forward
   source or justify raising its confidence cap; Cleveland states that a long
   real-time history of this particular nowcast series is unavailable. The
   official GDPNow workbook does provide `TrackingDeepArchives`,
   `TrackingArchives`, and `TrackRecord`; both shapes are parsed and TrackRecord
   forecasts are scored against BEA advance estimates. Cleveland remains
   source-blocked. Grouped walk-forward evaluation keeps correlated thresholds
   together: GDPNow has 237 test groups, Brier 0.0721 and max reliability gap
   0.0893, supporting a measured cap increase 0.65 -> 0.70. CPI caps remain
   unchanged (history-only recalibration worsened and does not test Cleveland);
   annual GDP SPF remains unchanged with only two walk-forward test groups.
7. PPI engine: no open PPI markets existed on 2026-07-09 (KXUSPPI empty);
   add the BLS `wp` flat-file/API reader when live markets return.
8. ~~Recession routing~~ — DONE 2026-07-10: `parse_economics_market` now
   classifies recession-shaped economics markets. A single-quarter real-GDP
   decline test with an explicit quarter (`economics.recession` /
   `quarterly_decline`) routes to `compute_recession_quarter_probability` and
   prices from the SPF RECESS anxious index (verified live end-to-end: Q4 2026
   -> 0.245, Q1 2027 -> 0.257, confidence 0.60). NBER-style declarations,
   multi-quarter ("two consecutive quarters") and year-level rules classify as
   `nber_declaration` / `source_missing` and stay non-actionable — so the live
   Polymarket 2026-recession market never enters the actionable set. Five
   offline tests in `tests/test_parsers_economics.py` pin both paths. STILL
   PENDING: a real live single-quarter-decline market to exercise the priced
   path against an actual venue (none existed on 2026-07-10).
9. Limitless daily weather markets: no qualifying live market existed on
   2026-07-09. DONE for the parser/engine boundary: Limitless and other venues
   can supply normalized metric/coordinates/timezone/date/strike/location and
   a recognized NOAA/NWS/Open-Meteo settlement authority; incomplete prose
   still fails closed. A real Limitless settlement test remains pending until
   such a market actually appears.
10. Non-US CPI (China/Korea/etc.): official sources (NBS/KOSIS) not wired;
    stays source_missing.
11. Sports beyond the World Cup:
    - Tennis — DONE 2026-07-10 (head-to-head): UTS Elo wired; "A vs B" /
      "Will A beat B?" markets price via the Elo win expectation with
      fail-closed YES-side binding. STILL OPEN: tennis tournament-winner
      outrights need a draw/bracket simulation (source reachable, sim not
      wired -> model_missing).
    - NBA — DONE 2026-07-10 (priced-but-deferred, head-to-head): ESPN
      standings wired; point-differential match engine prices but is capped
      below the actionable floor. STILL OPEN: NBA champion outright needs a
      season/playoff simulation (source reachable, sim not wired ->
      model_missing).
    - ClubElo — DONE for club-soccer head-to-head: dated CSV reader, exact team
      matching, fail-closed YES binding, and Elo probability are wired. It is
      capped below actionable because draw/home-field effects are not modeled;
      outrights remain model_missing. After an initial 2026-07-10 timeout, the
      hardened protocol/date fallback returned 592 current-day clubs in 4.27s
      and persisted the verified snapshot; outages still fail closed.
    - MLB StatsAPI — DONE for head-to-head: 1,420 completed 2026 regular-season
      games/30 teams verified live; current-season Elo replay, parser, scanner
      route, and fail-closed YES binding are wired. Pitcher/lineup/park effects
      and futures remain outside the supported shape.
    Still blocked/deferred and why: NHL (official API reachable but offseason —
    engine cannot honestly clear the confidence floor until real 2026-27
    results exist), esports (no free verified source). Player props and the
    ~600k Kalshi parlay/multigame markets need player-level sources and
    correlated-leg models — a separate, much deeper tier of work.

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

Backtest evidence: the focused live economics build now produces 4,620
records: the existing 27 settled Kalshi core-CPI markets and 1,400 SPF
core-CPI bins, plus 110 SPF annual-GDP bins, 1,123 explicitly history-only
headline-CPI baselines, and 1,960 archived GDPNow threshold records. Every
record passes the per-record source <= decision < resolution timestamp check.
Phase 5 prints the combined reliability curve and Brier score and demonstrates
deterministic recalibration only after measuring miscalibration.

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
placement API, max-size/risk-limit policy, or post-trade receipt is wired. The
scanner says what the engine would trade; it does not spend funds.

Note on Limitless fees (corrected 2026-07-10): the scanner does NOT need the
exact per-order fee to qualify a Limitless edge. `edge.py` already charges the
conservative UPPER BOUND of Limitless's published taker buy-fee table with
`missing_fee=False`, an upper bound can only under-call an edge (never over-call
it), and Phase 8 asserts every priced Limitless record carries that quantified
fee. Verified 2026-07-10 that a Limitless market with a clear edge returns
`actionable=True` with a real fee term. The EXACT `effectiveFeeBps` is not
exposed by any public read (the active-market `metadata.fee` field is a boolean
flag, not a number; the docs state the exact fee is returned only per executed
order), so exact fee reconciliation is an EXECUTION-phase concern — matching the
fill's real fee against the bound in the post-trade receipt — not a scanner
blocker.

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
markets into weather/economics/sports/other. "Read-only" means no order
placement is wired — the scanner CAN flag a Limitless edge as actionable.
Phase 8 checks that Limitless was read live, grouped children were flattened,
unsupported domain shapes were included as non-actionable records, and every
priced Limitless record carries a QUANTIFIED fee term (the upper bound of the
published buy-fee table; `fee > 0`, `fee_missing` retired).

Known support boundary:

- Weather remains the flagship domain, but the 2026-07-09 Limitless live scan
  did not expose a true parseable weather market. Limitless weather markets
  should be added before sports breadth whenever a market gives station/source,
  date, metric, strike, and settlement source clearly enough to feed
  `engines/weather.py`.
- Economics Limitless markets exist, including headline CPI, GDP, recession,
  and Fed-rate shapes. The engine prices US headline CPI (monthly + annual) and
  quarterly/annual GDP; single-quarter GDP-decline recession markets now route
  to the SPF RECESS engine (2026-07-10). These CAN be actionable — Limitless
  fees are quantified as an upper bound (see the fee note above). Still needing
  sources/engines: non-US CPI, Fed-rate decisions at scheduled meetings, and
  PPI.
- Sports Limitless markets are broad. The current supported sports engine is
  2026 FIFA World Cup national-team outright winner only. NBA/NHL/EPL/tennis,
  esports, props, stages, exact matchups, and player-stat markets need their
  own deterministic source/model paths before they can be actionable, but they
  are still included in the scan inventory.

Completion criteria:

- Exercise the normalized Limitless weather parser against a real live market
  once one exposes complete settlement fields; the parser and source-backed
  Phase 9 probes are already wired.
- Reconcile the exact per-order fee against the upper-bound bound at EXECUTION
  time (post-trade receipt), not in the scanner — the exact `effectiveFeeBps`
  is only available per executed order; the ex-ante upper bound is sufficient
  and already wired. Belongs to the funded-execution phase.
- Add new deterministic economics/sports engines before widening Limitless
  actionable support (already covers US headline CPI, GDP, single-quarter
  GDP-decline recession, and World Cup outright shapes).

Verified 2026-07-10 (recorded here so it is not re-litigated): Limitless
collateral is USDC on Base (token `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`,
6 decimals) on the markets sampled live. This is a data point for the still-open
OKX settlement-token question (USDT/USDG/USDC) — Limitless itself settles in
USDC — but it does NOT resolve what OKX's Payment SDK settles in on X Layer;
only a real funded call does.

### Broad venue coverage and engine expansion

Current status: inventory layer started; many engines still missing.

What exists: broad market ingestion is now the scanner's default direction.
Kalshi active markets are cursor-paginated, Polymarket Gamma markets are
offset-paginated, and Limitless active/search markets are flattened. Domain
markets are included with explicit family/shape/status metadata even when no
probability engine exists.

Known gap: broad inclusion is not the same as broad pricing. The next engine
work should be added family by family, with verification per family:

- Weather: high/low temperature, rain, snow, maximum wind, and maximum gust
  engines are wired. Archived rain/snow/wind forecasts are scored against
  historical reanalysis; rain/snow use a zero-inflated hurdle model. Kalshi's
  40 high/low series have verified station binding. Other venues require a
  strict normalized location/date/metric/strike/source contract. Remaining:
  a real qualifying Limitless market and venue-specific settlement proof.
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
