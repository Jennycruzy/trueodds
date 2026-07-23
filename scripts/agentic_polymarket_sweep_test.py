#!/usr/bin/env python3
"""One-off live sweep test: prove the deposit wallet can push pUSD back to its owner.

Why this exists
---------------
The just-in-time-balance safety model for the MaxUint256 exchange approval
depends on one thing: after a fill or a cancel, unspent collateral must be able
to leave the POLY_1271 deposit wallet. That withdrawal is an
``execute_deposit_wallet_batch`` whose single call is an ERC-20 ``transfer``
instead of ``approve`` -- mechanically identical to the approval batch already
confirmed by ``agentic_polymarket_setup.py`` (same relayer, same builder creds,
same ``TransactionType.WALLET``, same OnchainOS signer). The only open question
is whether Polymarket's relayer permits an *outbound* WALLET-batch transfer.

This script answers that with the smallest possible live move (default 0.1 pUSD),
reads the on-chain balances before and after, and prints sanitized evidence. A
successful run also re-confirms the Agentic Wallet signer over a WALLET batch.

It never loads the buyer private key; the buyer signature is delegated to
OnchainOS exactly as the setup script does. Dry-run by default; pass --execute to
broadcast.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path

# Reuse the proven wiring (relayer construction, OnchainOS signer, credential
# loading, word encoders, and the verified constants) rather than re-deriving it.
import agentic_polymarket_setup as setup

# ERC-20 selectors. transfer(address,uint256) is the standard 0xa9059cbb; this is
# the only difference from the approval batch, which uses 0x095ea7b3.
TRANSFER_SELECTOR = "0xa9059cbb"
BALANCE_OF_SELECTOR = "0x70a08231"

# 0.1 pUSD at 6 decimals. Small enough to be a throwaway de-risk, large enough to
# be unambiguous against balance noise.
DEFAULT_AMOUNT_UNITS = 100_000


def _pusd_balance(rpc_url: str, address: str) -> int:
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [
            {"to": setup.PUSD, "data": BALANCE_OF_SELECTOR + setup._word_address(address)},
            "latest",
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        rpc_url, data=body, headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read())
    if payload.get("error"):
        raise RuntimeError(f"balanceOf RPC error: {payload['error']}")
    return int(payload["result"], 16)


def _units(raw: int) -> str:
    return f"{raw / 1_000_000:.6f}"


def sweep(*, builder_creds_path: Path, to: str, amount_units: int, rpc_url: str) -> None:
    from py_builder_relayer_client.models import DepositWalletCall, TransactionType

    builder_creds = setup._load_credentials(builder_creds_path, {
        "key": ("key", "apiKey", "api_key"),
        "secret": ("secret", "api_secret"),
        "passphrase": ("passphrase", "api_passphrase"),
    })
    relayer = setup._relayer(builder_creds)

    expected = relayer.get_expected_deposit_wallet()
    if expected.lower() != setup.DEPOSIT_WALLET.lower():
        raise RuntimeError(f"derived deposit wallet mismatch: {expected}")

    # Sweep assumes the wallet already exists. Do NOT deploy here; deployment is a
    # separate, already-confirmed step and re-running it should be deliberate.
    if not relayer.get_deployed(setup.DEPOSIT_WALLET, TransactionType.WALLET.value):
        raise RuntimeError(
            "deposit wallet is not deployed; run agentic_polymarket_setup.py first"
        )

    before_wallet = _pusd_balance(rpc_url, setup.DEPOSIT_WALLET)
    before_to = _pusd_balance(rpc_url, to)
    if amount_units > before_wallet:
        raise RuntimeError(
            f"sweep amount {_units(amount_units)} pUSD exceeds deposit-wallet "
            f"balance {_units(before_wallet)} pUSD"
        )

    nonce_payload = relayer.get_nonce(setup.OWNER, TransactionType.WALLET.value)
    if nonce_payload is None or nonce_payload.get("nonce") is None:
        raise RuntimeError("relayer returned no deposit-wallet nonce")
    deadline = str(int(time.time()) + 900)

    call = DepositWalletCall(
        target=setup.PUSD,
        value="0",
        data=TRANSFER_SELECTOR + setup._word_address(to) + setup._word_uint(amount_units),
    )
    response = relayer.execute_deposit_wallet_batch(
        [call], setup.DEPOSIT_WALLET, str(nonce_payload["nonce"]), deadline
    )
    print(f"sweep batch submitted: {response.transaction_id}")
    if not response.wait():
        raise RuntimeError("sweep batch did not confirm")
    print("sweep batch confirmed")

    after_wallet = _pusd_balance(rpc_url, setup.DEPOSIT_WALLET)
    after_to = _pusd_balance(rpc_url, to)
    wallet_delta = before_wallet - after_wallet
    recipient_delta = after_to - before_to

    result = {
        "relayer_transaction_id": response.transaction_id,
        "deposit_wallet": setup.DEPOSIT_WALLET,
        "recipient": to,
        "requested_units": amount_units,
        "deposit_wallet_before": before_wallet,
        "deposit_wallet_after": after_wallet,
        "recipient_before": before_to,
        "recipient_after": after_to,
        "wallet_delta": wallet_delta,
        "recipient_delta": recipient_delta,
        "withdrawal_batch_permitted": True,
    }
    print(json.dumps(result, indent=2))

    # The core question: did the transfer actually land at the recipient?
    if recipient_delta != amount_units:
        raise RuntimeError(
            f"recipient received {_units(recipient_delta)} pUSD, expected "
            f"{_units(amount_units)} pUSD"
        )
    # A larger wallet debit than the transfer would mean the relayer skimmed a
    # pUSD fee from the batch -- surface it rather than hide it.
    if wallet_delta > amount_units:
        print(
            f"note: deposit wallet dropped {_units(wallet_delta)} pUSD but only "
            f"{_units(amount_units)} pUSD reached the recipient; the "
            f"{_units(wallet_delta - amount_units)} pUSD difference is a relayer "
            "fee taken from collateral -- factor it into the JIT sizing."
        )
    print("SWEEP CONFIRMED: the deposit wallet can withdraw pUSD via a WALLET batch.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--builder-credentials",
        default="/tmp/.trueodds_builder_creds.json",
        type=Path,
    )
    parser.add_argument(
        "--to",
        default=setup.OWNER,
        help="sweep destination; defaults to the deposit wallet owner (the reserve)",
    )
    parser.add_argument(
        "--amount-units",
        default=DEFAULT_AMOUNT_UNITS,
        type=int,
        help="pUSD base units to sweep (6 decimals); default 100000 = 0.1 pUSD",
    )
    parser.add_argument(
        "--rpc-url",
        default=os.environ.get("SPIKE_POLYGON_RPC_URL"),
        help="Polygon RPC for balance verification; defaults to $SPIKE_POLYGON_RPC_URL",
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if args.amount_units <= 0:
        raise SystemExit("--amount-units must be positive")
    if len(args.to) != 42 or not args.to.startswith("0x"):
        raise SystemExit("--to must be a 0x-prefixed EVM address")

    if not args.execute:
        print(json.dumps({
            "owner": setup.OWNER,
            "deposit_wallet": setup.DEPOSIT_WALLET,
            "recipient": args.to,
            "amount_units": args.amount_units,
            "private_key_required": False,
            "action": "withdraw_pusd_via_wallet_batch",
            "note": "dry run -- re-run with --execute to broadcast",
        }, indent=2))
        return

    if not args.rpc_url:
        raise SystemExit("--rpc-url (or $SPIKE_POLYGON_RPC_URL) is required for --execute")

    sweep(
        builder_creds_path=args.builder_credentials,
        to=args.to,
        amount_units=args.amount_units,
        rpc_url=args.rpc_url,
    )


if __name__ == "__main__":
    main()
