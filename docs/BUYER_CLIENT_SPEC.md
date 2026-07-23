# TrueOdds ASP — Buyer-Side Client Spec

Last updated: 2026-07-23

## Model: TrueOdds moves nothing

TrueOdds sells the signal, prepares and validates the order **intent**, and relays
the buyer's already-signed order to Polymarket. It never holds a key, a fund, or a
wallet session. The buyer's agent runs this client in its **own** environment,
signs locally, and hands TrueOdds only signed bytes.

```
buyer agent (own key + own funds)                 TrueOdds server
  fund EOA  →  ensure pUSD  →  approve  →  sign  →  POST /submit-signed  →  validate + relay → CLOB
```

Nothing above the arrow into `/submit-signed` ever touches TrueOdds infrastructure.

## Signer — pick either option (one interface)

The client is signer-agnostic. A buyer plugs in **one** of two backends; both
satisfy the same interface, so the rest of the client is identical.

```
Signer:
  address() -> str                    # the execution EOA / wallet address
  sign_order(order_eip712) -> str     # Polymarket order signature (sig-type 0)
  sign_and_send(tx) -> tx_hash        # broadcast an on-chain tx (approve/wrap/bridge/swap)
```

**Option A — raw local key.** The buyer's agent holds an EOA private key in its own
secret store (env var / secrets manager). `eth_account` signs orders and
transactions locally. Simplest; the key never leaves the buyer's process. This is
what `g0_spike.py` already does with `SPIKE_PRIVATE_KEY`.

**Option B — headless wallet provider.** The buyer's agent authenticates to a
provider they control (Turnkey / Privy / Coinbase CDP) with an **API key** they
hold — no browser. `sign_order` / `sign_and_send` become provider API calls. The
provider keeps the key under the buyer's policy.

Both are headless, both keep the key out of TrueOdds, and both work with **bounded**
approvals (a plain EOA, signature type 0 — no relayer, no MaxUint256 demand). The
OKX Agentic Wallet is **not** an option here: it needs a human browser login (no
headless auth for an agent) and it refuses the approval Polymarket requires.

## Funding — decoupled from any single wallet

The buyer tops up their **own EOA** however they want. Two supported top-up paths;
the client does not care which:

1. **From their OKX Agentic Wallet** — the buyer's own session, one-time login,
   their concern. TrueOdds does not drive this hop.
2. **Any other source** — a CEX withdrawal to Polygon, another wallet, a bridge.

Once *any* supported stable sits in the EOA, `ensure_pusd(eoa)` reaches pUSD
autonomously with the buyer's signer. Route selection is
`buyer_funding.plan_pusd_funding` (pure, unit-tested):

| EOA holds | Route to pUSD | Primitive |
|---|---|---|
| pUSD | none | — |
| USDC.e (Polygon) | wrap → pUSD | `g0_spike._wrap_usdce_to_pusd` (recipient = EOA) |
| X Layer USD₮0 | MESON bridge → USDC.e → wrap | G1 MESON sequence + wrap |
| Polygon USDT / native USDC | swap → USDC.e → wrap | DEX swap + wrap |

The bridge leg is floored at the 2.5-token MESON minimum and grossed up for the
fee; the post-bridge/-swap wrap consumes whatever actually lands (`CREDITED`).

> Do **not** route an EOA through `bridge.polymarket.com` — that endpoint is
> Polymarket-facing (geoblock-sensitive) and deposits into a POLY_1271 deposit
> wallet, not an arbitrary EOA. The EOA route is on-chain wrap, not the hosted
> bridge.

## Lifecycle

**One-time setup (buyer-side):**
1. Provision the EOA (raw key or provider).
2. Fund it with any supported stable (either top-up option).
3. `ensure_pusd(eoa)` → pUSD in the EOA.
4. Broadcast a **one-time bounded** approval to the exchange (sig-type-0 EOA tx).

**Per buy (autonomous, no prompt):**
1. Ask TrueOdds to prepare the intent.
2. `ensure_pusd` tops up if the balance drifted.
3. `sign_order` locally; `POST /submit-signed` with the signed bytes + headers.
4. TrueOdds validates against the prepared intent and relays byte-identical to CLOB.

## Implementation

- `scripts/buyer_funding.py` — `plan_pusd_funding`: pure route selection (tested).
- `scripts/buyer_client.py` — the executor:
  - `Signer` interface with `LocalKeySigner` (Option A, wired) and `ProviderSigner`
    (Option B, stubbed for the buyer's provider).
  - `ensure_pusd(signer, rpc, required_units, handlers=...)` — reads balances,
    plans, and runs each step through the signer. The `wrap` leg is built in;
    `bridge` (MESON) and `swap` (DEX) are injected handlers the buyer supplies,
    each of which must block until USDC.e is credited on Polygon.
  - Dependency-injected (signer / rpc / handlers), so orchestration is unit-tested
    without a live key, RPC, or venue.

## Server contract (already built)

- `POST /v1/executions/{intent_id}/submit-signed` — accepts `body_base64 + headers`,
  validates the order economics against the prepared intent, burns the body hash
  for replay protection, relays the exact original bytes.
- Buyer L2 credentials never receive the TrueOdds builder secret.

## What Codex must certify on the Mac

1. **EOA (signature type 0) bounded approval + rest-and-cancel** — the code exists
   (`g0_spike.py:_send_approval`, sig-type-0 handling); the live-proven run used the
   deposit-wallet path, so a tiny EOA order accepted-and-cancelled is the missing
   proof. Record it in `docs/evidence/`.
2. **The X Layer USD₮0 → MESON → USDC.e → wrap** chain lands a **wrappable** USDC.e
   balance in the EOA (not USDT, not a deposit wallet). One live confirmation.
3. Only after (1) mark the EOA execution path shippable.
