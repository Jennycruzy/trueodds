# Verification Ledger

Doctrine: **never assume, verify.** Every external fact this build depends on
is checked against a live call or a live primary-source document, and logged
here — with the exact evidence — before any code relies on it. Where reality
disagreed with the founding spec's assumptions, that disagreement is recorded
explicitly rather than quietly reconciled.

Log format per entry: **What I needed → Where verified → What I found → Date.**

---

## 1. Weather data

### 1.1 Open-Meteo — multi-model forecast access
- **Needed:** the exact parameter to request specific weather models (ECMWF/GFS/ICON) side by side, so multi-model spread can drive confidence.
- **Verified:** live call, 2026-07-08:
  ```
  curl "https://api.open-meteo.com/v1/forecast?latitude=41.85&longitude=-87.65&daily=temperature_2m_max&temperature_unit=fahrenheit&timezone=America%2FChicago&models=ecmwf_ifs025,gfs_seamless,icon_seamless"
  ```
- **Found:** the `models=` query parameter accepts a comma-separated list; the response suffixes each requested field with the model name, e.g. `temperature_2m_max_ecmwf_ifs025`, `temperature_2m_max_gfs_seamless`, `temperature_2m_max_icon_seamless` — one column per model, same date index. Real response (truncated):
  ```json
  {"latitude":41.75,"longitude":-87.75,"timezone":"America/Chicago",
   "daily_units":{"temperature_2m_max_ecmwf_ifs025":"°F","temperature_2m_max_gfs_seamless":"°F","temperature_2m_max_icon_seamless":"°F"},
   "daily":{"time":["2026-07-08","2026-07-09","2026-07-10","2026-07-11","2026-07-12","2026-07-13","2026-07-14"],
   "temperature_2m_max_ecmwf_ifs025":[90.1,88.0,80.4,84.0,90.5,95.3,99.4],
   "temperature_2m_max_gfs_seamless":[87.8,78.8,78.6,80.7,83.8,87.6,90.7],
   "temperature_2m_max_icon_seamless":[90.2,82.8,81.1,80.2,86.7,83.8,86.4]}}
  ```
  Note the coordinates snapped from the requested (41.85, -87.65) to the nearest model grid point (41.75, -87.75) — must account for this when matching a market's named station to a lat/lon.
  An invalid model name (`bogus_model_xyz`) returns `{"error":true,"reason":"Data corrupted at path ''. Cannot initialize MultiDomains from invalid String value bogus_model_xyz."}` — confirms the API validates model names server-side; exact valid model list to be pinned in Phase 2 from Open-Meteo's model docs.
- **Rate limits / auth:** none hit; Open-Meteo's free tier is keyless (documented elsewhere as ~10k calls/day, to be reconfirmed before high-frequency use in Phase 2).
- **Gap:** NWS/weather.gov, Meteostat, and NASA POWER calls are deferred to Phase 2 (the weather-engine phase) — not required for GATE 0, which only mandates one weather-model call. Kalshi's own weather markets (§1.2 below) already confirm NWS is the authoritative settlement source for US temperature markets, which is a real cross-check that NWS integration is necessary, not optional.

### 1.2 Kalshi weather markets — resolution rule format (bonus finding, feeds §2 too)
- **Verified:** live call, 2026-07-08: `GET https://api.elections.kalshi.com/trade-api/v2/markets?limit=5&series_ticker=KXHIGHCHI`
- **Found real example** — market `KXHIGHCHI-26JUL09-T91`, title "Will the high temp in Chicago be >91° on Jul 9, 2026?":
  ```
  "rules_primary": "If the highest temperature recorded at Chicago Midway, IL for July 09, 2026,
   is greater than 91° according to the National Weather Service's Climatological Report (Daily),
   then the market resolves to Yes."
  ```
  This confirms resolution rules are verbatim, station-specific, and cite an exact official source document (NWS Climatological Report (Daily) for Chicago Midway) — exactly the level of precision Stage 1 must capture and Stage 2 must answer to.

