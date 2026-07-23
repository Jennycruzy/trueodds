#!/usr/bin/env python3
"""Deploy and approve a Polymarket deposit wallet with OKX Agentic Wallet.

This script runs in the certification environment. It loads TrueOdds builder
credentials from a mode-600 temporary file and delegates the buyer signature
to OnchainOS. Builder credentials authenticate the relayer integration; they
are not the buyer's CLOB L2 credentials. The script never loads or accepts the
buyer's private key.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import time
from pathlib import Path

OWNER = "0x48ddC64e362e337b1eaEA67486A9F8c2869eAF38"
DEPOSIT_WALLET = "0x577108052c8D862984B724668E2f6035Eb6Fa5c5"
CHAIN_ID = 137
CLOB_HOST = "https://clob.polymarket.com"
RELAYER_URL = "https://relayer-v2.polymarket.com"
PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
APPROVE_SELECTOR = "0x095ea7b3"


def _word_address(value: str) -> str:
    return value.lower().removeprefix("0x").rjust(64, "0")


def _word_uint(value: int) -> str:
    return hex(value)[2:].rjust(64, "0")


def _load_credentials(path: Path, aliases: dict[str, tuple[str, ...]]) -> dict[str, str]:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise SystemExit(f"credential file must be mode 600, got {oct(mode)}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    result = {}
    for target, names in aliases.items():
        result[target] = next((str(payload[n]) for n in names if payload.get(n)), "")
        if not result[target]:
            raise SystemExit(f"credential file is missing {target}")
    return result


class OnchainOSSigner:
    """Minimal signer interface expected by py-builder-relayer-client."""

    def __init__(self, owner: str = OWNER):
        self._owner = owner

    def address(self) -> str:
        return self._owner

    def sign_typed_data(self, full_message: dict) -> str:
        encoded = json.dumps(full_message, separators=(",", ":"))
        result = subprocess.run(
            [
                "onchainos", "wallet", "sign-message",
                "--type", "eip712",
                "--message", encoded,
                "--chain", "polygon",
                "--from", self._owner,
                "--force",
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Agentic Wallet EIP-712 signing failed with exit code {result.returncode}"
            )
        payload = json.loads(result.stdout)
        signature = ((payload.get("data") or {}).get("signature") if payload.get("ok") else None)
        if not isinstance(signature, str) or not signature:
            raise RuntimeError("Agentic Wallet returned no EIP-712 signature")
        return signature if signature.startswith("0x") else f"0x{signature}"


def _relayer(builder_creds: dict[str, str]):
    from py_builder_relayer_client.client import RelayClient
    from py_builder_signing_sdk.config import BuilderApiKeyCreds, BuilderConfig

    config = BuilderConfig(
        local_builder_creds=BuilderApiKeyCreds(**builder_creds)
    )
    client = RelayClient(
        RELAYER_URL,
        CHAIN_ID,
        builder_config=config,
        rpc_url=os.environ.get("SPIKE_POLYGON_RPC_URL"),
    )
    client.signer = OnchainOSSigner()
    return client


def execute(*, builder_creds_path: Path, spender: str, approval_units: int) -> None:
    from py_builder_relayer_client.models import DepositWalletCall, TransactionType

    builder_creds = _load_credentials(builder_creds_path, {
        "key": ("key", "apiKey", "api_key"),
        "secret": ("secret", "api_secret"),
        "passphrase": ("passphrase", "api_passphrase"),
    })
    relayer = _relayer(builder_creds)

    expected = relayer.get_expected_deposit_wallet()
    if expected.lower() != DEPOSIT_WALLET.lower():
        raise RuntimeError(f"derived deposit wallet mismatch: {expected}")

    if not relayer.get_deployed(DEPOSIT_WALLET, TransactionType.WALLET.value):
        response = relayer.deploy_deposit_wallet()
        print(f"deployment submitted: {response.transaction_id}")
        if not response.wait():
            raise RuntimeError("deposit-wallet deployment did not confirm")
        print("deposit wallet deployed")
    else:
        print("deposit wallet already deployed")

    nonce_payload = relayer.get_nonce(OWNER, TransactionType.WALLET.value)
    if nonce_payload is None or nonce_payload.get("nonce") is None:
        raise RuntimeError("relayer returned no deposit-wallet nonce")
    deadline = str(int(time.time()) + 900)
    call = DepositWalletCall(
        target=PUSD,
        value="0",
        data=APPROVE_SELECTOR + _word_address(spender) + _word_uint(approval_units),
    )
    response = relayer.execute_deposit_wallet_batch(
        [call], DEPOSIT_WALLET, str(nonce_payload["nonce"]), deadline
    )
    print(f"bounded approval submitted: {response.transaction_id}")
    if not response.wait():
        raise RuntimeError("bounded approval did not confirm")
    print(f"bounded approval confirmed: {approval_units} pUSD base units")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--builder-credentials",
        default="/tmp/.trueodds_builder_creds.json",
        type=Path,
    )
    parser.add_argument("--spender", required=True)
    parser.add_argument("--approval-units", required=True, type=int)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.approval_units <= 0:
        raise SystemExit("--approval-units must be positive")
    if len(args.spender) != 42 or not args.spender.startswith("0x"):
        raise SystemExit("--spender must be a 0x-prefixed EVM address")
    if not args.execute:
        print(json.dumps({
            "owner": OWNER,
            "deposit_wallet": DEPOSIT_WALLET,
            "spender": args.spender,
            "approval_units": args.approval_units,
            "private_key_required": False,
            "actions": ["deploy_if_needed", "bounded_pusd_approval"],
        }, separators=(",", ":")))
        return
    execute(
        builder_creds_path=args.builder_credentials,
        spender=args.spender,
        approval_units=args.approval_units,
    )


if __name__ == "__main__":
    main()
