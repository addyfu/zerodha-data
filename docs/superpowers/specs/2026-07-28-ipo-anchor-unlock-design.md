# IPO Anchor-Unlock Study — Design Spec (Pre-Registered)

Date: 2026-07-28. Status: APPROVED & FROZEN (user). No changes after this line
except decision-log entries.
Origin: invention wave 2026-07-28 (idea #1). SEBI locks IPO anchor-investor
allocations for fixed calendar windows after listing. On unlock dates a block
of float becomes sellable at once with no obligated buyer. Hypothesis: unlock
days show mechanical selling pressure; the tradeable leg for a long-only cash
account is buying the post-unlock dip once the overhang clears.

## Regulatory calendar (builder must verify against primary sources — R1)

Pre-change: anchor lock-in 30 days from allotment. Post-change (SEBI ICDR
amendment, effective ~2022 — builder pins the exact effective date from the
SEBI circular): 50% locked 30 days, 50% locked 90 days. The spec's era split
follows that verified date; 90-day unlock events exist only post-change.
If the builder cannot pin the date from a primary source, HALT and report.

## Data

- Listings: first-appearance dates of genuinely new symbols in
  data/bhavcopy_full/ (2019-10 → 2026-05; require ≥60 forward trading days).
  Exclusions, documented per symbol: demergers/spin-offs, relists, symbol
  renames (cross-check corp-actions API + name-change announcements). SME
  boards excluded if distinguishable (mainboard only via listing-day turnover
  ≥ Rs 2 crore gate — the study's existing liquidity bar doubles as the SME
  filter; stated as approximation).
- Unlock events: listing_date + 30 and (post-change) + 90 calendar days,
  rolled to the next trading day.
- Anchor-size conditioning: OPTIONAL secondary. If per-IPO anchor allocation
  sizes are cheaply obtainable (NSE circulars / announcement attachments),
  a size-conditioned cut (anchor shares ≥ 1× 20d ADV) is reported as
  secondary information. The PRIMARY test is unconditional (all qualifying
  IPOs) so the verdict never depends on a data source we haven't secured.

## Windows and tradeable leg (frozen)

Information windows (no verdict): [-5,-1] pre-unlock drift, [0,+1] unlock
reaction — both abnormal vs EW universe.
PRIMARY (verdict) leg: IF cumulative [0,+1] abnormal return ≤ −2.0% (the
overhang materialized), BUY at E+2 open, hold 10 trading days, exit at open.
Costs: full delivery charges ['total'] + 0.2%/side slippage.

## Verdict (frozen, ALL must hold)

1. Mean net trade return > 0 in BOTH regulatory eras (pre/post the verified
   lock-in change), each era with ≥15 trades (else that era = NODATA and the
   study reports "underpowered", which is a recorded outcome, not a pass).
2. Pooled t ≥ +2.0, clustered by calendar month of the unlock (IPO waves
   cluster; the two unlocks of one IPO share a cluster).
3. Win rate ≥ 55% (a mechanical-rebound claim should win most of the time;
   a coin-flip with a fat tail is a different, unclaimed hypothesis).
Declared test count: 1 (the conditional long leg). The unconditional drift
windows and any anchor-size cut are information only.
On a pass: phase-2 spec for an incubator swing candidate (separate approval).

## Caveats (stated before results)

- Big-name unlocks are covered by media — the effect may live only in the
  ignored tail, where liquidity is thinnest. Turnover gate at entry applies.
- The −2% trigger conditions on a realized dip; that is pre-registered
  selection, not a bug, but it shrinks N (~expected 100-200 trades).
- Listing-date detection from panel first-appearance can mislabel edge cases
  (relists); exclusion list is part of the reviewed deliverable.

## Build plan

Opus builds kite/research/ipo_anchor_unlock_study.py (+ a small listing-
detector helper). Smoke: 2023 listings only. Reviewer verifies the exclusion
list, the regulatory-date pin, cluster-by-month, cost calls, then runs the
verdict. Results appended here.

## Decision log

- 2026-07-28: Spec frozen (user approved).
- 2026-07-28 (build, reviewer-accepted): SEBI date pinned from the gazette
  PDF — ICDR Amendment 2022, 50/50 @30/90d lock-in effective for issues
  OPENING on/after 2022-04-01 (notification date 2022-01-14 is a
  distractor); 3 ambiguous-era listings excluded from era cells. Listing
  detector: 4,580 first-appearances → 391 IPOs, full exclusion taxonomy
  (whole-rupee issue-price heuristic as the demerger filter, validated
  35/35 on hand-listed IPOs; known ~5% leak documented). Spec's two
  clustering sentences conflict (union-find over months degenerates to
  G=1); resolved as anchor-month clustering, both sentences hold,
  diagnostics printed. Side finding: sec_bhavdata_full_08082022.csv is a
  ZIP misnamed .csv — that day absent from panel.
- 2026-07-28 (results): **FAIL — dead, no re-tuning.** Criterion 1 PASSED
  (mean net +0.218% PRE / +1.046% POST — the first invented candidate to
  pass any criterion), but t=+1.361 vs +2.0 and win rate 47.8% vs 55%.
  Median trade is negative (−0.22%); the positive mean rides occasional
  +20-28% outliers. The realized profile is a lottery ticket, not the
  claimed mechanical rebound — exactly what criterion 3 existed to catch.
  200 trades, 53 clusters. Recorded and closed.
