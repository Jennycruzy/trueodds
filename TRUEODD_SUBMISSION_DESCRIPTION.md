# TrueOdd — Submission Description

Paste the whole thing, or lift the labeled sections into matching form fields.

- **Project name:** TrueOdd (Real-World Odds Oracle)
- **OKX agent:** #5560 — https://www.okx.ai/agents/5560?source=search
- **Website:** https://trueodd.xyz
- **Playground (live demo, no wallet):** https://trueodd.xyz/playground
- **API docs:** https://api.trueodd.xyz/docs
- **Category:** AI agents · agent payments (x402) · prediction markets / DeFi data

---

## One-line pitch

TrueOdd is a paid probability oracle that AI agents call — and pay for automatically in crypto via x402 — to get an independent, verifiable estimate of the true odds of a real-world event, and see where the prediction market is mispriced.

---

## The problem

Prediction markets (Kalshi, Polymarket, Limitless) let people trade on the outcome of real-world events — elections, weather, inflation prints, sports. But their prices are just crowd sentiment, and crowds are frequently wrong or slow to update.

An autonomous trading agent operating on these markets faces two hard gaps:

1. **No independent ground truth.** The agent sees the market's price, but has no trustworthy, model-driven estimate of what the probability actually is — so it can't tell a real edge from noise.
2. **No way to buy that estimate machine-to-machine.** Even if a good probability service existed, an agent can't sign up, add a credit card, and manage an API key. It needs to discover the service and pay for a single call, autonomously, with no human in the loop.

TrueOdd closes both gaps.

---

## What TrueOdd does

TrueOdd continuously scans live prediction markets, computes its own **independent probability** for each event from real-world data sources, and reports where its estimate and the market's implied price **meaningfully disagree**. That gap — after costs — is the edge, and it's the core product.

An agent can:
- **Rank opportunities** — get the best current signals across supported markets.
- **Check one market** — get probability, uncertainty, executable-price expected value, a source trace, calibration, and a receipt.
- **Compare across venues** — find the same contract priced differently on Kalshi vs. Polymarket vs. Limitless, with rule/resolution equivalence verified.
- **Inspect calibration** — see, for free, how the oracle's past forecasts have actually scored against real outcomes.

---

## Why the number can be trusted (the core design principle)

Every probability is produced by **deterministic engines — never by an LLM.** A language model may route a request or narrate an explanation, but it can never create, alter, veto, or "sanity-check" a probability. This is enforced as a hard rule ("the Deterministic-Core Law"):

- Deterministic code produces every probability.
- If the exact resolution rule, settlement source, resolution time, entity/strike, or which side "YES" prices **cannot be bound**, the oracle **refuses** rather than guesses. Ambiguous and unsupported markets **fail closed**.
- Missing data stays missing — never silently becomes zero.
- Every result identifies its exact model version.
- Model agreement is never presented as empirical calibration; losses are kept and published, not hidden.

This is what separates TrueOdd from "ask an LLM what it thinks the odds are." The answer is auditable, reproducible, and honest about what it doesn't know.

---

## How it lives on OKX

TrueOdd is published on the **OKX agent marketplace as Agent #5560**, so other agents can discover and call it directly. Payment runs on the **OKX Agent Payments Protocol, which is x402-compatible** — the calling agent's wallet settles the charge automatically at request time. No accounts, no API keys, no invoices.

---

## How it runs — end to end

1. **Request.** An agent calls a paid endpoint (e.g. `POST /v1/check-market`) with a market object (venue + market id).
2. **402 challenge.** The API responds `HTTP 402 Payment Required` with a signed price quote in a `PAYMENT-REQUIRED` header. This is the x402 challenge — not an error.
3. **Pay.** The agent's wallet signs the challenge and resends the *identical* request with a `PAYMENT-SIGNATURE` header.
4. **Priced answer.** The API returns `HTTP 200` with the independent probability, an uncertainty interval, the executable-price expected value after fees, a source/why trace, calibration context, and a receipt.
5. **Receipt committed.** The decision is hash-committed into an **append-only, tamper-evident ledger**, linked by request id. A receipt exists whether or not the market later resolves.
6. **Resolve & calibrate.** When the market settles, the outcome is scored against the precommitted forecast and the public calibration record updates.

---

## Verifiability

Every priced or refused decision is written to a **keccak256 hash-chained ledger**. Any later edit to a past result breaks the chain and is detectable. The buyer takes their receipt hash and verifies it against the chain **themselves** — they never have to trust the operator. Public calibration pages show precommitted vs. resolved forecasts and how the odds have actually performed, with families that haven't hit a checkpoint honestly marked as still accumulating.

---

## Coverage today

- 🌦 **Weather** — daily temperature maxima/minima and precipitation for verified stations; NOAA-resolved Atlantic hurricane season count thresholds.
- 📊 **Economics** — headline & core CPI, GDP, unemployment, payrolls, Fed rate decisions, recession-quarter nowcasts, against official releases.
- 🔥 **Energy** — Henry Hub natural gas (EIA-resolved daily spot-price thresholds).
- ⚽ **Sports** — World Cup 2026 winner and stage-of-elimination markets; selected tennis, MLB, and club-soccer engines. Unsupported sports/props fail closed.

Anything whose rule, source, timing, entity, strike, or YES side can't be bound is deliberately deferred rather than faked.

---

## Tech summary

- **API:** paid endpoints `rwoo.best_signals`, `rwoo.check_market`, `rwoo.cross_venue_edge`; free `rwoo.get_calibration`.
- **Payments:** x402 / OKX Agent Payments Protocol (402 challenge → wallet-signed retry → 200), with replay protection (nonce) and payment verification.
- **Probability engines:** deterministic, versioned, real-world-source-driven; LLM confined to routing/narration.
- **Integrity:** append-only evidence and receipt ledgers; keccak256 chaining; public calibration.
- **Venues:** Kalshi, Polymarket, Limitless.

---

## What we're looking for / next

Feedback from builders, traders, and prediction-market participants on which venues, data sources, and market families to add next, and how to make the output drop-in usable inside production trading agents. Try it against markets you know at https://trueodd.xyz.

---

## Honest scope note

The public site and Playground demonstrate the real product output and the genuine live x402 `402` challenge without requiring a wallet. A full paid call (`402` → wallet signs → `200` → receipt verifies on-chain-style against the ledger) is executed by a funded OKX buyer agent. Probabilities are estimates, not guarantees — no forecast is guaranteed to win, and calibration is reported with losses included.
