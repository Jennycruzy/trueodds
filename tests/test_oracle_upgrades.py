import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from rwoo import calibration, edge
from rwoo.calibration import CalibrationRecord
from rwoo.explanations import build_why_trace
from rwoo.trades import RealTradeLedger
from tests.support import make_market


class OracleUpgradeTests(unittest.TestCase):
    def test_calibration_breaks_out_domain_and_band(self):
        records = [
            CalibrationRecord("weather", "k", "1", "q", "2026-01-01", "2026-01-02", 0.86, 1, "", "s", "2025-12-31", "2026-01-02"),
            CalibrationRecord("weather", "k", "2", "q", "2026-01-03", "2026-01-04", 0.84, 0, "", "s", "2026-01-02", "2026-01-04"),
            CalibrationRecord("sports", "p", "3", "q", "2026-01-05", "2026-01-06", 0.62, 1, "", "s", "2026-01-04", "2026-01-06"),
        ]
        result = calibration.calibration_breakdown(records)
        self.assertEqual(result["by_domain"]["weather"]["count"], 2)
        self.assertIn("weather:0.8-0.9", result["by_domain_and_probability_band"])

    def test_why_trace_identifies_outlier(self):
        trace = build_why_trace({"per_model_prob": {"a": .44, "b": .45, "gfs": .61}, "confidence": .74})
        self.assertEqual(trace["largest_outlier"]["model"], "gfs")
        self.assertIn("3 deterministic", trace["summary"])

    def test_edge_exposes_expected_value_at_executable_ask(self):
        market = replace(make_market(venue="kalshi"), implied_prob=.40, spread=.04)
        result = edge.compute_edge(market, {"oracle_prob": .70, "confidence": .8, "prob_low": .65, "prob_high": .75})
        self.assertAlmostEqual(result["execution"]["yes_ask"], .42)
        self.assertGreater(result["execution"]["expected_profit_per_contract"], 0)

    def test_real_trade_ledger_never_counts_recommendation_as_fill(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RealTradeLedger(Path(tmp) / "trades.jsonl")
            precommit = ledger.precommit(recommendation={"actionable": True, "market_id": "m"}, risk_limits={"max_usd": 2}, operator_approval_id="approval-1")
            self.assertEqual(ledger.summary()["real_trades_filled"], 0)
            ledger.record_fill(trade_id=precommit.payload["trade_id"], venue_order_id="order-1", side="YES", contracts=2, fill_price=.4, fees=.02)
            ledger.settle(trade_id=precommit.payload["trade_id"], outcome=1, settlement_reference="official-result")
            summary = ledger.summary()
            self.assertEqual(summary["real_trades_settled"], 1)
            self.assertAlmostEqual(summary["realized_pnl"], 1.18)
            self.assertFalse(summary["paper_trades_included"])


if __name__ == "__main__":
    unittest.main()