### 1.3 Station coordinates — the exact physical point Kalshi's rule refers to (verified, not guessed)
- **Needed:** Kalshi's resolution rule names a specific NWS/GHCND station ("Central Park, New York", "Chicago Midway, IL") — the weather engine must forecast for that exact point, not a city centroid or an airport with a similar name.
- **Verified:** WebSearch against NOAA NCDC station detail pages, 2026-07-08.
  - **NY City Central Park, NY US** — GHCND:USW00094728 — 40°46'N, 73°58'W (40.7667, -73.9667). Source: https://www.ncdc.noaa.gov/cdo-web/datasets/GHCND/stations/GHCND:USW00094728/detail
  - **Chicago Midway Airport, IL US** — GHCND:USW00014819 — ~41.79N, -87.74W. Source: https://www.ncdc.noaa.gov/cdo-web/datasets/GHCND/stations/GHCND:USW00014819/detail
- **Found:** recorded in `src/rwoo/weather_stations.py` as a small, explicit registry keyed by Kalshi series ticker — a series with no verified station raises an error rather than silently guessing coordinates. Only these two stations are populated so far (the two series used in Phase 1/2 testing); more will be added and verified the same way as the daily loop (Phase 8) selects new series.

### 1.4 NASA POWER — historical daily data for the climatological base rate
- **Needed:** a keyless, live source of many years of real historical daily max-temperature observations at a given lat/lon, to compute an empirical base rate ("in 20 real past years, how often did this exact threshold get crossed on this calendar day") — independent of and a sanity check against the live model-ensemble probability.
- **Verified:** live call, 2026-07-08:
  ```
  GET https://power.larc.nasa.gov/api/temporal/daily/point?parameters=T2M_MAX&community=RE
      &longitude=-73.9667&latitude=40.7667&start=20050101&end=20241231&format=JSON
  ```
- **Found:** keyless, no auth. Returns one JSON object per day (`properties.parameter.T2M_MAX`, keyed `"YYYYMMDD"`, value in **Celsius**) — a full 20-year, 7305-day range came back in a single request. Real July 9 values pulled from the response: 2005=26.28°C, 2006=27.16°C, ... 2024=31.57°C (20 real values, converted to °F in code: `C * 9/5 + 32`). A documented fill value (`-999`) marks missing days — code guards against it (`celsius > -900`) rather than silently averaging in nonsense.
- **Rate limits:** not yet hit; no auth key required for point queries.

---

## 2. Kalshi API

- **Needed:** live base URL, auth scheme, market-listing/price-reading endpoints, how resolution rule + settlement source are represented, rate limits.
- **Verified:** live calls, 2026-07-08.
  - Legacy host `https://trading-api.kalshi.com/trade-api/v2/markets` returns HTTP 401 with body `"API has been moved to https://api.elections.kalshi.com/. Please check our docs on how to migrate."` — confirms the **current base URL is `https://api.elections.kalshi.com/trade-api/v2/`**.
  - `GET /trade-api/v2/markets?limit=3` succeeded **with no auth header** — read-only market listing is public/unauthenticated. Real response included live fields: `yes_bid_dollars`, `yes_ask_dollars`, `no_bid_dollars`, `no_ask_dollars`, `last_price_dollars`, `liquidity_dollars`, `volume_24h_fp`, `status`, `close_time`, `expiration_time`.
  - `GET /trade-api/v2/series?category=Climate%20and%20Weather` succeeded — series-level metadata includes a `settlement_sources` array (name + URL), e.g. for the Etna eruption series: NOAA, AP, Reuters, CNN, etc. named explicitly.
  - Market objects carry `rules_primary` (verbatim settlement rule) and `rules_secondary` (caveats about preliminary vs. final data) — see §1.2 example.
- **Found (implied probability):** the response exposes `yes_bid_dollars` / `yes_ask_dollars` directly in dollars — Stage 1's "midpoint, not last trade" requirement is directly satisfiable: `implied_prob = (yes_bid_dollars + yes_ask_dollars) / 2`, spread = `yes_ask_dollars - yes_bid_dollars`.
- **Auth for trading/order actions:** not yet verified (out of scope for GATE 0 — read-only market data is all Stage 1 needs; order placement is never in scope for this project since Real-World Odds Oracle only reads markets, never trades them).
- **Rate limits:** not yet hit or documented from a real 429; to be confirmed under load in Phase 1.
- **Gap:** none blocking — public market-read access confirmed keyless and working.

---

## 3. Polymarket API

