from datetime import date
import unittest
from unittest.mock import patch

from rwoo.backtests import economics
from rwoo.calibration import CalibrationRecord
from rwoo.economic_sources import SpfProbabilityRow


class AnnualGdpBacktestTests(unittest.TestCase):
    @patch("rwoo.backtests.economics.economic_sources.fetch_spf_density_rows")
    @patch("rwoo.backtests.economics.economic_sources.fetch_fred_series")
    def test_scores_each_prgdp_bin_against_realized_annual_growth(self, fred, spf):
        fred.return_value = [(date(2024, 1, 1), 2.8)]
        spf.return_value = [SpfProbabilityRow(2024, 2, 2024, "year_1", [0.01] * 11, "2024-05-10")]

        records, raw = economics.build_spf_annual_gdp_backtest()

        self.assertEqual(len(records), 11)
        self.assertEqual(sum(record.outcome for record in records), 1)
        self.assertEqual(records[4].outcome, 1)  # 2.5 to 3.9
        self.assertIn("does not validate GDPNow", raw[0]["engine_result"]["validation_scope"])

    @patch("rwoo.backtests.economics.economic_sources.fetch_gdpnow_track_record")
    def test_gdpnow_records_use_forecast_and_publication_dates(self, fetch):
        from rwoo.economic_sources import GdpNowHistoricalForecast
        fetch.return_value = [GdpNowHistoricalForecast(date(2024, 4, 20), "2024Q1", 2.5, 1.6, date(2024, 4, 25))]
        records, _ = economics.build_gdpnow_quarterly_backtest()
        self.assertEqual(len(records), 8)
        self.assertTrue(all(r.source_available_at == "2024-04-20" for r in records))
        self.assertTrue(all(r.resolution_timestamp == "2024-04-25" for r in records))


class EconomicsNoLookaheadTests(unittest.TestCase):
    def _record(self, source="2024-05-10", decision="2024-05-10", resolution="2025-01-31"):
        return CalibrationRecord(
            domain="economics",
            venue="test",
            market_id="test-record",
            question="test",
            decision_timestamp=decision,
            resolution_timestamp=resolution,
            oracle_prob=0.5,
            outcome=1,
            bucket="0.4-0.6",
            source_run="test",
            source_available_at=source,
            target_date="2024",
        )

    def test_accepts_source_at_decision_before_resolution(self):
        self.assertTrue(economics.economics_no_lookahead_checks([self._record()])[0]["passed"])

    def test_rejects_source_after_decision(self):
        check = economics.economics_no_lookahead_checks(
            [self._record(source="2024-05-11")]
        )[0]
        self.assertFalse(check["passed"])

    def test_rejects_unparseable_timestamp(self):
        check = economics.economics_no_lookahead_checks(
            [self._record(source="all values available")]
        )[0]
        self.assertFalse(check["passed"])
        self.assertIn("unparseable", check["reason"])


if __name__ == "__main__":
    unittest.main()
