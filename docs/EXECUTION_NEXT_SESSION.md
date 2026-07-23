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

- `scripts/g0_spike.py` exercised the caller-signed relay path using the local
  `.env.spike` private-key backend, POLY_1271 deposit wallet, pUSD collateral,
  CTF Exchange V2, and relayer-managed deposit-wallet approval. On 2026-07-23
  the venue accepted the byte-identical relayed order (HTTP 200), returned order
  ID `0xc1072646a124d8f7a21f5bdecd214347174cababe943b9864443899a75db05eb`,
  and the caller cancelled it with zero matched size. Sanitized acceptance and
  cancellation evidence is retained in
  [`evidence/G0_POLYMARKET_LIVE_RELAY_2026-07-23.md`](evidence/G0_POLYMARKET_LIVE_RELAY_2026-07-23.md).
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
  `local-private-key` backend is live-proven for setup, signing, byte-identical
  relay, and cancellation. The
  `okx-agentic-wallet` backend currently produces a no-private-key funding plan
  but is not yet allowed to execute because order signing is still unverified.
- Stablecoin funding routes are declared for direct pUSD, Polygon USDC.e,
  Polygon native USDC, Polygon USDT, and the normal autonomous ASP route:
  X Layer USDT/USDT0 via OKX cross-chain into the caller's Polymarket bridge
  deposit address.
- The Polymarket bridge minimum (2.5 USDT, `BRIDGE_MIN_DEPOSIT_UNITS =
  2_500_000`) is now published on every bridge route in `funding_routes()` and
  enforced in one place, `_bridge_units()`, in the caller helper. Below the floor
  the bridge credits no pUSD **and reports no error**, so a caller sizing from
  the order notional alone would stall with nothing to debug.
- Agentic Wallet funding and bridging now run unattended. Funding and order
  signing are gated separately: bridging needs only the wallet session, which
  the Agentic Wallet already provides, so only order signing refuses.

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
ASP path above does not depend on it.

The contract to read is now known — 2026-07-23:

```text
0xf7f27c29e60fe6325bef8da7f93250353d2e3294
```

Read `isValidSignature` and the `WALLET` batch authorization there. Do **not**
read `0x58CA52ebe0DadfdF531Cde7062e76746de4Db1eB`, the address
`get_contract_config(137).deposit_wallet_implementation` advertises: deployed
wallets are beacon proxies, so that UUPS address answers the question about the
wrong contract. This is likely why public search never turned up the source.

Found by calling `UpgradeableBeacon.implementation()` (`0x5c60da1b`) on the
factory's beacon `0x7a18edfe055488a3128f01f563e5b479d92ffc3a`; the result holds
20,858 bytes of deployed code.

This is a research pointer for the custody question only. No code change is
required — see the derivation note below, which is already handled.

## Deposit-wallet derivation (no fix needed, just don't hand-roll it)

Two call paths, both correct:

- With a private key: `RelayClient.get_expected_deposit_wallet()`
  (`scripts/g0_spike.py:116`). The SDK resolves beacon-vs-UUPS itself. This is
  the path the proven G0 run used.
- With an Agentic Wallet session: `_derive_deposit_wallet_for_owner()`
  (`scripts/polymarket_agent_helper.py:75`). `RelayClient` cannot be used here
  because constructing it requires a private key, so this reproduces the same
  resolution by hand.

Do not call `derive_uups_deposit_wallet` directly. Deployed wallets are beacon
proxies, so it returns a **different address for the same owner** than either
path above, and funding it would send collateral to an address that is not the
deposit wallet.

## Current blocker: Agentic Wallet backend test

Most ASP buyers will use OKX Agentic Wallet email/API-key sessions, not raw
private keys. That is acceptable only if the caller-side helper can use the
wallet session for all required operations:

1. read the caller EVM address;
2. derive or accept the caller's Polymarket POLY_1271 deposit wallet;
3. fund pUSD by routing the caller's X Layer USDT/USDT0 through OKX/onchainos
   into the caller-owned Polymarket bridge deposit address; Polygon
   pUSD/USDC.e/native USDC/USDT remain fallback/setup routes;
4. deploy/approve the Polymarket deposit wallet as needed;
5. create or derive Polymarket L2 credentials;
6. sign the POLY_1271 order exactly as CLOB expects;
7. call ASP `submit-signed`.

