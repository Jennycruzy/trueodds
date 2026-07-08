# Build Gaps And Sequencing

Last updated: 2026-07-08

This file records incomplete work that must not be forgotten between phases.
It is intentionally blunt: if a component is not complete, it stays listed
until a verification gate proves otherwise.

## Sequencing Decision

Do **Phase 6 next** before upgrading economics/sports.

Reason: Phase 6 provides the integrity backbone: receipts, append-only records,
tamper detection, and X Layer anchoring. After that exists, every future
economics/sports improvement can be recorded and proven under the same receipt
system. Improving models before receipts would add model work while the
"proven / cannot rewrite history" claim is still incomplete.

Recommended order:

1. Before Phase 6, clean up quick primary-source verification gaps where
   feasible: Kalshi fee schedule and primary hackathon rules/form.
2. Phase 6: receipts, append-only ledger, tamper evidence, X Layer anchoring.
3. Alongside Phase 6, verify X Layer RPC/path/cost facts needed for anchoring.
4. Upgrade economics: verified consensus forecast source, no-lookahead backtest,
   calibration curve, Brier score.
5. Upgrade sports: simulator or multiple independent rating sources,
   no-lookahead backtest, calibration curve, Brier score.
6. Continue Phase 7+: OKX listing/payment, daily proof loop, public pages.

## Immediate Checklist

Do before starting Phase 6:

- [x] Try to verify Kalshi's primary fee schedule directly.
- [x] Try to verify the primary OKX AI Genesis hackathon rules, deadline, and
      Google submission form.
- [x] Update `docs/VERIFICATION_LEDGER.md` with either successful primary
      evidence or a precise blocked/not-found finding.

Do in Phase 6:

- [x] Add append-only local calibration/receipt ledger.
- [x] Add receipt hash generation for verdict/calibration records.
- [x] Add hash-chain or equivalent tamper detection.
- [x] Add a tamper test to the verification harness.
- [x] Verify X Layer RPC path.
- [ ] Verify X Layer anchoring cost/token facts beyond RPC chain ID.
- [ ] Verify the OKX Agentic Wallet transaction-signing flow for anchoring a
      real commitment on X Layer mainnet.
- [ ] If OKX Agentic Wallet anchoring is approved and available, anchor a real
      commitment on X Layer mainnet and print the transaction/explorer evidence.
- [x] If OKX Agentic Wallet anchoring is not yet verified/approved, make the
      gate fail and mark that exact prerequisite honestly; do not fake an anchor.

Current Phase 6 blocker:

- `python3 verify.py --phase 6` passes local integrity checks but fails the
  full gate because the OKX Agentic Wallet anchoring flow is not yet
  verified/approved. Do not mark Gate 6 complete until a real X Layer mainnet
  transaction/explorer link is produced through that path.

## Gaps From Completed Phases Not Fully Covered By The Immediate Next Phase

### Production economics model and calibration

Current status: incomplete.

What exists: a conservative BLS-history baseline for core CPI markets.

Why incomplete: it is backward-looking official history, not a verified
forward-looking consensus forecast distribution. It is useful for a safe
baseline and for exercising the pipeline, but it is not yet "true odds" for a
future release.

Not covered by Phase 6: Phase 6 handles receipts and anchoring, not better
economic modeling.

Completion criteria:

- Verify a consensus forecast distribution source for CPI/PCE/NFP.
- Store raw pre-release forecast distributions with timestamps.
- Backtest with no lookahead against resolved historical releases/markets.
- Produce economics reliability curve and Brier score.
- Apply and document recalibration only if the backtest proves it is needed.

### Production sports model and calibration

Current status: incomplete.

What exists: a conservative World Cup baseline using live World Football Elo
ratings and two deterministic transforms.

Why incomplete: it is not a tournament simulator, does not model bracket path,
qualification state, injuries/lineups, or multiple independent rating systems.

Not covered by Phase 6: Phase 6 handles receipts and anchoring, not better
sports modeling.

Completion criteria:

- Add a proper simulator or multiple independent rating/projection sources.
- Verify all source timestamps and data availability.
- Backtest against resolved sports markets/events with no lookahead.
- Produce sports reliability curve and Brier score.
- Recalibrate if the backtest proves miscalibration.

### Primary Kalshi fee schedule PDF

Current status: incomplete primary-source verification.

What exists: fee formula corroborated by independent secondary sources and
Kalshi live API fields (`fee_type`, `fee_multiplier`).

Why incomplete: the primary PDF was blocked by a bot checkpoint when fetched.

Not covered by Phase 6 unless explicitly included.

Completion criteria:

- Retrieve/read the primary Kalshi fee schedule from Kalshi directly, or
  document a support-confirmed source.
- Update the Verification Ledger with the primary evidence.

### Primary hackathon rules and submission form

Current status: incomplete primary-source verification.

What exists: secondary-sourced deadline/submission information.

Why incomplete: the primary rules page/form must be checked before submission.

Not covered by Phase 6.

Completion criteria:

- Verify deadline, form URL, required assets, and eligibility criteria against
  primary OKX hackathon sources.
- Update the Verification Ledger.

### OKX payment settlement token

Current status: unresolved.

What exists: conflicting sources mention USDT/USDG/USDC on X Layer.

Why incomplete: only a real Payment SDK funded call can settle the discrepancy.

Not covered by Phase 6 unless payment work is pulled forward; normally covered
in Phase 7.

Completion criteria:

- Run a real funded OKX payment flow.
- Record actual settlement token and rail.
- Update service pricing accordingly.

### Public calibration page

Current status: not built.

What exists: Phase 5 computes weather calibration data in the harness.

Why incomplete: there is no live page reading from the same calibration store.

Not covered by Phase 6; covered later by Phase 8.5.

Completion criteria:

- Build a live public page from the calibration store.
- Show Brier score, reliability curve, call log, misses, and receipt hashes.
- Prove the page updates from data, not hardcoded HTML.
