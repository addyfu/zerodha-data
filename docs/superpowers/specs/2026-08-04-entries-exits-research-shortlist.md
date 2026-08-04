# Entries & Exits — Post-October Research Shortlist

Date: 2026-08-04. Status: APPROVED shortlist (user: "lgtm"). Type: RESEARCH
QUEUE — not a spec. Each item that graduates gets its own frozen spec
(pre-registered pass bars, kill switches) before any code, per house rule.
NOTHING here touches the live trial before the October verdict.

## Evidence this shortlist answers (why current entries/exits fail)

- 140 closed intraday trades: gross -267, charges -2,708. Bets break even;
  fees decide. (2026-08-04 ledger analysis.)
- Stop-width sweep, minute-level replay of all 140 real entries: WIDER stops
  strictly worse at every step (0.5% -> -253 ... 3% -> -2,301; no stop
  -1,546). Tight take-profits mean extra room rescues ~4 trades while
  deepening every loss. Stops are the tourniquet, not the wound.
- Held-to-EOD counterfactual on the 72 stopped trades: stops helped 36,
  hurt 35 — coin flip. Entries carry no directional information.
- Prior graveyard: 140+ backtests, 0 beat buy-and-hold; shuffle tests show
  the strategy zoo co-fires on structure, not signal; overnight study 0/11;
  event studies (pledge, AMFI, announcements, bulk-buyer) all FAIL.

## Frozen ground rules

- Pass bar for every candidate: beats buy-and-hold NIFTY out-of-sample,
  net of charges, slippage, and (where exits realize gains) taxes.
- Spec frozen before code; kill conditions pre-registered; shuffle/placebo
  control mandatory for anything with tunable parameters.
- Fee reality at our size (~Rs 20k positions): intraday round trip ~Rs 19
  (0.10%), delivery round trip ~0.2% STT + DP. Candidates must trade
  infrequently or not at all.

## The shortlist (ranked)

### A. Rotation entry/exit refinement — best prior
The monthly momentum rotation (momo_rotation_63) is the one running
structure fees cannot kill. Untested knobs, entries AND exits:
- Entry staggering: tranche the monthly buy across 3-5 days vs single shot.
- Exit: regime brake (index below long MA => rotate to cash) vs current
  15% disaster stop; time-based re-evaluation vs price-based.
- Rebalance-date sensitivity: is first-trading-day special or noise?
Test: walk-forward on the 6.8yr corp-action-adjusted dataset; shuffle
control mandatory (prime overfit territory — this would be backtest #141).
Kill: no variant beats plain rotation out-of-sample after fees.
Data: already on disk. Effort: medium.

### B. Zero-signal ("zombie") long — freshest anomaly
Stocks on which ALL ~130 zoo strategies are silent drifted +0.30%/10d
(anti-consensus finding, July 2026). A validation spec (2024-26 window,
pre-registered kill-switch for mean-reversion decoration) was already in
flight 2026-07-29. FIRST STEP: recover that run's verdict from disk before
anything else — do not duplicate or re-run without checking.
Kill: per the already-frozen zoo-silence spec.
Data: exists. Effort: small (verdict recovery) then per existing spec.

### C. Closing Auction Session (CAS) artifact — novelty monopoly
SEBI's closing auction went live 2026-08-03. Day one: official close
printed ~200pts above last traded level (verified via options put-call
parity, 2026-08-03 collector smoke). New microstructure = temporary
inefficiencies nobody has data on yet — including us (the honest weakness).
Hypothesis: auction-vs-traded gap partially reverts at next open.
Test: log daily triple (15:29 traded level, auction close, next 09:15 open)
— all three already flow through our collectors; ~60 sessions before any
test has power. Purely accumulative until then.
Kill: gap does not predict open beyond noise (sign test vs shuffle).
Data: accrues passively from existing infra. Effort: tiny logging + wait.

### D. Regime exit on the buy-and-hold core — cheap likely-funeral
Exit-to-cash on long-horizon signal (e.g. 200-day MA) over the core
holding. Included ONLY because it is the one pure-exit idea compatible
with hold-and-build and costs an afternoon against 20yr daily data.
Honest prior: industry-mined to death, and our bar includes capital-gains
tax on every exit, which historically kills these. Expected verdict: FAIL.
Kill: after-tax CAGR trails buy-and-hold (likely).
Data: NIFTY daily, public. Effort: small.

## Explicitly rejected (do not revisit without new evidence)

- New intraday entries: no entry family we tested carried edge; fee floor
  ~0.15%/trade at our size is a structural wall.
- Overnight gap entries: 0/11, the night is priced by 09:15 (frozen study).
- Event-driven entries: four dead specs (pledge-release, AMFI band,
  announcement drift, bulk-buyer persistence).
- Options strategies: deferred until the minute archive matures and
  capital exists post-October; note Apr 2026 STT hike (premium 0.15%)
  raised the bar further.

## Sequencing

1. Now -> October: nothing. Trial runs untouched. CAS triple-logging is the
   only permissible addition (data collection, not strategy) and only with
   explicit user go-ahead.
2. Post-verdict, in order: B verdict recovery (hours) -> A spec (the main
   event) -> D quick test (one afternoon, expect funeral) -> C once ~60
   CAS sessions exist (~late October anyway).

## Decision log

- 2026-08-04: Shortlist brainstormed and approved (user). Scope: "wherever
  evidence points"; bar: beat buy-and-hold; deliverable: this ranked doc.
  Full specs deferred to post-October, one candidate at a time.
