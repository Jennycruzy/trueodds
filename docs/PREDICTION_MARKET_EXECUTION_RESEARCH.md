# Prediction-Market Execution Research Inventory

Last reviewed: 2026-07-21

## Decision summary

The supplied repositories are useful, but none should be installed directly on
the production VPS or treated as proof that funded execution is ready.

This inventory now feeds the production-scale architecture in
[`LISTING_STABLE_MILLION_DOLLAR_EXECUTION_PLAN.md`](LISTING_STABLE_MILLION_DOLLAR_EXECUTION_PLAN.md).
That plan supersedes the earlier small-sample/micro-canary product framing. The
commercial objective is a complete execution platform behind a stable OKX.AI
identity and endpoint; capital remains interlocked until the production path is
certified.

The recommended path is:

1. Keep RWOO's deterministic signal, evidence, calibration, and execution
   interlock as the authority.
2. Prototype the venue adapter against Polymarket's current official unified
   Python SDK, not an unreviewed autonomous bot and not the archived
   `py-clob-client`.
3. Use the large historical datasets and a backtesting engine in an isolated
   research environment after building and testing a point-in-time schema
   adapter.
4. Borrow risk, reconciliation, monitoring, and paper/live separation patterns
   from the third-party bots; do not import their strategies or key-management
   practices blindly.
5. Keep LLM/web-research tools upstream of the deterministic model. Their output
   may become cited evidence or a human-review prompt, but must never mutate a
   probability or trigger an order directly.

No package from this inventory has been installed, no dataset has been
downloaded, and no live-trading setting has been enabled.

## Important correction to the email claims

The 107 GB and 36 GiB repositories are trade/fill and market-metadata datasets.
Their public descriptions do not establish that either dataset works
"perfectly" with `prediction-market-backtesting` without transformation.
RWOO needs an explicit adapter for market/outcome identity, YES/NO orientation,
timestamps, fees, splits/merges, resolution, and decimal precision.

More importantly, historical fills are not a complete historical order book.
They do not by themselves reproduce cancelled orders, queue position, resting
liquidity, or the fill probability of our own limit order. A fill-only backtest
can test directional ideas, but it cannot honestly validate production
execution quality. Full-depth point-in-time snapshots/deltas and latency-aware
fill simulation are a separate requirement.

## Recommended components

### 1. Official Polymarket SDK — preferred adapter baseline

