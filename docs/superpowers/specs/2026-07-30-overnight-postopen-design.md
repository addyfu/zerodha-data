# Overnight-Information Post-Open Drift — Design Spec (Pre-Registered)

Date: 2026-07-30. Status: APPROVED & FROZEN (user). No changes after this line
except decision-log entries.
Origin: user's "decide next day's trades overnight" idea → research memo
2026-07-30 (sonnet, sourced): every overnight channel except one is priced
into the 09:15 open or already buried; the untested slice is whether the
Indian market's post-open drift retains ANY trace of overnight foreign
signals AFTER controlling for the gap that priced them. Piggyback: the
ADR-fade hypothesis (the one India ADR study found REVERSAL of overnight
ADR moves, not continuation).

## Stated prior (before any result)

NULL. The US-side overnight anomaly itself decayed to ~flat post-2021
(NY Fed); our own overnight-premium test died at −1.7bp net; India's gap
mechanism is well documented. If any coefficient survives, tradeability
after costs is a second, harder bar. This study exists to close the
overnight question with evidence, not to find treasure.

## Data (frozen)

- Indian side: data/bhavcopy_full/ panel (OPEN and CLOSE, corp-action
  adjusted, delivery_factor_study conventions; eligibility gates turnover
  ≥ Rs 2cr, close ≥ Rs 20).
- Overnight signals, 3 declared: S&P 500 (^GSPC), front crude (CL=F or
  equivalent free series), USDINR (INR=X) — daily closes from free sources
  (yfinance/stooq), 2019-07 → 2026-07.
- Signal mapping (frozen): foreign daily close of calendar date d maps to
  the NEXT Indian trading day t after d. Signal value = log return of the
  foreign series over its latest close-to-close available before 09:00 IST
  of day t. Imperfection stated: crude/INR trade nearly 24h, their "daily
  close" is a convention; acceptable for daily-horizon inference.
- Alignment gate: each signal series must pair with ≥95% of Indian trading
  days 2019-10..2026-07, else HALT as data-blocked.
- ADR piggyback: overnight ADR returns for INFY, WIT, IBN, HDB (US closes)
  mapped the same way to their NSE listings.

## Method (frozen)

Per Indian trading day t and stock s:
- GAP(s,t)   = open(s,t)/close(s,t−1) − 1
- POST(s,t,k) = close(s, t+k−1)/open(s,t) − 1 for k ∈ {1, 3, 10}
- Market-level arm (PRIMARY): EW eligible-universe means GAP(t), POST(t,k).
  Regression per (signal, k) cell: POST(t,k) = a + b·SIGNAL(t) + c·GAP(t) + e.
  The test is on b — does the signal predict post-open drift AFTER the gap
  is controlled. Inference: cluster-robust by ISO week.
- ADR arm (PIGGYBACK, fade hypothesis): per name, POST(s,t,k) for
  k ∈ {1,3} regressed on overnight ADR return with GAP control, pooled
  across the 4 names (name-clustered + week-clustered — use week clusters,
  name pooling stated). Hypothesis sign: NEGATIVE b (fade).
- Sector splits (IT vs USDINR/Nasdaq, OMC/paints vs crude): reported as
  information only, never verdict-bearing.

## Declared cells and verdict (frozen)

- Cells: 3 signals × 3 horizons (market arm) + 2 (ADR arm k ∈ {1,3}) = 11.
- Per cell, ALL required to count as a FINDING:
  1. Validation-era (2024-01..2026-07) cluster-robust |t(b)| ≥ 2.9
     (Bonferroni for 11 cells at α=0.05, one-sided in the pre-declared
     direction: market arm sign-free two-sided at 2.9 is stricter — use
     2.9 regardless; ADR arm must be NEGATIVE b specifically).
  2. Train era (2019-10..2023-12) b has the SAME SIGN.
  3. TRADEABILITY: a long-only implementation (enter eligible-universe
     basket at open on favorable-signal-tercile days, exit close(t+k−1),
     Rs 20k slots, delivery ['total'] + 0.2%/side slippage for wide
     universe / 0.05% for the 4 ADR names) shows validation mean net
     per-trade > 0. Statistical-but-untradeable = recorded as such, NOT
     a finding.
- Expected findings: 0. Any finding → phase-2 spec, incubator path only.

## Caveats (stated before results)

- Signals are market-wide: the market arm is a TIME-SERIES test (~1,150
  train / ~640 validation days; ~240/130 weekly clusters) — power is
  days, not stock-days. Stated.
- Foreign-series daily closes are conventions for 24h markets; GIFT Nifty
  (better composite) exists only post-2023-07 — optional robustness line,
  never verdict-bearing.
- The 09:00-09:15 pre-open auction partially prices signals into the open
  we buy at; that is the point of the gap control, not a flaw.

## Build plan

Sonnet builds kite/research/overnight_postopen_study.py (fetch + align +
regress + tradeability sim + verdict, one file; reuse panel loader, EW
benchmark, cluster_t, cost conventions). Smoke on 3 months. Reviewer
verifies signal-date mapping (the timezone trap is THE bug surface),
gap/POST definitions, cluster inference, then runs the verdict. Results
appended here.

## Decision log

- 2026-07-30: Spec frozen (user approved).
