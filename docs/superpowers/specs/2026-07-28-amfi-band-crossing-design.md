# AMFI Band-Crossing Study — Design Spec (Pre-Registered)

Date: 2026-07-28. Status: APPROVED & FROZEN (user). No changes after this line
except decision-log entries.
Origin: invention wave 2026-07-28 (idea #8). SEBI's 2017 fund-categorization
circular forces mutual funds to hold category minimums keyed to AMFI's
half-yearly market-cap ranking (top 100 = large, 101-250 = mid, 251+ = small).
A stock crossing a boundary obliges the fund industry to trim/add it —
mandated flow with a published schedule, far less watched than index
reconstitution (which stays covered by the separate niche-brief §1.5-1.7
family; this spec is the AMFI-mandate population, a distinct mechanism).

## Data (with a gating recon step)

- Events: AMFI's own published half-yearly "Average Market Capitalization"
  lists (Jan-Jun / Jul-Dec periods, published ~early Jan/Jul), 2018 → 2026.
  GATE: builder must first verify these historical lists are downloadable
  from amfiindia.com (recon 2026-07-28 confirmed AMFI serves plain HTML but
  did not test this specific archive). If lists cannot be retrieved for ≥12
  of the ~17 reviews, the study HALTS as data-blocked — that is a recorded
  outcome, not a failure to route around. We use AMFI's published ranks, NOT
  a recomputation (funds respond to the published list; our panel lacks
  shares-outstanding to recompute honestly).
- Prices: existing survivorship-free daily panel (data/bhavcopy_full/).
- Event date E: the list's publication date (obtain actual dates; if a
  publication date is unverifiable, use the 5th trading day of Jan/Jul and
  say so per event — conservative, late).

## Events (frozen cells)

Between consecutive lists: PROMOTION-TO-LARGE (rank crosses into top 100),
PROMOTION-TO-MID (into 101-250 from below), DEMOTION-FROM-LARGE,
DEMOTION-FROM-MID. Four cells, reported separately.
Tradeable verdict leg (long-only constraint): PROMOTIONS ONLY — long at E+1
open, hold 20 trading days, exit at open. Demotion cells measured as
information (would-be shorts, untradeable multi-day).

## Costs / benchmark (frozen)

Full delivery charges via calculate_charges(...)['total'] (incl. DP) + 0.2%/
side slippage. Benchmark: equal-weight universe abnormal return (same
construction as event_study.py). Round-trip cost hurdle ≈ 0.9% stated in
report.

## Verdict (frozen, per promotion cell, ALL must hold)

1. Mean 20d excess AR (net of costs) > 0 in BOTH era halves
   (reviews 2018-2021 vs 2022-2026).
2. Pooled t ≥ +2.0 clustered BY REVIEW DATE (≈16-17 clusters only — thin,
   stated loudly; review-date clustering is mandatory because all events in
   one review share one market regime).
3. Combined promotion cells' net edge ≥ 1.5× the 0.9% cost hurdle.
Declared test count: 2 (the two promotion cells). Demotions + pre-publication
drift windows are information only.
On a pass: phase-2 spec for an incubator swing candidate (separate approval);
never straight to live.

## Caveats (stated before results)

- ~16 review clusters is low power; a marginal pass is weak evidence and will
  be labeled as such in the verdict.
- SEBI allows funds ±20% flexibility, softening the "forced" flow.
- Funds can anticipate crossings before publication; E+1 entry may be late.
  Pre-publication drift is measured to size what we're missing.
- AMFI ranks use NSE+BSE combined mcap; borderline misclassification vs our
  NSE-only panel affects joins, not ranks (we use their ranks verbatim).

## Build plan

Opus builds kite/research/fetch_amfi_bands.py (list fetcher, gating recon
first) + kite/research/amfi_band_study.py. Smoke: 2 reviews only. Reviewer
verifies rank-parsing, cell definitions, cluster-by-review, cost calls, then
runs the verdict. Results appended here.

## Decision log

- 2026-07-28: Spec frozen (user approved).
- 2026-07-28 (pre-verdict, reviewer): recon PASSED — 18/18 AMFI half-year
  lists retrieved (Jul-Dec 2017 → Jan-Jun 2026), ISIN-exact joins, top-300
  join rates 96.3-99.0%. Two realities recorded BEFORE the verdict run, no
  criteria touched: (a) the price panel starts 2019-10, so ~13 review
  clusters are usable, not the ~16-17 the spec estimated — era halves are
  ~4 vs ~9 clusters, power thinner than sized; (b) only 2/18 publication
  dates are externally verifiable (AMFI's 2025 site migration destroyed
  Last-Modified history) — 16 reviews use the spec's 5th-trading-day
  fallback, flagged per event. Notional per event Rs 25,000 (October
  Contract first tranche) for the flat-DP cost conversion; realized drag
  ~0.67% vs the frozen 0.9% hurdle — the frozen number stays.
- 2026-07-28 (results): **FAIL — all criteria, both promotion cells, and
  the effect is INVERTED.** PROMOTION-TO-MID: net 20d AR −5.94%, t=−6.07
  (G=13), negative in both era halves. PROMOTION-TO-LARGE: −2.8%, t=−1.93.
  Combined promotion edge −4.63% vs +1.35% required. Mechanism read:
  promotion is a lagging badge on a 6-month run-up; by publication the run
  mean-reverts — buying promotions is buying tops. Demotions (info-only)
  also fall (−4 to −5%) with −17 to −21% pre-publication drift: the news
  is stale by print date. Caveats that temper the magnitudes, per the
  pre-verdict notes: EW-benchmark small-cap tilt inflates every negative
  AR in small-cap-led eras, and G=13 clusters is thin — but no reading of
  these numbers rescues a LONG promotion trade. Candidate observation
  (NOT pre-registered, needs its own spec if ever pursued): the inverse
  — avoid/defer fresh-promotion buys for ~20 days — overlaps with what
  momo rotation naturally buys and was NOT tested here.
