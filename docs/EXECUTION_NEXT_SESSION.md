# Execution — Continue Here Next Session

Last updated: 2026-07-23

## Where we are

The ASP is now a non-custodial Polymarket execution-assist design:

- The server prepares/risk-checks an intent and exposes the `submit-signed`
  relay endpoint.
- The caller agent keeps signing authority and funds locally.
- The ASP receives only opaque Polymarket `/order` body bytes plus caller-created
  L2 headers, verifies the signed order matches the prepared intent, burns the
  body hash for replay protection, then relays byte-identical to CLOB.
- Funds do not route through TrueOdds.

Done so far:

- `scripts/g0_spike.py` live-proved the caller-signed relay path against
  Polymarket CLOB using POLY_1271 deposit wallet, pUSD collateral, CTF Exchange
  V2, and relayer-managed deposit-wallet approval. A real order was accepted and
  then cancelled.
- `src/rwoo/signed_relay.py` accepts `body_base64 + headers`, validates the order
  economics against the prepared intent, and relays the exact original bytes.
- `src/rwoo/execution.py` persists one-shot signed body hashes in
  `signed_order_submissions`, preventing replay of one signed order against the
  same or another intent.
- `src/rwoo/api/app.py` exposes
  `POST /v1/executions/{intent_id}/submit-signed` and enriches execution
  prepare/inspect responses with `client_execution`: target pUSD collateral,
  supported funding routes, wallet backend status, and the submit URL.
- `src/rwoo/adapters/polymarket.py` is updated from old USDC.e/V1 assumptions to
  pUSD/V2/POLY_1271 settlement metadata.
- `scripts/polymarket_agent_helper.py` is the caller-side helper. The
  `local-private-key` backend can set up, sign, and submit. The
  `okx-agentic-wallet` backend currently produces a no-private-key funding plan
  but is not yet allowed to execute because order signing is still unverified.
- Stablecoin funding routes are declared for direct pUSD, Polygon USDC.e,
  Polygon native USDC, Polygon USDT, and X Layer USDT via OKX cross-chain into
  the caller's Polymarket bridge deposit address.

Verification completed:

- `PYTHONPATH=src python3 -m py_compile scripts/g0_spike.py scripts/polymarket_agent_helper.py src/rwoo/api/app.py src/rwoo/adapters/polymarket.py`
- `PYTHONPATH=src python3 -m unittest tests.test_api.ExecutionApiTests tests.test_polymarket_live_contract`
- Both passed on 2026-07-23. Existing Pydantic protected-namespace warnings are
  still present and unrelated.

## Key decision (settled)

The ASP path is **non-custodial execution-assist**, not a custodial fund:
- The ASP sells signals + prepares/validates order **intents**; the **caller
  signs using their own wallet authority**. That can be a raw local private key
  in the developer spike, or an authenticated OKX Agentic Wallet session once
  the wallet signer adapter is implemented and tested.
- L2 can *post* a pre-signed order but cannot *create* one without the owner
  signature — so the ASP can validate + post + reconcile + receipt a caller's
  already-signed order **without ever holding a key**.
- Multi-funder scales as N callers each with their own key. No master key, no
  honeypot. Revenue = per-call + per-execution fees, not AUM.

## Open blocker (verify before ANY custodial multi-funder)

Whether a Polymarket deposit-wallet **session signer can be contract-enforced to
trade-only** (refuse `WALLET` batch withdrawals) is UNRESOLVED and the evidence
**leans against** it (one authorization set appears to gate both CLOB orders and
withdrawals). This only matters for the *custodial* model; the non-custodial
ASP path above does not depend on it. To settle: read the deposit-wallet
**implementation** contract source (not the factory
`0x00000000000Fb5C9ADea0298D729A0CB3823Cc07`) or get written confirmation from
Polymarket.

## Current blocker: Agentic Wallet backend test

Most ASP buyers will use OKX Agentic Wallet email/API-key sessions, not raw
private keys. That is acceptable only if the caller-side helper can use the
wallet session for all required operations:

1. read the caller EVM address;
2. derive or accept the caller's Polymarket POLY_1271 deposit wallet;
3. fund pUSD from Polygon pUSD/USDC.e/native USDC/USDT or bridge X Layer USDT;
4. deploy/approve the Polymarket deposit wallet as needed;
5. create or derive Polymarket L2 credentials;
6. sign the POLY_1271 order exactly as CLOB expects;
7. call ASP `submit-signed`.

Items 1-4 are straightforward through OnchainOS wallet/cross-chain commands.
Items 5-6 are not yet verified with OKX Agentic Wallet. The SDK path used in the
live spike assumes a local private key signer; an Agentic Wallet signer adapter
must be built around the wallet's EVM/EIP-712 signing primitive and tested
against CLOB before this can be shipped.

Local OnchainOS status on 2026-07-23:

```json
{"loggedIn": false, "accountCount": 0}
```

So the next live test needs an OKX Agentic Wallet login in this local OnchainOS
session. Do not put a private key in chat or `.env` for this path.

## Next actions (pick up here)

1. Log into OKX Agentic Wallet locally with email and verification code, then run
   `onchainos wallet status` and `onchainos wallet addresses --chain polygon`.
2. Build the Agentic Wallet signer adapter for Polymarket CLOB auth/order
   signing. Do not mark it executable until a tiny live rest-and-cancel order is
   accepted.
3. Test the funding routes with tiny amounts:
   Polygon USDC.e -> pUSD direct onramp, Polygon native USDC/USDT -> Polymarket
   bridge deposit, and X Layer USDT -> OKX cross-chain -> Polymarket bridge
   deposit -> pUSD.
4. After Agentic Wallet signing is verified, switch
   `client_execution.wallet_backends[].status` for `okx_agentic_wallet` from
   `funding_ready_order_signing_adapter_pending` to `executable` and allow
   `scripts/polymarket_agent_helper.py --wallet-backend okx-agentic-wallet
   --execute`.
5. Only if going custodial multi-funder: resolve the trade-only contract
   question + legal counsel first.

## Standing reminder

Rotate the VPS root password shared in chat. Do not enable funded execution on
the production VPS (8 GB, no swap, prior OOM).
