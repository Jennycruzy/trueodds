# G2 — Deposit-wallet pUSD sweep (withdrawal batch) — PENDING

Date: 2026-07-23
Status: **PENDING LIVE RUN** — this file is a template. Do not treat the placeholder
values below as confirmed. Fill them from a real `--execute` run on a
non-geoblocked host, then change Status to `CONFIRMED` or `FAILED`.

## Purpose

Prove the single remaining unknown behind the just-in-time-balance safety model
for the MaxUint256 exchange approval: that unspent collateral can leave the
POLY_1271 deposit wallet after a fill or cancel. The sweep is an
`execute_deposit_wallet_batch` whose one call is an ERC-20 `transfer` instead of
`approve` — mechanically identical to the approval batch confirmed in
[`G1_OKX_AGENTIC_WALLET_XLAYER_PARTIAL_2026-07-23.md`](G1_OKX_AGENTIC_WALLET_XLAYER_PARTIAL_2026-07-23.md).
The open question is whether Polymarket's relayer permits an *outbound*
WALLET-batch transfer (a withdrawal). A pass also re-confirms the OnchainOS
Agentic Wallet signer over a WALLET batch.

If this withdrawal is permitted, the autonomous JIT flow becomes:
`fund exact notional → approve(MaxUint256) once → trade → sweep unspent → idle at ~0`,
with real exposure capped at one order's notional and no Polymarket business ask.

## Fixed facts (known before the run)

- Script: `scripts/agentic_polymarket_sweep_test.py`
- Owner (sweep destination / reserve): `0x48ddC64e362e337b1eaEA67486A9F8c2869eAF38`
- POLY_1271 deposit wallet: `0x577108052c8D862984B724668E2f6035Eb6Fa5c5`
- pUSD collateral: `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`
- Chain: Polygon `137`
- Relayer: `https://relayer-v2.polymarket.com`
- Call: `transfer(owner, 0.1 pUSD)` = `0xa9059cbb` + owner + `0x186a0` (100000 base units)
- Signer: OnchainOS Agentic Wallet (`kingsjanet0@gmail.com`) — no private key
- Pre-run deposit-wallet balance of record (from G1): `2.391351 pUSD`. A 0.1 pUSD
  sweep leaves ~`2.29 pUSD`, clear of the 2.5 X Layer bridge floor, so no
  re-funding is needed and the completed G1 bridge is not retried.

## Preconditions (must hold on the run host)

- `onchainos wallet geoblock` → `{"blocked":false}` (certify on the Mac).
- `onchainos wallet status` logged in as `kingsjanet0@gmail.com`.
- Builder credentials present at `/tmp/.trueodds_builder_creds.json` (mode 600).
- `$SPIKE_POLYGON_RPC_URL` set.
- `py_builder_relayer_client` importable (the `.venv-spike` environment).

## Command

```bash
python scripts/agentic_polymarket_sweep_test.py --execute
```

## Result (fill from the run)

- relayer transaction id: `<PENDING>`
- Polygon transaction: `<PENDING>`
- receipt status: `<PENDING — expect 0x1>`
- deposit wallet before: `<PENDING>` pUSD
- deposit wallet after: `<PENDING>` pUSD
- recipient (owner) before: `<PENDING>` pUSD
- recipient (owner) after: `<PENDING>` pUSD
- recipient delta: `<PENDING — must equal 0.100000 pUSD>`
- wallet delta: `<PENDING — 0.100000 pUSD, or more if the relayer skims a fee>`
- relayer fee taken from collateral, if any: `<PENDING>`

## Interpretation (fill from the run)

- [ ] `withdrawal batch permitted` — the deposit wallet can push pUSD to its owner
  via a relayer WALLET batch. **Unblocks the JIT sweep leg.**
- [ ] signer re-confirmed over a WALLET transfer batch (not just an approval).
- [ ] JIT sizing note: subtract any observed relayer fee when computing how much
  to sweep vs. leave for gas.

If the batch is instead **rejected**, record the exact relayer/API error here.
A rejection would mean withdrawals are gated separately from orders, which both
kills the autonomous sweep and answers the custodial "trade-only" question in the
opposite direction — see the Open blocker in
[`../EXECUTION_NEXT_SESSION.md`](../EXECUTION_NEXT_SESSION.md).

No key, secret, HMAC, or signed body is recorded in this file.
