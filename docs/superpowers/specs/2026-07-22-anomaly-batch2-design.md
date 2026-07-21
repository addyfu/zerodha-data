# Anomaly Batch 2 — Design Spec (Pre-Registered)

Date: 2026-07-22. Status: APPROVED (user: "build it"). Tests #121-124 of the
project's falsification program. All thresholds frozen before any result is
seen; amendments require dated decision-log entries and never apply
retroactively.

## 0. Meta-guard (read first)

This project has run ~120 honest tests. Family-wise, running four more means
**at least one lucky "survivor" is statistically expected even if all four
anomalies are dead.** Therefore: a PASS in this batch carries strictly less
evidential weight than an early-project PASS would have, and NO outcome here
grants access to real money. Survivors go to the incubator under the October
Contract (docs/superpowers/specs/2026-07-21-promotion-contract.md), full
months-long paper trial, no exceptions. Failures get tombstones as usual.

## 0.1 Common methodology (all four tests)

- Data: `data/daily_universe/` (679 symbols, 2015 → Jul 2026) and
  `data/announcements/` (973k events, 2020 → Jul 2026).
- Liquidity gate at signal time: 60d median turnover > ₹2cr, close > ₹20.
- Costs: delivery charges via `config.zerodha_charges(is_intraday=False)`;
  slippage 0.2%/side (smallcap-honest, matching universe_lab).
- Benchmark: the universe's own daily-rebalanced equal-weight index
  (clipped ±25% daily returns — universe_lab convention). Survivorship
  inflation applies equally to strategy and benchmark; comparisons are
  RELATIVE for exactly this reason.
- Splits where applicable: train 2015-2021, validation 2022-2026 (matching
  universe_lab). Selection on train, verdict on validation, no re-runs.
- Engine reuse: portfolio tests (B, C) run through the universe_lab `USim`
  pattern; event test (A) extends the event_study.py conventions.

---

## Test A — Surprise-Conditioned PEAD (the properly-specified retry)

**Prior result being corrected:** Phase 2 measured unconditional
post-announcement drift for results announcements and found it NEGATIVE
(~-0.6%/5d) — because it pooled beats and misses. Academic PEAD (Bernard &
Thomas 1989; India: Harshita-Singh-Yadav 2018, +4.2-4.8%/60d) conditions on
surprise. This test adds the conditioning.

**Events:** category `Financial Result Updates` from the announcements
archive, joined to the price universe, liquidity-gated.

**Surprise proxy (price-SUE):** the market's own first reaction.
- E = first trading day on/after the announcement timestamp (after-15:30
  rule, identical to event_study.py — reuse its verified mapping).
- Reaction R = (close[E]/close[E-1] − 1) − (universe EW return on E's date).

**LEAKAGE WALL (the amendment that makes or breaks this test):** the signal
window ends at close[E]. The holding window begins at open[E+1]. They may
never overlap; drift windows are measured from the E+1 open. Any
implementation where the reaction day's return appears inside the drift
measurement invalidates the test.

**Bucketing — fixed absolute thresholds, NOT sample-relative ranks** (rank
breakpoints computed over the full sample would leak the future's return
distribution into the past): POSITIVE bucket R > +2%; NEGATIVE bucket
R < −2%; middle excluded from trading, reported for monotonicity.

**Holding:** long the POSITIVE bucket from open[E+1] to close[E+20] (primary)
and close[E+60] (secondary, data permitting). NEGATIVE bucket drift is
measured but untradeable (no overnight retail shorts) — if it qualifies, it
feeds the avoid-filter, like the Phase 2 categories.

**Clustering honesty:** results cluster in earnings seasons, so events are
cross-sectionally correlated. Primary inference aggregates events into
calendar-week cohorts and computes the t-stat on cohort mean CARs
(conservative). Raw per-event stats reported alongside, labeled optimistic.

**Frozen verdict (PASS requires ALL):**
1. POSITIVE-bucket mean abnormal CAR at 20d, net of costs, ≥ +1.0%
2. Positive in ≥2 of 3 eras (2020-22 / 2023-24 / 2025-26)
3. N(positive bucket) ≥ 300 events
4. Monotonicity: mean CAR(positive) > mean CAR(middle) > mean CAR(negative)
5. Cohort-level t-stat ≥ 2.0

## Test B — 52-Week-High Momentum (filling the India literature gap)

**Basis:** George & Hwang (2004); replicated in 18/20 international markets;
no rigorous India test exists.

**Signal:** ratio = close / rolling-252-trading-day max(high). Monthly
rebalance (first trading day), rank liquid universe by ratio, long top 20
equal-weight. USim engine, standard costs/slippage.

**Survivorship amendment:** proximity-to-52-week-high partially IS the
survivorship tilt of a today-liquid universe. The verdict is therefore only
RELATIVE to the same universe's EW B&H — never absolute CAGR.

**Also report:** rank correlation between the 52wk-high signal and mom63
(is this a distinct signal here or momentum in a costume?).

**Frozen verdict (PASS requires ALL, on validation 2022-2026):**
1. Sharpe ≥ B&H Sharpe + 0.10
2. CAGR ≥ B&H CAGR − 2 points
3. Same-direction result on train (no train/val sign flip)

## Test C — Low-Volatility Long-Only Tilt

**Basis:** Frazzini-Pedersen (2014); India: Agarwalla et al. (IIM-A 2014) —
BAB factor "dominates size, value and momentum" in India.

**Signal:** 126-day daily-return standard deviation. Monthly rebalance, long
the LOWEST-vol 20 of the liquid universe, equal weight. USim engine.

**Pre-registered definition of success — RISK-ADJUSTED, decided now per the
momo lesson:** low-vol's documented value is smoother compounding, not
higher raw return. Grading it on CAGR would repeat the mistake of grading
momo on the wrong axis.

**Frozen verdict (PASS requires ALL, on validation):**
1. Sharpe ≥ B&H Sharpe + 0.10
2. Max drawdown at least 25% (relative) shallower than B&H
3. CAGR ≥ B&H CAGR − 3 points
4. Same-direction on train

## Test D — Overnight Anomaly (cheap falsification, expected death)

**Basis:** Cooper et al. 2008, Lou-Polk-Skouras 2019 — globally real,
globally decaying; never systematically measured on NSE. Expectation,
stated in advance: the decomposition is real but the tradeable version dies
on India's 0.2% round-trip delivery STT.

**Measurement:** decompose the universe EW index into cumulative overnight
(open/prev_close − 1) and intraday (close/open − 1) legs, 2015-2026, per era.
Pure accounting — this part has no verdict, it's a fact worth knowing.

**Tradeable check:** buy-at-close/sell-at-next-open every day, full delivery
costs. **Frozen verdict:** tradeable only if net mean ≥ +2bp/day after all
costs (≈ +5%/yr). Anything less = tombstone with the decomposition preserved
as reference knowledge.

---

## Execution plan

- Builder 1 (sonnet): Test A — `kite/research/pead_conditioned.py`,
  reusing event_study.py's verified E-mapping helpers.
- Builder 2 (sonnet): Tests B, C, D — `kite/research/anomaly_batch2.py`,
  reusing universe_lab's loader/USim/benchmark.
- Reviewer (Fable): line-review both for the leakage wall (A) and benchmark
  parity (B/C); independently recompute one quarter of Test A's events and
  one rebalance of Test B before accepting any verdict.
- No parameter changes after first results. Whatever prints is the answer.

## Decision log

- 2026-07-22: Spec frozen, builders launched.
