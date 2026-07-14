# Evidence, Promotion, And Optional Execution

Last updated: 2026-07-14

## Product boundary

Real-World Odds Oracle is a paid decision API. Its primary deliverable is an
independent probability with uncertainty, net expected value, a deterministic
why trace, calibration context, and a hash-committed receipt. Cross-venue
comparison is a second paid decision surface. Execution is an optional
downstream adapter and is never required to use the oracle.

The oracle does not promise winning bets. It proves what it knew, when it knew
it, how the number was produced, and how forecasts performed after resolution.

## Continuous evidence lifecycle

1. The live scanner evaluates supported weather, economics, and sports markets.
2. Every priced record is appended to `data/receipts/forecast_evidence.jsonl`.
3. The record commits the event group, rule hash, authority, model version,
   probability interval, confidence, executable EV, and why trace.
4. Same-market/same-model snapshots are deduplicated within a UTC day.
5. A six-hour systemd timer checks unresolved records.
6. Kalshi finalized results, Polymarket closed outcomes, and Limitless resolved
   outcomes are appended without altering the original forecast.
7. Supported US high/low weather results are checked directly against NOAA
   NCEI Daily Summaries for the registered station and date.
8. Calibration reports are written atomically under `data/public/`.

Legacy venue rows created before venue-specific resolution IDs existed remain
in the immutable ledger but are labeled unsupported for automatic resolution.

## Independence and anti-selection rules

- One location/date/metric or underlying sporting/economic event is one group.
- Multiple thresholds remain visible but do not increase independent sample size.
- All priced calls are retained, including non-actionable calls and losses.
- Model changes require a new version and are evaluated separately.
- Checkpoints are fixed before results and cannot move afterward.
- Forecast and funded-trade records remain separate. A trade requires a real fill ID.

## Promotion gates

Reviews occur at 30, 100, 250, and 500 independent resolved events. The first
weather gate currently requires:

| Criterion | Threshold |
| --- | ---: |
| Independent event groups | at least 30 |
| Brier score | at most 0.20 |
| Maximum calibration gap | at most 0.15 |
| Venue/NOAA concordance | at least 95% |

Passing numbers is necessary but insufficient. Review also covers source
failures, parser/entity safety, confidence bands, executable costs, forecast
horizon, regime stability, and incidents. Every economics and sports family
has an independent gate.

Weather promotion is model-version-specific. Results from
`weather-ensemble-v2` cannot promote `weather-ensemble-v3-power-calibrated`.
At every crossed 30/100/250/500 checkpoint the public artifact now freezes a
review containing calibration, probability-band results, comparison with the
forecast-time market probability, and cost-adjusted paper performance. A band
becomes promotion-relevant at 30 independent event groups. Drift monitoring
segments results by station, metric, forecast horizon, and warm/cool season;
an adequately sampled segment with Brier score above 0.20 locks execution.

Paper performance selects at most one recommendation per independent event
(the highest precommitted expected profit) and settles one contract at the
recorded executable entry price after the recorded fee. This prevents a large
threshold ladder from inflating the apparent number of independent bets.
Closing-price comparison is reported only when a venue returns a genuine final
quote; resolved 0/1 settlement prices are never mislabeled as closing forecasts.

## Execution policy

Funded execution is disabled. `src/rwoo/trades.py` records a real trade only
after explicit approval and a genuine venue fill identifier. A recommendation
or unfilled order is never counted as a trade.

The trade ledger now has a fail-closed execution interlock. A precommit is
rejected unless the operator explicitly enables funded execution, a readable
promotion report exists, the required family is eligible, and its interlock is
`unlocked`. Missing, stale, malformed, or failing evidence keeps it locked.
Reports older than 12 hours automatically re-lock execution. An append-only
operator kill switch overrides every other setting. Funded recommendations
must be limit orders, include an independent event-group identity, and are
limited to one position per event. A separate mandatory correlation-group
identity caps combined exposure across related locations, dates, or contracts.

Risk limits rise only with passed checkpoints: at 30 groups the maximum is $5
per position, $15 daily exposure, and $25 trailing-seven-day realized loss;
the corresponding tiers at 100/250/500 are $10/$20/$50 per position,
$30/$60/$150 daily exposure, and $50/$100/$250 weekly loss. These are hard
ceilings, not suggested bet sizes, and operator-supplied limits may be lower.

After weather passes, the next implementation is a disabled-by-default Kalshi
adapter enforcing operator approval, a weather-only allowlist, limit orders,
per-event/daily/weekly-loss/drawdown limits, correlation-aware exposure,
minimum net edge, complete receipts, and an immediate kill switch. Secrets may
never enter logs, prompts, receipts, or public artifacts.

## Public communication

Moltbook/X posts must come from already-precommitted forecasts, link to the
receipt, disclose unresolved status, and include the why trace. A market may
not be selected after partial result information appears. Free public calls
demonstrate the product; paid API calls remain the business model.

## Current production state

- Evidence timer: enabled every six hours.
- Release-candidate suite: 186 passing tests as of 2026-07-14.
- Weather v2: 1,920 precommitted contract rows; 1,200 resolved rows across 160
  independent event groups; Brier 0.1246. This historical exact-version record
  does not promote v3.
- Weather v3: 888 prospective precommits and zero resolved independent groups.
- V3 model-development validation: the fixed gamma-0.65 transform improves
  retrospective Brier from 0.1246 to 0.1201, with walk-forward improvement
  across 152 later test groups. It is published separately and counts as zero
  prospective promotion events.
- Weather v3 next checkpoint: 30 prospective independently resolved events.
- Funded execution: disabled.
- Henry Hub v2 rolling-year validation beats the naive baseline, but has zero
  captured historical closing-market rows; it is therefore not promotion
  eligible. Prospective resolution and pre-cutoff closing-price capture are the
  next evidence priorities.
