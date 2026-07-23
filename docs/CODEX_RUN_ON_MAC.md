# Codex: run the deposit-wallet sweep test on the Mac

This is the cheap de-risk for the just-in-time-balance safety model. It proves the
POLY_1271 deposit wallet can push unspent pUSD back to its owner via a relayer
WALLET batch — the one unknown blocking the autonomous
`fund → approve(MaxUint256) → trade → sweep` flow. See
[`evidence/G2_DEPOSIT_WALLET_SWEEP_2026-07-23.md`](evidence/G2_DEPOSIT_WALLET_SWEEP_2026-07-23.md)
for the full rationale and the result template to fill in.

The sweep batch is mechanically identical to the already-confirmed approval batch
(`agentic_polymarket_setup.py`): same relayer, same builder creds, same
`TransactionType.WALLET`, same OnchainOS signer. Only the call changes —
`transfer(owner, 0.1 pUSD)` instead of `approve`. No private key is used.

## Preconditions (verify all before `--execute`)

1. `onchainos wallet geoblock` → `{"blocked":false}`. **Must be the Mac**, not a
   geoblocked host. A blocked host will have the relayer reject the batch.
2. `onchainos wallet status` logged in as `kingsjanet0@gmail.com` — the owner of
   deposit wallet `0x577108052c8D862984B724668E2f6035Eb6Fa5c5`. Not the okx.ai
   registration account, not `jennyoliver630@gmail.com`.
3. Builder credentials at `/tmp/.trueodds_builder_creds.json`, mode 600.
4. `export SPIKE_POLYGON_RPC_URL=<polygon rpc>`.
5. Run inside the `.venv-spike` environment so `py_builder_relayer_client` and
   `py_builder_signing_sdk` import.

## Dry run first (no broadcast, no creds needed)

```bash
python scripts/agentic_polymarket_sweep_test.py
```

Confirms the batch plan: sweep 100000 base units (0.1 pUSD) from the deposit
wallet to owner `0x48ddC64e362e337b1eaEA67486A9F8c2869eAF38`.

## Live run

```bash
python scripts/agentic_polymarket_sweep_test.py --execute
```

Defaults: 0.1 pUSD, recipient = owner, creds at `/tmp/.trueodds_builder_creds.json`,
RPC from `$SPIKE_POLYGON_RPC_URL`.

## Pass criteria

- Prints `SWEEP CONFIRMED: the deposit wallet can withdraw pUSD via a WALLET batch.`
- The emitted JSON shows `recipient_delta` == 100000 and a `0x1`-status batch.
- If `wallet_delta` > 100000, the extra is a relayer fee skimmed from collateral —
  record it; it feeds the JIT sizing.

## After the run

1. Paste the full JSON output and the Polygon tx hash back into the TrueOdds
   thread.
2. Fill `docs/evidence/G2_DEPOSIT_WALLET_SWEEP_2026-07-23.md` with the real
   relayer tx id, Polygon tx, receipt status, before/after balances, deltas, and
   any fee, then flip Status to `CONFIRMED` (or `FAILED` with the exact relayer
   error).

## Do NOT

- Do **not** re-fund or re-bridge. The G1 bridge is complete; a 0.1 pUSD sweep
  leaves ~2.29 pUSD in the wallet, clear of the 2.5 X Layer bridge floor.
- Do **not** deploy the deposit wallet — it is already deployed; the script errors
  rather than redeploy.
- The sweep step itself does not change the exchange allowance; the approval is the
  next step (below), now that the JIT policy is decided.

## If it passes: the autonomous JIT approval (policy decided 2026-07-23)

The sweep proves the withdrawal leg. The remaining approval leg is now sanctioned:
grant `MaxUint256` and keep the wallet at ~0 between trades. It is an explicit,
gated opt-in (`scripts/jit_execution.py`).

**Spender is market-dependent — derive it, do not hardcode.** A neg-risk market
settles through `neg_risk_exchange_v2`, everything else through `exchange_v2`
(`0xE111180000d2663C0091e4f400237545B87B996B`). Approving the wrong one leaves the
order's allowance at 0. Derive it from the order's token:

```bash
SPENDER=$(python - <<'PY'
import sys; sys.path.insert(0, "scripts")
import polymarket_agent_helper as h
print(h._spender_for_token({"SPIKE_CHAIN_ID": "137"}, "<ORDER_TOKEN_ID>"))
PY
)
echo "spender: $SPENDER"

# dry run — confirms approval_kind=maxuint256_jit_policy, no broadcast
python scripts/agentic_polymarket_setup.py --spender "$SPENDER" --max-approval --jit

# live — grants the MaxUint256 allowance from the deposit wallet via the relayer
python scripts/agentic_polymarket_setup.py --spender "$SPENDER" --max-approval --jit --execute
```

`--max-approval` without `--jit` is refused by design. After the approval confirms,
re-submit the same order: it should now clear the allowance check and rest — capture
the order ID, then cancel to complete the rest-and-cancel certification. The full autonomous cycle is
then `fund exact notional → approve(MaxUint256) once → sign+submit → sweep unspent
→ idle at ~0`; `SPIKE_JIT_MAX_APPROVAL=1` selects tight funding + MaxUint256 in the
`g0_spike.py` deposit-wallet setup path.

## The one remaining gate before a live BUY

The **order-signing adapter** (Agentic Wallet POLY_1271 / ERC-1271 / ERC-7739) is
still uncertified — the primitives pass (eip712 sign, L2 creds, HMAC, ERC-7739
digest match) but no order has been accepted through the Agentic Wallet backend.
A live BUY needs: this approval **and** a tiny rest-and-cancel order accepted and
cancelled through the adapter. Approval alone does not enable trading. Do not mark
`okx_agentic_wallet` executable until that rest-and-cancel is recorded in
`docs/evidence/`.
