# TrueOdd Listing-Stable, Revenue-Scale Execution Plan

Last reviewed: 2026-07-21

## North star

TrueOdd is not a mock, a paper-trading demo, or a small experimental bot. The
product target is an autonomous prediction-market business that can turn a
paid, receipt-backed decision into a real YES order without sending the buyer
to another interface.

The architecture must support that ambition without repeatedly changing the
OKX.AI marketplace record. Agent **#5560**, its accumulated marketplace
history, its public hostname, and its callable contract are commercial assets.
Backend releases must not be coupled to ASP identity edits.

[OKX.AI's current public language](https://www.okx.ai/) explicitly frames the
opportunity as “one person, one company, $1M a year.” The official
[ASP introduction](https://web3.okx.com/onchainos/dev-docs/okxai/asp-introduction)
states that A2MCP calls settle per call and A2A work supports negotiated
delivery. The engineering and revenue model therefore need to be designed
together.

Primary-source note: the current public
[OKX.AI Genesis page](https://web3.okx.com/xlayer/build-x-series) verifies a
Revenue Rocket award based on qualified revenue, orders, and positive reviews.
The pages reviewed did not expose a separate public rule awarding a prize to
the first ASP to cross $1M in generated revenue. Treat that specific race as a
team-supplied target until its official terms/link are archived; do not weaken
the $1M operating target while that evidence is collected.

## Correction to the previous plan

The earlier “start with 50–100 markets, then one micro-stake canary” sequence
was too small as a product plan. It confused safe capital activation with small
system ambition.

The corrected operating model is:

- Build the complete production execution path, capacity model, revenue
  ledger, and full-dataset validation system in one release train.
- Exercise the same binaries, schemas, ledgers, signer boundary, and
  reconciliation path during certification that will run after launch.
- Keep capital disabled until certification passes; this is a production
  interlock, not a mock implementation.
- Once enabled, scale capital and throughput through predeclared risk tiers and
  feature flags. Do not change the ASP listing for each capability release.
- Never present a backtest, simulated fill, or unsigned intent as a live order.

Large ambition does not justify unknown-outcome resubmission, unrestricted
keys, hidden leverage, or bypassing an evidence gate. A million-dollar service
needs stronger accounting and failure handling than a hobby bot, not weaker
controls.

## Marketplace continuity rule

### Freeze the commercial identity

The following form the marketplace control plane and should be treated as
frozen configuration:

- OKX.AI Agent ID **5560**;
- public brand and category;
- durable service name and capability promise;
- production hostname `api.trueodd.xyz`;
- marketplace-facing endpoint;
- payment rail and published price;
- service identifier and ownership wallet.

An ordinary code deployment, model upgrade, new venue adapter, risk-policy
change, or database migration must not require an identity update. Registry
updates can return an ASP to review and temporarily remove it from the live
marketplace. The observed effect on visible usage counters makes unnecessary
edits commercially unacceptable even if the platform later restores the
underlying history.

Before any future registry change, save a dated evidence pack containing the
agent page, service IDs, exact fields, price, endpoint, status, sales/usage,
reviews, wallet, and public URLs. Store the response payload as well as
screenshots. This is operational evidence, not a substitute for the platform's
own ledger.

### One final expansion only if honesty requires it

Execution must not be hidden behind a listing whose wording promises only
read-only research. First compare the exact registered service description
with the proposed execution contract.

- If its existing language already covers decision and execution
  orchestration, keep the registry unchanged and ship the new behavior as a
  backward-compatible API capability.
- If the listing would become materially misleading, finish and certify the
  full execution product first, then make one deliberate, complete expansion
  of the marketplace wording. Expect review, preserve the pre-change evidence
  pack, and freeze the record again after approval.
- Do not make a sequence of incremental listing edits while the backend is
  being built.

This is a commercial change-control decision. It must be made from the exact
live Agent #5560 record, not from a draft or a local submission document.

## Stable public contract

The marketplace should point to one durable gateway. Capability evolution
happens behind that gateway through additive schema versions.

The request envelope should support these stable operations from the outset:

- `discover`: ranked, paid opportunities;
- `evaluate`: one market with evidence, costs, and a decision receipt;
- `prepare_execution`: fresh venue checks plus a deterministic executable
  intent;
- `execute`: submit an authorized intent;
- `get_execution`: retrieve acknowledgement, fills, cancellation, settlement,
  and P&L state;
- `cancel_execution`: cancel remaining quantity when venue state permits;
- `get_calibration`: public performance evidence.

Existing `/v1/signals` behavior remains backward compatible. A missing
operation keeps today's safe default. Every request and response carries a
contract version; new optional fields do not break older callers. Breaking
changes use a new API version behind the same hostname, not an ASP identity
edit.

The API must separate three things that are often incorrectly collapsed:

1. a research signal;
2. an authorized order intent;
3. a venue-acknowledged or filled order.

Only the third is execution. Paid delivery receipts, order receipts, venue
receipts, and settlement receipts must link to one correlation ID without
claiming that payment for analysis funded the trade itself.

## Production architecture

```text
OKX.AI Agent #5560 / x402
            |
            v
stable API gateway + billing/usage ledger
            |
            +--> deterministic intelligence and evidence plane
            |
            +--> execution orchestrator --> deterministic risk service
                                      |                |
                                      |                +--> policy / exposure store
                                      v
                              durable intent ledger
                                      |
                                      v
                              isolated signer service
                                      |
                                      v
                         pinned Polymarket venue adapter
                                      |
                         REST acknowledgement + user WS
                                      |
                                      v
                         reconciler / positions / settlement
                                      |
                                      v
                      append-only order, P&L, and audit receipts
```

### Immutable marketplace plane

This plane contains Agent #5560, service discovery, pricing, the stable
endpoint, and the payment protocol. Its job is continuous availability and
commercial continuity. It should change rarely.

### Mutable capability plane

This plane contains model releases, market adapters, execution workers,
reconciliation, analytics, capacity, and feature flags. It uses blue/green
deployments and backward-compatible schemas. It can improve daily without
changing the marketplace identity.

### Isolated signing plane

The public API never holds a raw venue key. The signer runs under a dedicated
non-root identity, accepts only a canonical order digest plus an already
approved policy decision, and enforces wallet, venue, chain, token, notional,
price, and expiry limits independently. It cannot browse the web, execute a
shell, or accept prompt text.

For a multi-user service, prefer user-owned wallet authorization or narrowly
scoped delegated policies. Do not commingle customer trading capital with ASP
revenue. The ASP fee, venue collateral, gas, venue fees, and realized trading
P&L require separate ledgers.

### Durable execution plane

Orders cannot live only in process memory. Store intent and state transitions
transactionally in a durable database before submission. A worker crash,
deploy, WebSocket disconnect, or venue timeout must resume reconciliation from
the ledger without duplicating the order.

Required state model:

```text
RECEIVED -> VALIDATED -> AUTHORIZED -> SIGNED -> SUBMITTING
                                           |          |
                                           |          +-> ACKNOWLEDGED
                                           |          +-> UNKNOWN
                                           |          +-> REJECTED
                                           v
                                    policy-expired/blocked

ACKNOWLEDGED -> OPEN -> PARTIALLY_FILLED -> FILLED -> SETTLED
                    \-> CANCEL_PENDING -> CANCELLED
                    \-> EXPIRED

UNKNOWN -> reconcile by deterministic signed-order hash / account state
        -> ACKNOWLEDGED, REJECTED, or OPERATOR_REVIEW
```

`UNKNOWN` is a first-class state. It must never trigger blind resubmission.

## Autonomous execution contract

The buyer should not need a manual hop to Polymarket. Autonomy comes from an
explicit wallet policy, not from silently spending whatever is available.

An executable request must bind:

- tenant/user and policy ID;
- source decision receipt and exact model version;
- venue, chain, event, market, condition, and YES token;
- resolution rule hash and close time;
- side, order type, maximum price, maximum total spend, and expiry;
- maximum fee/slippage budget and minimum net edge;
- event group and correlation group;
- idempotency key and request nonce;
- approved wallet or delegated authorization;
- policy and code version used for the decision.

Immediately before signing, the risk service re-fetches the market and book,
proves the YES binding again, verifies tick size and minimum size, recalculates
cost-adjusted edge, and checks balance, allowance, open orders, exposure,
drawdown, loss, concentration, venue health, time sync, and kill switches.

The public capability can launch with YES limit buys while the stable contract
already covers the entire order lifecycle. That is a deliberate commercial
action, not a toy adapter. Further order types are enabled behind policy only
after their execution semantics and failure cases are certified; they do not
require a new marketplace identity.

## Risk system built for scale

Risk is a separate deterministic service and a second line of defense in the
signer. Minimum controls are:

- per-order, per-market, per-event, per-family, per-venue, per-user, and global
  exposure;
- correlated-event aggregation rather than counting related contracts as
  diversification;
- maximum open orders and maximum unacknowledged submissions;
- daily and weekly loss, peak-to-trough drawdown, and capital-at-risk limits;
- stale-book, spread, depth, price-impact, and minimum-edge constraints;
- close-time and settlement-window guards;
- venue/API/WS health and clock-skew guards;
- manual global kill, automated global kill, and tenant-level suspend;
- cancel-on-stale and cancel-on-policy-revocation;
- manual reset for capital-loss and unknown-state breakers. A timer must not
  automatically re-enable trading after a serious trip.

Capital tiers are predeclared in policy and promoted by measured performance,
operational health, and reconciliation quality. Tier changes are internal
policy events with audit receipts, not listing edits.

## Revenue architecture

A $0.01 service needs **100,000,000 settled paid calls** to generate $1,000,000
of gross ASP revenue. That price is useful for distribution, but it cannot be
the only commercial engine.

| Average recognized revenue | Deliveries needed for $1M |
| ---: | ---: |
| $0.01 | 100,000,000 |
| $0.10 | 10,000,000 |
| $0.50 | 2,000,000 |
| $1.00 | 1,000,000 |
| $5.00 | 200,000 |
| $25.00 | 40,000 |

The target model should combine:

- low-cost A2MCP discovery calls for reach;
- higher-value market evaluation and execution orchestration calls;
- recurring agent workflows that poll order state and calibration;
- high-value A2A mandates for custom portfolios, research, integration, or
  managed execution policy where the platform rules permit them;
- builder or venue economics only when they are disclosed, permitted, and
  accounted for separately.

Do not change a live service price impulsively. Pricing, description, and
service structure are registry-governed commercial fields. Build a revenue
model from current conversion, demand, delivery cost, refund/failure behavior,
and marketplace comparables; then make any required registry change once as a
fully prepared commercial migration.

The internal revenue ledger must reconcile every paid call to payment ID,
service, price, settlement asset, settlement transaction, request ID, delivery
result, refund/dispute state where applicable, and recognized revenue. Public
“sold” counts are a distribution metric, not the accounting system of record.

## Capacity and reliability targets

Before launch, load tests must demonstrate the revenue model's required call
rate rather than an arbitrary developer benchmark. For each price/mix scenario,
calculate deliveries per day, peak paid requests per second, concurrent order
states, venue API load, WebSocket subscriptions, database writes, reconciliation
lag, and payment-settlement throughput.

Initial production SLOs should include:

- 99.95% monthly availability for paid read operations;
- no acknowledged paid request lost from the usage ledger;
- no duplicate venue order from a repeated idempotency key;
- 100% of order submissions reaching a terminal or explicit `UNKNOWN` state;
- reconciliation lag and stale-order age alarms with hard thresholds;
- recovery-point objective near zero for order and payment ledgers;
- tested recovery-time objectives for gateway, database, signer, and venue WS;
- blue/green rollback without changing the public hostname or ASP record.

These targets require at least a separate durable database and execution
worker. The current 8 GB/no-swap VPS, which has already experienced OOM kills,
must not also host full datasets, ClickHouse/Redpanda, agent research crawlers,
and a funded signer. Keep the public gateway lean, move research to an isolated
compute/data plane, and place the signer and execution worker in a tightly
restricted service boundary. Add a second failure domain before meaningful
capital or revenue depends on the service.

## Full-scale research and certification

Certification should use the full useful dataset, not a 50-market product
plan. The data plane should ingest versioned partitions from the large supplied
datasets, join point-in-time market metadata, and use L2 book snapshots/deltas
where available.

Required evaluation layers:

1. **Universe validation:** all supported historical markets, identity joins,
   YES orientation, rules, token migrations, timestamps, and resolution.
2. **Directional evaluation:** trade/fill datasets for probability and
   selection performance.
3. **Execution replay:** L2 book deltas plus trade ticks, latency, tick size,
   fee curves, depth, partial fills, cancellation, and settlement.
4. **Maker realism boundary:** report that L2 cannot fully establish our queue
   position. Do not advertise maker P&L as proven without suitable L3 evidence
   or conservative queue assumptions.
5. **Walk-forward selection:** precommitted training/tuning/holdout windows,
   related-market grouping, all candidate results, and no resolution leakage.
6. **Failure certification:** duplicate calls, timeouts, unknown submission,
   WS gaps, restarts, balance/allowance changes, venue halt, reorg/settlement
   delay, stale books, and corrupted external data.
7. **Scale certification:** production request mix, payment load, ledger write
   volume, and millions of concurrent historical order transitions in replay.

Backtest artifacts must retain dataset hashes, source commit, adapter version,
model version, configuration, seeds, environment, result hashes, and rejected
runs. Research jobs run outside the production host.

## Source review translated into build decisions

### Official Polymarket Python SDK

Use the current official `Polymarket/py-sdk` as the pinned venue primitive, not
the archived `py-clob-client`. The inspected SDK is beta, uses exact `Decimal`
through core order paths, supports signed limit/market orders, user streams,
allowance recovery, cancellation, positions, and settlement workflows.

It does not provide a generic HTTP retry/idempotency layer for CLOB order
submission. Its normal transport converts timeouts into transport errors. The
TrueOdd adapter must therefore own durable intent persistence, deterministic
signed-order hashing, unknown-outcome reconciliation, rate limiting, and safe
retry policy. Do not wrap `POST /order` in a generic automatic retry.

### prediction-market-backtesting

Use it as a candidate production research harness. Its active Polymarket path
replays L2 order-book deltas and uses trade ticks as execution evidence; it
models fees, latency, queue assumptions, settlement, and multi-market
portfolios. Its own roadmap says fuller maker slippage realism still needs L3
data. The live components remain sandbox/alpha material and are not the funded
execution engine.

### ent0n29/polybot

Borrow the service separation, event schemas, paper/live guard, analytics
tables, and monitoring ideas. Do not copy its order monitor as the production
truth: the inspected monitor keeps tracked orders in an in-memory map, drops
them after six hours or repeated polling errors, and reconstructs state from
loosely shaped JSON. TrueOdd needs durable order state and restart-safe
reconciliation.

### alsk1992/CloddsBot

Borrow the capability catalog, operator surfaces, and risk test ideas. Do not
adopt its persistence or breaker defaults as-is: inspected order tables use
SQLite `REAL` monetary fields and `INSERT OR REPLACE`, while an execution
breaker automatically resets after a timer. Production money fields must use
integer base units or exact decimals, state updates must be transactional, and
serious breaker trips require explicit recovery policy.

### Other supplied repositories

Use SII-WANGZJ and Jon-Becker datasets for large-scale research and cross-checks;
PMXT as a normalization/reference layer; the LP tool for cancel/replace and
reconciliation test cases; Harrier for adapter/risk interface ideas; poly_data
as an isolated completeness cross-check after GPL review; and the research
agents only to produce sourced context upstream of deterministic decisions.
None becomes a trusted signer or strategy authority by installation.

Source-level cautions apply: SII's convenience processing uses float/rounding;
PMXT can move credentials through its sidecar and converts trading values
through JavaScript numbers; the LP tool can retry replacement posts without a
bound and fails open to zero inventory on position errors; and Harrier's
current `FetchBook` risk result is not enforced before execution while its
positions remain in memory. Use each repository to construct adversarial tests,
not as permission to reuse its money path.

## One production release train

These workstreams should proceed in parallel under one architecture, not as a
sequence of marketplace edits:

### Commercial continuity

- snapshot the current Agent #5560 record and usage evidence;
- impose a registry-edit freeze;
- record the exact current price and capability wording;
- decide whether one final honest wording expansion is required;
- build internal payment, usage, and recognized-revenue reconciliation.

### Stable API and billing

- publish the versioned operation envelope and schemas;
- preserve the current safe default response;
- make x402 idempotency and delivery receipts durable;
- load-test the price/mix scenarios required for the revenue target.

### Execution and custody

- durable intent/order ledger and deterministic state machine;
- policy service, signer boundary, official-SDK adapter, user WS, REST
  reconciliation, cancellation, positions, and settlement;
- delegated/user-owned wallet model and separation of ASP fees from trading
  capital;
- active/passive failover and disaster recovery.

### Data and model factory

- partitioned object storage and analytical warehouse outside the VPS;
- full dataset normalization and provenance;
- L2 replay, walk-forward evaluation, stress testing, and reproducible reports;
- promotion policy that can scale internally without changing the ASP record.

### Operations and security

- secrets manager or hardware/TEE-backed signing where available;
- non-root services, network allowlists, egress limits, audit logs, key rotation,
  backup/restore, and incident runbooks;
- SLOs, dashboards, alerts, order/revenue reconciliation, and a global kill;
- third-party dependency and license inventory pinned by version/commit.

### Launch and growth

- production certification using the real path with capital disabled;
- funded activation only after the complete path passes and an operator grants
  the required authority;
- predeclared capital tiers, not repeated product rewrites;
- distribution, recurring agent workflows, marketplace conversion analysis,
  and pricing decisions tied to the $1M revenue equation.

## Current go/no-go statement

As of 2026-07-21, TrueOdd is **not ready for funded prediction-market
execution**. The live service has strong signal, evidence, payment, and receipt
foundations, but no venue credentials, isolated signer, durable intent ledger,
order API, user-stream reconciliation, settlement accounting, or production
execution policy. All current model-family promotion gates are also locked.

That is a status finding, not a recommendation to build a toy. The required
next product is the full listing-stable execution platform described here.
Until it exists and passes certification, the correct public claim is paid
prediction-market intelligence with execution under construction—not live
autonomous trading.

## Immediate decisions and deliverables

1. Freeze Agent #5560 marketplace edits and capture its current evidence pack.
2. Approve the stable multi-operation API contract and custody model.
3. Decide whether the exact live listing wording can honestly cover execution;
   if not, schedule one final post-certification expansion.
4. Provision separate execution/signer and research/data infrastructure rather
   than loading the current shared VPS further.
5. Build the durable order/payment/revenue ledgers before connecting a funded
   wallet.
6. Pin and wrap the official SDK with exact arithmetic, unknown-outcome
   reconciliation, and contract tests.
7. Run full-scale historical, failure, and capacity certification.
8. Activate funded execution under predeclared policies without changing the
   ASP identity on each release.
