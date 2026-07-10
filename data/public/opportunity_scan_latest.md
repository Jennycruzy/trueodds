# Opportunity Scan

- Created: 2026-07-10T19:11:54.684879+00:00
- Markets seen: 5756
- Markets evaluated: 822
- Markets included: 1590
- Included unsupported: 768
- Markets skipped: 4165
- Actionable: 277
- Rule: YES if price < prob_low - costs; NO if price > prob_high + costs; otherwise no trade

| Rank | Status | Venue | Family | Market | Side | Oracle | Market | Net edge | Cost | Reason |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | actionable | kalshi | weather.temperature | Will the minimum temperature be <71° on Jul 10, 2026? | NO | 0.0077 | 0.9950 | 0.9819 | 0.0053 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 2 | actionable | kalshi | weather.temperature | Will the **high temp in Miami** be 93-94° on Jul 10, 2026? | NO | 0.0348 | 0.9950 | 0.9548 | 0.0053 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 3 | actionable | kalshi | weather.temperature | Will the minimum temperature be 75-76° on Jul 10, 2026? | NO | 0.0917 | 0.9850 | 0.8773 | 0.0160 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 4 | actionable | kalshi | weather.temperature | Will the maximum temperature be 89-90° on Jul 10, 2026? | NO | 0.0897 | 0.9650 | 0.8679 | 0.0074 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 5 | actionable | kalshi | weather.temperature | Will the **high temp in LA** be 74-75° on Jul 10, 2026? | NO | 0.0440 | 0.9100 | 0.8503 | 0.0157 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 6 | actionable | kalshi | weather.temperature | Will the maximum temperature be 89-90° on Jul 10, 2026? | NO | 0.0902 | 0.9500 | 0.8364 | 0.0233 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 7 | actionable | kalshi | weather.temperature | Will the minimum temperature be 55-56° on Jul 10, 2026? | NO | 0.1682 | 0.9700 | 0.7898 | 0.0120 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 8 | actionable | kalshi | weather.temperature | Will the minimum temperature be 75-76° on Jul 10, 2026? | NO | 0.1372 | 0.9350 | 0.7885 | 0.0093 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 9 | actionable | kalshi | weather.temperature | Will the maximum temperature be 93-94° on Jul 10, 2026? | NO | 0.0548 | 0.8650 | 0.7770 | 0.0332 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 10 | actionable | kalshi | weather.temperature | Will the maximum temperature be 90-91° on Jul 10, 2026? | NO | 0.2033 | 0.9750 | 0.7649 | 0.0067 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 11 | actionable | kalshi | weather.temperature | Will the minimum temperature be 88-89° on Jul 10, 2026? | NO | 0.2417 | 0.9900 | 0.7376 | 0.0107 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 12 | actionable | kalshi | weather.temperature | Will the minimum temperature be 56-57° on Jul 10, 2026? | NO | 0.2452 | 0.9850 | 0.7338 | 0.0060 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 13 | actionable | kalshi | weather.temperature | Will the **high temp in Austin** be 95-96° on Jul 10, 2026? | NO | 0.1544 | 0.9050 | 0.7296 | 0.0210 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 14 | actionable | kalshi | weather.temperature | Will the minimum temperature be 79-80° on Jul 10, 2026? | NO | 0.0955 | 0.8350 | 0.7248 | 0.0146 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 15 | actionable | kalshi | weather.temperature | Will the minimum temperature be 80-81° on Jul 10, 2026? | NO | 0.2561 | 0.9650 | 0.6915 | 0.0174 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 16 | actionable | kalshi | weather.temperature | Will the minimum temperature be 73-74° on Jul 10, 2026? | NO | 0.2302 | 0.9250 | 0.6849 | 0.0099 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 17 | actionable | kalshi | weather.temperature | Will the minimum temperature be 73-74° on Jul 10, 2026? | NO | 0.2438 | 0.9350 | 0.6820 | 0.0093 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 18 | actionable | kalshi | weather.temperature | Will the maximum temperature be 93-94° on Jul 10, 2026? | NO | 0.1509 | 0.8300 | 0.6592 | 0.0199 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 19 | actionable | kalshi | weather.temperature | Will the **high temp in Philadelphia** be 88-89° on Jul 10, 2026? | NO | 0.0319 | 0.6750 | 0.6228 | 0.0204 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 20 | actionable | kalshi | weather.temperature | Will the minimum temperature be 73-74° on Jul 10, 2026? | NO | 0.1784 | 0.8850 | 0.6144 | 0.0921 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |

