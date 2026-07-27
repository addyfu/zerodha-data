# Announcement-Category Excess-Drift Confirmation — Design Spec (Pre-Registered)

Date: 2026-07-27. Status: APPROVED & FROZEN (user, 2026-07-28). No changes after this line except decision-log entries.
Origin: category-drift map (kite/research/category_drift_map.txt, 2026-07-22,
330,073 events). The map was EXPLORATORY — it scanned all 40 categories on the
full 2020–2026 history, so its candidates are mined by construction and its own
note #5 demands any follow-up be a pre-registered EXCESS-over-baseline test with
fixed sign and window, never raw CAR. This spec is that follow-up.

## Candidates (fixed now, from the map — no additions after this line)

| Category | Map excess 5d | N |
|---|---|---|
| Monitoring Agency Report | −0.25% | 1,367 |
| Cessation | −0.21% | 1,254 |
| Related Party Transactions | −0.20% | 1,872 |

All three are WEAK (< 0.3%/5d — below any tradeable edge after costs). The only
deployment on the table is an addition to the announcement red-flag AVOID
filter (zero trading cost, skip-the-stock semantics), never a trade.

## Honesty about contamination

Full-history numbers above have been SEEN. A rerun on the same data cannot
"confirm" anything; it can only test robustness the map skipped. The genuinely
new evidence comes from two things this spec adds: (1) era-consistency with
cluster-corrected inference (the map used pooled naive stats), and (2) a live
forward kill-criterion that carries the true out-of-sample weight after
deployment — the same pattern the results-miss gate shipped with.

## Method (frozen)

- Data: data/announcements/ (already on disk) joined to the daily price panel;
  same join and clean-window conventions as event_study.py.
- Metric per event: 5-day forward abnormal return vs equal-weight universe,
  MINUS the same-era all-announcement baseline drift (excess, per map note #5).
  20-day excess reported as secondary information, no verdict weight.
- Eras: 2020-01..2021-12, 2022-01..2023-12, 2024-01..2026-07.
- Inference: cluster-robust by calendar week (the PEAD lesson — clustered
  events are one observation, not hundreds).

## Verdict (frozen, per category, ALL must hold)

1. Excess 5d drift ≤ −0.15% in EVERY one of the three eras (sign + floor
   consistency; the floor is modest because the known effect is modest).
2. Pooled cluster-corrected t ≤ −2.4 (≈ Bonferroni for 3 declared tests).
3. On pass → category joins announcement_filter with a forward kill-criterion:
   after 60 live blocks, the blocked names' realized 5d excess drift must be
   negative, else the category removes itself from the filter automatically —
   identical mechanism to the results-miss gate.

Failures are recorded per category; a category that fails stays failed (no
window shopping, no threshold nudging). Declared test count: 3 categories ×
1 primary window = 3. The 20d secondary is reported, never verdict-bearing.

## Caveats (stated before results)

- This cannot escape being an in-sample robustness gate; the forward
  kill-criterion is the real out-of-sample test. Stated plainly in any report.
- Expected block cost if all three deploy: order of a few hundred stock-days
  per year (Monitoring Agency + Cessation + RPT are ~700 events/yr combined,
  ~20-day nominal windows would be excessive — the filter uses the SAME 7-day
  refresh window the existing red-flag categories use, so marginal cost is
  small; measured and reported monthly like the existing filter).
- Dividend (−0.24%, N=3,751) also cleared the map's excess screen but is
  EXCLUDED here: ex-date mechanics contaminate the return window and the
  category is dominated by routine announcements — declared out now so it
  cannot be quietly added later.

## Build plan

1. Study script `kite/research/announcement_drift_confirmation.py` —
   sonnet builds, Fable/Opus reviews (baseline subtraction, week clustering,
   era boundaries, and the cost-free join are the review focal points).
2. Run is minutes on existing on-disk data. Rs 0.
3. On any pass: filter-category addition + kill-criterion wiring is a separate
   reviewed deploy (announcement_filter.py + EntryPipeline untouched — the
   category list is config).
4. Results appended here as a decision-log entry.

## Decision log

- 2026-07-27: Spec drafted, pending user approval to freeze.
