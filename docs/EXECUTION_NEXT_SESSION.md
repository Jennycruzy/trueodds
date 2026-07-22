# Execution — Continue Here Next Session

Last updated: 2026-07-22

## Where we are

Built the isolated, unfunded execution layer for the ASP. Funds are structurally
impossible to move — no signer ships, and `RWOO_EXECUTION_MODE` stays `disabled`.

Done this session:
- `src/rwoo/adapters/polymarket.py` — isolated Polymarket adapter: read-only
  public market/book data, exact-`Decimal` pre-trade gate (binding, tick, min
  size, staleness, empty/crossed book, price protection), fail-closed
  `PolymarketAdapter` that raises `SIGNER_UNAVAILABLE` unless a signer is
  injected (none is). `HttpPolymarketDataSource` field mapping is PROVISIONAL.
- `src/rwoo/execution.py` — added `_pre_submit_validate` hook and split the
  submit exception handling: `ExecutionError` → clean `REJECTED`
  (pre-transmission), any other exception → `UNKNOWN` (reconcile).
- `tests/test_polymarket_adapter.py` — 16 tests. All green (26 execution/adapter
  + 35 API).
- `docs/EXECUTION_SIGNER_AND_CERTIFICATION.md` — signer/custody/certification
  runbook, incl. §6 multi-funder gates.

## Key decision (settled)

The ASP path is **non-custodial execution-assist**, not a custodial fund:
- The ASP sells signals + prepares/validates order **intents**; the **caller
  signs with their own key** (the same wallet they pay x402 from).
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

## Next actions (pick up here)

1. Build the non-custodial execution-assist flow: `prepare → validate →
   post-signed-order`, where the caller signs and the ASP never holds a key.
2. Optionally wire `PolymarketAdapter` into `create_app` behind a `certification`
   flag for local end-to-end exercise (still unfunded).
3. Only if going custodial multi-funder: resolve the trade-only contract
   question + legal counsel first.

## Standing reminder

Rotate the VPS root password shared in chat. Do not enable funded execution on
the production VPS (8 GB, no swap, prior OOM).