- Source: [Polymarket/py-sdk](https://github.com/Polymarket/py-sdk)
- Status: official, MIT, currently beta.
- Use: isolated adapter prototype for public data, authenticated account state,
  order placement/cancellation, and order/fill reconciliation.
- Do not use the archived
  [Polymarket/py-clob-client](https://github.com/Polymarket/py-clob-client);
  Polymarket marks it non-functional for new and existing integrations and
  directs new work to the unified SDK.
- Engineering guard: represent prices, sizes, and fees with `Decimal`/integer
  base units. Do not allow binary floating-point values into signing or tick
  validation.
- Release guard: pin an exact prerelease version and commit hash, run contract
  tests against a non-funded or metered test setup, and require a reviewed SDK
  upgrade before changing the pin.

### 2. SII-WANGZJ/Polymarket_data — primary large-scale research dataset

- Source: [SII-WANGZJ/Polymarket_data](https://github.com/SII-WANGZJ/Polymarket_data)
- Claimed coverage: 107 GB, 1.1 billion records, 268K+ markets; raw
  `OrderFilled` logs, processed trades, normalized YES-side data, user-level
  data, and market metadata.
- License: MIT according to the repository.
- Best use: market microstructure research, maker/taker behavior, trader
  cohorts, fee studies, and directional walk-forward evaluation.
- Precision caveat: the inspected processing path converts integer fill
  amounts to Python `float`, rounds price to six decimals, and rounds token/USD
  amounts to two decimals. Use raw `OrderFilled` base units for authoritative
  execution and fee studies; treat the processed/quant files as analytical
  convenience layers that need independent precision checks.
- Do not download the dataset to the production VPS. Ingest the full useful
  universe as versioned partitions in a separate research worker/object store;
  use `markets.parquet` and bounded partitions only for adapter unit and
  recovery tests, not as the scale of the product validation.
- Validate its claimed completeness independently by block-range sampling and
  contract-address checks before using it as evidence.

### 3. prediction-market-backtesting — candidate replay harness

- Source: [evan-kolberg/prediction-market-backtesting](https://github.com/evan-kolberg/prediction-market-backtesting)
- Architecture: NautilusTrader extension using Python/Rust, book replay, trade
  ticks, multi-portfolio runners, optimizers, and a live sandbox path.
- Status: the repository labels the newest live sandbox work `4.1-alpha`.
- License: mixed licensing; review file-level boundaries before copying or
  distributing anything.
- Best use: isolated proof of concept for event replay, execution-cost models,
  order-state handling, and portfolio-level simulations.
- Required qualification: prove deterministic schema conversion on a fixed
  contract-test fixture, then run the complete supported historical universe
  through versioned, restartable partitions. Do not commit to this framework
  until the adapter, licensing, and full-scale resource use are understood.

### 4. Jon-Becker/prediction-market-analysis — cross-venue validation dataset

- Source: [Jon-Becker/prediction-market-analysis](https://github.com/Jon-Becker/prediction-market-analysis)
- Coverage: Polymarket and Kalshi market metadata/trades, Parquet storage,
  resumable collectors, and a 36 GiB compressed download.
- License: MIT.
- Best use: cross-check the SII dataset, test cross-venue contract matching,
  validate older market coverage, and reproduce published analysis scripts.
- Do not assume the compressed size is the required disk footprint after
  extraction.

### 5. PMXT — useful interface reference, not the production signer

- Source: [pmxt-dev/pmxt](https://github.com/pmxt-dev/pmxt)
- Architecture: MIT unified read/trade API across prediction-market venues,
  with Python, TypeScript, CLI, MCP, hosted writes, and a self-host option.
- Value: its CCXT-like adapter surface is a good reference for a future RWOO
  venue protocol and for read-only cross-venue normalization.
- Blocker: the sidecar accepts raw private keys in per-request credentials, its
  WebSocket exchange cache constructs keys containing credential values, and
  the inspected Polymarket market-order example supplies no explicit maximum
  price. The unified implementation also converts order amounts and venue
  responses through JavaScript numbers/`parseFloat`. Those choices are
  incompatible with RWOO's isolated-signer, exact-arithmetic execution policy.
- Decision: prototype only in a disposable, unfunded environment if it saves
  adapter work. Production should use our own risk gateway and signer boundary;
  never send an RWOO private key to a hosted third-party write service.

### 6. PolyWeather — weather-source and UX comparison only

- Source: [yangyuan-zhen/PolyWeather](https://github.com/yangyuan-zhen/PolyWeather)
- Value: aviation observations, runway/weather alerting, source cadence,
  settlement-station UX, health/metrics, and realtime patch patterns can inform
  RWOO's weather evidence and operations review.
- License: AGPL-3.0. Treat it as an external comparison unless the team accepts
  the license obligations; do not copy code into RWOO casually.
- It is not the Polymarket order adapter RWOO is missing.

## Architecture references — inspect, do not install wholesale

### ent0n29/polybot

- Source: [ent0n29/polybot](https://github.com/ent0n29/polybot)
- MIT Java 21 microservices with paper/live execution, strategy, ingestion,
  ClickHouse, Redpanda, Grafana, Prometheus, and Alertmanager.
- Borrow: paper/live separation, event-driven order state, observability, and
  replication-analysis concepts.
- Reject for this host: the stack is much heavier than RWOO and is a poor fit
  for the current 8 GB/no-swap VPS, which has already OOM-killed a quote job.

### HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits

- Source: [HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits](https://github.com/HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits)
- MIT Rust code organized around a venue adapter, common execution core, risk
  layer, strategies, and UI/service modules.
- Borrow: adapter traits, shared risk layer, deterministic strategy/execution
  separation, and Rust concurrency ideas.
- Do not borrow the current order truth or numeric model. The inspected
  executor continues when its risk guard returns `FetchBook` instead of
  actually performing the required depth check, records a position after POST
  even when the order ID is optional, and keeps position/exposure state in an
  in-memory `HashMap` of `f64` values. Its breaker also clears after a timed
  cooldown. Repository claims such as "production-grade" are not independent
  verification.

### alsk1992/CloddsBot

- Source: [alsk1992/CloddsBot](https://github.com/alsk1992/CloddsBot)
- MIT and feature-rich, with order building, balance/slippage/fees, PnL,
  settlement polling, credential modules, execution modules, and many venues.
- Borrow: capability inventory and operator UX ideas.
- Do not adopt wholesale: it is a very broad autonomous terminal originally
  built rapidly for a hackathon, mixes many unrelated chains/products, and
  expands the secret and dependency attack surface far beyond RWOO's needs.

### lihanyu81/polymarket_lp_tool

- Source: [lihanyu81/polymarket_lp_tool](https://github.com/lihanyu81/polymarket_lp_tool)
- Useful for order monitoring, post-only behavior, midpoint-jump filters,
  cooldowns, WebSocket-first updates, and fill-detection test cases.
- It is an LP/repricing tool, not a directional YES execution adapter. Its
  Python path explicitly expects the initial order to be created manually.
- Do not adopt its replacement or risk defaults. The inspected cancel/replace
  path retries replacement posting forever when `max_retries=0` (the default)
  without reconciling an ambiguous submission first, uses floating-point order
  values, and treats position API failure as zero inventory. Those are
  duplicate-order and fail-open exposure risks.
- No recognized repository license was visible during this review. Treat the
  code as reference-only unless a valid license is confirmed.

### MrFadiAi/Polymarket-bot

- Source: [MrFadiAi/Polymarket-bot](https://github.com/MrFadiAi/Polymarket-bot)
- MIT bot advertising daily/monthly/drawdown/total-loss controls and dynamic
  sizing.
- Borrow: risk-control test cases, not strategy claims.
- Caveats: small public history, direct private-key configuration, and no
  independent validation of the advertised win-rate/strategy behavior.

### warproxxx/poly_data

- Source: [warproxxx/poly_data](https://github.com/warproxxx/poly_data)
- Current v2 collector reads exchange events through Envio HyperSync, joins
  CLOB metadata, supports chunked processing, and warns that its older Goldsky
  path is incomplete after the 2026 contract migration.
- Value: optional incremental collector or a second implementation for data
  completeness checks.
- License: GPL-3.0. Prefer an isolated data pipeline or independent
  implementation after license review.

## Optional research enrichment — never an execution authority

### TradingAgents

- Source: [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
- Apache-2.0 multi-agent research/debate framework with news, sentiment,
  fundamentals, technical analysis, and risk roles.
- It now mentions Polymarket as a data vendor, but the framework is broader
  financial analysis rather than a verified prediction-market executor.
- Possible use: produce a cited research appendix for human review. Its output
  must not alter deterministic RWOO probabilities or bypass promotion gates.

### last30days-skill

- Source: [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill)
- MIT agent skill for recent Reddit/X/YouTube/HN/Polymarket/web synthesis.
- Possible use: topic discovery and emerging-news context with source URLs and
  timestamps. Social popularity is not probability evidence by itself.

### gpt-researcher

- Source: [assafelovic/gpt-researcher](https://github.com/assafelovic/gpt-researcher)
- Apache-2.0 general deep-research framework.
- Possible use: asynchronous evidence packets for markets whose settlement
  rules are already understood. Every factual claim still needs provenance,
  freshness, and an explicit cutoff timestamp.

### Pydantic AI

- Source: [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai)
- MIT production agent framework with typed tools, graphs, and evaluation
  components.
- RWOO already has deterministic Python services. Do not add a framework merely
  to place an order; reconsider only if typed multi-agent research orchestration
  becomes a real product requirement.

### Awesome Prediction Market Tools

- Source: [aarora4/Awesome-Prediction-Market-Tools](https://github.com/aarora4/Awesome-Prediction-Market-Tools)
- Keep as a discovery bookmark. Inclusion is not a security, performance,
  licensing, or accuracy endorsement; audit every downstream project separately.

## Required RWOO execution boundary

The production contract must cover the complete order lifecycle behind a
stable marketplace endpoint. The first publicly enabled money action may be an
explicit Polymarket YES limit buy, but it is part of the full durable execution
platform—not a disposable adapter or a reason to edit the ASP again later.

```text
signed RWOO decision receipt
        -> execution eligibility bridge
        -> fresh market/rule/token/order-book verification
        -> deterministic policy and exposure checks
        -> immutable order intent + idempotency key
        -> isolated Polymarket adapter
        -> isolated signer
        -> venue acknowledgement
        -> order/fill/cancel reconciliation
        -> append-only trade receipt and P&L lifecycle
```

Hard requirements:

- A decision marked `actionable` is not automatically executable.
- Family promotion must be eligible and its execution interlock unlocked.
- The request must identify event group, correlation group, market, YES outcome
  token, maximum price, maximum USDC, expiry, and operator/policy approval.
- Re-fetch and revalidate the market, resolution rule, YES binding, tick size,
  book depth, edge after current costs, staleness, balance, and allowance just
  before signing.
- Limit orders only for the first release. No example-derived 30% slippage and
  no unrestricted market orders.
- Use exact decimal/base-unit arithmetic.
- Enforce one idempotency key across retries; a timeout must reconcile venue
  state before any resubmission.
- Record submitted, acknowledged, partially filled, filled, cancelled,
  rejected, expired, and reconciled states. Never infer a fill from submission.
- Place the signer outside the public API process, under a dedicated non-root
  identity with a narrowly scoped wallet and spend policy. Never expose a raw
  key to prompts, logs, receipts, hosted third parties, or shell history.
- Preserve current per-event, correlated-exposure, daily-exposure, weekly-loss,
  drawdown, and kill-switch controls. Add max open orders and stale-order
  cancellation.
- Fail closed if the receipt, promotion report, clock, market binding, venue
  status, signer, or reconciliation path is unavailable.

## Production certification gate

Before funded activation, the research and execution pipelines must prove all
of the following on fixed, versioned data snapshots and at the capacity implied
by the revenue model:

1. No look-ahead: features, market state, and resolution information are
   timestamped and available before the simulated order.
2. Stable identity: market, outcome token, resolution rule, and YES orientation
   are bound exactly and reject ambiguity.
3. Realistic execution: latency, tick size, fees, spread, available depth,
   partial fills, queue assumptions, cancellation, and settlement are explicit.
4. Walk-forward evaluation: train/tune/test windows and strategy selection are
   fixed before the holdout; related thresholds stay in one event group.
5. Baselines: compare against market probability, no-trade, and simple fixed
   rules; report all candidates, not only wins.
6. Stress tests: stale book, crossed/empty book, API timeout, duplicate request,
   adverse move, partial fill, balance/allowance failure, and venue halt.
7. Reproducibility: dataset hashes, code commit, configuration, random seeds,
   and output receipt hashes are retained.

## Production release train

1. Freeze the Agent #5560 marketplace record and capture its exact service,
   price, endpoint, status, usage, reviews, and wallet evidence.
2. Approve one backward-compatible operation envelope covering discovery,
   evaluation, preparation, execution, status, cancellation, and calibration.
3. Build durable payment, usage, intent, order, fill, settlement, P&L, and audit
   ledgers before connecting a funded wallet.
4. Build the deterministic risk service, isolated signer, official-SDK venue
   adapter, user WebSocket path, REST reconciler, cancellation, and recovery.
5. Ingest and normalize the full useful historical universe outside the VPS;
   run L2 replay, walk-forward, stress, restart, duplicate, unknown-outcome,
   and capacity certification.
6. Certify the same production binaries and state machine with capital
   interlocked. This is pre-production certification, not a separate mock.
7. Resolve all model-family, custody, security, SLO, disaster-recovery, and
   operator-authorization gates.
8. Activate funded execution under predeclared capital tiers. Scale through
   internal policy and feature flags without changing the ASP identity for each
   release.

## Production-host constraint

The current VPS has approximately 8 GB RAM, no swap, and recent OOM kills in a
quote-capture worker. Large dataset processing, ClickHouse/Redpanda stacks,
multi-agent research crawlers, and third-party bot suites must not be added to
that host. Keep production execution minimal and move research/backtests to a
separate worker or managed batch environment.
