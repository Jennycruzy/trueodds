# Execution Signer & Certification Runbook

Last reviewed: 2026-07-22

This runbook covers step 2 (isolated signer) and step 3 (reconciliation,
policy, certification) of the release train in
[`PREDICTION_MARKET_EXECUTION_RESEARCH.md`](PREDICTION_MARKET_EXECUTION_RESEARCH.md).
It exists so the custody and certification decisions are made **before** any
private key is generated. Nothing here authorizes funded trading; it defines
the gates that must all pass first.

Current state (as of last review):

- Step 1 — isolated Polymarket adapter + exact-arithmetic pre-trade gate:
  `src/rwoo/adapters/polymarket.py`. Read-only, no key, cannot move funds.
- Step 1b — coordinator pre-submit validation hook and clean-state contract:
  `ExecutionCoordinator._pre_submit_validate` and the `ExecutionError →
  REJECTED` / other-exception → `UNKNOWN` split in `submit()`.
- Step 2 — signer: **not started**. No key exists.
- Production `RWOO_EXECUTION_MODE` remains `disabled`.

## 1. The signer boundary

The signer is the only component that can move funds, so it is deliberately the
most constrained.

- **Separate process, not the API.** The FastAPI app must never import the
  signer or hold a key. The signer runs as its own OS process under a dedicated
  **non-root** service account, reachable only over a local, authenticated
  channel (unix socket or loopback mTLS). The API sends a normalized, already
  risk-checked intent; the signer decides whether to sign.
- **Least privilege.** The signer account has no shell login, no outbound
  network except the venue endpoint and the RPC it needs, and no read access to
  the API's ledgers beyond what it is handed per request.
- **Exception contract (already encoded).** The signer raises `ExecutionError`
  **only** for a pre-transmission refusal (balance/allowance/policy checked
  before signing). Once an order may have been transmitted, a transport/timeout
  failure must propagate as a non-`ExecutionError` so the coordinator records
  `UNKNOWN` and reconciles instead of assuming a rejection. See the
  `OrderSigner` protocol docstring in `src/rwoo/adapters/polymarket.py`.
- **Independent spend policy.** The signer enforces its own per-order,
  per-event, daily, and total caps — it does not trust the caller's limits. A
  request that passes the API risk gateway can still be refused by the signer.
- **Session-scoped signing key.** The signer holds the private key in memory
  **only while an operator has armed a session.** `arm` decrypts it from the
  KMS/keystore; `disarm`, an idle timeout, a cumulative session-notional cap, or
  the kill switch **zeroizes** it. The key is never persisted in the process, an
  env var, a log, or a prompt. Ending the session ends the exposure window.
- **Kill switch.** A single operator action (file flag or signal) puts the
  signer into refuse-all mode without a redeploy. Refuse-all is the default on
  startup until an operator explicitly arms it for the session.

## 2. Custody model (operator, before any key exists)

Separate **funds** from **signing authority**. Three roles, not one wallet:

1. **Treasury (cold).** Holds the bulk of capital, offline, never connected to
   the signer host. Profits sweep back here. Never the wallet tied to the Agent
   #5560 marketplace identity.
2. **Funder / deposit wallet (warm).** Holds only the **active capital tier**.
   On Polymarket, use a **POLY_1271 deposit wallet (signature type 3)** so the
   address holding funds is distinct from the key that signs orders — the flow
   Polymarket recommends for new API users.
3. **Signer (hot key).** The EOA private key on the signer host. Under POLY_1271
   it is authorized to place orders **on behalf of** the funder but is **not the
   fund custodian**. It is the only secret on the trading box, and it is
   session-scoped (§1).

Because order payloads are always signed locally with this key (L2 credentials
alone cannot create an order), the signer key must be present at sign time — so
the whole point of POLY_1271 is that a compromise of the trading box exposes
**trading authority over the tier**, not custody of the treasury.

Decisions to record before any key is generated:

- **Key generation & storage.** Generate the signer key on the target under the
  non-root account; store encrypted (KMS/HSM or an encrypted keystore). Never
  printed, never in an env var visible to the API, never in logs, receipts,
  shell history, or a prompt.
- **Allowance policy.** The funder's USDC allowance to the exchange is capped to
  the tier, never unlimited. Re-approve deliberately when raising a tier.
- **API (L2) credentials.** Derived from the signer key via an L1 EIP-712
  signature (`ClobAuthDomain`, chainId 137), deterministic per nonce. Rotation
  is supported (verified 2026-07-22): `POST /auth/api-key` creates,
  `GET /auth/derive-api-key` re-derives per nonce, and `DELETE /auth/api-key`
  revokes the currently authenticated key — usable for incident response.
