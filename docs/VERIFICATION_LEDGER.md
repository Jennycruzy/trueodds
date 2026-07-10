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
  - **Los Angeles International Airport, CA US** — GHCND:USW00023174 — 33.93816, -118.3866. Kalshi's KXHIGHLAX rule names "Los Angeles Airport" specifically (checked live), not LA Downtown — the wrong same-city station was deliberately ruled out, not assumed away. Source: https://www.ncdc.noaa.gov/cdo-web/datasets/GHCND/stations/GHCND:USW00023174/detail
  - **Miami International Airport, FL US** — GHCND:USW00012839 — 25.78805, -80.31694. Source: https://www.ncdc.noaa.gov/cdo-web/datasets/GHCND/stations/GHCND:USW00012839/detail
  - **Denver International Airport, CO US** — GHCND:USW00003017 — 39.8517, -104.6734. Source: https://www.ncdc.noaa.gov/cdo-web/datasets/GHCND/stations/GHCND:USW00003017/detail
- **Found:** recorded in `src/rwoo/weather_stations.py` as a small, explicit registry keyed by Kalshi series ticker — a series with no verified station raises an error rather than silently guessing coordinates. All 5 stations used by the Phase 5 weather backtest are now populated this way; a real gap was caught here on 2026-07-08 — an earlier pass claimed "all 5 verified stations" in README.md while only NYC and Chicago actually had verified entries (LA/Miami/Denver had only been checked for real-market-count purposes, not added to this registry). Caught and fixed rather than left as a stale claim.

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
- **Honest anchoring method:** not yet finalized. The build spec points to OKX Agentic Wallet as the primary path, so the next implementation step is to verify and use that transaction-signing flow for committing receipt hashes to X Layer. A plain calldata-only transaction or minimal attestation contract may still be the on-chain shape, but the signing/authorization path should be OKX Agentic Wallet unless live OKX docs prove otherwise.
- **Phase 6 RPC verification, 2026-07-08:** live JSON-RPC calls to both `https://xlayerrpc.okx.com` and `https://196.rpc.thirdweb.com` with `eth_chainId` returned `0xc4` (decimal 196). This confirms both RPC paths point to X Layer mainnet. No transaction was sent because the OKX Agentic Wallet anchoring flow has not yet been verified/approved in this workspace.

---

## 9. OKX AI Genesis Hackathon — submission logistics

- **Verified:** primary OKX page + official Google Form, 2026-07-08.
  - `GET https://web3.okx.com/xlayer/build-x-series`
  - `GET https://forms.gle/mddEUagmDbyV37ws8` → resolved to `https://docs.google.com/forms/d/e/1FAIpQLSfIAgP_WmMGtZ5qyW_LnKZonsjyfOYwV3bduRwiuN4oBmcqjQ/viewform?usp=send_form`
- **Found:** the primary OKX Build X page lists **OKX.AI Genesis** as an online Build X Series event running **Jul 2, 12:00 - Jul 17, 23:59 UTC**. The page's FAQ says submissions are open from **July 3, 2026, 00:00 UTC to July 17, 2026, 23:59 UTC**. Requirements found on the primary page:
  1. Build an ASP that solves a clear real-world use case.
  2. Submit the ASP for listing through OKX.AI; it **must pass OKX AI's internal review and go live** to remain eligible. If listing is not approved or cannot go live, the hackathon submission is invalid.
  3. Post on X using `#OKXAI`; introduce the ASP, explain the use case, and include a clear demo/walkthrough. Demo content should be no longer than 90 seconds.
  4. Submit the Google Form before **July 17, 2026, 23:59 UTC**, including ASP details and a link to the X participation post.
- **Google Form fields verified from embedded form data:** form title is **"OKX.AI Genesis Hackathon"**. Fields include **ASP Name**, **Agent ID** ("The ID you received after the ASP was listed on OKX.AI."), **ASP Description**, and X participation/demo-post guidance.
- **Correction vs earlier status:** this is no longer secondary-sourced. Primary OKX page and official form are now verified.

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
- **Verified:** WebSearch across multiple independent secondary sources (predictionhunt.com, marketmath.io, botforkalshi.com — all describing the same formula independently), 2026-07-08. **Primary source:** `help.kalshi.com/trading/fees` (fetched live — confirms fees exist and links to the fee-schedule PDF) and `kalshi.com/docs/kalshi-fee-schedule.pdf` (browser retrieval, 2026-07-08, returned the primary PDF, "Fee Schedule for July 2026 - 7.7.26 Update"). The PDF states the general taker fee formula as `round up(M x 0.07 x C x P x (1-P))` and maker fee formula as `round up(M x 0.0175 x C x P x (1-P))`.
- **Found:** taker fee = `ceil_to_cent(fee_multiplier * 0.07 * contracts * price * (1-price))`; maker fee uses `0.0175` instead of `0.07`. **Cross-validated against Kalshi's own live API**, independent of the secondary sources: real market objects returned by `GET /trade-api/v2/series/{ticker}` carry `"fee_type": "quadratic"` and a `"fee_multiplier"` field — `price * (1-price)` is exactly quadratic in price, and `fee_multiplier` is exactly the `M` term the secondary sources describe. The live API field and the independently-sourced formula corroborate each other.
- **Used as:** `KALSHI_TAKER_FEE_RATE = 0.07` in `src/rwoo/edge.py`, applied as `0.07 * P * (1-P)` per $1-notional contract, added to half the live quoted spread for the total friction estimate. Polymarket's fee schedule has **not** been verified at all — Stage 3 uses spread only for Polymarket markets and states that gap explicitly in the friction method string returned to the caller, rather than guessing a fee.
- **Pre-listing recheck, 2026-07-08:** official Kalshi Help Center article `https://help.kalshi.com/trading/fees` was fetched and its embedded article JSON parsed. It states that Kalshi charges a transaction fee on expected earnings and that the complete Fee Schedule and math are linked at `https://kalshi.com/docs/kalshi-fee-schedule.pdf`. The PDF can be read by browser retrieval, but still returns a Vercel Security Checkpoint / HTTP 429 to this workspace even with a browser User-Agent. Official API fields (`fee_type: "quadratic"`, `fee_multiplier: 1`) remain live and verified at `GET /trade-api/v2/series/KXHIGHNY`.
- **Workspace constraint:** `verify.py --phase 7` cannot parse the PDF through this workspace while it returns HTTP 429. The gate now explicitly checks the official Help Center link, the official API fee fields, and the direct PDF fetch status so the blocked workspace download is recorded rather than silently assumed.

