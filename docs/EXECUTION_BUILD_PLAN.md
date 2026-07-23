# Execution Build Plan — Non-Custodial Execution-Assist

Created: 2026-07-22
Scope: Polymarket to completion, then Kalshi and Limitless.
Owner: Jenny

This plan assumes the revenue target is serious. Every phase below has an exit
criterion that is a *verifiable artifact*, not a feeling. Nothing advances on
"it looked right."

---

## Historical G0 note — 2026-07-22: first run blocked by geofence

The first funded run did not answer the Variant A question. It surfaced a
larger legal/geography issue that still applies to any relay service.

    HTTP 403
    {"error": "Trading restricted in your region, please refer to available
     regions - https://docs.polymarket.com/developers/CLOB/geoblock"}

**Polymarket geoblocks the party that submits the order — i.e. the relay's IP,
not the caller's.** Per Polymarket's published restrictions (read 2026-07-22),
"close-only" jurisdictions may close existing positions but **cannot place new
orders**. That list includes the **United States**, the **United Kingdom**, and
the Canadian provinces of **Quebec, Ontario, British Columbia and Alberta**,
plus France, Germany, Italy, Australia, Singapore, Poland, Brazil and others.

Both hosts available to this project are inside that list:

| Host | Location | Status |
|---|---|---|
| Test runner (codespace) | London, GB | restricted — produced the 403 |
| Production VPS `38.49.216.59` | Montréal, Quebec, CA | **also restricted** |

So "re-run it from production" does not work, and would not be legitimate if it
did. This is not an infrastructure problem to be routed around; the geoblock is
a regulatory control and treating it as an obstacle is its own, much worse,
category of risk.

### What this does and does not tell us

- **At that time, Variant A was neither proven nor disproven.** The 403 fired on
  geography, not authentication. A later 2026-07-23 live run did prove the
  relayed HMAC/order path with POLY_1271/pUSD/V2.
- **The relay is the trading party, in the venue's eyes.** That is the finding
  that matters. A design where TrueOdds submits the order makes TrueOdds' own
  jurisdiction the binding constraint — and if it ever relayed for callers in
  restricted regions, it would be supplying the mechanism by which those callers
  trade. That is circumvention of a regulatory geoblock, which is a different
  and far more serious thing than the custody question this plan started with.

### Consequence: Phase 3 may be the wrong build

`POST /v1/executions/{id}/submit-signed` puts TrueOdds in the submission path.
The alternative preserves nearly all the product value and removes TrueOdds from
that path entirely:

> **Prepare-and-hand-back.** TrueOdds sells the signal, prepares the intent, and
> runs the full pre-trade gate — binding, tick, min size, staleness, crossed
> book, price protection, settlement requirements. It returns a validated,
> ready-to-submit order intent plus a signed decision receipt. **The caller signs
> AND submits it themselves**, from wherever they are lawfully able to trade.

That keeps everything already built and paid for, stays non-custodial, and
additionally keeps TrueOdds out of the geo/regulatory path. It is the same
posture already chosen for Kalshi ("route, don't execute") — the geoblock
suggests it may be the correct posture for Polymarket too.

This remains a business/legal decision, not an engineering workaround. However,
it no longer means G0 is technically unproven: on 2026-07-23 a later live run
proved byte-identical caller-signed relay with POLY_1271/pUSD/V2, and the live
test order was cancelled. The next engineering blocker is the OKX Agentic Wallet
backend, not the raw-key spike.

---

## 0. The load-bearing question (resolve before Phase 3 is designed)

`docs/EXECUTION_SIGNER_AND_CERTIFICATION.md:111-118` records a **verified** fact
that the non-custodial plan has not yet been reconciled with:

> Two-level auth: L1 (wallet private key, EIP-712) creates/derives credentials
> and signs orders; **L2 (apiKey/secret/passphrase, HMAC-SHA256) authenticates
> each request** but cannot itself create an order.

The earlier framing — "the ASP can post a caller's pre-signed order without ever
holding a key" — is **half true**. Correct half: TrueOdds never needs the
caller's L1 private key, and therefore can never move their funds. Missing half:
`POST /order` still requires **L2 headers bound to the maker's account**. L2
credentials are a *credential*, even if they are not a *fund-moving* one.

So there are exactly two non-custodial variants, and choosing between them is
the first real decision:

### Variant A — Caller-supplied headers (zero credential stored) — **CHOSEN 2026-07-22**
The caller's agent does two things locally and sends both:
1. Signs the EIP-712 order struct with its L1 key.
2. Computes its own L2 HMAC over the exact request it wants relayed.

TrueOdds validates, relays **byte-identical**, and stores neither the key nor
the L2 secret.

- Custody claim becomes literally true: **zero caller secrets at rest.**
- Hard constraint: the HMAC covers method + path + body + timestamp. TrueOdds
  must relay the body as an **opaque byte blob** — any re-serialization (key
  reordering, whitespace, Decimal→float) invalidates the HMAC. This dictates the
  storage schema and must be designed in from line one, not retrofitted.
- Cost: the caller's agent needs a small client-side helper. Ship one.

### Variant B — Caller-delegated L2 credentials (stored) — FALLBACK ONLY
TrueOdds stores the caller's apiKey/secret/passphrase.

- Blast radius on breach: attacker can cancel the caller's open orders and read
  their positions. Attacker **cannot** withdraw and **cannot** create orders
  (no L1 key). Materially smaller than custody — but non-zero, and it forfeits
  the "we hold nothing" sentence that makes this sellable.
- Take this only if a spike proves Variant A cannot work.

**Decision (2026-07-22, Jenny): build Variant A.** Variant B is retained only as
a documented fallback if gate G0 fails outright. The byte-identical opaque-blob
constraint is therefore binding on the Phase 3 storage schema from the first
line of code.

**Gate G0:** a spike (Phase 2) proves Variant A end-to-end against the live CLOB
with a throwaway wallet and sub-dollar size. Phase 3 does not start until G0
passes or formally falls back to B, with the decision written into this file.

---

## Phase 1 — Infrastructure and credential hygiene. No product work.

Independent of everything else. One item is urgent; the rest are latent hazards
that must clear before Phase 3, not tonight.

**URGENT — active exposure.** The VPS root password was shared in chat, port 22
is reachable from the open internet, and password root login is enabled. Every
other secret on the box sits behind it. Rotate now.

The remaining three are latent: nothing is currently misbehaving, but each one
fails at the worst possible moment (a 2am rollback, a flag flip, relay traffic).

1. **Rotate every credential exposed.** VPS root password (shared in chat);
   `RWOO_OKX_API_KEY` / `RWOO_OKX_SECRET_KEY` / `RWOO_OKX_PASSPHRASE` in
   `/etc/rwoo` (used by `receipts.py`, `xlayer.py`).

   **Key access is already in place** — an ed25519 deploy key
   (`claude-code-deploy@caliber`) is installed in `/root/.ssh/authorized_keys`
   and verified working with password auth forced off. Rotating the password
   does not disrupt deploys. Private key lives at
   `~/.ssh/trueodd_vps_ed25519` on the dev machine.

   **Rotation alone is insufficient.** `/root/.ssh/authorized_keys` already
   carries five other standing root logins that a password change does not
   revoke: `KitchenCopilot`, `devfun-jennycruzy`, `codespace@codespaces-ec068e`,
   `rwoo-deploy`, `codex-jennycruzy-2026-07-12`. Audit every one; delete anything
   not positively accounted for. Then harden via a drop-in that sorts *first*
   (first value wins on Ubuntu 24.04):
   `/etc/ssh/sshd_config.d/00-hardening.conf` with `PermitRootLogin
   prohibit-password` + `PasswordAuthentication no`. Verify with `sshd -T`, not
   by reading the file; keep a live session open while testing.
2. **Fix the release topology.** Production runs `WorkingDirectory=/opt/rwoo/staging`
   with `PYTHONPATH=/opt/rwoo/staging/src`, while a divergent, stale
   `/opt/rwoo/current` exists without an `api/` directory. Prod must not run from
   a directory named "staging". Make `current` a symlink into `releases/<tag>`,
   point the unit at it, and make rollback a symlink flip.
3. **Pin configuration explicitly.** `/etc/rwoo/rwoo.env` — the only file the
   unit loads — sets neither `RWOO_PAYMENT_ENABLED` nor any `RWOO_EXECUTION_*`.
   Both currently resolve from code defaults. Two *unloaded* env files contradict
   each other (`okx-seller.env` = true, `rwoo-release.env` = false). Set every
   safety-relevant flag explicitly, including `RWOO_EXECUTION_MODE=disabled`.
   Delete or clearly quarantine the unloaded files.
4. **Capacity.** 8 GB, no swap, prior OOM (per the signer runbook). Add swap and
   a memory alarm before any signing/relay traffic lands.

**Exit:** new credentials in place; `systemctl cat rwoo-api` shows a versioned
release path; `curl /v1/service-metadata` reports flags that match the env file
byte for byte; documented rollback executed once in a drill.

---

## Phase 2 — Ship what exists, then spike the unknown.

### 2a. Deploy `765b39c`
`/v1/executions/prepare` and the pre-trade gate exist locally with 277 passing
tests and are **entirely absent from production** (live `openapi.json` has no
`/v1/executions/*`; `/version` reports `4c9a0d1`, two commits behind). Ship it
with `RWOO_EXECUTION_MODE=disabled`. Callers get validated intents and receipts;
nothing can trade. Zero custody risk, immediate visible surface.

### 2b. Pin the data mapping (certification gate A) — **mapping DONE 2026-07-22**
Verified against the live CLOB. This was not academic — it found a blocking
defect:

> `_parse_market` read `payload["tick_size"]`. Polymarket does not emit that key;
> the field is **`minimum_tick_size`**, and it arrives as a **JSON float**. The
> tick silently resolved to `Decimal(0)`, so `validate_order` would have raised
> `VENUE_CONFIG_INVALID` on **every real order**. All 16 original adapter tests
> passed throughout, because their fixtures used the invented key name.

Fixed, plus three hardening items the gap exposed:
- `tick_from_venue()` accepts the venue's float via a `str` round-trip but only
  against an allow-list of documented ticks (0.1 / 0.01 / 0.001 / 0.0001).
- `/markets` and `/book` each report a tick independently; disagreement now
  refuses rather than silently picking one.
- The book is now verified to belong to the order's token. Previously a data
  source returning the wrong book would price the order against a different
  market with every other check still green.

Verbatim venue payloads are pinned in `tests/fixtures/`, asserted by
`tests/test_polymarket_live_contract.py`. Suite: 277 → 293.

**Standing rule this establishes:** venue-contract fixtures are *captured*, never
hand-written. A hand-written fixture tests our assumption, not the venue.

Still open in 2b: pin `py-sdk` to an exact commit and re-verify the mapping
against it.

### 2c. The Variant A spike (Gate G0)
**Runnable: `scripts/g0_spike.py`.** Configure via `.env.spike` (copy from
`.env.spike.example`, `chmod 600`, gitignored). Jenny runs it; the throwaway key
is never pasted into a prompt, a chat, or a shared terminal, and the script
redacts every secret it loads.

The script encodes the experiment in its own structure: `caller_stage()` holds
the key and emits `(path, body_bytes, headers)`; `relay_stage()` takes exactly
those three arguments and **has no parameter through which a key or credential
could be passed**. If a future edit needs to add one, Variant A has failed. L1/L2
conventions come from `py-clob-client` verbatim rather than being reimplemented,
because a subtly wrong HMAC serialisation is the exact failure this gate exists
to catch.

    python scripts/g0_spike.py --pick-market   # no key needed
    python scripts/g0_spike.py --dry-run       # default; no POST
    python scripts/g0_spike.py --live          # rests a real order

**SDK evidence for Variant A — verified 2026-07-22 against `py-clob-client`
0.34.6.** The design is not merely possible, it is the pattern the SDK is built
around:

- `RequestArgs` carries an optional **`serialized_body`**, and
  `create_level_2_headers` *prefers* it over re-rendering `body` — its own
  comment says "for deterministic signing".
- `ClobClient.post_order` then sends `data=request_args.serialized_body`.

So the SDK already signs and transmits the identical string by construction.
Separating "who serialises + signs" from "who transmits" is a supported split,
which is exactly what Variant A needs.

**Trap found while validating the spike (would have produced a false NEGATIVE on
this gate):** the HMAC covers `timestamp + method + path + body_string`, and the
SDK renders that string with `json.dumps(..., separators=(",", ":"),
ensure_ascii=False)`. A default `json.dumps` emits `", "` / `": "` instead. Sign
one, post the other, and auth fails — which reads as *"the venue rejects relayed
orders"* when it is really our own serialisation bug. The spike now takes the
string from the SDK path verbatim.

**Smoke-tested end to end 2026-07-22** with a disposable zero-funds key against
the live CLOB: L2 derivation, order signing, and header construction all pass;
only the funded POST remains.

Throwaway wallet, own funds, sub-dollar size, off the production box.
Prove, in order:
- Caller-computed L2 HMAC survives relay by a third-party server byte-identical.
- CLOB accepts an order whose maker == the L2 account, posted by a foreign IP.
- Confirm whether CLOB rejects L2-key/maker mismatch (it should; verify, don't
  assume).
- Capture the exact rejection taxonomy for later state mapping.

**Exit:** `/v1/executions/prepare` live in prod; SDK pinned with mapping diffed;
G0 decided in writing (A or B).

---

## Phase 3 — `POST /v1/executions/{id}/submit-signed` (Polymarket)

The one genuinely missing piece. Design notes that are not optional:

1. **Signature-to-intent binding is the integrity core.** Recover the signer from
   the EIP-712 struct and verify it equals the declared maker. Then assert the
   signed struct's tokenID, side, price, size, expiration, and nonce **match the
   prepared intent exactly**. Without this, TrueOdds prepares intent X, the
   caller signs Y, and the receipt attests to X. That single gap would void every
   receipt the product sells.
2. **Opaque-body discipline.** Store and relay the caller's payload as received
   bytes plus a hash. Never round-trip it through a dict.
3. **One-shot replay protection.** Bind each signature to exactly one intent_id
   and burn it on use. TrueOdds must be structurally incapable of re-posting a
   caller's signed order — reuse the existing SQLite uniqueness lock
   (`execution.py:146`), which is already the idempotency mechanism.
4. **Reuse the state machine as built.** `execution.py:252-267` already has the
   correct discipline: `ExecutionError` → clean `REJECTED` (pre-transmission),
   anything else → `UNKNOWN` + mandatory reconcile. Do not weaken it. Every
   ambiguous outcome reconciles before any resubmission.
5. **Revalidate immediately before relay.** `_pre_submit_validate` already runs
   the gate and leaves a failed intent `PREPARED` and retryable. Keep that.
6. **Expiry handling.** Signed orders carry an expiration. Reject on arrival if
   too near expiry to relay safely; surface remaining validity in the response.
7. **Fees stay non-custodial.** Charge the execution-assist fee via the **existing
   x402 rail** on the endpoint itself. Never take a cut from proceeds — that
   would reintroduce a flow of funds through TrueOdds and undo the whole design.
8. **Per-caller isolation.** Tag every intent, receipt, and risk check with a
   caller id. Limits and the kill switch operate per caller *and* globally
   (§6 of the signer runbook already specifies this).

**Exit:** Variant-A relay of a real caller-signed order on mainnet at capped
size; receipt chain verifiable end to end; forced-`UNKNOWN` drill reconciles
correctly; TrueOdds holds no caller secret at rest, demonstrated by inspecting
the datastore.

---

## Phase 4 — Certification before it is a product

Work the existing gate list in `EXECUTION_SIGNER_AND_CERTIFICATION.md:120+`.
Non-negotiable additions for the relay model:
- Restart/crash mid-relay leaves no intent in a lying state.
- Duplicate submission of the same signature is refused, provably.
- Venue halt / market closed between prepare and relay is caught by revalidation.
- Rejection taxonomy from the 2c spike is fully mapped to states.
- Rate limiting and per-caller quotas — a shared relay is a shared blast radius.

**Legal, in parallel, not after:** signal + sizing + venue routing + order
relay is a materially different regulatory posture than a data feed. This needs
counsel's opinion **before** the endpoint is public, and it is the item most
likely to invalidate work if left to the end. Start it during Phase 2.

---

## Phase 5 — Kalshi and Limitless (deferred, by design)

Not started until Polymarket is certified and earning.

- **Limitless** — verify the order-signing scheme first. If it is
  Polymarket-shaped (on-chain, user-signed, relayable), it inherits the Phase 3
  design almost directly. Unverified today; do not assume.
- **Kalshi** — structurally different. A CFTC-regulated exchange with
  account-based API credentials and no user-signed-order model. Relaying a Kalshi
  order means holding the caller's Kalshi credential; there is no Variant A. The
  honest interim product is **routing**: deep-link the caller into the correct
  Kalshi market with the intent pre-filled, and receipt the recommendation, not
  the execution. Revisit only if Kalshi ships a delegated-trading model.

Both already have live read coverage (`readers/kalshi.py`, `readers/limitless.py`)
and are already in `/v1/supported-markets` and `/v1/cross-venue-edge`. Signal
coverage is done for all three; only execution is Polymarket-first.

---

## Sequencing summary

| Phase | Blocks on | Custody risk |
|---|---|---|
| 1 Infra/security | nothing — start now | none |
| 2a Deploy prepare | Phase 1 | none (execution disabled) |
| 2b Pin SDK mapping | nothing | none |
| 2c Variant A spike | 2b | own throwaway funds only |
| 3 submit-signed | **G0** | none if Variant A holds |
| 3b Agentic Wallet backend | 3 + OKX wallet login test | caller-owned funds only |
| 4 Certification | 3b + legal | first real caller funds |
| 5 Kalshi/Limitless | 4 earning | Kalshi: credential — revisit |

## Open items

- [x] Variant chosen: **A** (caller-supplied L2 headers, zero secrets at rest) — 2026-07-22.
- [x] G0: Variant A proven against live CLOB with POLY_1271/pUSD/V2, then live order cancelled — 2026-07-23.
- [x] ASP `submit-signed`: accepts caller-signed opaque body bytes + L2 headers,
      validates order economics against prepared intent, relays byte-identical,
      and burns body hash for replay protection — 2026-07-23.
- [x] Settlement metadata updated from old USDC.e/V1 assumptions to
      pUSD/V2/POLY_1271, with funding routes for direct pUSD, Polygon USDC.e,
      Polygon native USDC, Polygon USDT, and X Layer USDT via OKX bridge.
- [ ] OKX Agentic Wallet signer backend: email/API-key session can fund/bridge,
      but Polymarket L2 credential creation and POLY_1271 order signing are not
      yet live-tested without a raw private key.
- [ ] Limitless order-signing scheme — verified or not.
- [ ] Counsel opinion on signal + sizing + routing + relay.
- [ ] Trade-only deposit-wallet contract question — remains open but is
      **irrelevant to this plan**; it only gates the custodial model, which this
      plan does not pursue.
