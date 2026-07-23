# Post-ASP Handoff: Mainnet Listing Acceptance

Last updated: 2026-07-23 (listing-stable execution architecture; dated
production facts below retain their original audit dates)

The callable natural-language signal layer is deployed on `trueodd.xyz`, and
all production services use the weather v3 model. Payments target X Layer
mainnet only and remain disabled until OKX seller credentials are installed
securely. No testnet payment is part of this handoff.

The Agentic Wallet logged in by email is the receiving wallet and the buyer-side
TEE signer. Its X Layer address is already the configured `payTo` recipient.
That wallet session is distinct from the server-to-broker authentication used
by the OKX seller SDK during payment verification and settlement.

Important execution status as of 2026-07-23: the Polymarket caller-signed relay
path has been live-proven with a local private-key spike, but the normal
OKX Agentic Wallet email-session backend is not yet certified for Polymarket
order signing. Agentic Wallet funding/bridge operations are the intended caller
path; the remaining work is to prove CLOB L2 credential creation and POLY_1271
order signing through that wallet session without a raw private key.

The reviewed external data, backtesting, research-agent, and Polymarket
execution repositories are classified in
[`PREDICTION_MARKET_EXECUTION_RESEARCH.md`](PREDICTION_MARKET_EXECUTION_RESEARCH.md).
That inventory is an engineering input, not permission to install a bot or
enable funded execution.

The production execution and commercial-continuity architecture is defined in
[`LISTING_STABLE_MILLION_DOLLAR_EXECUTION_PLAN.md`](LISTING_STABLE_MILLION_DOLLAR_EXECUTION_PLAN.md).
It supersedes the earlier “start small” framing: Agent #5560 and its marketplace
history are to remain stable while a full execution platform is built behind a
backward-compatible endpoint. Do not edit the ASP record as part of ordinary
backend releases.

## Two workstreams continue in parallel

### A. Prove the paid oracle on mainnet

Do not enable payments until the operator installs the three OKX seller
credential variables directly on the VPS. Do not send them through chat. Then:

1. Run the complete production-compatible suite before restart.
2. Use `GET https://api.trueodd.xyz/v1/signals` as the primary marketplace
   review endpoint. It has safe defaults, so an unpaid body-free request can be
   replayed byte-for-byte after payment and return the service result.
3. Verify the unpaid response advertises x402 v2, X Layer `eip155:196`, USD₮0,
   the configured recipient, $0.01 price, and the intended timeout.
4. Ensure the external buyer has USD₮0 plus sufficient X Layer gas; gas alone
   is not the payment asset.
5. From that separate client, prove unpaid request -> valid HTTP 402 -> explicitly
   confirmed payment -> HTTP 200 oracle response.
6. If testing a raw-key buyer backend, keep the private key only in the buyer's
   local environment; never copy it to the VPS, repository, request body, logs,
   or chat. If testing OKX Agentic Wallet, use the local OnchainOS email/API-key
   session instead and do not create a private-key `.env`.
7. Confirm settlement to the recipient and prove the authorization cannot be replayed.
8. Confirm the paid response creates a linked oracle receipt.
9. Run external health, OpenAPI, docs, TLS, and rollback smoke tests.
10. Register the service as API/A2MCP+x402. Build A2A separately only if the
   chosen OKX listing type explicitly requires it.
11. While review runs, prepare the <=90-second demo, X post with `#OKXAI`, and
    submission form fields.
12. Seed genuine paid calls only through normal confirmed buyer flows; never
    fabricate orders, revenue, reviews, or users.

Required operator inputs are tracked in the callable-ASP build prompt. None may
be guessed by the coding agent.

### B. Let evidence accumulate automatically

The production `rwoo-evidence.timer` runs every six hours. It precommits priced
forecasts, checks finalized venue outcomes, performs supported NOAA station
concordance, and refreshes the calibration report. `rwoo-closing-quotes.timer`
commits the fresh scanner quotes every 30 minutes, while
`rwoo-closing-quotes-near.timer` targets only the final trading hour every five
minutes. Both write to the same locked append-only evidence chain.

Expected evidence sequence:

1. Correctly grouped forecasts are committed.
2. Venue results begin resolving after their underlying events finalize.
3. NOAA observations may arrive later; the source check stays pending until then.
4. The public report updates without manual selection.
5. The first formal weather review occurs only at 30 independent resolved events.

Do not count the initial legacy rows lacking new venue-resolution metadata toward
the promotion gate. Preserve them in the append-only ledger and label their
automatic-resolution limitation honestly.

## The 30-event checkpoint

Do not unlock execution merely because 30 events exist. Review all four numeric
criteria:

- independent weather groups >=30;
- Brier score <=0.20;
- maximum calibration gap <=0.15;
- venue/NOAA concordance >=95%.

Also review parser/entity incidents, source failures, confidence-band behavior,
forecast horizon, executable fees/slippage assumptions, and any model changes.
Record a dated GO / CONDITIONAL GO / NO-GO decision without moving the checkpoint.

## Work explicitly deferred until a checkpoint pass

- Authenticated Kalshi order submission.
- Funded activation of the production execution platform.
- Automatic promotion through predeclared capital tiers.
- Public claims based on realized trading performance.
- Promotion of economics or sports based on weather evidence.

The checkpoint controls whether that exact model family may receive capital; it
does not define the size of the execution system. Build the listing-stable
platform in parallel, then activate only families whose independent gates pass.
Every family remains subject to hard exposure/loss/drawdown limits and a global
kill switch.

## Post-Claude verification checklist

- [ ] Existing deterministic and evidence tests still pass.
- [ ] New API/frontend/payment tests pass.
- [ ] Three service schemas match their documentation.
- [ ] Unknown entities and ambiguous YES sides fail closed.
- [ ] Frontend reads live artifacts rather than hardcoded metrics.
- [ ] Calibration shows an honest insufficient-evidence state.
- [ ] Unpaid protected endpoints return a valid 402.
- [ ] Real confirmed payment replay returns 200 exactly once.
- [ ] Payment and oracle receipts are linked but private payment data is hidden.
- [ ] Domain, HTTPS, nginx, systemd, UFW, health, and rollback are verified.
- [ ] Other VPS tenants remain healthy.
- [ ] OKX listing fields and URLs are ready.
- [ ] Execution remains disabled for server-side funded submission.
- [ ] `submit-signed` relay remains non-custodial: callers send signed bytes +
      headers only; no private key, wallet export, email OTP, or CLOB secret is
      accepted by the ASP.
- [ ] OKX Agentic Wallet backend has a live test record before being advertised
      as executable: email login -> wallet address -> tiny funding route -> pUSD
      credit -> POLY_1271 order signature -> `submit-signed` -> rest/cancel.

## Genuine next starting point

When Claude returns, begin with a read-only code and deployment review. Do not
immediately approve deployment. Verify its tests, payment implementation, live
data binding, and security claims first. For the execution workstream, the next
external state-changing test is an OKX Agentic Wallet login in the local
OnchainOS session, followed by a tiny caller-owned funding/sign/rest/cancel
test. Do not provide a private key for this path.