---

## 14. Sports data sources — World Football Elo + FIFA rankings

- **Needed:** real public sports rating sources for an end-to-end sports market run that does not copy the market price.
- **Verified:** live calls, 2026-07-08.
  - Polymarket market read: `GET https://gamma-api.polymarket.com/markets?limit=50&closed=false`
  - Rating table: `GET https://www.eloratings.net/World.tsv`
  - Team-name table: `GET https://www.eloratings.net/en.teams.tsv`
  - FIFA rankings: `GET https://api.fifa.com/api/v3/rankings?gender=1&count=211&language=en`
- **Found:** Polymarket exposed live 2026 FIFA World Cup outright markets, including "Will Spain win the 2026 FIFA World Cup?", with live bid/ask and a resolution rule naming FIFA as the primary resolution source. World Football Elo exposes the current national-team rating table as plain TSV. Field mapping was verified from `https://www.eloratings.net/scripts/ratings.js`: `pushRatingRow` maps `fields[2]` to team code and `fields[3]` to rating. FIFA exposes the official men's ranking API; the live check returned Spain with publication date `2026-06-11T10:00:00+00:00`.
- **Method status:** the sports engine now converts both source families into deterministic baselines (`elo_rating_softmax_top64`, `elo_rank_decay_top64`, `fifa_points_softmax_top64`, `fifa_rank_decay_top64`) and deterministic 48-team simulators (`elo_48_team_tournament_simulator`, `fifa_48_team_tournament_simulator`). Confidence is capped at 0.78 because the engine still does not condition on draw state, injuries, lineups, or a wider projection ensemble.
- **Gap:** a production sports engine should add bracket/team-qualification state, injuries/lineups where relevant, and independent projection-market/bookmaker/projection sources beyond ranking systems. The pre-listing gate now proves an honest multi-source deterministic sports path, not a finished sports trading model.

---

## 15. Calibration backtest sources — finalized Kalshi outcomes + Open-Meteo Single Runs

- **Needed:** a real historical forecast source that proves no lookahead, and real resolved market outcomes.
- **Verified:** live calls and official docs, 2026-07-08.
  - Kalshi finalized weather markets: `GET https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXHIGHNY&status=settled&limit=40`
  - Open-Meteo Single Runs: `GET https://single-runs-api.open-meteo.com/v1/forecast?run=2026-07-06T06:00&hourly=temperature_2m&models=ecmwf_ifs025`
  - Official docs: `https://open-meteo.com/en/docs/historical-forecast-api` and the linked Single Runs API docs.
- **Found:** Kalshi finalized markets expose `result` (`yes`/`no`), `expiration_value`, `open_time`, `settlement_ts`, structured strike fields, and the verbatim resolution rule. Open-Meteo Single Runs returns an archived model run selected by `run=<UTC initialisation datetime>`; the docs state model output is generally available about 4-6 hours after initialization. Phase 5 conservatively records `source_available_at = run + 6h` and requires `source_available_at <= market.open_time < settlement_ts` for every backtest record.
- **Real Gate 5 run:** `python3 verify.py --phase 5` built 18 resolved weather calibration records from finalized Kalshi NYC high-temperature markets. The run printed raw Kalshi outcome evidence, archived per-model forecast values (`ecmwf_ifs025`, `gfs_global`, `icon_global`), a no-lookahead proof for every record, a weather reliability curve, and a weather Brier score.
- **Scoring result from the verified run:** Weather Brier score `0.0533` across 18 resolved calls. Reliability buckets printed by the harness: `0.0-0.2` bucket had 13 calls with mean predicted `0.0336` and actual hit rate `0.0000`; `0.2-0.4` had 3 calls with mean predicted `0.2545` and actual hit rate `0.3333`; `0.4-0.6` and `0.8-1.0` each had one call. Max bucket calibration gap was `0.5618`.
- **Recalibration:** because max bucket gap exceeded 0.20, Phase 5 fit a one-parameter power recalibration by deterministic grid search over the calibration record. Best gamma was `1.05`; Brier improved slightly from `0.053335` to `0.053264`. This is disclosed as a tiny seed-set correction path, **not** production-ready calibration.
- **Gap:** Phase 5 calibration currently covers weather only and is seeded by a small recent resolved sample. Econ/sports calibration is incomplete until those domain engines have proper forecast sources and resolved historical sample paths. Append-only on-disk record storage and hash anchoring are deferred to Phase 6 receipts; the Phase 5 harness discloses this rather than pretending the anchor exists.

