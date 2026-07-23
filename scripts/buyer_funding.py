#!/usr/bin/env python3
"""Buyer-side funding route planner: reach pUSD from whatever stable the EOA holds.

TrueOdds moves nothing. The buyer tops up their **own** EOA from any source they
like — their OKX Agentic Wallet, a CEX withdrawal to Polygon, or another wallet —
and this planner then decides the on-chain path to turn that balance into
Polymarket pUSD collateral, every step signed by the buyer's own key.

It is pure decision logic and signer-agnostic: it returns an ordered list of
steps; the executor maps each step to the existing g0_spike on-chain primitives
(`_wrap_usdce_to_pusd`, the MESON bridge, a DEX swap) using whichever signer the
buyer chose (raw local key or a headless provider). Because it is pure, the route
selection is unit-testable without a live RPC, key, or venue.

Supported EOA routes to pUSD:
  - pUSD already present            -> no-op
  - USDC.e on Polygon              -> wrap -> pUSD
  - X Layer USD₮0                  -> MESON bridge -> USDC.e -> wrap -> pUSD
  - Polygon USDT / native USDC     -> swap -> USDC.e -> wrap -> pUSD
"""
from __future__ import annotations

from decimal import ROUND_UP, Decimal

# Reference metadata for the executor; the planner itself only needs the keys.
SOURCE_TOKENS = {
    "pusd":         {"chain": "polygon", "address": "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB", "decimals": 6},
    "usdce":        {"chain": "polygon", "address": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", "decimals": 6},
    "native_usdc":  {"chain": "polygon", "address": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", "decimals": 6},
    "polygon_usdt": {"chain": "polygon", "address": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F", "decimals": 6},
    "xlayer_usdt0": {"chain": "xlayer",  "address": "0x779ded0c9e1022225f8e0630b35a9b54be713736", "decimals": 6},
}

# The MESON X Layer route credits nothing and reports no error below this floor,
# so any bridge leg must send at least this much. Mirrors g0_spike.
BRIDGE_MIN_UNITS = 2_500_000

# "credited" means: wrap whatever actually arrives after a bridge/swap, since the
# exact output is only known once the leg settles.
CREDITED = "credited"


class FundingError(Exception):
    """No single EOA source can cover the required pUSD."""


def _ceil_bps(units: int, bps: int) -> int:
    return int((Decimal(units) * Decimal(bps) / Decimal(10_000)).to_integral_value(rounding=ROUND_UP))


def _wrap(amount) -> dict:
    return {"action": "wrap", "from_token": "usdce", "to_token": "pusd", "amount_units": amount}


def _bridge(src: str, amount: int) -> dict:
    return {"action": "bridge", "from_token": src, "to_token": "usdce", "amount_units": amount}


def _swap(src: str, amount: int) -> dict:
    return {"action": "swap", "from_token": src, "to_token": "usdce", "amount_units": amount}


def plan_pusd_funding(
    balances: dict,
    required_units: int,
    *,
    bridge_min_units: int = BRIDGE_MIN_UNITS,
    margin_bps: int = 0,
    bridge_fee_bps: int = 500,
) -> list[dict]:
    """Ordered steps to reach `required_units` pUSD from the EOA's balances.

    `balances` maps SOURCE_TOKENS keys to base units the EOA holds. `margin_bps`
    pads the pUSD target for fees/slippage; `bridge_fee_bps` grosses up a bridge
    leg so the credited amount still clears the shortfall. Raises FundingError
    when no single source suffices.
    """
    if required_units <= 0:
        raise ValueError("required_units must be positive")
    if margin_bps < 0 or bridge_fee_bps < 0:
        raise ValueError("bps must be non-negative")

    need = required_units + _ceil_bps(required_units, margin_bps)
    pusd = balances.get("pusd", 0)
    if pusd >= need:
        return []
    shortfall = need - pusd

    # Cleanest EOA route: USDC.e is directly wrappable into pUSD.
    if balances.get("usdce", 0) >= shortfall:
        return [_wrap(shortfall)]

    # X Layer USD₮0 -> MESON -> USDC.e -> wrap. Gross up for the bridge fee and
    # honor the route floor; wrap whatever actually lands.
    bridge_in = max(shortfall + _ceil_bps(shortfall, bridge_fee_bps), bridge_min_units)
    if balances.get("xlayer_usdt0", 0) >= bridge_in:
        return [_bridge("xlayer_usdt0", bridge_in), _wrap(CREDITED)]

    # Polygon USDT / native USDC need a same-chain swap to USDC.e first.
    for src in ("polygon_usdt", "native_usdc"):
        if balances.get(src, 0) >= shortfall:
            return [_swap(src, shortfall), _wrap(CREDITED)]

    have = ", ".join(f"{k}={balances.get(k, 0)}" for k in SOURCE_TOKENS)
    raise FundingError(
        f"no single source covers {shortfall} pUSD base units of shortfall "
        f"(required {required_units}, have pUSD {pusd}); balances: {have}"
    )