Items 1-4 are implemented and run unattended, but have **not** yet been proven
live end to end with the Agentic Wallet. Items 5-6 are not yet verified with OKX
Agentic Wallet. The SDK path used in the live spike assumes a local private key
signer; an Agentic Wallet signer adapter must be built around
`onchainos wallet sign-message --type eip712` and tested against CLOB before
this can be shipped and certified from a lawfully supported region.

Test wallet, logged in 2026-07-23 (external test identity, deliberately **not**
the okx.ai registration account):

```text
email            kingsjanet0@gmail.com
owner EVM/XLayer 0x48ddC64e362e337b1eaEA67486A9F8c2869eAF38
deposit wallet   0x577108052c8D862984B724668E2f6035Eb6Fa5c5   (beacon-derived)
```

Do not put a private key in chat or `.env` for this path.

### Where this can and cannot be tested

OnchainOS auth on CLI 4.3.0 is **browser social login** (`--phase init` → `open`
→ `poll`). There is no email/OTP flag and no API-key session flag; older docs
describing `wallet login <email> --locale` do not match the shipped CLI. The
session then persists in `~/.onchainos/keyring.enc`, so the one browser step is
per-machine bootstrap and everything after it is unattended.

Codespaces reports `onchainos wallet geoblock` → `{"blocked":true}`. Signing is
host-independent and works there (it hits OKX, not Polymarket), but L2 credential
creation, `bridge.polymarket.com`, and order submission are all Polymarket-facing
and will not certify from a blocked host. Build the adapter anywhere; certify it
from the Mac.

## Next actions (pick up here — on the Mac)

Certify on the Mac: it is the host where the funded private-key G0 run
completed and the order was accepted and cancelled. Confirm its geoblock status
at the time of the run rather than assuming it — `d067f93` recorded a 403 from a
London host, so the answer depends on where the machine is egressing from.

1. Log the Agentic Wallet into OnchainOS on the Mac. `onchainos wallet login`
   prints a URL; open it, sign in as `kingsjanet0@gmail.com`, then
   `onchainos wallet login --phase poll`. Confirm with `wallet status` and
   `wallet geoblock` — the latter must report `{"blocked":false}` before any
   Polymarket-facing step.
2. Fund `0x48ddC64e362e337b1eaEA67486A9F8c2869eAF38` on **X Layer** with USDT or
   USDT0, at least **2.5** (the bridge floor). The wallet starts at zero, so
   check whether X Layer gas is needed or whether `wallet gas-station` covers it.
3. Bridge autonomously:
   `python scripts/polymarket_agent_helper.py --intent-file <prepared.json>
   --wallet-backend okx-agentic-wallet --source-asset xlayer-usdt --execute`
   (or `xlayer-usdt0` when that is the funded balance).
   This resolves the owner from the session, derives the deposit wallet, floors
   the amount, bridges, and waits for the pUSD credit. It then stops before
   signing by design.
4. Build the Agentic Wallet signer adapter on
   `onchainos wallet sign-message --type eip712 --chain polygon --from <owner>`.
   Prove L2 credential creation first (`ClobAuthDomain`, chainId 137) — it needs
   no funds — then the POLY_1271 order signature. The open question is whether
   the wallet's EIP-712 output satisfies the deposit wallet's ERC-1271
   `isValidSignature` and the ERC-7739 wrapping the v2 SDK applies.
5. Do not mark the backend executable until a tiny live rest-and-cancel order is
   accepted through it, and the result is recorded as a sanitized evidence file
   in `docs/evidence/` matching the shape of
   `G0_POLYMARKET_LIVE_RELAY_2026-07-23.md` — order ID, status, cancellation
   confirmation, no key/secret/HMAC/signed body. Then switch
   `client_execution.wallet_backends[].status` for `okx_agentic_wallet` from
   `funding_ready_order_signing_adapter_pending` to `executable`.
6. Test the remaining funding routes with tiny amounts: Polygon USDC.e -> pUSD
   direct onramp, and Polygon native USDC/USDT -> Polymarket bridge deposit.
7. Only if going custodial multi-funder: resolve the trade-only contract
   question at `0xf7f27c29e60fe6325bef8da7f93250353d2e3294` + legal counsel first.

## Standing reminder

Rotate the VPS root password shared in chat. Do not enable funded execution on
the production VPS (8 GB, no swap, prior OOM).
