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
- B3 PRE-HOLIDAY: filed on the last trading day before an NSE holiday
  (non-weekend holiday per the NSE_HOLIDAYS calendars already in
  parity_monitor.py; weekend-only gaps do NOT count).
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
