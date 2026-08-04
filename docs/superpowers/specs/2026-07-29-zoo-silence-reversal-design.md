# Zoo-Silence Reversal — Design Spec (Pre-Registered)

Date: 2026-07-29. Status: APPROVED & FROZEN (user). No changes after this line
except decision-log entries.
Origin: consensus probe 2026-07-28 (exploratory, TRAIN era only, committed
26aa553). Its one positive-after-costs cell: D=0 — (symbol, day) cells where
NONE of the 67 clean zoo strategies emitted a long signal — showed the best
10-day forward net (+0.30%) with mean prior-3d move −1.08%. Hypothesis: the
zoo's silence marks recent small losers that drift up; i.e., the strategy zoo
is a contrarian silence detector. This spec confirms or kills that cell on
validation data the probe NEVER loaded.

## Contamination statement

The probe saw train data (2021-07..2023-12) only; its truncation was enforced
at load with asserts. Validation (2024-01 onward) is untouched by both the
probe and this design. This is therefore a true out-of-sample confirmation —
the strongest evidence class this project can produce short of live paper.

## Data (frozen)

- Same universe and files as the probe: data/daily/ (48 NIFTY symbols, the
  zoo's home), STRATEGY_REGISTRY signals via the probe's exact generation
  path, the same 67-strategy clean set (the probe's 9 leak-suspects + 2
  erroring strategies stay excluded; the identical exclusion list is part of
  the deliverable and must match the probe's, byte for byte).
- VALIDATION ERA: signals from 2024-01-01; forward windows must end by the
  panel's last bar (~2026-01-09). Train-era bars may be loaded ONLY for
  indicator warmup (strategies need lookback); no cell dated before
  2024-01-01 enters any statistic. Assert both boundaries in code.

## Signal (frozen — exactly the probe's cell, zero new conditions)

- D(symbol, day) = count of clean zoo strategies emitting a LONG signal.
- Event: D = 0. No prior-return condition, no volatility condition, nothing
  added that the probe cell did not have. (The probe's observation was
  unconditioned D=0; conditioning now would be tuning.)
- Entry next trading day's OPEN; exit at close of the 10th trading day after
  entry (H=10, the probe's best horizon, declared primary). H=5 reported as
  secondary information, never verdict-bearing.

## Costs (frozen)

Rs 20,000 position, delivery charges via calculate_charges(...)['total']
(never sum(values())), 0.05%/side slippage (NIFTY tier). Identical to probe.

## Verdict (frozen, ALL must hold)

1. Validation D=0 mean net (H=10) > 0.
2. Cluster-robust t ≥ +2.0, clustered by ISO week of entry (overlapping
   10-day windows within a week share a cluster; residual overlap across
   weeks is noted as a limitation, not patched post hoc).
3. MOMENTUM/REVERSAL CONTROL — the probe's own warning: D=0 must add
   information beyond "recent loser." Split all validation cells into
   quintiles of prior-3d return (quintile breakpoints computed on validation
   cells, all D values pooled). Within each quintile: mean net H=10 of D=0
   cells minus D≥1 cells. Criterion: the pooled (cell-count-weighted) D=0
   minus D≥1 difference > 0 AND positive in at least 3 of 5 quintiles.
   If C1 and C2 pass but C3 fails, the recorded verdict is "short-term
   reversal re-discovered, zoo-silence decorative" — a FAIL for this spec.
Declared test count: 1 (the D=0 cell at H=10).

## Caveats (stated before results)

- Train-era exploration found this cell among ~15 bucket cells examined —
  a mild selection effect the true-OOS design exists to discipline.
- The reversal family has graveyard cousins; C3 exists precisely to stop a
  re-labeled short-term-reversal from passing as novel.
- 48 large-cap symbols only; any pass generalizes to nothing wider without
  its own test.
- On a pass: phase-2 spec (portfolio construction, incubator candidacy) —
  separate approval. Never straight to live.

## Build plan

Opus builds kite/research/zoo_silence_confirmation.py (reuse consensus_probe.py
machinery via import or verbatim copy — reviewer checks signal-path identity).
Smoke = one validation month. Reviewer verifies era walls, the 67-set match,
the quintile control, then runs the verdict. Results appended here.

## Decision log

- 2026-07-29: Spec frozen (user approved).
- 2026-07-29 (build, reviewer-accepted): era walls hard-asserted;
  exclusion-list drift-guard passes (67-set byte-identical to the probe).
  Horizon ambiguity in the spec's own wording resolved to the probe's
  exact bar (CLOSE[sig+10]); literal alternative in a non-verdict
  appendix. SHREECEM (price > Rs 20k) contributes no net cells under the
  frozen cost model — now loud, effective net universe 47 symbols.
- 2026-08-04 (correction, verdict unchanged): the entry below cites the
  APPENDIX horizon's numbers (+0.091%, t=+1.17 — CLOSE[sig+11], explicitly
  non-verdict-bearing). The PRIMARY verdict-bearing block (H=10,
  CLOSE[sig+10]) reads mean net +0.0404%, t=+0.939 — OOS shrinkage vs the
  +0.30% train cell is ~86%, not ~70%. Every block (primary, secondary,
  appendix) fails C2 and C3 identically; FAIL and Tombstone #137 stand.
- 2026-07-29 (results): **FAIL — C1 PASS / C2 FAIL / C3 FAIL. Tombstone
  #137.** Validation D=0 (8,276 cells): mean net +0.091% (train cell was
  +0.30% — shrank ~70% OOS), t=+1.17 vs +2.0. C3 was decisive: within
  prior-3d-return quintiles, D=0 UNDERPERFORMS D≥1 (pooled diff −0.096
  pts, 1/5 quintiles positive) — the zoo's silence adds nothing beyond
  the reversal factor, and less than nothing after matching. The probe's
  best cell was a train-era selection artifact, exactly the failure mode
  the true-OOS design existed to catch. Consensus/ensemble line of
  inquiry now fully closed: voting (probe), K-of-N (probe), and
  silence-as-signal (this) all dead on Indian data.
