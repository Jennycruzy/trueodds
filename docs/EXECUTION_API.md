# Prediction-Market Execution API

Last reviewed: 2026-07-23

This release adds the durable execution control plane behind the existing
TrueOdd API and does not change Agent #5560 or its marketplace listing.

## What is implemented

- `POST /v1/executions/prepare` creates a receipt-bound, risk-checked limit
  order intent. `Idempotency-Key` is mandatory.
- `GET /v1/executions/{intent_id}` returns the current state and complete
  transition history.
- `POST /v1/executions/{intent_id}/submit` is the funded submission boundary.
- `POST /v1/executions/{intent_id}/submit-signed` relays a caller-signed
  Polymarket order without receiving a private key.
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
API never accepts a private key, seed phrase, wallet export, or email OTP.

Prepared and inspected Polymarket intents include `client_execution`, a
machine-readable package for caller agents:

- `target_collateral`: pUSD on Polygon.
- `funding_routes`: direct pUSD, Polygon USDC.e onramp, Polygon native USDC,
  Polygon USDT, and X Layer USDT via OKX cross-chain into the caller's
  Polymarket bridge deposit address.
- `wallet_backends`: currently `local_private_key` is executable for the live
  spike; `okx_agentic_wallet` is declared as
  `funding_ready_order_signing_adapter_pending`.
- `submit_signed.url`: the ASP relay endpoint for the prepared intent.

The intended one-call caller-agent flow is:

```text
prepare intent from ASP
caller helper funds caller-owned pUSD/deposit wallet
caller helper signs POLY_1271 order and L2 headers locally
caller helper POSTs body_base64 + headers to submit-signed
ASP validates intent match + replay guard, then relays byte-identical to CLOB
```

`submit-signed` payload:

```json
{
  "body_base64": "<base64 of exact serialized Polymarket /order body>",
  "headers": {
    "POLY_ADDRESS": "<caller address>",
    "POLY_API_KEY": "<caller CLOB api key>",
    "POLY_PASSPHRASE": "<caller CLOB passphrase>",
    "POLY_SIGNATURE": "<caller L2 HMAC>",
    "POLY_TIMESTAMP": "<caller timestamp>"
  }
}
```

The relay validates that the signed order matches the prepared intent:
`tokenId`, BUY side, `orderType`, maker/taker integer amounts, POLY_1271
`signatureType`, deposit-wallet maker/signer shape, and signature presence.
Each accepted body hash is stored before relay so the same signed order can only
be used once.

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
is intentionally not ready for general ASP callers yet. Live activation still
requires:

1. a verified OKX Agentic Wallet signer backend for Polymarket L2 credential
   creation and POLY_1271 order signatures;
2. live tiny-amount tests for Polygon USDC.e, native USDC, Polygon USDT, and
   X Layer USDT funding into caller-owned pUSD;
3. account-stream plus REST reconciliation, startup recovery, and settlement
   accounting;
4. global exposure, correlated-event, daily-loss, and kill-switch policy state;
5. load, fault-injection, venue test-order, and operator runbook certification.

Until those gates pass, metadata reports `execution_enabled: false`. The
caller-signed relay path exists, but `okx_agentic_wallet` remains marked
`funding_ready_order_signing_adapter_pending`.
