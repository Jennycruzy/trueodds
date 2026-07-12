"""Auditable lifecycle for real trades.

This module records intent/fill/settlement; it does not hold keys or submit an
order.  A wallet adapter can only append a fill after returning a venue order
or transaction identifier.  That separation prevents a recommendation from
being misrepresented as a real trade.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from rwoo.receipts import AppendOnlyLedger, hash_hex


class RealTradeLedger:
    def __init__(self, path: str | Path, *, funded_execution_enabled: bool = False,
                 promotion_report_path: str | Path | None = None,
                 required_family: str = "weather.temperature"):
        self.ledger = AppendOnlyLedger(path)
        self.funded_execution_enabled = funded_execution_enabled
        self.promotion_report_path = Path(promotion_report_path) if promotion_report_path else None
        self.required_family = required_family

    def execution_gate(self) -> dict[str, Any]:
        records = self.ledger.read_records()
        kill_events = [r for r in records if r.record_type in {"execution_kill_switch", "execution_kill_switch_cleared"}]
        if kill_events and kill_events[-1].record_type == "execution_kill_switch":
            return {"allowed": False, "reason": "execution kill switch is active",
                    "kill_switch": kill_events[-1].payload}
        if not self.funded_execution_enabled:
            return {"allowed": False, "reason": "funded execution is disabled by operator configuration"}
        if self.promotion_report_path is None or not self.promotion_report_path.exists():
            return {"allowed": False, "reason": "promotion report is missing"}
        try:
            report = json.loads(self.promotion_report_path.read_text(encoding="utf-8"))
            promotion = (report.get("promotion_readiness") or {}).get(self.required_family) or {}
        except (OSError, ValueError):
            return {"allowed": False, "reason": "promotion report is unreadable"}
        if not promotion.get("eligible") or promotion.get("execution_interlock") != "unlocked":
            return {"allowed": False, "reason": "all evidence, benchmark, calibration, and drift gates have not passed"}
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(report["created_at"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            return {"allowed": False, "reason": "promotion report timestamp is invalid"}
        if age > timedelta(hours=12):
            return {"allowed": False, "reason": "promotion report is stale; execution automatically re-locked"}
        checkpoint = int(promotion.get("last_reassessed_checkpoint") or 0)
        tiers = {
            30: {"max_position_usd": 5.0, "max_correlated_exposure_usd": 5.0, "max_daily_exposure_usd": 15.0, "max_weekly_loss_usd": 25.0},
            100: {"max_position_usd": 10.0, "max_correlated_exposure_usd": 15.0, "max_daily_exposure_usd": 30.0, "max_weekly_loss_usd": 50.0},
            250: {"max_position_usd": 20.0, "max_correlated_exposure_usd": 30.0, "max_daily_exposure_usd": 60.0, "max_weekly_loss_usd": 100.0},
            500: {"max_position_usd": 50.0, "max_correlated_exposure_usd": 75.0, "max_daily_exposure_usd": 150.0, "max_weekly_loss_usd": 250.0},
        }
        tier_checkpoint = max((n for n in tiers if checkpoint >= n), default=0)
        if not tier_checkpoint:
            return {"allowed": False, "reason": "no passed execution checkpoint"}
        return {"allowed": True, "reason": "operator enabled execution and every promotion gate is unlocked",
                "checkpoint": tier_checkpoint, "limits": tiers[tier_checkpoint]}

    def activate_kill_switch(self, reason: str, operator_approval_id: str) -> Any:
        if not reason.strip() or not operator_approval_id.strip():
            raise ValueError("kill switch requires a reason and operator approval id")
        return self.ledger.append("execution_kill_switch", {
            "reason": reason, "operator_approval_id": operator_approval_id, "status": "active"})

    def clear_kill_switch(self, operator_approval_id: str) -> Any:
        if not operator_approval_id.strip():
            raise ValueError("clearing kill switch requires operator approval")
        return self.ledger.append("execution_kill_switch_cleared", {
            "operator_approval_id": operator_approval_id, "status": "cleared"})

    def _events(self, trade_id: str) -> list:
        return [r for r in self.ledger.read_records() if r.payload.get("trade_id") == trade_id]

    def precommit(self, *, recommendation: dict[str, Any], risk_limits: dict[str, Any],
                  operator_approval_id: str) -> Any:
        gate = self.execution_gate()
        if not gate["allowed"]:
            raise PermissionError(gate["reason"])
        if not operator_approval_id.strip():
            raise ValueError("real trading requires an explicit operator approval identifier")
        if recommendation.get("actionable") is not True:
            raise ValueError("cannot precommit a non-actionable recommendation")
        if recommendation.get("order_type") != "limit":
            raise ValueError("funded execution permits limit orders only")
        event_group = str(recommendation.get("event_group_id") or "").strip()
        if not event_group:
            raise ValueError("recommendation requires an independent event_group_id")
        correlation_group = str(recommendation.get("correlation_group_id") or "").strip()
        if not correlation_group:
            raise ValueError("recommendation requires a correlation_group_id")
        existing = self.ledger.read_records()
        if any(r.record_type == "real_trade_precommit" and
               r.payload.get("recommendation", {}).get("event_group_id") == event_group
               for r in existing):
            raise ValueError("only one funded position is allowed per independent event")
        requested = float(risk_limits.get("max_usd") or 0)
        if requested <= 0 or requested > gate["limits"]["max_position_usd"]:
            raise ValueError("position exceeds checkpoint-tier maximum")
        correlated_exposure = sum(float(r.payload.get("risk_limits", {}).get("max_usd") or 0)
                                  for r in existing if r.record_type == "real_trade_precommit" and
                                  r.payload.get("recommendation", {}).get("correlation_group_id") == correlation_group)
        if correlated_exposure + requested > gate["limits"]["max_correlated_exposure_usd"]:
            raise ValueError("correlated exposure limit exceeded")
        now = datetime.now(timezone.utc)
        today = now.date()
        daily_exposure = sum(float(r.payload.get("risk_limits", {}).get("max_usd") or 0)
                             for r in existing if r.record_type == "real_trade_precommit" and
                             datetime.fromisoformat(r.created_at.replace("Z", "+00:00")).date() == today)
        if daily_exposure + requested > gate["limits"]["max_daily_exposure_usd"]:
            raise ValueError("daily exposure limit exceeded")
        week_start = now - timedelta(days=7)
        weekly_loss = -sum(min(0.0, float(r.payload.get("realized_pnl") or 0)) for r in existing
                           if r.record_type == "real_trade_settlement" and
                           datetime.fromisoformat(r.created_at.replace("Z", "+00:00")) >= week_start)
        if weekly_loss >= gate["limits"]["max_weekly_loss_usd"]:
            raise PermissionError("weekly loss limit reached; execution re-locked")
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
            "checkpoint": gate["checkpoint"],
            "enforced_limits": gate["limits"],
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
