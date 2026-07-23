#!/usr/bin/env python3
"""Buyer-side ASP execution client: reach pUSD and trade with the buyer's own signer.

Ties the pieces together:
  - a `Signer` the buyer chooses (raw local key, or a headless provider),
  - `buyer_funding.plan_pusd_funding` to pick the route from whatever stable the
    EOA holds, and
  - `ensure_pusd`, which walks each planned step through the chosen signer.

TrueOdds never sees the key: signing and broadcasting happen here, in the buyer's
own process. The self-contained on-chain legs (ERC-20 approve, USDC.e -> pUSD wrap)
are wired; the external legs (MESON bridge, DEX swap) are *injected* handlers,
because they need live quotes/routers the buyer supplies and that TrueOdds must
not hardcode.

Everything is dependency-injected (signer, rpc, handlers), so the orchestration is
unit-testable without a live key, RPC, or venue.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from abc import ABC, abstractmethod

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buyer_funding  # noqa: E402  (sibling module, path inserted above)

# ---------------------------------------------------------------- constants
SEL_APPROVE = "0x095ea7b3"       # approve(address,uint256)
SEL_TRANSFER = "0xa9059cbb"      # transfer(address,uint256)
SEL_BALANCE_OF = "0x70a08231"    # balanceOf(address)
SEL_ALLOWANCE = "0xdd62ed3e"     # allowance(address,address)
SEL_WRAP = "0x62355638"          # wrap(address,address,uint256) on the on-ramp

COLLATERAL_ONRAMP = "0x93070a847efEf7F70739046A929D47a521F5B8ee"
USDCE = buyer_funding.SOURCE_TOKENS["usdce"]["address"]
PUSD = buyer_funding.SOURCE_TOKENS["pusd"]["address"]

_MAX_UINT256 = (1 << 256) - 1


class ExecutionError(Exception):
    """A funding step could not be executed."""


def _addr(value: str) -> str:
    return value.lower().removeprefix("0x").rjust(64, "0")


def _uint(value: int) -> str:
    if value < 0 or value > _MAX_UINT256:
        raise ValueError(f"uint256 out of range: {value}")
    return format(value, "x").rjust(64, "0")


# ---------------------------------------------------------------- signer
class Signer(ABC):
    """What the client needs from a wallet. Both backends satisfy this."""

    @abstractmethod
    def address(self) -> str: ...

    @abstractmethod
    def sign_order(self, order_eip712: dict) -> str:
        """Sign a Polymarket order (EIP-712, signature type 0). Returns 0x-hex."""

    @abstractmethod
    def sign_and_send(self, tx: dict) -> str:
        """Broadcast an on-chain tx ({to, data, value?}). Returns the tx hash."""


class LocalKeySigner(Signer):
    """Option A — a raw EOA private key held in the buyer's own process."""

    def __init__(self, private_key: str, rpc, chain_id: int = 137):
        from eth_account import Account

        self._account = Account.from_key(private_key)
        self._rpc = rpc
        self._chain_id = chain_id

    def address(self) -> str:
        return self._account.address

    def sign_order(self, order_eip712: dict) -> str:
        from eth_account.messages import encode_typed_data

        signed = self._account.sign_message(encode_typed_data(full_message=order_eip712))
        sig = signed.signature.hex()
        return sig if sig.startswith("0x") else f"0x{sig}"

    def sign_and_send(self, tx: dict) -> str:
        addr = self._account.address
        nonce = int(self._rpc("eth_getTransactionCount", [addr, "pending"]), 16)
        gas_price = int(self._rpc("eth_gasPrice", []), 16)
        full = {
            "to": tx["to"],
            "value": tx.get("value", 0),
            "data": tx["data"],
            "nonce": nonce,
            "chainId": tx.get("chainId", self._chain_id),
            "gas": tx.get("gas", 250_000),
            "maxFeePerGas": gas_price * 2,
            "maxPriorityFeePerGas": min(gas_price, 30_000_000_000),
        }
        signed = self._account.sign_transaction(full)
        raw = signed.raw_transaction.hex()
        return self._rpc("eth_sendRawTransaction", ["0x" + raw.removeprefix("0x")])


class ProviderSigner(Signer):
    """Option B — a headless wallet provider (Turnkey / Privy / CDP).

    The buyer holds the provider API key; TrueOdds never does. Each method maps to
    the provider's sign / broadcast API. Left unimplemented on purpose — the
    provider and its auth are the buyer's choice; wire the two calls below.
    """

    def __init__(self, wallet_address: str, *, provider: str = "turnkey"):
        self._address = wallet_address
        self._provider = provider

    def address(self) -> str:
        return self._address

    def sign_order(self, order_eip712: dict) -> str:
        raise NotImplementedError(f"wire {self._provider} EIP-712 order signing")

    def sign_and_send(self, tx: dict) -> str:
        raise NotImplementedError(f"wire {self._provider} tx signing + broadcast")


