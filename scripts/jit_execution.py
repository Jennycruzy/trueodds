#!/usr/bin/env python3
"""Autonomous just-in-time (JIT) execution policy for the Agentic Wallet path.

Policy decision (TrueOdds, 2026-07-23)
--------------------------------------
Polymarket's hosted relayer requires the deposit-wallet -> Exchange V2 approval to
be MaxUint256 and rejects any bounded approval. TrueOdds previously refused to set
an unlimited approval on principle. That refusal is **lifted for the autonomous
ASP**, because the safety it was buying is delivered more directly at the *balance*
layer:

    fund exact order notional -> approve(MaxUint256) once -> trade -> sweep unspent

An unlimited allowance over a wallet deliberately kept at ~0 pUSD except during a
single order's fill window has the same real exposure ceiling as a bounded
approval: one order's notional. The withdrawal ("sweep") leg that makes this true
is proven separately (docs/evidence/G2). MaxUint256 is therefore encoded **only**
when the JIT policy is explicitly enabled and the caller commits to the sweep; the
bounded default is preserved for the EOA / non-JIT paths.

This module is pure and side-effect free so the policy is unit-testable without a
live relayer, RPC, or wallet session.
"""
from __future__ import annotations

from decimal import ROUND_UP, Decimal

MAX_UINT256 = (1 << 256) - 1

# Env flag that turns the autonomous JIT policy on for the deposit-wallet
# (POLY_1271 / sig_type 3) path. Absent or not "1" means bounded, as before.
JIT_ENV_FLAG = "SPIKE_JIT_MAX_APPROVAL"

APPROVE_SELECTOR = "0x095ea7b3"    # approve(address,uint256)
TRANSFER_SELECTOR = "0xa9059cbb"   # transfer(address,uint256)


def jit_enabled(env: dict) -> bool:
    """True only when the autonomous JIT policy is explicitly switched on."""
    return str(env.get(JIT_ENV_FLAG, "")) == "1"


def _word_address(value: str) -> str:
    return value.lower().removeprefix("0x").rjust(64, "0")


def _word_uint(value: int) -> str:
    if value < 0 or value > MAX_UINT256:
        raise ValueError(f"uint256 out of range: {value}")
    return format(value, "x").rjust(64, "0")


def exchange_approval_units(*, jit_policy: bool, required_units: int) -> int:
    """Allowance to grant Exchange V2 from the deposit wallet.

    Under the autonomous JIT policy the relayer forces MaxUint256; safety comes
    from JIT-to-zero balance, not the allowance number. Off the policy, stay
    bounded to a small buffer over the order so a stray balance can't be drained.
    """
    if required_units <= 0:
        raise ValueError("required_units must be positive")
    return MAX_UINT256 if jit_policy else required_units * 4


def jit_fund_units(required_units: int, *, fee_bps: int = 0, slippage_bps: int = 0) -> int:
    """pUSD base units to move owner -> deposit wallet for exactly one order.

    Funds the order notional plus a fee/slippage margin and nothing more, so the
    wallet holds ~one order's worth during the fill window and is swept back to ~0
    afterward. This tight sizing is the balance-layer safety that justifies the
    MaxUint256 approval; over-funding would reintroduce the exposure it removes.
    """
    if required_units <= 0:
        raise ValueError("required_units must be positive")
    if fee_bps < 0 or slippage_bps < 0:
        raise ValueError("bps must be non-negative")
    margin = Decimal(required_units) * Decimal(fee_bps + slippage_bps) / Decimal(10_000)
    return required_units + int(margin.to_integral_value(rounding=ROUND_UP))


def erc20_approve_data(spender: str, amount_units: int) -> str:
    return APPROVE_SELECTOR + _word_address(spender) + _word_uint(amount_units)


def erc20_transfer_data(to: str, amount_units: int) -> str:
    return TRANSFER_SELECTOR + _word_address(to) + _word_uint(amount_units)
