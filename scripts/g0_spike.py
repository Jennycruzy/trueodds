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
Polymarket settles in **bridged** USDC.e on Polygon
(0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174), not native Circle USDC. Both
report symbol "USDC" with 6 decimals on the same chain, so this is easy to get
wrong and silent when you do. The preflight checks the right token, and tells
you explicitly if your balance is sitting in the wrong one.

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

REQUIRED = ("SPIKE_PRIVATE_KEY", "SPIKE_FUNDER_ADDRESS", "SPIKE_TOKEN_ID")
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
    if missing:
        die(f"{ENV_PATH.name} is missing: {', '.join(missing)}")
    return env


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
    from rwoo.adapters.polymarket import COLLATERAL, NATIVE_USDC_NOT_COLLATERAL

    owner = env["SPIKE_FUNDER_ADDRESS"]
    token = COLLATERAL["address"]

    step("0", "PREFLIGHT: on-chain balances and allowance")
    print(f"   owner    {owner}")
    print(f"   token    {token}  ({COLLATERAL['name']})")
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
    if gas <= 0.005:
        warn("not enough POL to send an approval transaction")
        ready = False

    print(f"   collateral balance {_units(bal_raw)} {COLLATERAL['symbol']}")
    if bal_raw == 0:
        # The single most likely funding mistake, so name it precisely.
        wrong_raw = int(_rpc("eth_call", [
            {"to": NATIVE_USDC_NOT_COLLATERAL, "data": SEL_BALANCE_OF + _word(owner)}, "latest"
        ]) or "0x0", 16)
        if wrong_raw > 0:
            warn(f"you hold {_units(wrong_raw)} of NATIVE USDC ({NATIVE_USDC_NOT_COLLATERAL}).")
            warn("Polymarket does not settle in that token. Swap or bridge to the address above.")
        else:
            warn("collateral balance is zero; fund the address above with bridged USDC.e")
        ready = False
    elif bal_raw < required_units:
        warn(f"balance {_units(bal_raw)} is below the order notional {_units(required_units)}")
        ready = False

    print(f"   allowance          {_units(allow_raw)} {COLLATERAL['symbol']}")
    if allow_raw < required_units:
        if not approve:
            warn(f"allowance below the {_units(required_units)} needed. Re-run with --approve to set it.")
            ready = False
        else:
            ready = _send_approval(env, token, spender, required_units) and ready
    else:
        ok("allowance is sufficient")

    return ready


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

    step("3", "CALLER: build and sign the order struct (L1 signature)")
    side = BUY if env.get("SPIKE_SIDE", "BUY").upper() == "BUY" else SELL
    order = client.create_order(OrderArgs(
        token_id=env["SPIKE_TOKEN_ID"],
        price=float(env.get("SPIKE_PRICE", "0.02")),
        size=float(env.get("SPIKE_SIZE", "5")),
        side=side,
    ))
    ok("order signed locally; the private key never leaves this function")

    step("4", "CALLER: serialise ONCE and compute L2 headers over that exact string")
    # THE CRUX OF VARIANT A.
    #
    # The L2 HMAC is computed over `timestamp + method + path + body`, where the
    # body contribution is a *string*. The server reconstructs that string from
    # the bytes it receives. So the signed string and the posted bytes must be
    # identical, character for character.
    #
    # py-clob-client anticipates exactly this: RequestArgs carries an optional
    # `serialized_body`, and create_level_2_headers prefers it over re-rendering
    # `body`. post_order then sends `data=request_args.serialized_body`. Sign and
    # send are the same string by construction — which is the whole of Variant A.
    #
    # The separators matter. json.dumps defaults to ", " / ": " and the SDK uses
    # ",", ":" — signing one and posting the other fails auth and would look
    # like "the venue rejects relayed orders" when it is really our own bug.
    from py_clob_client.headers.headers import create_level_2_headers
    from py_clob_client.clob_types import OrderType, RequestArgs
    from py_clob_client.utilities import order_to_json

    body = order_to_json(order, creds.api_key, OrderType.GTC)
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
        spender = EXCHANGE_BY_MARKET_TYPE[bool(market.neg_risk)]["address"]

        notional = Decimal(env.get("SPIKE_PRICE", "0.02")) * Decimal(env.get("SPIKE_SIZE", "5"))
        required_units = int(notional * (10 ** 6))

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