- **Signer authority scope — verified 2026-07-22, CONFLICTING evidence.** The
  deposit wallet is a per-user ERC-1967 proxy. Polymarket's docs state the
  "owner **or session signer**" can sign `WALLET` batches for "token approvals,
  **transfers, withdrawals**, splits, or merges" — i.e. the documented session
  signer is **withdrawal-capable, not trade-only.** Separately, third-party
  copy-trade services advertise a revocable, bounded, **trade-only "scoped
  trading signature"** ("USDC stays in your own wallet; the bot can only place
  CLOB orders within limits"). Those two claims conflict, and the vendor claim
  is marketing that may describe a different (relayer- or convention-enforced)
  mechanism rather than a contract-enforced scope. **This is UNRESOLVED and is
  the linchpin for any multi-funder model.** It must be settled by reading the
  Deposit Wallet Factory Proxy source
  (`0x00000000000Fb5C9ADea0298D729A0CB3823Cc07` on Polygon) to prove whether a
  session signer's authority can be **contract-enforced to trade-only**. Until
  then, assume a session signer can move funds and do **not** treat the
  funder/signer split as a custody boundary.
- **Funding limits.** Predeclare capital tiers (e.g. $50 → $250 → $1k …) with a
  named approver per tier. `RWOO_EXECUTION_MAX_ORDER_USD` and the signer caps
  move together and only forward through the tier ladder.
- **Recovery & rotation.** Document signer-key rotation, the procedure to drain
  the funder deposit wallet to the treasury on kill, and compromise response.
- **Authorization record.** Who may arm the signer, who approves a tier bump,
  and where each approval is logged.

**Venue auth model — verified 2026-07-22** against Polymarket's docs. Two-level
auth: L1 (wallet private key, EIP-712) creates/derives credentials and signs
orders; L2 (apiKey/secret/passphrase, HMAC-SHA256) authenticates each request
but cannot itself create an order. Signature types: EOA (0), POLY_PROXY (1),
GNOSIS_SAFE (2), POLY_1271 (3). This is verified; the read-only
`HttpPolymarketDataSource` *data-endpoint field mapping* in
`src/rwoo/adapters/polymarket.py` remains PROVISIONAL until pinned against the
SDK (gate A).

## 3. Certification gates (all must pass before `mode=live`)

These restate the research doc's "Remaining live activation work", "Production
certification gate", and "Hard requirements" as a checkable list. Each gate
needs a named owner and a retained artifact (test run, hash, or sign-off).

### A. Adapter & data integrity
- [x] Venue auth model (L1/L2, signature types, POLY_1271 signer/funder split)
      verified against Polymarket docs — 2026-07-22.
- [ ] `py-sdk` pinned to an exact prerelease + commit; upgrade requires review.
- [ ] `HttpPolymarketDataSource` field mapping verified against the pinned SDK
      (it is marked PROVISIONAL today).
- [ ] Contract tests against a non-funded/metered venue setup pass.
- [ ] All prices/sizes/fees are `Decimal`/base-unit end to end; no binary float
      reaches signing or tick validation.

### B. Pre-trade correctness
- [ ] Market status, YES/NO token binding, tick size, minimum size, book
      freshness, empty/crossed book, and price protection reject as designed
      (unit-tested in `tests/test_polymarket_adapter.py`).
- [ ] Balance and allowance checks added at the signer (out of scope for the
      read-only adapter) and proven to fail closed.
- [ ] Decision-receipt binding enforced: venue, market, event group, and side
      match an actionable `check-market` receipt.

### C. Order lifecycle & recovery
- [ ] One idempotency key across retries; a timeout reconciles venue state
      before any resubmission (never blind resubmit).
- [ ] `UNKNOWN` is reachable and always reconciles; a fill is never inferred
      from submission.
- [ ] Startup recovery: on restart, every non-terminal intent is reconciled
      against the venue before new work is accepted.
- [ ] User account-stream + REST reconciler agree; divergences alert.

### D. Policy & exposure
- [ ] Per-event, correlated-event, daily-exposure, weekly-loss, drawdown, and
      kill-switch state enforced and independently held by the signer.
- [ ] Max open orders and stale-order cancellation enforced.

### E. Certification stress matrix (on fixed, versioned snapshots)
- [ ] Stale book, crossed/empty book, API timeout, duplicate request, adverse
      move, partial fill, balance/allowance failure, venue halt.