- **Needed:** how to read markets/prices, bid/ask/last exposure, on-chain vs. hosted API, resolution/UMA mechanics, rate limits.
- **Verified:** live calls, 2026-07-08.
  - `GET https://gamma-api.polymarket.com/markets?limit=3&closed=false` succeeded, no auth. Real market returned: "New Rihanna Album before GTA VI?" with `outcomePrices: ["0.515","0.485"]`, `resolutionSource` field (empty here, populated on other markets), and a full-text `description` carrying the exact resolution rule and named resolution source (e.g. "official information from Rockstar Games or its parent company, Take-Two Interactive" and "any official streaming or download site, e.g. Apple Music or Spotify").
  - `GET https://clob.polymarket.com/markets` (CLOB/order-book API) succeeded, no auth. Returns per-token order-book metadata: `tokens[].price`, `minimum_tick_size`, `condition_id`, `question_id`, `neg_risk`, and UMA-adjacent fields (`umaBond`, `umaReward` — seen in the Gamma response).
- **Correction (2026-07-08, caught before Phase 1 code was written):** an earlier pass of this Ledger claimed Gamma's `outcomePrices` was the only price field and that a separate CLOB order-book call was required for a true bid/ask. A closer live check disproved that: **the Gamma market object directly exposes `bestBid`, `bestAsk`, and a precomputed `spread` field** (verified live: `bestBid: 0.51`, `bestAsk: 0.52`, `spread: 0.01` for the Rihanna-album market — and this matches, exactly, independent CLOB calls to `GET /price?token_id=...&side=buy` → `0.51` and `side=sell` → `0.52`, and `GET /midpoint?token_id=...` → `0.515`, which equals `(bestBid+bestAsk)/2`). So Stage 1 can compute `implied_prob = (bestBid + bestAsk) / 2` and `spread = bestAsk - bestBid` **directly from one Gamma API call** — no separate CLOB round-trip is required for the canonical market object. (CLOB remains useful later for order-book depth/liquidity analysis, but is not required for Stage 1's midpoint.)
- **UMA resolution:** confirmed present via `umaBond`/`umaReward` fields — Polymarket markets ultimately resolve via UMA's optimistic-oracle dispute process; exact mechanics to be verified in Phase 1 when building the resolution-tracking path.
- **Rate limits:** not yet hit.

---

## 4. OKX AI / okx.ai marketplace — does OKX host its own market/feed?

- **Verified:** WebSearch + WebFetch against `okx.ai`, `www.okx.com/en-us/learn/okx-ai`, `www.okx.com/en-us/learn/agent-payments-protocol`, and the `okx/onchainos-skills` GitHub repo (primary source — actual SKILL.md files), 2026-07-08.
- **Found:** OKX AI is a **marketplace for agent services** (identity, payments, task escrow) — it is not itself a prediction-market price feed. No evidence found of OKX hosting a readable prediction-market venue comparable to Kalshi/Polymarket. Conclusion: **no third venue exists to read from OKX directly**; Real-World Odds Oracle's Stage 1 venues remain Kalshi + Polymarket only. (If this changes, it only adds a venue — nothing here is load-bearing against it.)

---

## 5. OKX ASP listing + service registration — **major terminology correction from the founding spec**

