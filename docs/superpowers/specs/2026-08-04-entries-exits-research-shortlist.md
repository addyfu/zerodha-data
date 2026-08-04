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

### B. Zero-signal ("zombie") long — RESOLVED: FAIL (2026-08-04 recovery)
The 2026-07-29 validation run had already finished and recorded its
verdict: **FAIL, Tombstone #137** (C1 PASS +0.0404% / C2 FAIL t=+0.939 /
C3 FAIL — D=0 underperforms D>=1 in 4 of 5 prior-return quintiles; the
apparent edge was ordinary short-term reversal, zoo-silence decorative).
Consensus/ensemble line of inquiry fully closed: voting, K-of-N, and
silence-as-signal all dead on Indian data. Removed from the queue.
One citation slip in the spec's decision log corrected 2026-08-04
(appendix vs primary numbers; verdict unaffected).

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

### D. Regime exit on the buy-and-hold core — RESOLVED: FAIL (2026-08-04)
Funeral held same day, prior confirmed. 2008-2026 NIFTY daily, both
variants, after real costs and verified FY2026-27 capital-gains rates:
buy-and-hold +9.81% CAGR beats V1 monthly-200DMA +6.46% and V2
hysteresis +5.15% in ALL THREE eras and the full period (0/3 era wins,
needed 2). Tax drag on switching (17-31 round trips) plus whipsaws bury
the crash-avoidance benefit. Spec + results:
2026-08-04-regime-exit-design.md, kite/research/regime_exit_results.txt.
Do not revisit without a structurally different regime signal.

### (original D entry, for the record) — cheap likely-funeral
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

REVISED 2026-08-04 (user): offline research starts NOW — the October freeze
binds the LIVE books only (no strategy edits, no gate changes), exactly as
during July's research wave. Acting on any result still waits for the verdict.

1. Now (parallel, sonnet builders + reviewer verification): B verdict
   recovery from disk -> D funeral test (spec frozen first) -> C logger
   built + deployed so sessions accrue from day two of CAS.
2. A (rotation refinement) next: spec brainstormed WITH the user (knob
   selection is a judgment call), then built under the same
   builder/reviewer pattern.
3. C's ANALYSIS still waits for ~60 logged sessions (~late October) —
   only the logging starts now.

## Decision log

- 2026-08-04: Shortlist brainstormed and approved (user). Scope: "wherever
  evidence points"; bar: beat buy-and-hold; deliverable: this ranked doc.
  Full specs deferred to post-October, one candidate at a time.