- [ ] No look-ahead, stable identity, realistic execution (latency/fees/depth/
      partial/queue/settlement), walk-forward windows fixed before holdout,
      baselines reported (market prob, no-trade, fixed rules), reproducibility
      (dataset hashes, commit, config, seeds, output hashes).

### F. Operations
- [ ] Research/backtests run **off** the production VPS (8 GB, no swap, prior
      OOM). Production execution stays minimal on-host.
- [ ] Operator runbook, SLOs, disaster recovery, and authorization gates signed
      off.

## 4. Activation sequence (only after §3 is fully green)

1. Freeze and snapshot the Agent #5560 marketplace record.
2. Arm the signer at tier 0 with a single venue **test order** at or below
   `RWOO_EXECUTION_MAX_ORDER_USD`; reconcile and cancel it; retain the receipt.
3. Enable `RWOO_EXECUTION_MODE=live` **and** inject the real adapter+signer
   (mode alone stays insufficient by design).
4. Run the first predeclared capital tier. Scale only through the tier ladder
   and feature flags — never by editing the ASP identity per release.

## 6. Multi-funder (segregated) — additional gates

Selected model: each funder has their **own** POLY_1271 deposit wallet; the
chain self-accounts (funds due to a funder = their own wallet balance); no
pooling, no NAV. This removes the commingling/accounting problem but introduces
two blockers that do **not** exist when trading only your own capital. Neither
may be skipped before a single funder deposits.

### Blocker 1 — Non-custodial scope (technical, must verify on-chain)
The only safe form of this model is **non-custodial**: the funder is the
**owner** of their deposit wallet and keeps withdrawal control; your signer is
added as a **contract-scoped, revocable, trade-only** session signer that
physically cannot transfer or withdraw. Whether that scope is contract-enforced
is the unresolved linchpin in §2 (signer authority scope). If the deposit-wallet
contract does **not** enforce a trade-only scope, then a segregated bot key that
can sign `WALLET` batches can **drain every funder's wallet** on a single box
compromise — an unacceptable, and likely unlawful, custody posture. Resolve the
contract question first; if trade-only cannot be contract-enforced, this model
does not proceed as designed.

**Verification status (2026-07-22): leans AGAINST contract-enforced trade-only.**
POLY_1271 orders validate through the wallet's ERC-1271 `isValidSignature`,
which appears to authorize signatures from the same "owner or session signer"
set that also signs `WALLET` batches (transfers/withdrawals). If one
authorization list governs both, an authorized trading signer can also withdraw.
Not yet disproven only because the verified implementation *source* was not
locatable via public search — settle it by reading the implementation contract
directly or getting written confirmation from Polymarket. Assume not-trade-only
until then.

**Fallback if trade-only is not contract-enforceable — the only non-custodial
forms are:** (a) the **funder signs each order** with their own key/session (you
never hold a fund-moving signer); or (b) the **funder self-hosts** the agent
with their own key and you provide **signals only**. Both sell signals, not
discretionary execution over other people's funds.

### Blocker 2 — Regulatory posture (legal, not an engineering task)
Discretionary trading of **other people's money** is very likely a regulated
activity (investment adviser / discretionary account management / money
services) in most jurisdictions **even when segregated and non-custodial**.
Segregation removes the *custody/pooling* problem; it does not remove the
*discretionary management* one. This needs qualified legal counsel before
onboarding funders. It is out of scope for this repo and is not something to
engineer around.

### If both blockers clear, the segregated design is:
- **Funder registry** mapping funder identity → deposit-wallet address → owner
  address → granted-scope reference → per-funder risk limits and status. Chain
  balances are authoritative; the registry is routing/limits, never a shadow
  ledger of "who is owed what."
- **Per-funder isolation in execution.** Every intent, risk check, exposure
  cap, decision receipt, and trade receipt is tagged with a funder/account id.
  Limits and the kill switch operate **per funder and globally**.
- **Per-wallet reconciliation and recovery**, independently per funder.
- **Fee collection** must itself be non-custodial (funder-authorized settlement
  or an explicit invoice), never an implicit withdrawal right for the signer.
- **Onboarding proves scope + revocation** for each funder before any order:
  the funder can revoke in one step and withdraw at any time without the
  operator.

## 5. What is intentionally NOT automatable from a prompt

Key generation, funding, allowance approval, arming the signer, and tier bumps
are operator actions with custody consequences. They are performed by a named
human on the signer host, logged per §2.6 — not from an assistant session and
not over a pasted root credential.
