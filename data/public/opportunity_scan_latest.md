# Opportunity Scan

- Created: 2026-07-09T19:46:22.050079+00:00
- Markets seen: 2163
- Markets evaluated: 168
- Markets included: 915
- Included unsupported: 747
- Markets skipped: 1248
- Actionable: 39
- Rule: YES if price < prob_low - costs; NO if price > prob_high + costs; otherwise no trade

| Rank | Status | Venue | Family | Market | Side | Oracle | Market | Net edge | Cost | Reason |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | actionable | kalshi | weather.temperature | Will the **high temp in Miami** be 92-93° on Jul 9, 2026? | NO | 0.1544 | 0.9550 | 0.7926 | 0.0080 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 2 | actionable | kalshi | weather.temperature | Will the **high temp in LA** be 73-74° on Jul 9, 2026? | NO | 0.0265 | 0.6550 | 0.5977 | 0.0308 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 3 | actionable | kalshi | weather.temperature | Will the **high temp in LA** be 74-75° on Jul 10, 2026? | NO | 0.0183 | 0.4400 | 0.3944 | 0.0272 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 4 | actionable | kalshi | weather.temperature | Will the high temp in Chicago be 86-87° on Jul 9, 2026? | NO | 0.2561 | 0.6500 | 0.3479 | 0.0459 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 5 | actionable | kalshi | weather.temperature | Will the **high temp in Miami** be 91-92° on Jul 10, 2026? | NO | 0.2047 | 0.5550 | 0.3281 | 0.0223 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 6 | actionable | kalshi | weather.temperature | Will the **high temp in Miami** be 93-94° on Jul 10, 2026? | NO | 0.0348 | 0.3650 | 0.3090 | 0.0212 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 7 | actionable | kalshi | weather.temperature | Will the **high temp in LA** be 76-77° on Jul 10, 2026? | NO | 0.0375 | 0.3450 | 0.2867 | 0.0208 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 8 | actionable | kalshi | weather.temperature | Will the **high temp in LA** be 75-76° on Jul 9, 2026? | NO | 0.0432 | 0.3350 | 0.2612 | 0.0306 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 9 | actionable | kalshi | weather.temperature | Will the **high temp in Miami** be <90° on Jul 9, 2026? | YES | 0.2669 | 0.0050 | 0.2565 | 0.0053 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 10 | actionable | kalshi | weather.temperature | Will the **high temp in Miami** be 90-91° on Jul 9, 2026? | YES | 0.2508 | 0.0050 | 0.2405 | 0.0053 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 11 | actionable | kalshi | weather.temperature | Will the high temp in Chicago be 88-89° on Jul 9, 2026? | NO | 0.0841 | 0.3350 | 0.2203 | 0.0306 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 12 | actionable | kalshi | weather.temperature | Will the **high temp in NYC** be 83-84° on Jul 9, 2026? | YES | 0.2223 | 0.0150 | 0.2013 | 0.0060 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 13 | actionable | polymarket | sports.world_cup | Will France win the 2026 FIFA World Cup? | NO | 0.1255 | 0.3225 | 0.1965 | 0.0005 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 14 | actionable | kalshi | weather.temperature | Will the high temp in Chicago be 83-84° on Jul 10, 2026? | NO | 0.0614 | 0.2850 | 0.1944 | 0.0293 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 15 | actionable | kalshi | weather.temperature | Will the **high temp in Denver** be 90-91° on Jul 9, 2026? | NO | 0.2492 | 0.4850 | 0.1933 | 0.0425 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 16 | actionable | kalshi | weather.temperature | Will the **high temp in NYC** be 85-86° on Jul 9, 2026? | YES | 0.1983 | 0.0050 | 0.1880 | 0.0053 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 17 | actionable | kalshi | weather.temperature | Will the **high temp in Miami** be <89° on Jul 10, 2026? | YES | 0.1696 | 0.0050 | 0.1593 | 0.0053 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 18 | actionable | kalshi | weather.temperature | Will the **high temp in Miami** be 89-90° on Jul 10, 2026? | YES | 0.2167 | 0.0550 | 0.1530 | 0.0086 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 19 | actionable | kalshi | weather.temperature | Will the high temp in Chicago be 81-82° on Jul 10, 2026? | NO | 0.2417 | 0.4250 | 0.1511 | 0.0321 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 20 | actionable | kalshi | weather.temperature | Will the high temp in Chicago be 84-85° on Jul 9, 2026? | YES | 0.1406 | 0.0050 | 0.1303 | 0.0053 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |

## Included Unsupported

- limitless_sports_unknown_sports_parse_missing: 317
- limitless_sports.world_cup_prop_or_exact_outcome_model_missing: 142
- limitless_sports.esports_match_or_tournament_source_missing: 116
- limitless_sports.nhl_league_champion_model_missing: 32
- limitless_sports.nba_league_champion_model_missing: 30
- limitless_sports.tennis_tournament_winner_model_missing: 16
- limitless_economics.fed_rates_rate_decision_or_path_model_missing: 16
- limitless_economics.headline_cpi_monthly_bin_or_threshold_model_missing: 16
- limitless_sports.world_cup_stage_of_elimination_model_missing: 16
- polymarket_economics_not_supported: 14
- limitless_economics_unknown_economics_parse_missing: 9
- limitless_economics.gdp_quarterly_growth_bin_or_threshold_model_missing: 8

| Venue | Domain | Family | Shape | Market | Reason |
| --- | --- | --- | --- | --- | --- |
| kalshi | sports | sports | unknown_sports | no France wins the 1H by more than 1.5 goals,yes Over 1.5 1H goals scored,yes France advances,yes Reg Time: Both Teams To Score | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes 1st Half: Both Teams To Score,no France wins the 1H by more than 1.5 goals,yes Morocco advances,yes Kylian Mbappe: 1+,yes Achraf Hakimi: 1+,yes Brahim Diaz: 1+,no Goal Diff Reg Time: Morocco wins by more than 1.5 goals | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| polymarket | economics | economics.gdp | quarterly_growth_bin_or_threshold | US recession by end of 2026? | included but not actionable: polymarket GDP market included; GDP engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will no Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 1 Fed rate cut happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 2 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 3 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 4 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 5 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 6 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 7 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 8 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 9 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 10 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 11 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 12 or more Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| limitless | sports | sports.esports | match_or_tournament | Mandatory vs UCAM Esports Club - Mandatory | included but not actionable: limitless esports market included; reliable source/model path has not been approved yet |
| limitless | sports | sports.esports | match_or_tournament | Mandatory vs UCAM Esports Club - UCAM Esports Club | included but not actionable: limitless esports market included; reliable source/model path has not been approved yet |
| limitless | sports | sports.esports | match_or_tournament | Çilekler vs Misa Esports - Çilekler | included but not actionable: limitless esports market included; reliable source/model path has not been approved yet |
| limitless | sports | sports.esports | match_or_tournament | Çilekler vs Misa Esports - Misa Esports | included but not actionable: limitless esports market included; reliable source/model path has not been approved yet |

## Skip Reasons

- kalshi_other_not_supported: 498
- polymarket_other_not_supported: 478
- limitless_other_domain_or_price_oracle_not_supported: 272
