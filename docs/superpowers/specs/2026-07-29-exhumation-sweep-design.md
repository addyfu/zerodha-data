# Exhumation Sweep — Design Spec (Pre-Registered)

Date: 2026-07-29. Status: APPROVED & FROZEN (user). No changes after this line
except decision-log entries.
Origin: user proposal — "we now have more data than ever; backtest the dead
strategies on it and see if anything is worthy." This is NOT a new-idea hunt;
it is the FINAL audit of the existing strategy zoo on the widest honest data
this project will ever hold. One shot, then the book on price-pattern
strategies closes with no "but what if wider" asterisk.

## Stated prior (before any result)

The zoo died on 48 liquid large caps under 0.05%/side slippage. The wide
universe RAISES the cost bar (0.2%/side, smallcap spreads) — and the two
prior wide-universe tests (breadth momentum, delivery factor) both failed
hard on this exact panel. Expected outcome: 137-0 stands. The sweep's value
is decisive closure either way; a Bonferroni-clearing survivor would be the
strongest signal this project has ever produced and earns an incubator
discussion, never money.

## Data (frozen)

- data/bhavcopy_full/ panel: 3,204 NSE stocks, 2019-10-01..2026-07, corp-
  action adjusted via data/corp_actions_adjustments.csv (HALT on NaN-factor
  match), return clip guard ±25% (HALT >0.1% of eligible stock-days) —
  delivery_factor_study.py conventions verbatim.
- Eligibility per (symbol, day): series EQ, turnover ≥ Rs 2cr, adjusted
  close ≥ Rs 20 at signal time.
- Strategies: the SAME 67-strategy clean set as consensus_probe/zoo_silence
  (9 leak-suspects + 2 erroring excluded; byte-identical list asserted —
  drift guard reused).

## Execution model (frozen — retest_all.py conventions, wide-universe costs)

- Signals: each strategy's own vectorized generate_signals() on each
  symbol's daily bars (warmup allowed; signals only counted on eligible
  stock-days).
- Trades: LONG signals only (multi-day shorts untradeable; short signals
  counted as info). Entry next trading day's OPEN; exit at strategy SL/TP
  gap-aware (fill at the worse of stop/open on gap-through) or 10-trading-
  day time stop, whichever first — one convention for the whole zoo, stated
  as such (many zoo strategies carry their own SL/TP; those are used where
  defined, the 10d time stop is the universal backstop).
- One trade per (strategy, symbol, day); overlapping re-signals ignored
  while a position is open.
- Costs: Rs 20,000 position; delivery charges calculate_charges(...)['total']
  (incl. DP) + 0.2%/side slippage.
- Benchmark: per-trade abnormal return = net trade return MINUS the EW
  eligible-universe return over the identical holding window (event_study
  benchmark construction).

## Split and verdict (frozen)

- Train 2019-10..2023-12: reported, informational.
- VALIDATION 2024-01..2026-07: verdict era.
- Per-strategy criteria — ALL required to count as a SURVIVOR:
  1. ≥100 validation trades (else NODATA — underpowered, recorded, not a pass).
  2. Validation mean net abnormal return > 0.
  3. Cluster-robust t (ISO week of entry) ≥ +3.2 — the Bonferroni bar for 67
     simultaneous tests at α=0.05 (0.05/67 → one-sided z≈3.2). This is the
     resurrection-lottery guard: 67 dead strategies WILL produce ~3 nominal
     t≥2 passes by chance; the bar is set so chance survivors are expected
     ≈ 0.05 across the whole sweep.
  4. Train-era mean net abnormal return also > 0 (no sign flip).
- Survivors (if any): incubator-candidacy discussion with fresh phase-2 spec.
  Non-survivors: the zoo's graveyard verdict becomes FINAL on the widest
  data available; family closed permanently.
- Declared test count: 67. No per-strategy parameter variation, no timeframe
  variation, no post-hoc subgroups ("worked on smallcaps only" = FAIL, noted
  as unregistered observation at most).

## Parallelization (implementation, not statistics)

Shard by symbol into 10 worker processes (i5-12400F, 12 threads, 16GB);
each worker computes all 67 strategies for its symbol shard, writes partial
trade files; single-threaded merge + verdict pass at the end. Shard
boundaries cannot affect results (per-symbol independence); merge asserts
total symbol coverage and zero duplicate (strategy, symbol, entry-date)
trades.

## Caveats (stated before results)

- The universal 10d time-stop backstop means strategies whose exits differ
  from their live/zoo configuration are tested in a HARMONIZED form; a
  survivor must be re-validated under its own exact exit before candidacy.
- Signal-generation compute at 3,204 symbols is ~66x the 48-symbol probe
  (~10.5h single-core); shard estimate 1.5-2.5h wall-clock. If a strategy's
  generate_signals() errors on wide-universe data quirks, it is skipped and
  counted (reported), not silently dropped.
- Smallcap slippage 0.2%/side remains an inference, not a measurement
  (stated repeatedly since 2026-07-26).

## Build plan

Opus builds kite/research/exhumation_sweep.py (+ worker/merge entrypoints).
Smoke: 2 shards × 50 symbols. Reviewer verifies exclusion-list assert,
gap-aware fills, cost calls, Bonferroni verdict logic, then launches the
10-shard run and the verdict pass. Results appended here.

## Decision log

- 2026-07-29: Spec frozen (user approved; user explicitly requested
  same-day parallel execution).
- 2026-07-29 (build, reviewer-accepted): builder caught and fixed a
  LOOKAHEAD BIAS in the benchmark itself (same-day eligibility membership
  inflates the EW benchmark 0.21%/day via the Rs-20 floor admitting stocks
  the day they jump it; lagged membership used — the HARDER bar), plus a
  datetime-resolution bug that a blanket except had laundered into "58
  erroring strategies", plus a resume-corruption path. Hand-verified trade
  economics to 8dp; 4 gap-fill cases 0 mismatches. 9/67 strategies are
  structurally SILENT (0 long signals ever, matching the probe). Bonferroni
  bar NOT relaxed for the effective-58 (frozen means frozen).
- 2026-07-29 ~23:15 (results): **ZERO SURVIVORS out of 67. The stated
  prior held — on the widest honest data this project will ever run.**
  10 shards × 2,369 symbols × 2.84M bars, ~2M simulated trades, full
  delivery costs + 0.2%/side slippage. The rout is total: even the
  best-ranked strategy (trix_zero_line) posts NEGATIVE validation
  abnormal returns (t=−2.64); nothing was even close to the +3.2 bar —
  nothing was above ZERO at the top of the table. Notable for October
  context: cci_divergence (live incubator candidate) shows val abnormal
  −1.05%/trade (t=−4.76) on the wide universe — its incubator trial is
  on its own 48-stock home turf with its own card, but this number
  belongs in the October weighing. THE PRICE-PATTERN FAMILY IS NOW
  CLOSED PERMANENTLY: 48 stocks and 2,369 stocks, 0.05% and 0.2%
  slippage, 2020-2026 — the answer is the same everywhere. No "but what
  if wider" remains. Buy-and-hold: 138-0.