# ---------------------------------------------------------------- rpc + reads
def http_rpc(url: str):
    """A minimal JSON-RPC callable: rpc(method, params) -> result."""

    def call(method: str, params: list):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
        if payload.get("error"):
            raise RuntimeError(f"{method} rpc error: {payload['error']}")
        return payload["result"]

    return call


def _erc20_uint_call(rpc, token: str, selector_data: str) -> int:
    return int(rpc("eth_call", [{"to": token, "data": selector_data}, "latest"]) or "0x0", 16)


def balance_of(rpc, token: str, holder: str) -> int:
    return _erc20_uint_call(rpc, token, SEL_BALANCE_OF + _addr(holder))


def allowance(rpc, token: str, owner: str, spender: str) -> int:
    return _erc20_uint_call(rpc, token, SEL_ALLOWANCE + _addr(owner) + _addr(spender))


def read_balances(rpc, address: str, *, xlayer_rpc=None) -> dict:
    """EOA balances keyed to the planner's sources. X Layer needs its own RPC."""
    out = {}
    for key, meta in buyer_funding.SOURCE_TOKENS.items():
        if meta["chain"] == "polygon":
            out[key] = balance_of(rpc, meta["address"], address)
        elif meta["chain"] == "xlayer" and xlayer_rpc is not None:
            out[key] = balance_of(xlayer_rpc, meta["address"], address)
        else:
            out[key] = 0
    return out


def _wait_receipt(rpc, tx_hash: str, *, tries: int = 40, delay: float = 3.0) -> None:
    for _ in range(tries):
        receipt = rpc("eth_getTransactionReceipt", [tx_hash])
        if receipt:
            if int(receipt.get("status", "0x0"), 16) == 1:
                return
            raise ExecutionError(f"transaction reverted: {tx_hash}")
        time.sleep(delay)
    raise ExecutionError(f"transaction not confirmed: {tx_hash}")


# ---------------------------------------------------------------- handlers
def wrap_handler(signer: Signer, rpc, step: dict) -> str:
    """USDC.e -> pUSD on-ramp, minted straight to the buyer's own EOA.

    Resolves a CREDITED amount to the EOA's current USDC.e balance (so it consumes
    whatever a preceding bridge/swap actually delivered), tops up the on-ramp
    allowance if needed, then wraps.
    """
    owner = signer.address()
    amount = step["amount_units"]
    if amount == buyer_funding.CREDITED:
        amount = balance_of(rpc, USDCE, owner)
    if amount <= 0:
        raise ExecutionError("wrap step has nothing to wrap (USDC.e balance is 0)")

    if allowance(rpc, USDCE, owner, COLLATERAL_ONRAMP) < amount:
        approve_hash = signer.sign_and_send({
            "to": USDCE,
            "data": SEL_APPROVE + _addr(COLLATERAL_ONRAMP) + _uint(amount),
        })
        _wait_receipt(rpc, approve_hash)

    wrap_hash = signer.sign_and_send({
        "to": COLLATERAL_ONRAMP,
        "data": SEL_WRAP + _addr(USDCE) + _addr(owner) + _uint(amount),
    })
    _wait_receipt(rpc, wrap_hash)
    return wrap_hash


# `bridge` and `swap` are injected: they need the buyer's MESON route / DEX router,
# and each MUST block until the destination USDC.e is credited on Polygon so the
# following CREDITED wrap can consume it. Handler signature: (signer, rpc, step).
DEFAULT_HANDLERS = {"wrap": wrap_handler}


# ---------------------------------------------------------------- orchestrator
def ensure_pusd(
    signer: Signer,
    rpc,
    required_units: int,
    *,
    handlers: dict | None = None,
    xlayer_rpc=None,
    margin_bps: int = 0,
) -> dict:
    """Bring the buyer's EOA to `required_units` pUSD, signing every step locally.

    Reads the EOA's balances, plans the route, and executes each step with the
    chosen signer. Injected `handlers` add/override step executors (e.g. a MESON
    `bridge` and a DEX `swap`); the built-in `wrap` needs nothing external. Returns
    a summary with the executed steps and the final pUSD balance.
    """
    active = {**DEFAULT_HANDLERS, **(handlers or {})}
    balances = read_balances(rpc, signer.address(), xlayer_rpc=xlayer_rpc)
    plan = buyer_funding.plan_pusd_funding(balances, required_units, margin_bps=margin_bps)
    if not plan:
        return {"status": "already_funded", "steps": [], "pusd_units": balances.get("pusd", 0)}

    executed = []
    for step in plan:
        handler = active.get(step["action"])
        if handler is None:
            raise ExecutionError(
                f"no handler for step '{step['action']}' — inject a "
                f"'{step['action']}' handler (MESON bridge / DEX swap) via handlers="
            )
        tx_hash = handler(signer, rpc, step)
        executed.append({"action": step["action"], "from_token": step["from_token"], "tx": tx_hash})

    final = balance_of(rpc, PUSD, signer.address())
    return {
        "status": "funded" if final >= required_units else "incomplete",
        "steps": executed,
        "pusd_units": final,
    }
