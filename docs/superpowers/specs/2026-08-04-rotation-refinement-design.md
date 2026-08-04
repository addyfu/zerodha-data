# Rotation Refinement Study — Design Spec (Candidate A)

Date: 2026-08-04. Status: FROZEN before any code. Type: RESEARCH STUDY.
Parent: 2026-08-04-entries-exits-research-shortlist.md, candidate A (user
approved all three knobs). Builder: sonnet subagent. Reviewer: Fable.
NOTHING here touches live code, live DBs, or the frozen October trial.

## Question

The monthly momentum rotation (momo_rotation_63) is the one live structure
fees cannot kill. Can any of three pre-registered refinements beat it
out-of-sample — or is the plain version already the right one?

## Baseline (the thing to beat)

Replicate the LIVE momo_rotation_63 logic offline: builder extracts the
exact rules from kite/live_monitor/momentum_rotation.py (and its config) —
ranking metric (63-day momentum), top-N count, universe, equal-weight
sizing, first-trading-day-of-month rebalance, 15% disaster stop. The
extracted parameters MUST be echoed verbatim in the results file; any
place the live code is ambiguous, the builder documents the reading taken.
No parameter of the baseline may be "improved" in passing.

## Variants (pre-registered; nothing else may be tested)

KNOB 1 — entry staggering (2 variants vs baseline single-shot):
  S3: each rebalance's buys split equally across the first 3 trading days.
  S5: same across 5 days. Sells stay single-shot on day 1 (the exit list
  is known day 1; dribbling exits is a different idea, not this spec).

KNOB 2 — exit rule (2 variants vs baseline 15% disaster stop):
  X0: no stop at all — pure hold-to-next-rebalance.
  XR: index regime brake — when NIFTY 50 closes below its own 200DMA at a
  rebalance date, the whole book goes/stays cash until a rebalance date
  where NIFTY is back above; the 15% stop is kept. (Note: the 2026-08-04
  regime-exit funeral killed this shape for BUY-AND-HOLD on tax drag; the
  rotation book already realizes gains monthly, so the tax asymmetry that
  buried it there does not apply — that is WHY it is worth one test here,
  and the only reason.)

KNOB 3 — rebalance-date sensitivity (robustness check, NOT an optimization):
  Run the baseline with rebalance on trading day 1 (baseline), 5, 10, 15
  of each month. FROZEN INTERPRETATION: we do not pick the best date. We
  report the spread. Spread of full-period CAGR > 2 percentage points =
  the strategy is fragile to an arbitrary choice — a red flag recorded
  against the whole rotation family, whatever the other knobs say.

Declared comparisons against baseline: S3, S5, X0, XR = 4 verdict-bearing
tests (+3 date alternates, non-verdict). No other variant, filter, or
parameter may be evaluated. If the builder thinks of a better idea
mid-build, it goes in the results file as a note, untested.

## Data

The corp-action-adjusted daily panel built for the delivery-% study
(~6.8 years; builder locates it under kite/research/ or data/ and records
the exact file + date range used). Universe = the panel's NIFTY-large-cap
membership; survivorship caveats inherited from that panel must be
restated in the results header. No fresh downloads, no Zerodha calls,
no enctoken.txt, no writes outside kite/research/ and this spec's results.

## Costs and taxes (same conventions as the regime-exit study)

- Delivery round trip per switch: STT 0.1% each side, stamp 0.015% buy,
  exchange+SEBI ~0.00317% each side, slippage 0.05% each side, DP Rs 15.34
  per sell per scrip (flat — matters at Rs ~20k position sizes; state
  position-size assumption: book capital Rs 1,00,000 / top-N equal weight,
  matching the live book).
- Primary verdict metric: net-of-costs, PRE-tax CAGR (matches how the live
  books are scored). After-tax table (STCG 20% / LTCG 12.5% per the
  regime-exit spec's verified rates) reported informationally.

## Verdict bars (frozen)

A variant PASSES only if ALL hold:
1. Full-period net CAGR exceeds baseline by >= 0.5 percentage points/yr.
2. Beats baseline in >= 2 of 3 eras (split the panel into 3 equal-length
   eras; report all).
3. Placebo control: rerun the winning variant with momentum ranks replaced
   by a uniform random permutation (fixed seed, 20 draws, mean reported).
   The variant's edge over baseline must NOT survive rank shuffling — if
   random ranks show a similar "improvement", the effect is harness
   artifact, verdict INVALID (not PASS, not FAIL — INVALID, and say so).
4. Knob-3 fragility flag not raised (date spread <= 2pp), OR the variant's
   margin exceeds the date spread.
Anything else = FAIL for that variant. Overall study verdict = list of
per-variant verdicts; no cherry-picking a "best config" post hoc.

## Self-checks required before the real run

Plain-assert synthetic cases with hand-computable answers: (a) staggered
entry cost/exposure arithmetic on a 3-day known series; (b) regime brake
enters/exits cash on the right rebalance dates for a constructed
above/below-MA sequence; (c) DP+STT cost per switch matches a hand
computation to the paisa; (d) baseline replication sanity — one month's
picks recomputed by hand from the panel and matched.

## Deliverables

- kite/research/rotation_refinement_study.py (standalone, self-checks then
  real run)
- kite/research/rotation_refinement_results.txt (extracted baseline echo,
  era tables per variant, date-sensitivity spread, placebo table,
  per-variant verdicts)
- No git commits by the builder; reviewer commits after verification.

## Decision log

- 2026-08-04: Spec frozen. User approved all three knobs; reviewer wrote
  spec; sonnet builds; reviewer verifies before any commit.
