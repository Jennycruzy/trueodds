"""Auditable lifecycle for real trades.

This module records intent/fill/settlement; it does not hold keys or submit an
order.  A wallet adapter can only append a fill after returning a venue order
or transaction identifier.  That separation prevents a recommendation from
being misrepresented as a real trade.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rwoo.receipts import AppendOnlyLedger, hash_hex


class RealTradeLedger:
    def __init__(self, path: str | Path):
        self.ledger = AppendOnlyLedger(path)

    def _events(self, trade_id: str) -> list:
        return [r for r in self.ledger.read_records() if r.payload.get("trade_id") == trade_id]

    def precommit(self, *, recommendation: dict[str, Any], risk_limits: dict[str, Any],
                  operator_approval_id: str) -> Any:
        if not operator_approval_id.strip():
            raise ValueError("real trading requires an explicit operator approval identifier")
        if recommendation.get("actionable") is not True:
            raise ValueError("cannot precommit a non-actionable recommendation")
        trade_id = hash_hex({
            "recommendation": recommendation,
            "risk_limits": risk_limits,
            "approval": operator_approval_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return self.ledger.append("real_trade_precommit", {
            "trade_id": trade_id,
            "recommendation": recommendation,
            "risk_limits": risk_limits,
            "operator_approval_id": operator_approval_id,
            "status": "approved_not_filled",
        })

    def record_fill(self, *, trade_id: str, venue_order_id: str, side: str,
                    contracts: float, fill_price: float, fees: float) -> Any:
        events = self._events(trade_id)
        if not events or events[0].record_type != "real_trade_precommit":
            raise ValueError("fill has no matching precommit")
        if any(e.record_type == "real_trade_fill" for e in events):
            raise ValueError("trade already has a recorded fill")
        if not venue_order_id.strip() or side not in {"YES", "NO"}:
            raise ValueError("fill requires a venue order id and YES/NO side")
        if contracts <= 0 or not 0 < fill_price < 1 or fees < 0:
            raise ValueError("invalid fill economics")
        return self.ledger.append("real_trade_fill", {
            "trade_id": trade_id,
            "venue_order_id": venue_order_id,
            "side": side,
            "contracts": contracts,
            "fill_price": fill_price,
            "fees": fees,
            "status": "filled_unsettled",
        })

    def settle(self, *, trade_id: str, outcome: int, settlement_reference: str) -> Any:
        events = self._events(trade_id)
        fills = [e for e in events if e.record_type == "real_trade_fill"]
        if len(fills) != 1:
            raise ValueError("settlement requires exactly one recorded fill")
        if any(e.record_type == "real_trade_settlement" for e in events):
            raise ValueError("trade is already settled")
        if outcome not in {0, 1} or not settlement_reference.strip():
            raise ValueError("settlement requires a binary outcome and source reference")
        fill = fills[0].payload
        side_won = outcome == 1 if fill["side"] == "YES" else outcome == 0
        payout = fill["contracts"] if side_won else 0.0
        cost = fill["contracts"] * fill["fill_price"] + fill["fees"]
        return self.ledger.append("real_trade_settlement", {
            "trade_id": trade_id,
            "outcome": outcome,
            "settlement_reference": settlement_reference,
            "payout": payout,
            "realized_pnl": payout - cost,
            "status": "settled",
        })

    def summary(self) -> dict[str, Any]:
        records = self.ledger.read_records()
        settlements = [r.payload for r in records if r.record_type == "real_trade_settlement"]
        return {
            "real_trades_precommitted": sum(r.record_type == "real_trade_precommit" for r in records),
            "real_trades_filled": sum(r.record_type == "real_trade_fill" for r in records),
            "real_trades_settled": len(settlements),
            "realized_pnl": sum(row["realized_pnl"] for row in settlements),
            "ledger_verification": self.ledger.verify(),
            "paper_trades_included": False,
        }
