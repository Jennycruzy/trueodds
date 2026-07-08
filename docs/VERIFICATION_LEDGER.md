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
- **Found:** Gamma API's `outcomePrices` gives last-traded-ish prices per outcome, not an explicit bid/ask pair — for a true midpoint, Stage 1 must pull the CLOB order book (`tokens[].price` per side, or the book endpoint) rather than relying on Gamma's `outcomePrices` alone. This is a real correction to the spec's assumption that bid/ask is trivially exposed — Polymarket requires combining Gamma (question/resolution metadata) with CLOB (live order-book price) to get an honest midpoint + spread. To be finalized with a live order-book call in Phase 1.
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

- **Status:** not yet verified — out of scope for GATE 0 (Phase 0 only mandates weather + Kalshi + Polymarket + OKX facts). Deferred to Phase 4 (econ/sports engines): BLS release calendar/API, Federal Reserve releases, and a consensus-forecast source (e.g. an econ-calendar provider) will each get their own live-call verification row before the econ engine is built.

---

### Ledger status as of 2026-07-08 (Phase 0)
All GATE 0-required facts are verified with real evidence above. Two items are explicitly flagged as **open and not assumed**: the Payment SDK settlement token (§7) and the primary hackathon rules page (§9) — both will be re-verified live at the phase that actually depends on them (7 and 9 respectively) rather than guessed now.
