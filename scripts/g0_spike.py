#!/usr/bin/env python3
"""G0 spike — prove Variant A: a third party can relay a caller-signed order.

WHAT THIS PROVES (or disproves)
-------------------------------
The non-custodial design in ``docs/EXECUTION_BUILD_PLAN.md`` rests on one
unverified claim: that TrueOdds can accept an order a caller signed *and*
authenticated locally, forward it **byte for byte**, and have Polymarket accept
it — while TrueOdds holds no secret of any kind.

Polymarket auth has two levels. L1 (the private key) signs the order struct;
L2 (apiKey/secret/passphrase, HMAC-SHA256) authenticates the HTTP request. The
adapter never needs L1. But L2 headers are still required on ``POST /order``,
and they are computed over the request body. That is the crux: if the relay
re-serializes the body at any point, the HMAC breaks and Variant A is dead.

STRUCTURE — read this before running
------------------------------------
The script splits into two roles with a hard boundary:

    caller_stage()   holds the key, signs, builds L2 headers, emits opaque bytes
    relay_stage()    receives ONLY (path, body_bytes, headers) — no key, no
                     secret, no ability to re-sign. This is TrueOdds.

``relay_stage`` is deliberately written to take no credential argument. If a
future edit needs to pass one in, Variant A has failed and the plan must fall
back to Variant B. That signature is the experiment.

USAGE
-----
    cp .env.spike.example .env.spike && chmod 600 .env.spike
    # fill in .env.spike, then:
    python scripts/g0_spike.py --pick-market      # find a market, no key needed
    python scripts/g0_spike.py --dry-run          # preflight + sign, no POST
    python scripts/g0_spike.py --approve          # set the allowance (costs gas)
    python scripts/g0_spike.py --live             # actually rests an order

``--dry-run`` is the default. ``--live`` spends real money; keep it tiny.

PRICE IT TO REST, NOT TO FILL
-----------------------------
G0 only needs the venue to *accept* a relayed order — it does not need a trade.
A BUY at or above the best ask matches immediately and leaves you holding a
position. A BUY well below the best ask simply rests in the book: the venue
returns an order id (the proof we want), you cancel it, and you end up owning
nothing. Use ``--pick-market`` to see the touch, then price far away from it.

FUNDING
-------
Polymarket CLOB V2 settles in pUSD on Polygon. The direct on-chain onramp wraps
USDC.e into pUSD. If a caller holds native Polygon USDC or Polygon USDT, the
caller-side setup can route that token through the caller's own Polymarket bridge
deposit address, which credits pUSD to the caller's deposit wallet. X Layer
USDT/USDT0 should be routed caller-side with OKX/onchainos into that same
Polymarket EVM deposit address. TrueOdds never receives the funds or the key.

SECRETS
-------
Nothing here prints a secret. Values loaded from .env.spike are redacted in all
output. Run it yourself — the key does not need to pass through anyone else.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV_PATH = REPO / ".env.spike"

REQUIRED = ("SPIKE_PRIVATE_KEY", "SPIKE_TOKEN_ID")
SECRET_KEYS = ("SPIKE_PRIVATE_KEY",)


# ---------------------------------------------------------------- utilities


def redact(key: str, value: str) -> str:
    """Never let key material reach stdout, a log, or a screen share."""
    if key in SECRET_KEYS or "KEY" in key or "SECRET" in key or "PASSPHRASE" in key:
        return f"<redacted:{len(value)} chars>"
    return value


def load_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        die(f"{ENV_PATH.name} not found. Copy .env.spike.example to .env.spike and fill it in.")

    mode = stat.S_IMODE(ENV_PATH.stat().st_mode)
    if mode & 0o077:
        die(f"{ENV_PATH.name} is mode {mode:o} — readable by others. Run: chmod 600 {ENV_PATH}")

    env: dict[str, str] = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()

    missing = [k for k in REQUIRED if not env.get(k)]
    sig_type = int(env.get("SPIKE_SIGNATURE_TYPE", "0") or "0")
    if sig_type != 3 and not env.get("SPIKE_FUNDER_ADDRESS"):
        missing.append("SPIKE_FUNDER_ADDRESS")
    if missing:
        die(f"{ENV_PATH.name} is missing: {', '.join(missing)}")
    if sig_type == 3 and not env.get("SPIKE_FUNDER_ADDRESS"):
        env["SPIKE_FUNDER_ADDRESS"] = derive_deposit_wallet_address(env)
    return env


def derive_deposit_wallet_address(env: dict[str, str]) -> str:
    """Derive the POLY_1271 deposit wallet address from the owner key."""
    from py_builder_relayer_client.client import RelayClient

    chain_id = int(env.get("SPIKE_CHAIN_ID", "137"))
    relayer_url = env.get("SPIKE_RELAYER_URL", "https://relayer-v2.polymarket.com")
    relayer = RelayClient(
        relayer_url,
        chain_id,
        env["SPIKE_PRIVATE_KEY"],
        rpc_url=env.get("SPIKE_POLYGON_RPC_URL"),
    )
    address = relayer.get_expected_deposit_wallet()
    ok(f"derived deposit wallet funder {address}")
    return address


def die(message: str) -> None:
    print(f"\n  FAIL  {message}\n", file=sys.stderr)
    raise SystemExit(1)


def step(number: str, title: str) -> None:
    print(f"\n[{number}] {title}")


def ok(message: str) -> None:
    print(f"   ok   {message}")


def warn(message: str) -> None:
    print(f"   !!   {message}")


def require_sdk():
    """py-clob-client owns the exact auth conventions. Do not reimplement them.

    The L2 HMAC is computed over a string the *server* reconstructs its own way.
    Hand-rolling that serialization is precisely the class of subtle mismatch
    this spike exists to avoid, so the credential and order-signing steps go
    through the official SDK and only the relay boundary is ours.
    """
    try:
        import py_clob_client  # noqa: F401
    except ImportError:
        die(
            "py-clob-client is not installed. In a scratch venv:\n"
            "        python -m venv .venv-spike && . .venv-spike/bin/activate\n"
            "        pip install py-clob-client\n"
            "      Pin the exact version you use into docs/EXECUTION_BUILD_PLAN.md (gate A)."
        )


# ------------------------------------------------------- chain preflight
#
# The spike signs and relays, but an order also needs collateral and an
# allowance. Without this check a balance/allowance rejection looks identical to
# an auth failure, and G0 would be recorded as "the venue refuses relayed
# orders" when the real cause is an unfunded wallet. That false negative would
# push the whole plan to the weaker Variant B for no reason.

# Verified 2026-07-22 to serve eth_chainId, eth_getTransactionCount, eth_gasPrice
# and eth_maxPriorityFeePerGas without an API key. llamarpc, polygon-rpc.com,
# ankr and blxrbdn were tested and now require keys or refuse outright.
POLYGON_RPCS = (
    "https://polygon-bor-rpc.publicnode.com",
    "https://1rpc.io/matic",
    "https://polygon.drpc.org",
)

SEL_BALANCE_OF = "0x70a08231"   # balanceOf(address)
SEL_ALLOWANCE = "0xdd62ed3e"    # allowance(address,address)
SEL_APPROVE = "0x095ea7b3"      # approve(address,uint256)
SEL_TRANSFER = "0xa9059cbb"     # transfer(address,uint256)
SEL_WRAP = "0x62355638"         # wrap(address,address,uint256)

USDCE_COLLATERAL = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
NATIVE_USDC_POLYGON = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
POLYGON_USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
COLLATERAL_ONRAMP = "0x93070a847efEf7F70739046A929D47a521F5B8ee"
POLYMARKET_BRIDGE_BASE_URL = "https://bridge.polymarket.com"
POLYMARKET_BRIDGE_MIN_UNITS = 2_500_000

USDC_DECIMALS = 6


def _rpc(method: str, params: list) -> object:
    import httpx

    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    # Collect every failure rather than keeping only the last. A malformed
    # request fails at the FIRST endpoint for an informative reason and at the
    # rest for unrelated ones (rate limits, missing API keys); reporting only
    # the last error hides the actual cause behind noise.
    failures: list[str] = []
    for url in POLYGON_RPCS:
        try:
            with httpx.Client(timeout=25) as client:
                response = client.post(url, json=payload, headers={"User-Agent": "curl/8.5.0"})
            data = response.json()
            if "result" in data:
                return data["result"]
            failures.append(f"{url}: {data.get('error')}")
        except Exception as exc:  # try the next endpoint
            failures.append(f"{url}: {type(exc).__name__}: {exc}")
    detail = "\n          ".join(failures)
    die(f"{method} failed on every Polygon RPC endpoint:\n          {detail}")


def _word(value: str | int) -> str:
    if isinstance(value, str):
        return value.lower().replace("0x", "").rjust(64, "0")
    return f"{value:064x}"


def _units(raw: int) -> str:
    from decimal import Decimal
    return f"{Decimal(raw) / Decimal(10 ** USDC_DECIMALS):.6f}".rstrip("0").rstrip(".")


def chain_preflight(env: dict[str, str], required_units: int, spender: str,
                    *, approve: bool) -> bool:
    """Report POL, collateral balance, and allowance. Optionally set allowance.

    Returns True when the wallet is ready to have an order accepted.
    """
    from rwoo.adapters.polymarket import NATIVE_USDC_NOT_COLLATERAL

    owner = env["SPIKE_FUNDER_ADDRESS"]
    collateral = collateral_config(env)
    token = collateral["address"]

    step("0", "PREFLIGHT: on-chain balances and allowance")
    print(f"   owner    {owner}")
    print(f"   token    {token}  ({collateral['name']})")
    print(f"   spender  {spender}")

    gas_raw = int(_rpc("eth_getBalance", [owner, "latest"]), 16)
    gas = gas_raw / 10 ** 18
    bal_raw = int(_rpc("eth_call", [{"to": token, "data": SEL_BALANCE_OF + _word(owner)}, "latest"]) or "0x0", 16)
    allow_raw = int(_rpc("eth_call", [
        {"to": token, "data": SEL_ALLOWANCE + _word(owner) + _word(spender)}, "latest"
    ]) or "0x0", 16)

    ready = True
    print()
    print(f"   POL (gas)          {gas:.4f}" + ("" if gas > 0.05 else "   <-- low"))
    if int(env.get("SPIKE_SIGNATURE_TYPE", "0") or "0") == 3:
        ok("POL is not required in the deposit wallet; relayer handles wallet batches")
    elif gas <= 0.005:
        warn("not enough POL to send an approval transaction")
        ready = False

    print(f"   collateral balance {_units(bal_raw)} {collateral['symbol']}")
    if bal_raw == 0:
        # The single most likely funding mistake, so name it precisely.
        wrong_raw = int(_rpc("eth_call", [
            {"to": NATIVE_USDC_NOT_COLLATERAL, "data": SEL_BALANCE_OF + _word(owner)}, "latest"
        ]) or "0x0", 16)
        if wrong_raw > 0:
            warn(f"you hold {_units(wrong_raw)} of NATIVE USDC ({NATIVE_USDC_NOT_COLLATERAL}).")
            warn("Polymarket does not settle in that token. Swap or bridge to the address above.")
        else:
            warn(f"collateral balance is zero; fund the address above with {collateral['symbol']}")
        ready = False
    elif bal_raw < required_units:
        warn(f"balance {_units(bal_raw)} is below the order notional {_units(required_units)}")
        ready = False

    print(f"   allowance          {_units(allow_raw)} {collateral['symbol']}")
    if allow_raw < required_units:
        if not approve:
            warn(f"allowance below the {_units(required_units)} needed. Re-run with --approve to set it.")
            ready = False
        else:
            ready = _send_approval(env, token, spender, required_units) and ready
    else:
        ok("allowance is sufficient")

    return ready


def collateral_config(env: dict[str, str]) -> dict[str, str | int]:
    if int(env.get("SPIKE_SIGNATURE_TYPE", "0") or "0") == 3:
        from py_clob_client_v2.config import get_contract_config

        cfg = get_contract_config(int(env.get("SPIKE_CHAIN_ID", "137")))
        return {
            "address": cfg.collateral,
            "symbol": "pUSD",
            "name": "Polymarket USD collateral",
            "decimals": 6,
        }
    from rwoo.adapters.polymarket import COLLATERAL
    return COLLATERAL


def _send_approval(env: dict[str, str], token: str, spender: str, required_units: int) -> bool:
    """Send a BOUNDED ERC-20 approval. Never unlimited.

    The signer runbook requires allowances capped to the active tier and
    re-approved deliberately. An unlimited approval on a throwaway is harmless,
    but the spike should model the practice the real flow must follow, so the
    caller sees a bounded approval as the normal shape.
    """
    from eth_account import Account

    # Approve a small, explicit buffer over the requirement rather than 2**256-1.
    amount = required_units * 4
    account = Account.from_key(env["SPIKE_PRIVATE_KEY"])
    if account.address.lower() != env["SPIKE_FUNDER_ADDRESS"].lower():
        die("--approve requires SPIKE_FUNDER_ADDRESS to be the key's own address "
            "(a POLY_1271 deposit wallet must be approved by its owner separately)")

    step("0b", f"PREFLIGHT: approving {_units(amount)} (bounded, not unlimited)")
    nonce = int(_rpc("eth_getTransactionCount", [account.address, "pending"]), 16)
    base_fee = int(_rpc("eth_gasPrice", []), 16)
    tx = {
        "to": token,
        "value": 0,
        "gas": 100_000,
        "maxFeePerGas": base_fee * 2,
        "maxPriorityFeePerGas": min(base_fee, 30_000_000_000),
        "nonce": nonce,
        "chainId": int(env.get("SPIKE_CHAIN_ID", "137")),
        "data": SEL_APPROVE + _word(spender) + _word(amount),
    }
    signed = Account.sign_transaction(tx, account.key)
    # hexbytes 1.x returns .hex() WITHOUT a 0x prefix. Use removeprefix, never
    # lstrip("0x") -- lstrip strips any leading '0' and 'x' characters, so a
    # typed transaction beginning "02f86c..." becomes "2f86c...", silently
    # corrupting the payload into an unparseable transaction.
    raw = signed.raw_transaction.hex()
    tx_hash = _rpc("eth_sendRawTransaction", ["0x" + raw.removeprefix("0x")])
    ok(f"approval submitted: {tx_hash}")
    print("   waiting for confirmation…")

    import time
    for _ in range(40):
        time.sleep(3)
        receipt = _rpc("eth_getTransactionReceipt", [tx_hash])
        if receipt:
            if int(receipt.get("status", "0x0"), 16) == 1:
                ok("approval confirmed")
                return True
            die(f"approval transaction reverted: {tx_hash}")
    warn("approval not confirmed within 2 minutes; check the hash before continuing")
    return False


def _send_token_transfer(env: dict[str, str], token: str, to: str, amount: int) -> bool:
    return _send_eoa_contract_call(
        env,
        token,
        SEL_TRANSFER + _word(to) + _word(amount),
        f"transferring {_units(amount)} token units to {to}",
        "transfer",
    )


def _send_eoa_approval(env: dict[str, str], token: str, spender: str, amount: int,
                       *, label: str = "approval") -> bool:
    return _send_eoa_contract_call(
        env,
        token,
        SEL_APPROVE + _word(spender) + _word(amount),
        f"approving {_units(amount)} for {spender}",
        label,
    )


def _wrap_usdce_to_pusd(env: dict[str, str], to: str, amount: int) -> bool:
    from eth_account import Account

    step("0c", f"SETUP: wrapping {_units(amount)} USDC.e to pUSD")
    allowance = int(_rpc("eth_call", [
        {"to": USDCE_COLLATERAL, "data": SEL_ALLOWANCE + _word(Account.from_key(env["SPIKE_PRIVATE_KEY"]).address) + _word(COLLATERAL_ONRAMP)},
        "latest",
    ]) or "0x0", 16)
    if allowance < amount and not _send_eoa_approval(
        env, USDCE_COLLATERAL, COLLATERAL_ONRAMP, amount, label="onramp approval"
    ):
        return False
    return _send_eoa_contract_call(
        env,
        COLLATERAL_ONRAMP,
        SEL_WRAP + _word(USDCE_COLLATERAL) + _word(to) + _word(amount),
        f"wrapping {_units(amount)} USDC.e into pUSD for deposit wallet",
        "wrap",
    )


def _polymarket_bridge_deposit_address(env: dict[str, str], wallet: str) -> str:
    import httpx

    bridge_host = env.get("SPIKE_POLYMARKET_BRIDGE_HOST", POLYMARKET_BRIDGE_BASE_URL).rstrip("/")
    headers = {"Content-Type": "application/json", "User-Agent": "trueodds-polymarket-agent-helper/0"}
    builder_code = env.get("SPIKE_BUILDER_CODE")
    if builder_code:
        headers["X-Builder-Code"] = builder_code
    step("0c", "SETUP: requesting caller-owned Polymarket bridge address")
    with httpx.Client(timeout=30) as client:
        response = client.post(f"{bridge_host}/deposit", json={"address": wallet}, headers=headers)
    response.raise_for_status()
    payload = response.json()
    evm = (payload.get("address") or {}).get("evm")
    if not isinstance(evm, str) or not evm.startswith("0x"):
        die(f"Polymarket bridge did not return an EVM deposit address: {payload}")
    ok(f"Polymarket EVM deposit address {evm}")
    return evm


def _polymarket_bridge_quote(env: dict[str, str], source_token: str, to: str, amount: int) -> dict:
    import httpx

    bridge_host = env.get("SPIKE_POLYMARKET_BRIDGE_HOST", POLYMARKET_BRIDGE_BASE_URL).rstrip("/")
    token = collateral_config(env)["address"]
    payload = {
        "fromAmountBaseUnit": str(amount),
        "fromChainId": env.get("SPIKE_CHAIN_ID", "137"),
        "fromTokenAddress": source_token,
        "recipientAddress": to,
        "toChainId": "137",
        "toTokenAddress": token,
    }
    with httpx.Client(timeout=30, headers={"User-Agent": "trueodds-polymarket-agent-helper/0"}) as client:
        response = client.post(f"{bridge_host}/quote", json=payload, headers={"Content-Type": "application/json"})
    if response.status_code >= 400:
        warn(f"Polymarket bridge quote failed with HTTP {response.status_code}: {response.text[:240]}")
        return {}
    result = response.json()
    ok(f"Polymarket bridge quote accepted for {_units(amount)} source units")
    return result


def _wait_for_wallet_pusd(env: dict[str, str], wallet: str, required_units: int, label: str) -> bool:
    import time

    token = collateral_config(env)["address"]
    timeout = int(env.get("SPIKE_FUNDING_POLL_SECONDS", "300") or "300")
    deadline = time.time() + timeout
    step("0c", f"SETUP: waiting for pUSD credit after {label}")
    while True:
        balance = int(_rpc("eth_call", [{"to": token, "data": SEL_BALANCE_OF + _word(wallet)}, "latest"]) or "0x0", 16)
        print(f"   deposit wallet pUSD {_units(balance)} / {_units(required_units)} required")
        if balance >= required_units:
            ok("deposit wallet pUSD is sufficient")
            return True
        if time.time() >= deadline:
            warn("pUSD credit not observed before timeout; bridge may still be processing")
            return False
        time.sleep(10)


def _fund_with_polymarket_bridge(env: dict[str, str], source_token: str, symbol: str,
                                 wallet: str, required_units: int, amount: int) -> bool:
    bridge_amount = max(amount, POLYMARKET_BRIDGE_MIN_UNITS)
    step("0c", f"SETUP: routing {_units(bridge_amount)} {symbol} through Polymarket bridge")
    bridge_address = _polymarket_bridge_deposit_address(env, wallet)
    _polymarket_bridge_quote(env, source_token, wallet, bridge_amount)
    if not _send_token_transfer(env, source_token, bridge_address, bridge_amount):
        return False
    return _wait_for_wallet_pusd(env, wallet, required_units, f"{symbol} bridge deposit")


def _send_eoa_contract_call(env: dict[str, str], to: str, data: str, title: str, label: str) -> bool:
    from eth_account import Account

    account = Account.from_key(env["SPIKE_PRIVATE_KEY"])
    step("0c", f"SETUP: {title}")
    nonce = int(_rpc("eth_getTransactionCount", [account.address, "pending"]), 16)
    base_fee = int(_rpc("eth_gasPrice", []), 16)
    tx = {
        "to": to,
        "value": 0,
        "gas": 180_000,
        "maxFeePerGas": base_fee * 2,
        "maxPriorityFeePerGas": min(base_fee, 30_000_000_000),
        "nonce": nonce,
        "chainId": int(env.get("SPIKE_CHAIN_ID", "137")),
        "data": data,
    }
    signed = Account.sign_transaction(tx, account.key)
    raw = signed.raw_transaction.hex()
    tx_hash = _rpc("eth_sendRawTransaction", ["0x" + raw.removeprefix("0x")])
    ok(f"{label} submitted: {tx_hash}")
    return _wait_for_receipt(tx_hash, label)


def _wait_for_receipt(tx_hash: str, label: str) -> bool:
    import time

    print("   waiting for confirmation…")
    for _ in range(40):
        time.sleep(3)
        receipt = _rpc("eth_getTransactionReceipt", [tx_hash])
        if receipt:
            if int(receipt.get("status", "0x0"), 16) == 1:
                ok(f"{label} confirmed")
                return True
            die(f"{label} transaction reverted: {tx_hash}")
    warn(f"{label} not confirmed within 2 minutes; check the hash before continuing")
    return False


def setup_deposit_wallet(env: dict[str, str], required_units: int, spender: str) -> bool:
    """Autonomously prepare the POLY_1271 deposit wallet for the spike."""
    from py_builder_relayer_client.client import RelayClient
    from py_builder_relayer_client.models import DepositWalletCall, TransactionType
    from py_builder_signing_sdk.config import BuilderApiKeyCreds, BuilderConfig
    from py_clob_client_v2 import AssetType, BalanceAllowanceParams, ClobClient

    if int(env.get("SPIKE_SIGNATURE_TYPE", "0") or "0") != 3:
        die("--setup-deposit-wallet requires SPIKE_SIGNATURE_TYPE=3")

    chain_id = int(env.get("SPIKE_CHAIN_ID", "137"))
    host = env.get("SPIKE_CLOB_HOST", "https://clob.polymarket.com")
    relayer_url = env.get("SPIKE_RELAYER_URL", "https://relayer-v2.polymarket.com")
    owner_client = ClobClient(host=host, chain_id=chain_id, key=env["SPIKE_PRIVATE_KEY"])
    owner_creds = owner_client.create_or_derive_api_key()
    owner_client.set_api_creds(owner_creds)
    builder_creds = owner_client.create_builder_api_key()
    builder_config = BuilderConfig(local_builder_creds=BuilderApiKeyCreds(
        key=builder_creds["key"],
        secret=builder_creds["secret"],
        passphrase=builder_creds["passphrase"],
    ))
    relayer = RelayClient(
        relayer_url,
        chain_id,
        env["SPIKE_PRIVATE_KEY"],
        builder_config,
        rpc_url=env.get("SPIKE_POLYGON_RPC_URL"),
    )
    wallet = env["SPIKE_FUNDER_ADDRESS"]
    if wallet.lower() != relayer.get_expected_deposit_wallet().lower():
        die("SPIKE_FUNDER_ADDRESS does not match the derived deposit wallet")

    step("0a", "SETUP: deploy deposit wallet if needed")
    if relayer.get_deployed(wallet, TransactionType.WALLET.value):
        ok("deposit wallet already deployed")
    else:
        response = relayer.deploy_deposit_wallet()
        ok(f"wallet deployment submitted: {response.transaction_id}")
        confirmed = response.wait()
        if not confirmed:
            die("deposit wallet deployment did not confirm")
        ok("deposit wallet deployed")

    token = collateral_config(env)["address"]
    owner = owner_client.get_address()
    # Autonomous JIT policy: fund exactly one order's worth and sweep the
    # remainder to ~0 afterward, so the MaxUint256 approval below is only ever
    # live over a single order's notional. Off the policy, keep the historical
    # 4x buffer. jit and jit_execution stay in scope for the approval step below.
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    import jit_execution
    jit = jit_execution.jit_enabled(env)
    target_units = jit_execution.jit_fund_units(required_units) if jit else required_units * 4
    wallet_balance = int(_rpc("eth_call", [{"to": token, "data": SEL_BALANCE_OF + _word(wallet)}, "latest"]) or "0x0", 16)
    if wallet_balance < required_units:
        transfer_units = max(target_units - wallet_balance, required_units - wallet_balance)
        eoa_pusd = int(_rpc("eth_call", [{"to": token, "data": SEL_BALANCE_OF + _word(owner)}, "latest"]) or "0x0", 16)
        if eoa_pusd >= transfer_units:
            if not _send_token_transfer(env, token, wallet, transfer_units):
                return False
        else:
            eoa_usdce = int(_rpc("eth_call", [{"to": USDCE_COLLATERAL, "data": SEL_BALANCE_OF + _word(owner)}, "latest"]) or "0x0", 16)
            if eoa_usdce >= transfer_units:
                if not _wrap_usdce_to_pusd(env, wallet, transfer_units):
                    return False
            else:
                bridge_sources = [
                    ("USDC", NATIVE_USDC_POLYGON),
                    ("USDT", POLYGON_USDT),
                ]
                balances = []
                funded = False
                for symbol, address in bridge_sources:
                    raw = int(_rpc("eth_call", [{"to": address, "data": SEL_BALANCE_OF + _word(owner)}, "latest"]) or "0x0", 16)
                    balances.append(f"{symbol} {_units(raw)}")
                    if raw >= POLYMARKET_BRIDGE_MIN_UNITS:
                        if not _fund_with_polymarket_bridge(env, address, symbol, wallet, required_units, transfer_units):
                            return False
                        funded = True
                        break
                if not funded:
                    die(
                        f"EOA pUSD {_units(eoa_pusd)}, USDC.e {_units(eoa_usdce)}, "
                        f"and bridgeable Polygon balances ({', '.join(balances)}) are below setup need. "
                        "For X Layer USDT/USDT0, run scripts/polymarket_agent_helper.py "
                        "--funding-plan --source-asset xlayer-usdt or xlayer-usdt0 and execute that route locally."
                    )
    else:
        ok("deposit wallet collateral is sufficient")

    allowance = int(_rpc("eth_call", [
        {"to": token, "data": SEL_ALLOWANCE + _word(wallet) + _word(spender)}, "latest"
    ]) or "0x0", 16)
    if allowance >= required_units:
        ok("deposit wallet allowance is sufficient")
    else:
        step("0d", "SETUP: approving exchange from deposit wallet via relayer")
        nonce_payload = relayer.get_nonce(owner, TransactionType.WALLET.value)
        nonce = str(nonce_payload.get("nonce"))
        import time
        deadline = str(int(time.time()) + 900)
        approval_units = jit_execution.exchange_approval_units(
            jit_policy=jit, required_units=required_units
        )
        # Autonomous JIT policy (jit=True): the relayer forces MaxUint256, and
        # safety comes from JIT-to-zero balance -- funded tight above, swept after
        # -- not from the allowance number. Off the policy, stay bounded to this
        # order and let the relayer reject it deliberately.
        call = DepositWalletCall(
            target=token,
            value="0",
            data=SEL_APPROVE + _word(spender) + _word(approval_units),
        )
        response = relayer.execute_deposit_wallet_batch([call], wallet, nonce, deadline)
        ok(f"approval batch submitted: {response.transaction_id}")
        confirmed = response.wait()
        if not confirmed:
            die("deposit wallet approval batch did not confirm")
        ok("deposit wallet approval confirmed")

    step("0e", "SETUP: sync CLOB deposit-wallet balance cache")
    trading_client = ClobClient(
        host=host,
        chain_id=chain_id,
        key=env["SPIKE_PRIVATE_KEY"],
        creds=owner_creds,
        signature_type=3,
        funder=wallet,
    )
    result = trading_client.update_balance_allowance(
        BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
    )
    ok(f"CLOB balance cache synced: {result}")
    return True


# ---------------------------------------------------------------- discovery


def pick_market(host: str) -> None:
    """Find a liquid market and print ready-to-paste .env.spike lines."""
    import httpx

    with httpx.Client(timeout=30, headers={"User-Agent": "curl/8.5.0"}) as client:
        response = client.get(f"{host}/sampling-markets")
        response.raise_for_status()
        markets = response.json().get("data") or []

    live = [
        m for m in markets
        if m.get("active") and not m.get("closed")
        and m.get("accepting_orders") and not m.get("neg_risk")
    ]
    if not live:
        die("no active, order-accepting, non-neg-risk market found")

    print(f"\nFound {len(live)} candidate markets. First few:\n")
    for market in live[:5]:
        yes = next((t for t in market["tokens"] if t["outcome"].upper() == "YES"), None)
        if not yes:
            continue
        print(f"  {market['question'][:70]}")
        print(f"    tick={market.get('minimum_tick_size')}  min_size={market.get('minimum_order_size')}")
        print(f"    SPIKE_CONDITION_ID={market['condition_id']}")
        print(f"    SPIKE_TOKEN_ID={yes['token_id']}")
        print()

    print("Pick one, paste its two lines into .env.spike, and choose a price far")
    print("from the touch so the order RESTS rather than fills.\n")


# ---------------------------------------------------------------- the roles


def caller_stage(env: dict[str, str]) -> tuple[str, bytes, dict[str, str]]:
    """The CALLER's agent. Holds the key. Returns only what a relay may see.

    Everything secret stays inside this function. The return value is the exact
    payload TrueOdds would receive over the wire: a path, opaque bytes, and
    headers the caller already computed.
    """
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds, OrderArgs
    from py_clob_client.order_builder.constants import BUY, SELL

    chain_id = int(env.get("SPIKE_CHAIN_ID", "137"))
    host = env.get("SPIKE_CLOB_HOST", "https://clob.polymarket.com")
    sig_type = int(env.get("SPIKE_SIGNATURE_TYPE", "0"))

    if sig_type == 3:
        return caller_stage_poly_1271(env)

    step("1", "CALLER: initialise client with the throwaway key (L1)")
    kwargs = {"key": env["SPIKE_PRIVATE_KEY"], "chain_id": chain_id}
    if sig_type != 0:
        kwargs["signature_type"] = sig_type
        kwargs["funder"] = env["SPIKE_FUNDER_ADDRESS"]
    client = ClobClient(host, **kwargs)
    ok(f"signer address {client.get_address()}")
    if client.get_address().lower() != env["SPIKE_FUNDER_ADDRESS"].lower() and sig_type == 0:
        warn("SPIKE_FUNDER_ADDRESS does not match the derived address (fine only if sig_type != 0)")

    step("2", "CALLER: derive L2 credentials from the key (never leaves this box)")
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    ok("L2 creds derived: " + ", ".join(
        f"{name}={redact(name.upper(), str(getattr(creds, name)))}"
        for name in ("api_key", "api_secret", "api_passphrase")
        if hasattr(creds, name)
    ))

    step("3", "CALLER: build and sign the order struct (V3 patched)")

    # ---------------------------------------------------------------
    # Polymarket migrated to a new EIP-712 order struct (V2/V3).
    # The old struct had: salt, maker, signer, taker, tokenId,
    # makerAmount, takerAmount, expiration, nonce, feeRateBps, side,
    # signatureType.
    #
    # The new struct is:
    #   Order(uint256 salt, address maker, address signer,
    #         uint256 tokenId, uint256 makerAmount, uint256 takerAmount,
    #         uint8 side, uint8 signatureType, uint256 timestamp,
    #         bytes32 metadata, bytes32 builder)
    #
    # Removed: taker, expiration, nonce, feeRateBps.
    # Added: timestamp, metadata, builder.
    # Domain version changed from "1" to "2".
    #
    # py-clob-client 0.34.6 signs the OLD struct and the venue rejects
    # it with "invalid order version". We rebuild the signing from
    # scratch using eth_account's sign_typed_data, matching the new
    # ts-sdk (Polymarket/ts-sdk packages/client/src/exchange.ts).
    # ---------------------------------------------------------------
    import time as _time
    from eth_account import Account
    from py_clob_client.order_builder.builder import ROUNDING_CONFIG

    side_const = BUY if env.get("SPIKE_SIDE", "BUY").upper() == "BUY" else SELL
    price = float(env.get("SPIKE_PRICE", "0.02"))
    size = float(env.get("SPIKE_SIZE", "5"))
    token_id = env["SPIKE_TOKEN_ID"]

    # Resolve tick size from the venue.
    tick_size = client.get_tick_size(token_id)
    neg_risk = client.get_neg_risk(token_id)
    fee_rate_bps = client.get_fee_rate_bps(token_id)

    side_int, maker_amount, taker_amount = client.builder.get_order_amounts(
        side_const, size, price, ROUNDING_CONFIG[tick_size],
    )

    # Pick exchange contract based on neg_risk.
    from py_clob_client.order_builder.builder import get_contract_config as _gcc
    contract_cfg = _gcc(chain_id, neg_risk)
    exchange_addr = contract_cfg.exchange

    import secrets
    # The TS SDK uses Number.parseInt(salt, 10) on the wire, which truncates
    # to a JS-safe integer (2^53). Keep salt within that range.
    salt = int.from_bytes(secrets.token_bytes(6), "big")
    timestamp = int(_time.time())
    account = Account.from_key(env["SPIKE_PRIVATE_KEY"])
    maker_address = env["SPIKE_FUNDER_ADDRESS"] if sig_type != 0 else account.address

    # Build the V2 EIP-712 typed data and sign it.
    domain_data = {
        "name": "Polymarket CTF Exchange",
        "version": "2",
        "chainId": chain_id,
        "verifyingContract": exchange_addr,
    }
    order_types = {
        "Order": [
            {"name": "salt", "type": "uint256"},
            {"name": "maker", "type": "address"},
            {"name": "signer", "type": "address"},
            {"name": "tokenId", "type": "uint256"},
            {"name": "makerAmount", "type": "uint256"},
            {"name": "takerAmount", "type": "uint256"},
            {"name": "side", "type": "uint8"},
            {"name": "signatureType", "type": "uint8"},
            {"name": "timestamp", "type": "uint256"},
            {"name": "metadata", "type": "bytes32"},
            {"name": "builder", "type": "bytes32"},
        ],
    }
    order_message = {
        "salt": salt,
        "maker": maker_address,
        "signer": account.address,
        "tokenId": int(token_id),
        "makerAmount": int(maker_amount),
        "takerAmount": int(taker_amount),
        "side": side_int,
        "signatureType": sig_type,
        "timestamp": timestamp,
        "metadata": b'\x00' * 32,
        "builder": b'\x00' * 32,
    }

    signed = account.sign_typed_data(
        domain_data, order_types, order_message,
    )
    signature = signed.signature.hex()
    if not signature.startswith("0x"):
        signature = "0x" + signature

    ok(f"order signed with V2 struct; signer={account.address}")

    # Build the wire body matching the new ts-sdk format.
    # Field set matches Polymarket/ts-sdk createSendOrderPayload exactly.
    order_dict = {
        "builder": "0x" + "0" * 64,
        "expiration": "0",
        "maker": maker_address,
        "makerAmount": str(int(maker_amount)),
        "metadata": "0x" + "0" * 64,
        "salt": salt,
        "side": "BUY" if side_int == 0 else "SELL",
        "signature": signature,
        "signatureType": sig_type,
        "signer": account.address,
        "takerAmount": str(int(taker_amount)),
        "timestamp": str(timestamp),
        "tokenId": token_id,
    }

    step("4", "CALLER: serialise ONCE and compute L2 headers over that exact string")
    # THE CRUX OF VARIANT A.
    #
    # The L2 HMAC is computed over `timestamp + method + path + body`, where the
    # body contribution is a *string*. The server reconstructs that string from
    # the bytes it receives. So the signed string and the posted bytes must be
    # identical, character for character.
    from py_clob_client.headers.headers import create_level_2_headers
    from py_clob_client.clob_types import OrderType, RequestArgs

    body = {"order": order_dict, "owner": creds.api_key, "orderType": OrderType.GTC}
    serialized = json.dumps(body, separators=(",", ":"), ensure_ascii=False)

    request_args = RequestArgs(
        method="POST",
        request_path="/order",
        body=body,
        serialized_body=serialized,
    )
    headers = create_level_2_headers(client.signer, creds, request_args)

    body_bytes = serialized.encode("utf-8")
    ok(f"body frozen: {len(body_bytes)} bytes, sha256={hashlib.sha256(body_bytes).hexdigest()[:16]}…")
    ok("HMAC computed over the identical string that will be transmitted")
    ok(f"headers computed by the CALLER: {sorted(headers)}")

    return "/order", body_bytes, dict(headers)


def caller_stage_poly_1271(env: dict[str, str]) -> tuple[str, bytes, dict[str, str]]:
    """The deposit-wallet path for new Polymarket API users.

    POLY_1271 orders are not normal EOA EIP-712 order signatures. The CLOB
    validates them through ERC-1271 on the deposit wallet, and the signature is
    ERC-7739-wrapped. Use the official v2 client for this shape; hand-building
    it is exactly how this spike got a false rejection.
    """
    from py_clob_client_v2 import (
        ClobClient,
        OrderArgs,
        OrderType,
        PartialCreateOrderOptions,
    )
    from py_clob_client_v2.endpoints import POST_ORDER
    from py_clob_client_v2.order_utils.model.order_data_v2 import order_to_json_v2

    chain_id = int(env.get("SPIKE_CHAIN_ID", "137"))
    host = env.get("SPIKE_CLOB_HOST", "https://clob.polymarket.com")
    deposit_wallet = env["SPIKE_FUNDER_ADDRESS"]

    step("1", "CALLER: initialise v2 client with deposit wallet funder (POLY_1271)")
    client = ClobClient(
        host=host,
        chain_id=chain_id,
        key=env["SPIKE_PRIVATE_KEY"],
        signature_type=3,
        funder=deposit_wallet,
    )
    ok(f"owner signer address {client.get_address()}")
    ok(f"deposit wallet funder {deposit_wallet}")

    step("2", "CALLER: derive L2 credentials from the owner signer")
    creds = client.create_or_derive_api_key()
    client.set_api_creds(creds)
    ok("L2 creds derived: " + ", ".join(
        f"{name}={redact(name.upper(), str(getattr(creds, name)))}"
        for name in ("api_key", "api_secret", "api_passphrase")
        if hasattr(creds, name)
    ))

    step("3", "CALLER: build POLY_1271 wrapped order with official v2 SDK")
    token_id = env["SPIKE_TOKEN_ID"]
    tick_size = client.get_tick_size(token_id)
    neg_risk = client.get_neg_risk(token_id)
    order = client.create_order(
        OrderArgs(
            token_id=token_id,
            price=float(env.get("SPIKE_PRICE", "0.02")),
            size=float(env.get("SPIKE_SIZE", "5")),
            side=env.get("SPIKE_SIDE", "BUY").upper(),
        ),
        PartialCreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk),
    )
    ok(f"order signed via v2 SDK; maker={order.maker}; signer={order.signer}; signatureType={int(order.signatureType)}")

    step("4", "CALLER: serialise ONCE and compute L2 headers over that exact string")
    body = order_to_json_v2(order, creds.api_key or "", OrderType.GTC)
    serialized = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    headers = client._l2_headers("POST", POST_ORDER, body=body, serialized_body=serialized)

    body_bytes = serialized.encode("utf-8")
    ok(f"body frozen: {len(body_bytes)} bytes, sha256={hashlib.sha256(body_bytes).hexdigest()[:16]}…")
    ok("HMAC computed over the identical string that will be transmitted")
    ok(f"headers computed by the CALLER: {sorted(headers)}")

    return POST_ORDER, body_bytes, dict(headers)


def relay_stage(host: str, path: str, body_bytes: bytes, headers: dict[str, str],
                *, live: bool) -> dict | None:
    """TrueOdds. Receives opaque bytes and pre-computed headers. Holds nothing.

    NOTE THE SIGNATURE. There is no key parameter, no credential parameter, and
    no way to obtain one. This function cannot sign, cannot re-authenticate, and
    cannot create an order. It can only forward what it was handed — which is
    exactly the authority Variant A claims TrueOdds needs.
    """
    import httpx

    step("5", "RELAY: verify integrity without decoding intent")
    digest_in = hashlib.sha256(body_bytes).hexdigest()
    ok(f"received {len(body_bytes)} opaque bytes, sha256={digest_in[:16]}…")

    # A relay may inspect for its own risk checks, but must forward the ORIGINAL
    # bytes. Parsing to a dict and re-dumping is the failure mode being tested.
    try:
        preview = json.loads(body_bytes)
        ok(f"parsed for inspection only: keys={sorted(preview)}")
    except json.JSONDecodeError:
        die("relay received a body it cannot parse")

    step("6", "RELAY: forward byte-identical to the venue")
    if hashlib.sha256(body_bytes).hexdigest() != digest_in:
        die("body mutated inside the relay — Variant A violated")
    ok("body unchanged after inspection")

    if not live:
        warn("--dry-run: not posting. Re-run with --live to complete the proof.")
        print(f"\n   body preview (first 200 chars of the exact signed string):")
        print(f"     {body_bytes[:200].decode('utf-8', 'replace')}")
        print("\n   Would POST:")
        print(f"     {host}{path}")
        print(f"     headers: {sorted(headers)}")
        print(f"     body:    {len(body_bytes)} bytes (unmodified)")
        return None

    with httpx.Client(timeout=30) as client:
        # content=body_bytes — NOT json=payload. Passing a dict here would let
        # httpx re-serialise and silently invalidate the caller's HMAC.
        response = client.post(
            f"{host}{path}",
            content=body_bytes,
            headers={**headers, "Content-Type": "application/json"},
        )

    step("7", "RELAY: venue response")
    print(f"   HTTP {response.status_code}")
    try:
        result = response.json()
    except ValueError:
        print(f"   body: {response.text[:400]}")
        die("venue returned a non-JSON response")

    print("   " + json.dumps(result, indent=2)[:800].replace("\n", "\n   "))
    return result


# ---------------------------------------------------------------- entrypoint


def main() -> None:
    parser = argparse.ArgumentParser(description="G0 spike: prove non-custodial relay")
    parser.add_argument("--pick-market", action="store_true",
                        help="list candidate markets; needs no key")
    parser.add_argument("--live", action="store_true",
                        help="actually POST the order (spends real money)")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="do everything except the POST (default)")
    parser.add_argument("--approve", action="store_true",
                        help="set the ERC-20 allowance if it is short (sends a tx, costs gas)")
    parser.add_argument("--setup-deposit-wallet", action="store_true",
                        help="derive/deploy/fund/approve a POLY_1271 deposit wallet")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="skip the on-chain balance/allowance check")
    args = parser.parse_args()

    host = os.environ.get("SPIKE_CLOB_HOST", "https://clob.polymarket.com")

    if args.pick_market:
        pick_market(host)
        return

    print("=" * 72)
    print("G0 SPIKE — Variant A: caller signs and authenticates, relay forwards")
    print("=" * 72)

    require_sdk()
    env = load_env()
    host = env.get("SPIKE_CLOB_HOST", host)

    if not args.skip_preflight:
        # The required allowance spender depends on this market's neg_risk flag,
        # so it is resolved from the live market rather than hardcoded.
        sys.path.insert(0, str(REPO / "src"))
        from decimal import Decimal

        from rwoo.adapters.polymarket import EXCHANGE_BY_MARKET_TYPE, _parse_market

        import httpx
        condition_id = env.get("SPIKE_CONDITION_ID")
        if not condition_id:
            die("SPIKE_CONDITION_ID is required for the preflight "
                "(or pass --skip-preflight)")
        with httpx.Client(timeout=30, headers={"User-Agent": "curl/8.5.0"}) as client:
            response = client.get(f"{host}/markets/{condition_id}")
            response.raise_for_status()
        from datetime import datetime, timezone
        market = _parse_market(response.json(), datetime.now(timezone.utc))
        if int(env.get("SPIKE_SIGNATURE_TYPE", "0") or "0") == 3:
            from py_clob_client_v2.config import get_contract_config
            v2_cfg = get_contract_config(int(env.get("SPIKE_CHAIN_ID", "137")))
            spender = v2_cfg.neg_risk_exchange_v2 if market.neg_risk else v2_cfg.exchange_v2
        else:
            spender = EXCHANGE_BY_MARKET_TYPE[bool(market.neg_risk)]["address"]

        notional = Decimal(env.get("SPIKE_PRICE", "0.02")) * Decimal(env.get("SPIKE_SIZE", "5"))
        required_units = int(notional * (10 ** 6))

        if args.setup_deposit_wallet:
            setup_deposit_wallet(env, required_units, spender)

        ready = chain_preflight(env, required_units, spender, approve=args.approve)
        if not ready and args.live:
            die("preflight failed; refusing --live so a funding problem is not "
                "misrecorded as a Variant A failure. Fix the above, or re-run "
                "with --approve.")
        if not ready:
            warn("preflight incomplete — a --live run would likely be rejected "
                 "for funding, not for auth.")

    if args.live:
        warn("LIVE MODE — this will rest a real order with real funds.")
        if input("   type 'yes' to continue: ").strip().lower() != "yes":
            die("aborted by operator")

    path, body_bytes, headers = caller_stage(env)

    # The boundary. Everything above held the key; nothing below can reach it.
    result = relay_stage(host, path, body_bytes, headers, live=args.live)

    print("\n" + "=" * 72)
    if result is None:
        print("DRY RUN COMPLETE — signing and header construction verified.")
        print("G0 is NOT yet proven. Re-run with --live to complete it.")
    elif result.get("success") or result.get("orderID") or result.get("orderId"):
        print("G0 PASS — the venue accepted an order relayed by a party holding")
        print("no key and no credential. Variant A is proven. Record it in")
        print("docs/EXECUTION_BUILD_PLAN.md and proceed to Phase 3.")
        print("\nNow: cancel the resting order and drain the throwaway wallet.")
    else:
        print("G0 INCONCLUSIVE — the venue rejected the relayed order.")
        print("Capture the exact error above. If it indicates an auth/HMAC")
        print("mismatch, the serialisation convention differs from this script's")
        print("and must be taken from the SDK verbatim. Only after ruling that")
        print("out does Variant A fall back to Variant B.")
    print("=" * 72)


if __name__ == "__main__":
    main()