---

## 16. Receipt ledger and anchoring status

- **Needed:** tamper-evident receipts and real X Layer mainnet anchoring.
- **Verified locally:** `python3 verify.py --phase 6`, 2026-07-08.
- **Found:** the local receipt system commits a real verdict payload containing venue, market ID, resolution rule, `oracle_prob`, implied probability, qualified edge, confidence, source values, and timestamp. It writes records to an append-only JSONL ledger with sequence numbers, previous hash, record hash, and head hash. A tamper test altered a recorded probability and verification detected `record_hash mismatch at record 1`.
- **Hash algorithm:** the local ledger now uses real **keccak256** (via `pycryptodome`'s `Crypto.Hash.keccak`), matching the spec's explicit requirement — corrected from an earlier `hashlib.sha3_256` implementation, which is a *different* algorithm from Ethereum's keccak256 (different padding) despite the similar name. That correction changes every hash the ledger produces, which is directly relevant to the anchoring saga below.

### 16.1 First X Layer anchor attempt — invalid on two independent grounds, superseded
- **What happened:** a real transaction (`0xb636da3142cf3ba6b4e1b4a06b52fae3889ec2fbcc29456437852d8e7f55b64d`) was submitted via the real OKX Agentic Wallet CLI (`onchainos wallet contract-call --to <own wallet address> --input-data <commitment hash>`), and the outer transaction receipt showed `status: "0x1"` (success) on X Layer mainnet, chain ID 196. Gate 6 initially reported this as a passing real anchor.
- **What was actually wrong (caught 2026-07-08 during a live re-verification):**
  1. The anchored hash (`b91aed9d...`) was computed with the old `sha3_256` code, not the required keccak256 — invalid on its own.
  2. **A deeper bug in the verification logic itself:** this Agentic Wallet is an **ERC-4337 smart-contract account**. The outer transaction is a bundler calling `EntryPoint.handleOps()`; per the ERC-4337 spec, if a single inner `UserOperation` reverts, `handleOps()` does **not** revert the outer call — it simply emits a `UserOperationEvent(bytes32 userOpHash, address sender, address paymaster, uint256 nonce, bool success, uint256 actualGasCost, uint256 actualGasUsed)` with `success=false` and continues. So an outer receipt of `status: "0x1"` proves the *bundler's* transaction succeeded, not that *our* self-directed calldata call executed.
  - **Live re-verification, 2026-07-08:** fetched the transaction's receipt directly (`eth_getTransactionReceipt`) and decoded its `UserOperationEvent` log (topic `0x49628fd1471006c1482da88028e9ce4dbb080b815c9b0344d39e5a8e6ec1419f`) by hand: `nonce=0, success=0 (false), actualGasCost=0, actualGasUsed=152618`. **The inner call reverted.** Confirmed independently via `onchainos security tx-scan` on the same call shape, which returned `"revertReason": "execution reverted"`.
  - **Root cause of the revert:** the target (`--to`) was the wallet's own smart-account address, which has real deployed bytecode with no permissive fallback for arbitrary unrecognized calldata — calling it with a raw 32-byte hash (not a valid ABI-encoded function call) reverts.
  - **This transaction and its commitment hash are marked invalid and superseded**, not deleted — see `data/anchors/phase6_anchor.json`'s `supersedes` field for the full record.
- **The fix:** anchor calldata against an address with **no contract code** (a plain externally-owned/burn address), so the EVM-level call can never revert regardless of calldata content — this is the standard pattern for on-chain data anchoring. Used `0x000000000000000000000000000000000000dEaD` (the conventional Ethereum burn address). Confirmed via `security tx-scan` first (empty `revertReason`) before submitting for real.
- **Second anchor (the valid one):** transaction `0x655d283549f0e809985a7fa401b1a8a14b6ad1419e3ebd15dd57424950c53ef2`, X Layer mainnet, chain ID 196, block 64760384. Decoded `UserOperationEvent`: `nonce=1, success=1 (true), actualGasUsed=137378`. Transaction input independently confirmed (via direct RPC, not just the CLI's own report) to contain both the commitment hash `713fd39961a27c7b2c4ee54d6a17bae67a80f08a1edcf4075da948e00bade446` and the wallet address `38c3299ee0e771e8d0a756e1a5dd4b8a8e9930ca`. Explorer: https://www.oklink.com/xlayer/tx/0x655d283549f0e809985a7fa401b1a8a14b6ad1419e3ebd15dd57424950c53ef2
- **Verification code fix:** `src/rwoo/xlayer.py`'s `verify_anchor_transaction()` now decodes the `UserOperationEvent` log and requires `user_operation_success == True` as its own explicit check, in addition to (not instead of) the outer receipt status, chain ID, and calldata-content checks. An anchor is no longer accepted on outer-receipt status alone.
- **Completion status:** `python3 verify.py --phase 6` now genuinely passes, including the corrected on-chain proof.

---

## 17. Weather backtest — removing the artificial sample cap

- **What changed:** the Phase 5 weather backtest previously stopped at a hardcoded `max_records=18` even though it only fetched one page (`limit=40`) of a series that has far more real history. Caught when the Operator asked "why not more, and did you actually check." Live re-verification, 2026-07-08:
  - `GET /trade-api/v2/markets?series_ticker=KXHIGHNY&status=settled` fully paginated (following `cursor`): **402** real settled NYC markets exist.
  - Same check for KXHIGHCHI, KXHIGHLAX, KXHIGHMIA, KXHIGHDEN: 200+ each on the first page alone (not fully paginated in this check, but confirms the same order of magnitude).
- **Genuine (not artificial) constraint found in its place:** Open-Meteo's Single Runs archived-forecast API only retains a rolling window of past model runs. Verified live by probing specific `run=` dates: `2026-04-15` succeeds, `2026-04-01` fails ("model run is not available"), `2026-03-01`/`2025-*`/`2023-*`/`2018-*` all fail. So the real ceiling on usable weather backtest records is "settled markets whose target date falls in roughly the last ~3 months," not an arbitrary round number — this varies day to day as the rolling window moves forward.
- **Fix:** `src/rwoo/backtests/weather.py` now paginates fully through every settled market for a series (`fetch_finalized_weather_markets`), fetches all 3 archived models in one call instead of three (`fetch_single_run_all_models` — confirmed live that Single Runs accepts comma-separated `models=`), and runs across all 5 verified stations by default (`build_weather_backtest`) with no sample-size cap. A per-market try/except was added so one transient network failure can't abort a multi-hundred-record run.
- **Runtime fix after audit, 2026-07-08:** a true full no-cap run is correct but slow enough to make the harness look frozen because it may call Open-Meteo Single Runs hundreds of times. The code now has a transparent raw-response cache at `.cache/rwoo/open_meteo_single_runs` (each cache file stores the source URL, params, raw JSON response, parsed daily maxima, and `fetched_at`) plus progress callbacks. The human-readable gate defaults to `RWOO_WEATHER_GATE_RECORDS_PER_SERIES=5` (25 real records across 5 stations) and prints each station's market count/progress; setting `RWOO_WEATHER_GATE_RECORDS_PER_SERIES=0` runs the full no-cap path. This is a runtime control, not a data fabrication shortcut.
- **Most recent verified gate result:** `python3 verify.py --phase 5`, 2026-07-08, built **25** real weather calibration records across all 5 stations. Every no-lookahead check passed (`source_available_at <= decision < resolution`). Weather Brier score was **0.1431** across 25 resolved calls. Reliability buckets: `0.0-0.2` n=19 mean predicted `0.0304` actual hit rate `0.1579`; `0.2-0.4` n=3 mean predicted `0.2365` actual hit rate `0.0000`; `0.4-0.6` n=1 mean predicted `0.5706` actual hit rate `1.0000`; `0.8-1.0` n=2 mean predicted `0.9239` actual hit rate `0.5000`. A deterministic power recalibration was triggered; best gamma `0.40`, Brier improved from `0.143092` to `0.126977`.

---

## 18. BLS CPI release-date schedule + a real rate-limit finding

- **Needed:** the actual date each BLS CPI figure became public (not just which month it describes) to score an economics backtest without lookahead — BLS's API returns a value's reference month but not its publication date.
- **Verified:** the primary page `bls.gov/schedule/news_release/cpi.htm` is reachable from this workspace with a normal User-Agent and is checked by `python3 verify.py --phase 7`. The release-date table in `src/rwoo/engines/economics.py` covers the Kalshi CPI backtest window, including two real disruptions handled explicitly rather than smoothed over: the October 2025 release was **canceled** (government shutdown) and the November 2025 release was rescheduled to December 18, 2025 (from December 10).
- **Used as:** `CPI_RELEASE_DATES` in `src/rwoo/engines/economics.py` — an explicit `{(year, month): date | None}` table for the window this project's markets fall in, with a documented conservative fallback (day 20 of month+1, safely later than the real observed ~10th-14th pattern) for any month outside the verified table. `fetch_core_cpi_series(as_of=...)` filters BLS rows by this real release date, not the reference month, before handing them to the probability computation — this is what makes `compute_archived_cpi_probability` in `src/rwoo/backtests/economics.py` a genuine no-lookahead backtest rather than one with a subtle ~6-week lookahead leak.
- **Real rate-limit finding, 2026-07-08:** the unauthenticated BLS v2 API allows roughly 25 requests/day. The original economics engine re-fetched CPI's *entire* history separately for every market scored — a real inefficiency bug, not bad luck, confirmed by hitting `REQUEST_NOT_PROCESSED: daily threshold ... has been reached` while backtesting only 27 real settled KXCPICORE markets. **Fixed:** `_fetch_and_parse_full_history` now fetches the full raw history once per process (2 real chunked calls covering 2016-2026) and every `as_of` cutoff slices the cached result in memory — an entire backtest run now costs ~2 real BLS calls, not ~50+.
- **Status after pre-listing hardening:** `src/rwoo/engines/economics.py` now falls back to the official BLS flat-file mirror with a normal User-Agent when the BLS API quota refuses data. `verify.py --phase 5` no longer accepts quota-blocked economics as complete; it must build real economics records and print a Brier score.

---

## 19. Self-computed historical Elo ratings — for a genuine sports no-lookahead backtest

- **Needed:** national-team Elo ratings as they stood on a specific past date, to backtest the sports engine's tournament-outright method without leaking today's ratings into a 2024 tournament's prediction.
- **Verified no such API exists, 2026-07-08 (a real, checked dead end, not an assumption):** `eloratings.net/World.tsv` exposes only current ratings plus fixed 1/5/10-year-ago snapshots (columns confirmed live) — not arbitrary-date lookups. `api.clubelo.com/YYYY-MM-DD` does provide by-date ratings but for **club** football, a different rating system than the national-team one the sports engine uses. No free by-date national-team Elo API was found after checking both.
- **Real data found instead:** `github.com/martj42/international_results` — a real, actively-maintained public dataset, 49,506 international match results, 1872 through 2026 (including honestly-marked unplayed future fixtures with `NA` scores), with the exact `tournament` name and `neutral`-site flag every Elo calculation needs. Fetched live, 2026-07-08.
- **Formula, cross-verified from two independent sources** (Wikipedia's "World Football Elo Ratings" article and eloratings.net's own methodology description — eloratings.net's `/about` page itself is JS-rendered and didn't yield the formula text via direct fetch, disclosed rather than papered over): `R_new = R_old + K*(W - We)`, `We = 1/(10^(-dr/400)+1)` with `dr` = rating difference **+100 for the home team unless the match is at a neutral site**; `K` = 60 (World Cup finals), 50 (continental championship finals), 40 (World Cup/continental qualifiers), 30 (other tournaments), 20 (friendlies); goal-difference multiplier 1.0 (margin <=1), 1.5 (margin 2), 1.75 (margin 3), 1.75+(N-3)/8 (margin >=4).
- **Implemented as:** `src/rwoo/backtests/sports_elo.py` — replays every real match chronologically, so `replay_ratings_as_of(date)` gives a rating that only reflects matches strictly before that date. `tournament_field()` reconstructs the REAL set of teams that played in a specific tournament instance from the match data itself (not "top N by global rating," which would be wrong for a fixed continental field).
- **Validation against the live site, disclosed honestly:** replaying all 49,506 matches through today gives Spain 2233.9 and Argentina 2232.8, versus eloratings.net's live 2177 and 2156 — a systematic ~50-80 point gap for top teams. **The relative ranking matches well** (same teams at the top, same rough order: Spain, Argentina, France, England...), so this is a faithful replica of the general method, not a bit-perfect clone of eloratings.net's undisclosed exact internal seeding/adjustments. Since the backtest only needs relative strength within a single tournament's field (converted to a probability via softmax/rank-decay), this is judged sound for that purpose — but the absolute-value gap is disclosed here, not hidden.
- **Real backtest built:** `src/rwoo/backtests/sports.py` scores every real, resolved, per-team Polymarket market from Euro 2024 (won by Spain) and Copa América 2024 (won by Argentina) — 30 real records (one genuine non-team "will another team win" market correctly excluded, not a bug) — using the SAME softmax/rank-decay transform as the live engine (`engines/sports.py`), fed self-computed as-of ratings instead of today's.
- **Most recent verified gate result:** `python3 verify.py --phase 5`, 2026-07-08, built **30** real sports calibration records from those two resolved tournaments. Sports Brier score was **0.0492**. Reliability buckets: `0.0-0.2` n=29 mean predicted `0.0552` actual hit rate `0.0345`; `0.2-0.4` n=1 mean predicted `0.2702` actual hit rate `1.0000`. A deterministic power recalibration was triggered; best gamma `0.95`, Brier improved from `0.049192` to `0.049033`.

---

## 20. Pre-listing hardening gate — economics completed for this build

- **Needed:** the Operator correctly rejected listing a half-baked app. Economics could no longer be allowed to pass as "honestly quota-blocked"; it needed real forward-looking official inputs, a full calibration score, and a gate that fails if either is missing.
- **Implemented, 2026-07-08:**
  - `src/rwoo/economic_sources.py` reads the official Federal Reserve Bank of Cleveland inflation nowcasting page for monthly CPI/core-CPI nowcasts.
  - The same module reads the official Federal Reserve Bank of Philadelphia Survey of Professional Forecasters `prob.xlsx` workbook, specifically the `PRCCPI` sheet, and parses the official SPF release-date file so each survey row has a dated source availability timestamp.
  - `src/rwoo/engines/economics.py` now uses BLS official history plus Cleveland Fed nowcasts and Philadelphia Fed SPF density data for live core-CPI probabilities when those sources are available. Confidence is no longer capped only because the source is backward-looking history; the cap rises only when official forward-looking sources are actually present.
  - The BLS API remains the first path, but `src/rwoo/engines/economics.py` now falls back to the official BLS flat-file mirror (`download.bls.gov/pub/time.series/cu/cu.data.0.Current`) with a normal User-Agent. This removes the unauthenticated API quota as an excuse for not producing a calibration score.
  - `src/rwoo/backtests/economics.py` now adds official SPF PRCCPI probability-bin records and scores them against realized BLS Q4/Q4 core CPI. This is not a pseudo-market; it is a direct calibration of official professional-forecast probabilities against realized official data.
- **Verified:** `python3 verify.py --phase 5`, 2026-07-08, built **1,427 economics calibration records**: 27 real settled Kalshi CPI markets plus 1,400 official SPF probability-bin records. Economics Brier score was **0.0550**. Reliability buckets: `0.0-0.2` n=1128 mean predicted 0.0418 actual hit rate 0.0257; `0.2-0.4` n=244 mean predicted 0.2853 actual hit rate 0.1885; `0.4-0.6` n=44 mean predicted 0.4595 actual hit rate 0.6364; `0.6-0.8` n=7 mean predicted 0.6798 actual hit rate 1.0000; `0.8-1.0` n=4 mean predicted 0.9131 actual hit rate 1.0000. Deterministic power recalibration was triggered; best gamma 1.50 improved Brier from 0.054987 to 0.052806.
- **New hardening gate:** `python3 verify.py --phase 7`, 2026-07-08, passes and explicitly fails if official economics sources cannot be parsed, the live economics engine does not include forward-looking sources, economics does not produce real records plus a Brier score, sports lacks multi-source tournament simulators, primary-source checks fail, or the daily proof loop cannot create receipt-backed artifacts.
- **Sports hardening in the same gate:** `src/rwoo/engines/sports.py` now includes deterministic 48-team World Cup simulators for both World Football Elo and the official FIFA ranking source. A live check showed Spain at oracle probability `0.1512`, confidence `0.78`, and FIFA ranking publication date `2026-06-11T10:00:00+00:00`.
- **Primary-source cleanup status:** the primary OKX Build X page and official Google Form remain verified (§9). The BLS primary CPI schedule page is reachable with a normal User-Agent. Kalshi fee evidence now checks the official Help Center link, browser-readable PDF formula, official API quadratic fee fields, and the workspace's explicit PDF fetch status.
- **Daily proof loop:** `src/rwoo/daily.py` creates a real market verdict, appends it to a keccak256 hash-chained receipt ledger, verifies the ledger, and emits JSON/Markdown artifacts from the same committed record. Gate 7 fails if that loop does not run.
- **Live opportunity scanner, 2026-07-08:** `src/rwoo/scanner.py` scans batches from live Kalshi and Polymarket markets, runs only supported deterministic engines, applies the same uncertainty/cost restraint layer, ranks actionable candidates, and writes `data/public/opportunity_scan_latest.json` plus `.md`. `python3 verify.py --phase 8` passed after scanning **152** live markets, evaluating **79** supported markets, finding **36** actionable cost-adjusted candidates, and tolerating **1** item-level source timeout (under the 5% resilience threshold). A subsequent artifact run evaluated **80** supported markets and wrote `data/public/opportunity_scan_latest.*`.

---

## 21. Limitless Exchange API — read-only scanned venue

- **Needed:** add Limitless carefully as a scanned venue without pretending unsupported markets are actionable or that trading execution is wired.
- **Official docs pinned, 2026-07-09:**
  - Documentation index: `https://docs.limitless.exchange/llms.txt`
  - Production API base URL: `https://api.limitless.exchange`
  - Active markets docs: `https://docs.limitless.exchange/api-reference/markets/browse-active.md`
  - Search docs: `https://docs.limitless.exchange/api-reference/markets/search.md`
  - Market detail docs: `https://docs.limitless.exchange/api-reference/markets/get-market.md`
  - Orderbook docs: `https://docs.limitless.exchange/api-reference/trading/orderbook.md`
  - Fee docs: `https://docs.limitless.exchange/user-guide/fees.md`
  - Signed trading docs: `https://docs.limitless.exchange/api-reference/trading/create-order.md`
- **Public read-only endpoints verified live, 2026-07-09:**
  - `GET https://api.limitless.exchange/markets/active` returned `data` plus `totalMarketsCount`; the default page returned 25 active markets and reported 416 active markets at probe time.
  - `GET https://api.limitless.exchange/markets/search?query=World%20Cup%20Winner&limit=3` returned a parent `marketType: "group"` market with nested child markets. The parent has no orderbook; child slugs do.
  - `GET https://api.limitless.exchange/markets/{slug}` returned both single-market and group detail objects. Detail responses include `id`, `conditionId`, `slug`, `description`, `expirationTimestamp`, `categories`, `tags`, `collateralToken`, `prices`, `tradePrices`, `venue`, `marketType`, `winningOutcomeIndex`, and `metadata`.
  - `GET https://api.limitless.exchange/markets/{child_slug}/orderbook` returned a YES-side orderbook with `bids`, `asks`, `tokenId`, `adjustedMidpoint`, `midpoint`, `maxSpread`, `minSize`, and `lastTradePrice`. The official orderbook docs state the endpoint returns a single YES-side book and that NO prices are complementary (`YES + NO = 1`).
- **Auth/signed trading boundary:** public reads above do not require auth. Creating orders is explicitly a trading endpoint requiring signed order data: the official create-order docs say to fetch venue/token IDs, sign using EIP-712 with `venue.exchange` as verifying contract, and ensure token approvals. User/profile/order-management endpoints are not part of this read-only integration.
- **Field mapping implemented:** `src/rwoo/readers/limitless.py` maps child `conditionId`/`id`/`slug`, parent group context, title/question, HTML-stripped description as the resolution rule, `expirationTimestamp`, `categories`/`tags`, `collateralToken`, `metadata.fee`, and `tradePrices`. For CLOB markets, YES bid/ask are mapped from `tradePrices.sell.market[0]` and `tradePrices.buy.market[0]`, cross-checked against a live Spain World Cup child where the orderbook returned bid `0.174`, ask `0.214`, and midpoint `0.194`.
- **Group-market handling:** Limitless group parents are flattened into child `CanonicalMarket` rows. Example verified live: `World Cup Winner` parent `id=10000109`, `marketType="group"`, with child Spain `conditionId=0x7cec65c95efcb4755ab37df40c5045de33ee8c6c3dc1401381ab3ce3f7a02b16`, slug `spain-1765296582267`, USDC collateral (`0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`, decimals 6), `prices=[0.194,0.806]`, and bid/ask-like `tradePrices`.
- **Domain finding, 2026-07-09:** live Limitless search found broad sports markets (World Cup, NBA, NHL, Wimbledon, EPL, esports) and economics markets (headline US CPI, GDP, recession, Fed-rate, China/Korea inflation). It did **not** find a true parseable weather-temperature/rain market; a real classifier false positive (`Carolina Hurricanes`) was caught and fixed by making explicit sports labels outrank weather keywords.
- **Supported-market boundary:** Limitless is ingested broadly, but only markets whose source shape matches an existing deterministic engine can receive an oracle probability. Today that means named national-team 2026 FIFA World Cup outright winner children can run through `engines/sports.py`, and US annual headline-CPI children can run through the BLS all-items CPI-U annual-history path in `engines/economics.py`. The catch-all "Other" World Cup child, stages/matchups/props, non-US CPI, GDP, Fed, recession, PPI, and broad sports shapes remain included as non-actionable records with explicit missing reasons. Limitless weather is a first-priority future route when a live market exposes station/source/date/metric/strike fields cleanly enough for `engines/weather.py`.
- **Fee status:** official Limitless fee docs state AMM fees are flat 0.40% and CLOB taker fees are dynamic ranges (buy 0.40%-3.00%, sell 0.42%-1.50%), with profile/trading-experience adjustments. This build has not wired exact per-order/profile fee computation, so `src/rwoo/edge.py` uses measured spread only for display and refuses all Limitless records as actionable until the exact fee term is computed.
- **Broad coverage update, 2026-07-09:** `src/rwoo/scanner.py` now reads broad active Kalshi pages (`GET /markets?status=open` with cursor pagination), Polymarket Gamma pages (`offset` pagination), and Limitless active/search pages with group flattening. `src/rwoo/coverage.py` assigns included markets a deterministic `family`, `shape`, and `coverage_status` (`actionable`, `wait`, `model_missing`, `parse_missing`, `source_missing`, `fee_missing`, or `unsupported_domain`). A real classifier bug was caught and fixed: `rain` had matched inside `Ukraine`, causing "Zelenskyy out as Ukraine president..." to be misclassified as weather; keyword matching now uses word boundaries for single-word keywords.
- **Structured parser and headline-CPI expansion, 2026-07-09:** `src/rwoo/parsers.py` now parses supported weather/economics shapes into typed engine inputs rather than leaving that logic embedded in `scanner.py`. Kalshi high-temperature markets flow through this parser; unsupported weather metric families are recognized with explicit `model_missing`/`source_missing` reasons. US annual headline-CPI Limitless children such as `June Inflation US - Annual - 3.7%` are parsed into country/month/rounded-bin inputs and priced from official BLS CPI-U all-items annual changes (`CUUR0000SA0`). A live targeted check returned an oracle probability for that 3.7% bin using **112** usable annual changes, with latest BLS observation `2026-05`; confidence remains capped at 0.50 until a forward-looking headline-CPI distribution is added.
- **Phase 8 verification, 2026-07-09:** `python3 verify.py --phase 8` passed with broad ingestion enabled after the parser/headline-CPI update. It scanned **644** live markets in the gate run: venue counts `kalshi=192`, `polymarket=120`, `limitless=332`; included **336** records, including **236** non-actionable unsupported domain records; evaluated **100** records with existing engines; and skipped only **308** `other`/price-oracle records. Coverage status counts were `actionable=38`, `wait=42`, `fee_missing=20`, `source_missing=27`, `parse_missing=51`, `model_missing=158`. The gate now fails if coverage fields are missing, Limitless is not read, grouped markets are not flattened, unsupported Limitless domain shapes are not included as non-actionable records, or priced Limitless records become actionable while the fee gap remains.
- **Default artifact run, 2026-07-09:** `PYTHONPATH=src python3 -m rwoo.scanner --write --top 30` scanned **2,163** live markets, included **915** weather/economics/sports records, marked **747** included records as non-actionable coverage gaps, skipped **1,248** `other` records, evaluated **168** records, and found **39** actionable candidates. The run priced **12** US annual headline-CPI Limitless records as `fee_missing`; non-US CPI, monthly CPI, GDP, Fed, recession, PPI, tennis/NBA/NHL/esports, and unparsed sports shapes remain visible with explicit missing reasons.

## 22. Tennis and NBA sports sources — reachability reassessment (2026-07-10)

- **Needed:** verified, reachable ratings sources so tennis and NBA markets can move off `source_missing` and be priced honestly (or honestly deferred), rather than staying blocked on the 2026-07-09 assessment.
- **Re-probed live from this workspace, 2026-07-10 (browser-like User-Agent):**
  - Official ATP rankings `https://www.atptour.com/en/rankings/singles` → **HTTP 403** (Cloudflare "Just a moment…" bot challenge; needs a JS-solving browser).
  - Sackmann community CSV mirror (`.../JeffSackmann/tennis_atp/master/atp_matches_2024.csv`, `atp_rankings_current.csv`) → **HTTP 404**.
  - `https://stats.nba.com/stats/leaguestandings` → **read timeout** (NBA drops/deprioritizes datacenter IPs).
  - `https://api.balldontlie.io/v1/teams` → **HTTP 401** (moved behind an API key since the prior assessment).
- **Verified reachable and wired, 2026-07-10:**
  - Tennis Elo: `GET https://www.ultimatetennisstatistics.com/rankingsTableTable?rankType=ELO_RANK&count=500` → **HTTP 200 JSON**. Elo lives in each row's `points` field (live sample: Sinner 2414, Djokovic 2347, Alcaraz 2280). No key. Read by `src/rwoo/readers/tennis_uts.py`; a table under 20 usable rows raises rather than passing off a truncated feed.
  - NBA team strength: `GET https://site.api.espn.com/apis/v2/sports/basketball/nba/standings` → **HTTP 200 JSON**, `season.displayName = "2026-27"`. Per team: wins/losses and season point differential (`differential`, `pointDifferential`). The feed splits into two conference groups of 15; `src/rwoo/readers/nba_espn.py` merges both to the full 30 teams (deduped) and raises under 20.
- **Method status:**
  - `engines/sports.compute_tennis_match_probability` prices head-to-head from published UTS Elo via the existing Elo win expectation `_elo_win_probability`. Single-source, so confidence scales with rating-gap decisiveness and is capped at 0.68 (no surface/H2H/form adjustment, no independent second ratings source). Coverage: tennis head-to-head → `engine_available`; tennis tournament winner → `model_missing` (source reachable, draw/bracket simulation not wired).
  - `engines/sports.compute_nba_match_probability` prices head-to-head from season point differential via a normal game-margin model (SD 12 pts, SRS-style). Confidence is **hard-capped at 0.50 — deliberately below the 0.55 actionable floor** (`edge.DEFAULT_MIN_CONFIDENCE`): NBA prices as information but never stakes on a single signal, and refuses if a side has <10 games. Coverage: NBA champion → `model_missing` (source reachable, season/playoff simulation not wired).
- **Head-to-head orientation hardening:** `CanonicalMarket.yes_subtitle` records the venue-native label of the outcome `implied_prob` prices (Kalshi `yes_sub_title`, Polymarket `groupItemTitle`/`outcomes[0]`, Limitless flattened child `title`). The tennis parser binds the YES side to a specific player from that label or the resolution rule and returns `parse_missing` when it cannot bind exactly one, so an inverted edge cannot enter the actionable set. Verified end-to-end: the same matchup with YES bound to each side returns complementary probabilities (0.684 / 0.316).
- **Gate:** `python3 verify.py --phase 9` (added this session) prices tennis through the full `evaluate_market` path from live UTS Elo, and asserts NBA's deferred/sub-actionable behavior. It passes.
- **Caveat:** both UTS and ESPN's standings endpoint are **unofficial/undocumented** and can change shape or rate-limit without notice; parsing is defensive and the engines refuse on shape drift. NHL remains deferred (official API reachable but offseason), and esports has no verified free source.

---

### Ledger status as of 2026-07-10 (Phase 6 + pre-listing hardening + parser/headline-CPI scanner expansion + Phase 9 coverage gate + tennis/NBA sources complete)
All GATE 0–9-required facts are verified with real evidence above, including a real, correctly-verified X Layer mainnet anchor transaction (§16.1) after catching and fixing a genuine false-positive in the anchor verification logic itself, and the 2026-07-10 tennis/NBA source reassessment (§22). Other open items remain explicitly flagged and **not assumed**: the Payment SDK settlement token (§7), the Kalshi fee-schedule PDF direct fetch blocked by HTTP 429 from this workspace, exact Limitless fee/execution support (§21), tennis tournament-winner and NBA champion simulations (§22), the not-yet-wired ClubElo/MLB sources, future weather/economics/sports venue expansion, funded execution/risk controls, and the hosted public calibration page.