## Included Unsupported

- limitless_sports_unknown_sports_parse_missing: 319
- limitless_sports.world_cup_prop_or_exact_outcome_model_missing: 167
- limitless_sports.esports_match_or_tournament_source_missing: 78
- polymarket_economics_not_supported: 47
- kalshi_sports_not_supported: 34
- limitless_sports.nhl_league_champion_model_missing: 32
- limitless_sports.nba_league_champion_model_missing: 30
- limitless_sports.tennis_tournament_winner_model_missing: 16
- limitless_economics.fed_rates_rate_decision_or_path_source_missing: 10
- limitless_economics_unknown_economics_parse_missing: 9
- limitless_economics.gdp_quarterly_growth_bin_or_threshold_model_missing: 7
- limitless_economics.headline_cpi_monthly_bin_or_threshold_model_missing: 7

| Venue | Domain | Family | Shape | Market | Reason |
| --- | --- | --- | --- | --- | --- |
| kalshi | sports | sports | unknown_sports | no Spain wins the 1H by more than 1.5 goals,no Over 1.5 1H goals scored,yes 8+ corners,yes Lamine Yamal: 1+,yes Mikel Oyarzabal: 1+,yes Goal Diff Reg Time: Spain wins by more than 1.5 goals,yes Reg Time: Over 2.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Spain wins the 1H by more than 1.5 goals,yes Goal Diff Reg Time: Spain wins by more than 1.5 goals,yes Reg Time: Over 2.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Milwaukee,yes Over 3.5 runs scored,yes Over 3.5 runs scored,yes Over 4.5 runs scored,yes Over 4.5 runs scored,yes Over 4.5 runs scored,yes Over 2.5 runs scored,yes Over 3.5 runs scored,yes Over 2.5 runs scored,yes Over 3.5 runs scored,yes Over 3.5 runs scored,yes Over 4.5 runs scored,yes Over 3.5 runs scored,yes Over 3.5 runs scored,yes Over 3.5 runs scored,no Spain wins the 1H by more than 1.5 goals,yes Spain advances,yes Reg Time: Both Teams To Score,yes 8+ corners,yes Lamine Yamal: 1+,no Reg Time: Over 5.5 goals scored,yes Dallas,yes Golden State | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | no Spain wins the 1H by more than 1.5 goals,yes Spain advances,yes 9+ corners,yes Belgium: 4+,no Reg Time: Over 3.5 goals scored,yes Greet Minnen | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | no Spain wins the 1H by more than 1.5 goals,no Over 2.5 1H goals scored,yes Spain advances,no Goal Diff Reg Time: Spain wins by more than 2.5 goals,yes Belgium: 4+,yes Spain: 10+,no Reg Time: Over 5.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Spain wins 1st Half,no Spain wins the 1H by more than 1.5 goals,yes Spain advances,yes Mikel Oyarzabal: 1+,yes Belgium: 4+ | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Milwaukee,yes Over 3.5 runs scored,yes Over 3.5 runs scored,yes Over 4.5 runs scored,yes Over 4.5 runs scored,yes Over 4.5 runs scored,yes Over 2.5 runs scored,yes Over 3.5 runs scored,yes Over 2.5 runs scored,yes Over 3.5 runs scored,yes Over 3.5 runs scored,yes Over 4.5 runs scored,yes Over 3.5 runs scored,yes Over 3.5 runs scored,no Spain wins the 1H by more than 1.5 goals,yes Spain advances,yes Reg Time: Both Teams To Score,yes 8+ corners,yes Lamine Yamal: 1+,no Reg Time: Over 5.5 goals scored,yes Dallas,yes Golden State | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | no Spain wins the 1H by more than 1.5 goals,no Over 2.5 1H goals scored,yes Spain advances,no Goal Diff Reg Time: Spain wins by more than 2.5 goals,yes Belgium: 4+,no Reg Time: Over 5.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | no Spain wins the 1H by more than 1.5 goals,no Over 2.5 1H goals scored,yes Belgium advances,no Goal Diff Reg Time: Spain wins by more than 1.5 goals,yes Belgium: 6+,no Reg Time: Over 3.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Milwaukee,yes Over 3.5 runs scored,yes Over 3.5 runs scored,yes Over 4.5 runs scored,yes Over 4.5 runs scored,yes Over 4.5 runs scored,yes Over 2.5 runs scored,yes Over 3.5 runs scored,yes Over 2.5 runs scored,yes Over 3.5 runs scored,yes Over 3.5 runs scored,yes Over 4.5 runs scored,yes Over 3.5 runs scored,no Spain wins the 1H by more than 1.5 goals,yes Spain advances,yes Reg Time: Both Teams To Score,yes 8+ corners,yes Lamine Yamal: 1+,no Reg Time: Over 5.5 goals scored,yes Dallas,yes Golden State | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Spain wins the 1H by more than 1.5 goals,yes Spain advances,yes Argentina advances,yes Norway advances,yes Lionel Messi: 1+,yes Erling Haaland: 1+ | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Spain wins 1st Half,no Spain wins the 1H by more than 1.5 goals,yes 8+ corners,yes Lamine Yamal: 1+,yes Mikel Oyarzabal: 1+,yes Goal Diff Reg Time: Spain wins by more than 1.5 goals,yes Reg Time: Over 2.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Milwaukee,yes Over 3.5 runs scored,yes Over 3.5 runs scored,yes Over 4.5 runs scored,yes Over 4.5 runs scored,yes Over 4.5 runs scored,yes Over 2.5 runs scored,yes Over 3.5 runs scored,yes Over 2.5 runs scored,yes Over 3.5 runs scored,yes Over 3.5 runs scored,yes Over 4.5 runs scored,no Spain wins the 1H by more than 1.5 goals,yes Spain advances,yes Reg Time: Both Teams To Score,yes 8+ corners,yes Lamine Yamal: 1+,no Reg Time: Over 5.5 goals scored,yes Dallas,yes Golden State | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | no Spain wins the 1H by more than 1.5 goals,yes 8+ corners,yes Lamine Yamal: 1+,yes Mikel Oyarzabal: 1+,yes Goal Diff Reg Time: Spain wins by more than 1.5 goals,yes Reg Time: Over 2.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | no Spain wins the 1H by more than 1.5 goals,no Over 2.5 1H goals scored,yes Belgium advances,no Goal Diff Reg Time: Spain wins by more than 1.5 goals,yes Belgium: 4+,no Reg Time: Over 3.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Spain wins the 1H by more than 1.5 goals,yes Belgium advances,yes 8+ corners,yes Spain: 6+,yes Reg Time: Over 1.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Spain wins 1st Half,no Spain wins the 1H by more than 1.5 goals,yes 8+ corners,yes Reg Time: Spain,yes Belgium: 4+,no Reg Time: Over 2.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Milwaukee,yes Over 3.5 runs scored,yes Over 3.5 runs scored,yes Over 4.5 runs scored,yes Over 4.5 runs scored,yes Over 4.5 runs scored,yes Over 2.5 runs scored,yes Over 3.5 runs scored,yes Over 2.5 runs scored,yes Over 3.5 runs scored,yes Over 3.5 runs scored,no Spain wins the 1H by more than 1.5 goals,yes Spain advances,yes Reg Time: Both Teams To Score,yes 8+ corners,yes Lamine Yamal: 1+,no Reg Time: Over 5.5 goals scored,yes Dallas,yes Golden State | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | no Spain wins the 1H by more than 1.5 goals,no Over 2.5 1H goals scored,yes Spain advances,yes Dani Olmo: 1+,no Goal Diff Reg Time: Spain wins by more than 2.5 goals,yes Belgium: 4+,no Reg Time: Over 5.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Spain wins 1st Half,no Spain wins the 1H by more than 1.5 goals,no Over 1.5 1H goals scored,yes 12+ corners,yes Reg Time: Spain,yes Mikel Oyarzabal: 1+,yes Belgium: 4+,yes Spain: 6+,no Reg Time: Over 2.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |

## Skip Reasons

- kalshi_other_not_supported: 1968
- polymarket_other_not_supported: 1941
- limitless_other_domain_or_price_oracle_not_supported: 256

## Errors

- kalshi KXLOWTDC-26JUL11-T74: _ssl.c:983: The handshake operation timed out