- **Verified:** primary source, 2026-07-08 — `github.com/okx/onchainos-skills` repository directly (not press coverage): `CLAUDE.md`, and the raw `SKILL.md` files for `skills/okx-ai/` and `skills/okx-agent-payments-protocol/`.
- **Found — the real architecture (differs from the spec's "A2MCP" framing):**
  - There is no literal protocol called "A2MCP" in OKX's own source. The two real mechanisms are:
    1. **`okx-agent-payments-protocol`** skill — implements pay-per-call via the **open x402 HTTP-native payment standard** (HTTP 402 challenge → agent pays → resource returned). This is what press/marketing summarizes as "A2MCP" (instant, no negotiation). Supported schemes seen in the skill doc: `exact`, `aggr_deferred`, `upto`, `period` (subscription), `charge`, `session` — richer than a single "pay-per-call" mode.
    2. **`okx-ai`** skill — handles **ERC-8004 on-chain Agent Identity** registration (roles: User/Buyer, ASP/service-provider, Evaluator/arbitrator) and the **Task Marketplace** (A2A: publish → browse → negotiate/quote → deliver → dispute/arbitrate → rate). This is the negotiated-escrow channel the spec calls "A2A" — confirmed real and separate from the payment protocol.
  - **Agent identities deploy exclusively on X Layer** — direct quote from source: *"agent identities live on XLayer only. Never pass `--chain` to any `agent` identity command."* **OKX covers network fees for identity operations** (gasless registration/updates).
  - **Onchain OS install:** `npx skills add okx/onchainos-skills` (confirmed exact command from `okx.com/en-us/learn/okx-ai`).
  - **Agentic Wallet:** created with an email address, integrated into Onchain OS, provides the single on-chain identity used across both A2MCP-style and A2A work.
  - **ASP service-list definition:** confirmed real fields — each service requires **name, description, type, fee, and endpoint**, collected through a conversational flow (agent asks "Add another / Done" until the operator explicitly finishes) rather than a static web form. This flow runs inside an agentic CLI session (Claude Code/Codex/OpenClaw) with the Onchain OS skill installed — **it requires Jenny's own Agentic Wallet, her explicit approval at each confirmation-card gate, and cannot be completed by this build agent alone**, since identity writes and payment actions are gated on explicit human approval by design (`"All identity writes... must display a confirmation card and await explicit user approval"`).
- **Correction vs. spec §3/§4:** the spec assumed "even before review passes, the service is reachable via its Agent ID." Reality (verified against the live OKX AI Genesis Hackathon rules — see §9 below) is stricter for **this hackathon specifically**: *"Your ASP must pass OKX AI's internal review and go live to remain eligible... If the ASP listing is not approved or cannot go live, your hackathon submission will be deemed invalid."* This is a hard, load-bearing correction: passing review is not optional for a winning submission, regardless of whether the general platform allows pre-review reachability.
- **Gap flagged to Operator:** registering the actual ASP (Phase 7) requires **you** to run the Onchain OS skill install and Agentic Wallet creation yourself (email + explicit approvals) — I can build and test the backend service and its request/response contract now, but the on-chain registration step is not something I can do on your behalf without your wallet and your approval at each gate.

---

## 6. Work intake contract — x402 request/response shape

- **Verified:** primary source, 2026-07-08 — `web3.okx.com/onchainos/dev-docs/payments/x402-introduction` and the `okx-agent-payments-protocol` SKILL.md.
- **Found:** trigger priority order for a 402 challenge: `WWW-Authenticate: Payment` header → `PAYMENT-REQUIRED` header (v2) → `x402Version` field in the response body (v1) — three protocol variants, each with different capabilities. Seller-declared required parameters travel in `outputSchema.input`. Synchronous settlement (wait for on-chain confirmation before returning the resource) is recommended for one-off, higher-value, low-frequency calls — the shape that fits a per-market oracle call; asynchronous settlement (return resource immediately, confirm in background) is the alternative for high-frequency use.
- **Gap:** the full formal JSON schema (exact field names/types for the 402 body and the paid-request replay) was not fully retrievable from public docs in this pass — Phase 7's endpoint-contract work will need one more live round-trip test (or a follow-up doc fetch of `./app` and `./service-seller` linked from the x402-introduction page) before the endpoint is finalized. Flagging honestly rather than guessing a schema.

---

## 7. Payment SDK settlement token — **unresolved discrepancy, flagged rather than assumed**

- **Verified:** multiple primary/secondary sources, 2026-07-08.
- **Found — conflicting evidence, not yet resolved:**
  - Press coverage (`okx.com/en-us/learn/okx-ai`, third-party crypto news) states settlement is in **USDT or USDG**.
  - `okx.com/en-us/learn/agent-payments-protocol` (an OKX-owned page) shows a worked example funding an agent wallet with **"10 USDC"**, and does not mention USDT/USDG at all.
  - The x402 skill's own amount-display example also renders in **USDC** (`"0.0004 USDC (400)"`).
- **Conclusion:** I am **not assuming** which stablecoin is authoritative. This must be resolved by a live test transaction in Phase 7 (whatever token the Payment SDK actually accepts when Jenny's real Agentic Wallet attempts a funded call is the ground truth) rather than by picking one of the three from conflicting docs now. Pricing in the service list (Phase 7) will be set once this is confirmed live.
- **Chain:** all sources agree settlement happens on **X Layer**, described as "zero gas" / "sub-cent viable at scale" for payments specifically (distinct from the OKB gas token used for ordinary X Layer transactions — the Payment SDK appears to abstract/subsidize this).

---

## 8. X Layer mainnet — chain facts for receipt anchoring

- **Verified:** `thirdweb.com/x-layer` and `web3.okx.com/xlayer/docs/developer/build-on-xlayer/network-information`, 2026-07-08.
- **Found:**
  - **Chain ID:** 196
  - **RPC URL:** `https://196.rpc.thirdweb.com` (third-party mirror; OKX's own endpoint `https://xlayerrpc.okx.com` referenced in search summaries — to be confirmed with a live `eth_chainId` call in Phase 6).
  - **Native gas token:** OKB ("X Layer Global Utility Token", fixed supply 21M).
  - **Block explorer:** OKLink, `https://www.oklink.com/xlayer`.
  - **Architecture:** X Layer is an OP-Stack-based optimistic rollup (per an August 2025 upgrade), rated up to 20,000 TPS with negligible gas fees.
- **Cheapest honest anchoring method:** not yet finalized — a plain calldata-only transaction (hash committed in the `data` field of a zero-value tx to a known address, e.g. the sender's own address) is the simplest pattern and needs no custom contract; a minimal attestation contract (single `emit` event per commit) is the alternative if queryability-by-hash is required. Decision deferred to Phase 6 with a real testnet-then-mainnet dry run — flagged as open, not assumed.

---

## 9. OKX AI Genesis Hackathon — submission logistics

- **Verified:** WebSearch, 2026-07-08 (multiple secondary sources referencing the hackathon rules; primary rules page not yet directly fetched — **flagging this explicitly as needing a direct re-verification against the primary rules page before Phase 9 submission**, since a cached/secondary-source date is exactly the kind of "trust a cached date" mistake the spec warns against).
- **Found (secondary-sourced, to be reconfirmed at Phase 9):** submission window reported as **2026-07-03 00:00 UTC to 2026-07-17 23:59 UTC**, via a Google Form. ASP must pass OKX AI review and go live to be eligible (see §5).
- **Gap flagged to Operator:** I have not yet located and fetched the actual primary rules/submission page (only secondary summaries). This must be re-verified directly before Phase 9 — do not treat 2026-07-17 as final until confirmed against the primary source.

---

## 10. Alibaba Cloud hosting requirement

- **Verified:** WebSearch, 2026-07-08.
- **Found:** Alibaba Cloud appears only as a listed infrastructure/ecosystem partner in general Agent Payments Protocol coverage. **No evidence found that OKX AI Genesis Hackathon submissions must be hosted on Alibaba Cloud specifically.** Treated as **not a requirement** unless the primary hackathon rules page (still to be fetched per §9) states otherwise.

---

## 11. Moltbook — reachability (optional, non-blocking per spec)

- **Verified:** WebSearch + WebFetch against `moltbook.com/developers`, 2026-07-08.
- **Found:** Moltbook is a real, live "front page of the agent internet" — an internet forum restricted to AI-agent posting (humans view-only), launched 2026-01-28. An `okx_ai` agent account exists on it already. Documented API surface seen: agent registration (`POST /api/v1/agents/register` per third-party tutorials), identity-token issuance (`POST /api/v1/agents/me/identity-token`), identity verification (`POST /api/v1/agents/verify-identity`), and posting (`POST /api/v1/posts` with a submolt/title/content body and Bearer auth) — rate limit reported at 1 post per 30 minutes. Note: the official `/developers` page itself documents only the identity-token flow; the registration and posting endpoint shapes above come from third-party tutorials, not OKX's own docs — to be confirmed with a real registration call before Phase 8 if pursued.
- **Status: reachable, not yet integrated.** Per spec §4/§12, this remains optional and non-blocking — deferred to Phase 8 without holding up any gate before it.

---

## 12. Economic data sources

- **Needed:** a real official source for a volume-domain economics engine, plus a live economics market whose exact resolution rule names that source.
- **Verified:** live calls, 2026-07-08.
  - Kalshi event: `GET https://api.elections.kalshi.com/trade-api/v2/events/KXCPICORE-26JUL`
  - BLS API: `POST https://api.bls.gov/publicAPI/v2/timeseries/data/` with `seriesid=["CUSR0000SA0L1E"]`
- **Found:** Kalshi's `KXCPICORE-26JUL-T0.0` market resolves on the **seasonally adjusted Consumer Price Index for All Urban Consumers: All Items less Food and Energy** for July 2026, published by the **Bureau of Labor Statistics**, and asks whether the single-decimal month-over-month value is above 0.0%. The BLS public API returns the required official seasonally adjusted core-CPI index under series `CUSR0000SA0L1E`; Phase 4 converts consecutive monthly index values into month-over-month percentage changes and rounds to the single decimal used by Kalshi's rule.
- **Important bug caught during Phase 4:** one oversized unauthenticated BLS request for `2016-2026` returned data only through `2025-12` even though newer 2026 observations existed. A direct shorter live request (`2024-2026`) returned `2026-05` as the latest observation. Code now fetches BLS history in <=10-year chunks and deduplicates rows so the latest official value is not silently dropped. Phase 4 harness output showed the corrected latest observation: `2026-05`, index value `336.121`.
- **Method status:** the Phase 4 economics engine is a conservative official-history baseline, not a finished macro forecast engine. It uses real BLS history and reports a deterministic probability, but confidence is capped at 0.50 because a verified consensus-forecast distribution has **not** yet been integrated. The restraint layer correctly downgraded the live CPI run as low-confidence/thin-source rather than actionable.
- **Gap:** a real consensus-forecast distribution source for CPI/PCE remains unresolved and must be verified before the economics engine can be treated as production-quality.

---

## 13. Kalshi trading fee formula — for Stage 3's friction estimate

- **Needed:** the real cost of trading a Kalshi contract (beyond the quoted bid/ask spread), so Stage 3 can refuse edges that are smaller than genuine trading cost rather than an invented number.
- **Verified:** WebSearch across multiple independent secondary sources (predictionhunt.com, marketmath.io, botforkalshi.com — all describing the same formula independently), 2026-07-08. **Primary source attempt:** `help.kalshi.com/trading/fees` (fetched live — confirms fees exist and points to a fee-schedule PDF, but doesn't itself state the formula) and `kalshi.com/docs/kalshi-fee-schedule.pdf` (fetch attempt returned an HTTP 429 / Vercel bot-checkpoint HTML page, not the document — **this gap is disclosed, not papered over**).
- **Found:** taker fee = `ceil_to_cent(fee_multiplier * 0.07 * contracts * price * (1-price))`; maker fee uses `0.0175` instead of `0.07`. **Cross-validated against Kalshi's own live API**, independent of the secondary sources: real market objects returned by `GET /trade-api/v2/series/{ticker}` carry `"fee_type": "quadratic"` and a `"fee_multiplier"` field — `price * (1-price)` is exactly quadratic in price, and `fee_multiplier` is exactly the `M` term the secondary sources describe. The live API field and the independently-sourced formula corroborate each other.
- **Used as:** `KALSHI_TAKER_FEE_RATE = 0.07` in `src/rwoo/edge.py`, applied as `0.07 * P * (1-P)` per $1-notional contract, added to half the live quoted spread for the total friction estimate. Polymarket's fee schedule has **not** been verified at all — Stage 3 uses spread only for Polymarket markets and states that gap explicitly in the friction method string returned to the caller, rather than guessing a fee.

---

## 14. Sports data source — World Football Elo Ratings

- **Needed:** a real public sports rating source for an end-to-end sports market run that does not copy the market price.
- **Verified:** live calls, 2026-07-08.
  - Polymarket market read: `GET https://gamma-api.polymarket.com/markets?limit=50&closed=false`
  - Rating table: `GET https://www.eloratings.net/World.tsv`
  - Team-name table: `GET https://www.eloratings.net/en.teams.tsv`
- **Found:** Polymarket exposed live 2026 FIFA World Cup outright markets, including "Will Spain win the 2026 FIFA World Cup?", with live bid/ask and a resolution rule naming FIFA as the primary resolution source. World Football Elo exposes the current national-team rating table as plain TSV. Field mapping was verified from `https://www.eloratings.net/scripts/ratings.js`: `pushRatingRow` maps `fields[2]` to team code and `fields[3]` to rating. Phase 4 harness output showed Spain ranked #1 with rating `2177`, and the top eight teams/rating values from the live table.
- **Method status:** the Phase 4 sports engine converts that live Elo table into two deterministic baselines (`elo_rating_softmax_top64` and `elo_rank_decay_top64`). Confidence is capped at 0.45 because both transforms come from one public rating source and this is not yet a full tournament simulator. The restraint layer correctly downgraded the live sports run as low-confidence/thin-source rather than actionable.
- **Gap:** a production sports engine should add bracket/team-qualification state, injuries/lineups where relevant, and either multiple independent rating sources or a calibrated simulator. Phase 4 only proves an honest deterministic volume-domain path.

---

### Ledger status as of 2026-07-08 (Phase 4)
All GATE 0–4-required facts are verified with real evidence above. Open items remain explicitly flagged and **not assumed**: the Payment SDK settlement token (§7), the primary hackathon rules page (§9), the primary Kalshi fee-schedule PDF (§13), the economics consensus-forecast distribution (§12), and production-grade sports model inputs (§14).
