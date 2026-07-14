from __future__ import annotations

import unittest

from rwoo.engines.hurricane import compute_atlantic_season_count_probability
from rwoo.readers.noaa_hurricane import parse_atlantic_outlook, parse_current_counts


class NoaaHurricaneTests(unittest.TestCase):
    def test_outlook_ranges_are_parsed_from_source_text(self):
        page = """
        <h1>2026 North Atlantic Hurricane Season Outlook</h1>
        <p>Issued: 21 May 2026</p><p>8-14 Named Storms</p>
        <p>3-6 Hurricanes</p><p>1-3 Major Hurricanes</p>
        <p>70% probability for each of the ranges</p>
        """
        result = parse_atlantic_outlook(page)
        self.assertEqual(result["ranges"]["hurricanes"], [3, 6])
        self.assertEqual(result["range_probability"], 0.70)
        self.assertEqual(result["year"], 2026)
        self.assertFalse(result["includes_season_to_date"])

    def test_august_update_is_marked_as_incorporating_season_to_date(self):
        page = """
        <h1>2026 North Atlantic Hurricane Season Outlook</h1>
        <p>Issued: 6 August 2026</p><p>8-14 Named Storms</p>
        <p>3-6 Hurricanes</p><p>1-3 Major Hurricanes</p>
        <p>70% probability for each of the ranges</p>
        """
        result = parse_atlantic_outlook(page)
        self.assertTrue(result["includes_season_to_date"])

    def test_current_counts_read_first_summary_row_not_normal_comparisons(self):
        page = """
        <table><thead><tr><th colspan="3">2026 North Atlantic Summary as of 09 UTC 13 July 2026</th></tr>
        <tr><th>Named Storms</th><th>Hurricanes</th>
        <th>Major Hurricanes</th></tr></thead><tbody><tr>
        <td>1 (<span>14</span>)</td><td>0 (<span>7</span>)</td>
        <td>0 (<span>3</span>)</td></tr></tbody></table>
        """
        self.assertEqual(parse_current_counts(page), {
            "named_storms": 1, "hurricanes": 0, "major_hurricanes": 0, "parsed": True,
        })

    def test_engine_conditions_on_observed_count(self):
        outlook = {
            "year": 2026, "ranges": {"hurricanes": [3, 6]}, "range_probability": 0.70,
            "observed": {"hurricanes": 7, "parsed": True},
        }
        result = compute_atlantic_season_count_probability(
            "hurricanes", "greater", 6, target_year=2026, outlook=outlook,
        )
        self.assertEqual(result["oracle_prob"], 1.0)

    def test_engine_refuses_wrong_outlook_year(self):
        outlook = {
            "year": 2025, "ranges": {"hurricanes": [3, 6]}, "range_probability": 0.70,
            "observed": {"hurricanes": 0, "parsed": True},
        }
        result = compute_atlantic_season_count_probability(
            "hurricanes", "greater", 6, target_year=2026, outlook=outlook,
        )
        self.assertTrue(result["refused"])

    def test_august_total_outlook_is_not_conditioned_twice(self):
        base = {
            "year": 2026, "ranges": {"hurricanes": [3, 6]}, "range_probability": 0.70,
            "observed": {"hurricanes": 3, "parsed": True},
        }
        preseason = compute_atlantic_season_count_probability(
            "hurricanes", "greater", 5, target_year=2026,
            outlook={**base, "includes_season_to_date": False},
        )
        update = compute_atlantic_season_count_probability(
            "hurricanes", "greater", 5, target_year=2026,
            outlook={**base, "includes_season_to_date": True},
        )
        self.assertLess(update["oracle_prob"], preseason["oracle_prob"])
        self.assertEqual(update["per_source_values"]["observed_count_conditioning"],
                         "already incorporated by NOAA update")


if __name__ == "__main__":
    unittest.main()
