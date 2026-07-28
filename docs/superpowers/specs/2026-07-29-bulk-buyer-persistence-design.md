# Bulk-Deal Buyer Persistence — Design Spec (Pre-Registered)

Date: 2026-07-29. Status: APPROVED & FROZEN (user). No changes after this line
except decision-log entries.
Origin: invention wave 2026-07-28 (idea #2). NSE discloses every bulk deal
(>0.5% of shares) with the buyer's NAME, end of day. Hypothesis: buyer skill
persists — institutions/individuals whose past bulk purchases were followed
by positive abnormal returns keep doing better than average, and following
only the proven buyers at T+1 captures part of that. This is an information-
asymmetry story, not forced-flow; the relabel risk (generic "any bulk buy"
momentum) is guarded by a mandatory control arm.

## Data (frozen)

- data/bulk_deals/bulk_*.csv (232k rows, 2005-2026, buyer names) — BUY rows.
- Prices: data/bhavcopy_full/ panel (2019-10 →) with corp-action adjustment,
  loaded per delivery_factor_study.py conventions. THE PANEL, NOT THE DEAL
  FILE, BOUNDS THE MEASURABLE ERA: outcomes are computable only from
  2019-10 on. Deals 2005-2019-09 exist but have no in-repo prices; they are
  NOT used for track records (a track record computed on prices we cannot
  verify would be an act of faith). Stated plainly: the 20-year formation
  dream waits for a pre-2019 price fetch; this spec runs on what is on disk.
- Event-time structure (point-in-time, expanding):
  - WARMUP: buyer track records accumulate from 2019-10-01.
  - TEST ERA: events from 2022-01-01 to panel end. Events before 2022-01-01
    feed track records only, never statistics.

## Entity resolution (frozen rules — deterministic only)

- Normalize buyer names: uppercase, strip punctuation/multiple spaces, strip
  suffix noise tokens (LIMITED/LTD/PRIVATE/PVT/LLP/A/C/AC/HUF/.) — the exact
  token list lives in the code and the reviewer inspects it.
- NO fuzzy similarity matching (silent merges manufacture fake track
  records). An explicit, human-readable alias table may map obvious variants
  (e.g. "SBI MUTUAL FUND" family); the reviewer must read the full alias
  table and the top-50 entities by deal count before the verdict run.

## Signal (frozen)

- A buyer QUALIFIES at event date t if: ≥15 prior BUY deals with measurable
  outcomes (deal date ≥ 2019-10, outcome window complete before t — strict
  point-in-time), and trailing hit rate (fraction of prior deals with
  positive 20d abnormal return vs EW universe) in the TOP QUARTILE of all
  qualified buyers as of t.
- Event: a qualified top-quartile buyer's BUY bulk deal. Entry next trading
  day's OPEN, hold 20 trading days, exit at open. Liquidity gate at entry:
  symbol in panel, turnover ≥ Rs 2 crore, close ≥ Rs 20.
- Exclusion (mechanical, frozen): events where the same entity appears on
  BOTH sides of the same symbol-day (intraday round-trip — HFT churn, not a
  position; e.g. the Graviton pattern in the data's first rows).
- CONTROL ARM (mandatory): ALL bulk-deal BUYs passing the same gates,
  undifferentiated by buyer. Identical construction.
- Costs: Rs 20,000 position, delivery ['total'] + 0.2%/side slippage
  (wide-universe tier). Sell-side deals: information only.

## Verdict (frozen, ALL must hold)

1. Top-quartile arm mean net 20d abnormal return > 0 in BOTH era halves
   (2022-01..2023-12, 2024-01..panel end), each with ≥40 events.
2. Pooled cluster-robust t ≥ +2.0, clustered by ISO week of the deal.
3. RELABEL GUARD: top-quartile arm minus control arm pooled difference > 0
   with cluster-robust t(difference) ≥ +1.5. If C1/C2 pass and C3 fails,
   the verdict is "generic bulk-deal drift, buyer identity decorative" —
   a FAIL for this spec (and a note on whether the control arm itself looks
   like a separate candidate, which would need its own spec).
Declared test count: 1 (the top-quartile arm).

## Caveats (stated before results)

- Warmup-era track records rest on ~2.3 years of deals — buyers qualify on
  ~15+ deals, a thin skill estimate; stated, not patched.
- Entity resolution errors bias TOWARD null (split entities dilute track
  records), except alias-table mistakes which the reviewer audit exists for.
- The academic literature says bulk-deal alpha concentrates PRE-disclosure
  (front-running); the retail-accessible T+1 residual is expected small.
  A null here is the literature's predicted outcome.
- Quarterly/expanding recomputation makes this heavier compute than usual;
  correctness beats speed, no caching shortcuts that break point-in-time.

## Build plan

Opus builds kite/research/bulk_buyer_persistence.py (+ the alias table as a
separate reviewed file). Smoke = 2 test-era months. Reviewer verifies
point-in-time walls (no track-record peeking), the alias table, top-50
entities, both-sides exclusion, control arm construction — then runs the
verdict. Results appended here.

## Decision log

- 2026-07-29: Spec frozen (user approved).
