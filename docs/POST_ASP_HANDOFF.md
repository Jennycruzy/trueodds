# Post-ASP Handoff: What Happens After Claude Finishes

Last updated: 2026-07-10  
Current live report: 777 precommitted forecasts, 0 resolved, valid ledger,
weather checkpoint locked at 0/30 independent resolved events.

## Two workstreams continue in parallel

### A. Launch the paid oracle now

The ASP does not need to wait for 30 weather events to launch. After Claude
finishes the pages and endpoints, complete these steps in order:

1. Review Claude's diff; preserve the deterministic engine and all 94+ tests.
2. Supply the operator-controlled domain and DNS access.
3. Supply the OKX payment recipient, approved network/asset, and per-call prices.
4. Deploy the frontend and API behind dedicated HTTPS hostnames.
5. Verify internal API/frontend ports are not public.
6. From a separate client, prove unpaid request -> valid HTTP 402 -> explicitly
   confirmed payment -> HTTP 200 oracle response.
7. Confirm the payment settles to the configured recipient and cannot be replayed.
8. Confirm the paid response creates a linked oracle receipt.
9. Run external health, OpenAPI, docs, mobile, TLS, and rollback smoke tests.
10. Register the three services and submit the ASP for OKX.AI review.
11. While review runs, prepare the <=90-second demo, X post with `#OKXAI`, and
    submission form fields.
12. Seed genuine paid calls only through normal confirmed buyer flows; never
    fabricate orders, revenue, reviews, or users.

Required operator inputs are tracked in the callable-ASP build prompt. None may
be guessed by the coding agent.

### B. Let evidence accumulate automatically

The production `rwoo-evidence.timer` runs every six hours. It precommits priced
forecasts, checks finalized venue outcomes, performs supported NOAA station
concordance, and refreshes the calibration report.

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
- Micro-stake funded weather execution.
- Automatic stake sizing.
- Public claims based on realized trading performance.
- Promotion of economics or sports based on weather evidence.

After a pass, build a disabled-by-default, operator-approved, weather-only
execution adapter with hard exposure/loss/drawdown limits and a kill switch.

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
- [ ] Execution remains disabled.

## Genuine next starting point

When Claude returns, begin with a read-only code and deployment review. Do not
immediately approve deployment. Verify its tests, payment implementation, live
data binding, and security claims first. The first external state-changing step
after that review is operator-approved domain/DNS configuration; the first money
step is a deliberately confirmed small end-to-end paid API call.
