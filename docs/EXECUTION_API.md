# Prediction-Market Execution API

Last reviewed: 2026-07-21

This release adds the durable execution control plane behind the existing
TrueOdd API and does not change Agent #5560 or its marketplace listing.

## What is implemented

- `POST /v1/executions/prepare` creates a receipt-bound, risk-checked limit
  order intent. `Idempotency-Key` is mandatory.
- `GET /v1/executions/{intent_id}` returns the current state and complete
  transition history.
- `POST /v1/executions/{intent_id}/submit` is the funded submission boundary.
- `POST /v1/executions/{intent_id}/cancel` cancels a prepared intent locally or
  delegates an acknowledged order to the venue adapter.
- `POST /v1/executions/{intent_id}/reconcile` resolves nonterminal and
  ambiguous venue outcomes.

Prices and quantities are decimal strings. They are never accepted as binary
floating-point values. Intents and transitions are committed transactionally
to SQLite in WAL mode before any venue call. A transport timeout after a
submission becomes `UNKNOWN`; it is never treated as a rejection and is never
blindly resubmitted.

Preparation requires the hash of an existing actionable `check-market`
receipt. Venue, market, event group, and side must all match that receipt. The
API never accepts a private key, seed phrase, or wallet export.

## Fail-closed configuration

```text
RWOO_EXECUTION_DB_PATH=data/execution/intents.sqlite3
RWOO_EXECUTION_MODE=disabled
RWOO_EXECUTION_MAX_ORDER_USD=10.00
```

`disabled` is the production default. It permits preparation, inspection, and
local cancellation but returns `EXECUTION_DISABLED` for funded submission or
venue reconciliation. Setting `RWOO_EXECUTION_MODE=live` alone is insufficient:
the process must also receive an explicitly constructed venue adapter, so an
environment typo cannot activate trading.

## Remaining live activation work

The control plane is real, not a simulated-fill product, but funded execution
is intentionally not ready yet. Live activation still requires:

1. a pinned official Polymarket CLOB adapter with fresh quote, tick-size,
   balance, allowance, fee, and minimum-order validation;
2. an isolated non-root signing service with a dedicated execution wallet and
   independently enforced policy limits;
3. account-stream plus REST reconciliation, startup recovery, and settlement
   accounting;
4. global exposure, correlated-event, daily-loss, and kill-switch policy state;
5. load, fault-injection, venue test-order, and operator runbook certification.

Until those gates pass, metadata reports `execution_enabled: false`. No API
response claims a prepared intent is a venue order or fill.
