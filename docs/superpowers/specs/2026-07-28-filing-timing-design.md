# Filing-Timing Metadata Study — Design Spec (Pre-Registered)

Date: 2026-07-28. Status: APPROVED & FROZEN (user). No changes after this line
except decision-log entries.
Origin: invention wave 2026-07-28 (idea #7). Companies choose WHEN to file.
Hypothesis: low-attention timing (after-hours, Friday afternoon, pre-holiday)
marks news management and predicts negative drift BEYOND the filing's category.
Category-content drift is already dead here (0/3, 2026-07-28 confirmation
study); this tests TIMING as an orthogonal signal, within-category controlled.

## Data

data/announcements/ (973k records, timestamps) joined to the daily panel with
event_study.py conventions VERBATIM (E-date advance, E+1-open windows,
liquidity gate, abnormal-vs-EW-universe CAR). Excess = CAR minus same-era
all-announcement baseline (construction identical to the 2026-07-27
announcement-drift-confirmation study).

## Timing buckets (frozen — exactly three, no additions)

- B1 AFTER-HOURS: filed 15:30:00–08:59:59 IST (incl. weekends mapped to the
  next trading day's population).
- B2 FRIDAY-PM: filed Friday 12:00:00–15:29:59 IST.
- B3 PRE-HOLIDAY: filed on the last trading day before a non-weekend market
  closure. [AMENDED 2026-07-28, user-approved, BEFORE the verdict run:
  originally "per the NSE_HOLIDAYS calendars in parity_monitor.py" — that
  table covers 2026 only, leaving B3 blind for eras 1-2 and auto-failing on
  calendar coverage, not evidence. New instrument: closure days DERIVED from
  the price panel's own observed trading calendar (a weekday with no trading
  data inside the panel span = market closure; 158 such days 2019-2026 vs
  the 10 visible before). Data-sufficiency instrument fix; thresholds,
  buckets, windows, and inference untouched.]
Control group per bucket: all other filings of the SAME category in the same
era. The comparison is always bucket-vs-control WITHIN category, then pooled
across categories weighted by event count — never raw bucket vs zero
(that would re-discover the dead category effect through a proxy).

## Metric and inference (frozen)

- Primary: 5d excess AR difference (bucket minus same-category control),
  pooled across categories with ≥100 events in both arms.
- Eras: 2020-01..2021-12 / 2022-01..2023-12 / 2024-01..2026-07.
- Cluster-robust by ISO week (identical formula to the confirmation study).

## Verdict (frozen, per bucket, ALL must hold)

1. Bucket-minus-control 5d difference ≤ −0.10% in EVERY era.
2. Pooled cluster-corrected t ≤ −2.4 (Bonferroni for 3 declared buckets).
3. On pass: bucket becomes a candidate avoid-filter rule (design doc + forward
   kill-criterion like the results-miss gate) — separate reviewed deploy,
   never automatic.
Declared test count: 3 (one per bucket). 20d differences reported as
secondary information, never verdict-bearing.

## Caveats (stated before results)

- Timestamps may reflect exchange dissemination time, not company decision
  time — noted; the tradeable signal is the public timestamp either way.
- Some categories legitimately cluster after-hours (board-meeting outcomes).
  The within-category control absorbs level differences; if a category has
  <100 events in either arm it is excluded from the pool (count reported).
- This is in-sample exploration on mined announcement data; any pass gets the
  forward kill-criterion as its real out-of-sample test.

## Build plan

Opus builds kite/research/filing_timing_study.py (reuse event_study.py via
import, as the confirmation study did). Smoke on one month only. Reviewer
(Fable/Opus main) verifies bucket definitions, within-category control, and
week clustering, then runs the verdict. Results appended here.

## Decision log

- 2026-07-28: Spec frozen (user approved).
- 2026-07-28 (pre-verdict): B3 instrument amended, user-approved (see the
  [AMENDED] block above) — panel-derived closure calendar (158 pre-closure
  days) replaces the 2026-only holiday table. The new instrument also
  handles special Saturday sessions correctly (2024-01-20 traded; the
  table approach would have mislabeled it). Timestamp granularity
  verified: 0.0015% midnight-blank — B1/B2 have full vision.
- 2026-07-28 (results): **ALL THREE BUCKETS FAIL — timing is not a signal
  at the 5d horizon.**
  - B1 AFTER-HOURS (220k events): 5d diffs −0.01/−0.03/−0.10%, t=−1.00.
  - B2 FRIDAY-PM (13.6k): diffs flip positive in 2 of 3 eras, t=+1.36.
  - B3 PRE-HOLIDAY (14.4k): right sign in eras 1-2, −0.04% in era 3
    (floor −0.10%), t=−0.93.
  Candidate observation (pre-declared SECONDARY, never verdict-bearing,
  recorded only): B1's 20d difference is negative in all three eras
  (−0.12 to −0.25%, weekly t=−2.73) — a slow fade after off-hours filings
  that the 5d primary window doesn't see. Pursuing it would need a new
  spec with 20d declared primary on post-2026-07 data; NOT actioned.
  Tombstone #135. Invention wave 2026-07-28 closes 0-for-3.
