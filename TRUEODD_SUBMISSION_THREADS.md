# TrueOdd — X Threads

Two threads. Copy each post and publish it as a reply to the one before it.
Swap in live numbers from the site before posting where a post says `[…]`.

- Agent: **Real-World Odds Oracle (TrueOdd)** — OKX.AI Agent **#5560**
- OKX: https://www.okx.ai/agents/5560?source=search
- Site: https://trueodd.xyz · Playground: https://trueodd.xyz/playground · Docs: https://api.trueodd.xyz/docs

---

# Thread A — Hackathon submission

## 1/7
Our submission: **TrueOdd** — a probability oracle that AI agents pay, in crypto, to learn the true odds of a real-world event.

Live on OKX as Agent #5560. Real markets, real x402 payments, verifiable receipts.

https://www.okx.ai/agents/5560?source=search

## 2/7
**The problem.**

Prediction markets (Kalshi, Polymarket, Limitless) are priced by the crowd. Crowds are often wrong. An agent that wants to trade them has no trustworthy, independent estimate of what the odds *actually* are — and no way to buy one.

## 3/7
**What TrueOdd does.**

It scans live markets, computes an independent probability for each from real-world data, and surfaces where its estimate and the market's price meaningfully disagree.

That gap is the edge. It's the whole product.

## 4/7
**Why you can trust the number.**

Every probability comes from deterministic code — never an LLM. If the rule, source, deadline, entity, or YES side can't be pinned down, it refuses instead of guessing.

Ambiguous markets fail closed. Losses are kept, not hidden.

## 5/7
**How an agent buys it (the x402 part).**

Agent calls the API → gets `HTTP 402 Payment Required` with a price quote → its wallet signs the payment → resends the same request → gets the priced answer + a receipt.

Machine-to-machine payments, no human, no invoice.

## 6/7
**Proof, not promises.**

Every answer is hash-committed to an append-only ledger. Edit a past result and the chain breaks. The buyer verifies their receipt themselves — they never have to trust us.

Calibration is public and scored against real outcomes.

## 7/7
Try it in the browser — no wallet needed to see the live 402 challenge:

▶️ Playground: https://trueodd.xyz/playground
📊 Markets & edge: https://trueodd.xyz/markets
📜 Docs: https://api.trueodd.xyz/docs

Feedback from builders and traders very welcome.

---

# Thread B — Live on OKX

## 1/8
TrueOdd is **live on OKX** as Agent #5560. 🟢

It's a paid probability oracle any AI agent on OKX can call to get an independent, verifiable estimate of the true odds of a real-world event — and pay for it automatically, in crypto.

https://www.okx.ai/agents/5560?source=search

## 2/8
**The problem it solves.**

Prediction-market prices are just crowd sentiment. An autonomous agent trading them needs a second, independent opinion on the real probability — and a way to pay for that opinion without a human in the loop.

Neither existed. That's the gap.

## 3/8
**How the agent solves it.**

TrueOdd watches live markets across Kalshi, Polymarket and Limitless, and for each one computes its own probability from real-world sources — weather data, economic releases, energy prices, sports models.

Then it reports where the model and the market disagree.

## 4/8
**It's disciplined, not chatty.**

The probability is produced by deterministic engines, not a language model. An LLM may route or narrate, but it can never create or override a number.

Can't bind the exact rule, source, or resolution time? It refuses. No guessing.

## 5/8
**How it lives on OKX.**

It's published on the OKX agent marketplace, so other agents can discover and call it directly. Payment runs on the **OKX Agent Payments Protocol (x402)** — the agent's wallet settles the charge automatically at call time.

## 6/8
**How it runs, end to end.**

1. Agent requests a price
2. API replies `402` with a signed quote
3. Wallet pays, request is resent
4. TrueOdd returns probability, uncertainty, executable-price edge, and a receipt
5. Receipt is committed to a tamper-evident ledger

## 7/8
**Verifiable by design.**

That receipt hash chains into an append-only ledger. Any later edit to a past decision breaks the chain and is detectable. The buyer checks their receipt against the chain themselves.

Public calibration shows how the odds have actually scored over time.

## 8/8
Coverage today: 🌦 weather · 📊 economics (CPI, GDP, jobs, rates) · 🔥 Henry Hub natural gas · ⚽ sports incl. World Cup 2026.

Call it on OKX → https://www.okx.ai/agents/5560?source=search
See it work → https://trueodd.xyz
