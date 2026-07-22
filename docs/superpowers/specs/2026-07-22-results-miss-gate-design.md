# Results-Miss Gate — Design Spec (Pre-Registered)

Date: 2026-07-22. Status: IMPLEMENTED, PENDING REVIEWER DEPLOY. Code is written
and compiles; the reviewer commits and enables it after market close tomorrow
(2026-07-23), per the same falsification-first protocol as every other gate in
this project (docs/superpowers/specs/2026-07-21-news-event-alpha-design.md,
2026-07-22-anomaly-batch2-design.md). This is an extension of the existing
red-flag filter (kite/live_monitor/announcement_filter.py), not a new gate
class — same fail-soft, never-blocks-exits contract.

## 0. Meta-guard (read first)

This is the results-miss rule the batch-2 spec's Test A explicitly flagged as
untradeable-but-filter-worthy: NEGATIVE-bucket (R < -2%) results reactions
drift further down, but nothing here is a fresh discovery — it is the SAME
already-realized PEAD dataset re-purposed as an avoid-list, scored on data
that has already happened. Per the frozen recommendation in
`kite/research/results_miss_filter_study.txt`, this doc supplies the
forward-looking pre-registration that measurement explicitly said was a
prerequisite before this rule went anywhere near the live monitor. Passing
this gate live does not "prove" the effect; it is the walk-forward check
that could kill it.

## 1. The rule

**Block NEW entries for 20 trading days in any symbol whose most recent
'Financial Result Updates'-family announcement was followed by a
first-tradeable-day reaction R < -2% vs the NIFTY-50 EW same-day return.**

- R = (close[E]/close[E-1] − 1) − (benchmark EW same-day return), where E is
  the first trading day on/after the announcement (after-15:30 roll to next
  day — identical convention to `event_study.py` / `pead_conditioned.py`).
- Threshold is the fixed, pre-registered −2% used by the in-sample study —
  not re-fit, not sample-relative.
- Blocks entries only. Never touches exits or already-open positions (same
  contract as the existing red-flag filter — `check_holdings` alerts, does
  not act). Live, it is enforced through `EntryPipeline.try_enter`'s
  existing `ann_filter.is_flagged()` call — the same choke point the
  4-category red-flag filter already uses, so every strategy is covered
  automatically with zero changes to `entry_pipeline.py`.
- 20 trading days is approximated on the live system as **28 calendar days**
  (see risk 3d) — documented, not silently baked in.

## 2. In-sample basis (the measurement this rule is built on)

Source: `kite/research/results_miss_filter_study.txt`, itself built on
`kite/research/pead_events.csv` (8,022 `Financial Result Updates` PEAD events,
2020–2026) from `kite/research/pead_conditioned.py` (lines ~150–200 compute R
exactly as in section 1, with the leakage wall enforced: R uses only data
through close[E]; the drift window begins at open[E+1] and never overlaps).

Frozen numbers, pooled across all eras:
- NEGATIVE-bucket events (R < −2%): **2,560 / 8,022 (31.9%)**.
- Mean CAR_20d of NEGATIVE events: **−1.80%**; median: **−3.20%**.
- Share staying negative at 20d: **63.75%**; 10th-percentile (bad case):
  **−13.02%**.
- Era consistency: NEGATIVE-bucket incidence is stable across all three eras
  (31.9% / 31.6% / 34.1% of era volume); mean CAR_20d is negative in all
  three eras too (−2.94% / −0.81% / −1.37%).
- Overlap with the existing 4-category red-flag filter (±5 calendar days,
  same symbol): only **22.8%** (583/2,560) — **77.2% of NEGATIVE events are
  additive**, i.e. drift episodes the current filter does not already catch.
- Cost of the rule: ~**9,883 blocked-stock-days/year** across the universe
  (51,087 unique symbol-day pairs over a 5.17-year span, deduped for
  re-triggers/overlap — dedup only removed 0.2% of gross).

Read together: a large (2,560-event), mostly non-overlapping population with
a consistent negative aftermath at a cheap-relative-to-benefit blocked-days
cost. That is why the study's own verdict was "worth prototyping" rather than
"deploy directly" — which is the entire reason this doc exists.

## 3. Acknowledged risks

**a) In-sample measurement.** The bucket assignment and the car_20d being
scored were computed from the SAME realized data being used to justify the
rule. Nothing here has been tested walk-forward. This is exactly the
falsification-program discipline every other spec in this project uses
(anomaly-batch2 section 0: "at least one lucky survivor is statistically
expected"). Section 5 is the antidote — a frozen, un-negotiable forward test.

**b) Category-label taxonomy drift.** `pead_conditioned.py`'s own header
documents that the NSE `desc` label `'Financial Result Updates'` — the
literal category the 8,022-event study filtered on — **effectively
disappears from the announcements archive after 2025-Q1** (1,663–2,149
rows/quarter every quarter 2020–2024, then ~0 every quarter after). This
looks like an NSE/data-pipeline taxonomy change: quarterly-result disclosures
appear to migrate to other `desc` labels (e.g. `'Outcome of Board Meeting'`,
`'Clarification - Financial Results'`) from 2025-Q2 onward.

Consequence for the LIVE rule: matching only the literal string
`'Financial Result Updates'` would make the gate silently stop firing on any
recent announcement — exactly the failure mode we're trying to avoid.
`'Outcome of Board Meeting'` cannot be used as a blanket substitute either:
it is a broad, mixed-content category (dividends, buybacks, appointments,
open offers, results — anything a board resolves) and matching all of it
as "results" would be a much broader, unmeasured rule wearing this one's
in-sample numbers.

**Chosen approximation (frozen, not tuned):** match `desc` case-insensitively
against the substrings `'financial result'` OR `'results'` (i.e.
`'financial result' in desc.lower() or 'results' in desc.lower()`). This
catches the frozen category (`'Financial Result Updates'` contains
`'financial result'`), catches likely successor/variant labels containing
"Results" (e.g. `'Clarification - Financial Results'`), and does NOT
independently pull in `'Outcome of Board Meeting'` items unless their own
`desc` text separately mentions results. This is an explicit, documented
**approximation of the frozen category, not the frozen category itself** —
the live gate's population will differ somewhat from the exact 8,022-event
study population, in a direction and magnitude that is not measured here.

**c) Benchmark mismatch (surfaced during implementation, not previously
called out).** The study's R uses the 679-symbol `daily_universe` equal-weight
return (`build_universe_returns()` in `event_study.py`) as the benchmark leg.
The live gate, for data-availability reasons (see section 4), uses the
NIFTY-47 EW same-day mean (`self.stocks` in `monitor.py` — nominally "NIFTY
50", actually 47 names since TATAMOTORS's token went dead post-2025 demerger)
computed from `daily_data_cache`, which is guaranteed loaded early in every
scan cycle. NIFTY-47 is large-cap-tilted and will not track the 679-stock
universe day-to-day as closely as the universe tracks itself. This substitutes
a correlated but distinct benchmark for the one the in-sample numbers in
section 2 were measured against, adding basis risk to exactly where the −2%
threshold's live edge falls. Not correctable without restructuring the daily
data loads (out of scope for this surgical change) — documented, not fixed.

**d) 20 trading days ≈ 28 calendar days.** The live gate has no trading
calendar; it approximates 20 trading days as 28 calendar days (a 1.4×
multiplier — same convention `announcement_filter.py` already uses for
`LOOKBACK_CALENDAR_DAYS = 7` ≈ 5 trading days). This slightly over-blocks
across long weekends/holiday clusters and does not correct for NSE holidays.
Documented approximation, not exact trading-day arithmetic.

**e) "Last 2 trading days" announcement-recency window is also a calendar
approximation** (4 calendar days) for the same reason as (d), and interacts
with (c): `check_results_reactions()` tests the symbol's *latest* daily bar
against the benchmark, using announcement recency only to decide which
symbols are candidates. If a qualifying announcement is 2 trading days old,
"latest daily bar" is a same-day-of-check approximation of the true E-day
reaction, not a re-derivation of the exact historical E/E-1 pair. This is a
deliberate simplification (no announcement-timestamp-to-bar join in the live
path) and a source of noise relative to the offline R computation.

## 4. Implementation summary (what actually shipped)

- `kite/live_monitor/announcement_filter.py`: `AnnouncementFilter` gains
  `results_announcements` (collected during `refresh()`, filtered to the
  results-family substring match over the last ~2 trading days),
  `results_miss_flags` (symbol → ISO flag date, loaded from and persisted to
  `data/results_miss_flags.json`, fail-soft on read/write), `flag_results_miss(symbol)`
  (unconditional store + save + log), `note_results_reaction(symbol, reaction)`
  (threshold-checking convenience wrapper around `flag_results_miss`), and
  `_prune_expired_flags()` (called at the top of every `refresh()`,
  independent of network success). `is_flagged()` now also returns a reason
  for an unexpired results-miss flag — checked regardless of whether the live
  NSE feed is reachable that day, since the flag was derived from price data
  already on disk, not from today's announcement fetch.
- `kite/live_monitor/monitor.py`: one new method, `check_results_reactions()`
  (self-contained try/except, guarded on `daily_data_cache`/`wide_daily_cache`
  presence — no-ops if either is empty), and one new call site immediately
  after `self.ann_filter.refresh()` in the daily swing block (wide data is
  already loaded earlier in the same cycle via `load_historical_data()` by
  the time this block runs). No other line in `monitor.py` changed.
- No changes to `entry_pipeline.py` — the existing `ann_filter.is_flagged()`
  call already covers every strategy; that is the entire point of routing
  through the shared filter object instead of adding a parallel gate.
- State: `data/results_miss_flags.json`, `{symbol: "YYYY-MM-DD"}`. Survives
  restarts. Pruned every refresh.

## 5. Frozen forward evaluation (the walk-forward check that can kill this)

This gate is on paper-trial probation, same tier as any incubator strategy:

**After the gate has produced 60 live blocked-entry events** (a "blocked
event" = one `flag_results_miss` call that would otherwise have allowed a
`try_enter` — logged, countable from `monitor.log`):

- Compute each blocked symbol's realized abnormal return over the 20 trading
  days following its flag date (stock return minus NIFTY-47 EW return over
  the same span — consistent with the live benchmark actually used, per risk
  3c, not the study's 679-stock benchmark).
- **Frozen verdict:** the mean realized 20-trading-day abnormal return across
  all 60+ blocked events must be **negative**. If the mean is ≥ 0, the gate
  is **removed** (reverted to the pre-existing 4-category-only filter) — no
  re-fitting the threshold, no narrowing the category match first. Dead is
  dead, same as every other tombstoned test in this project.
- This check is not automated in this change (out of scope — "keep it
  simple" / surgical). It is a manual review triggered once
  `results_miss_flags.json` (or `monitor.log`) shows 60 cumulative flag
  events; the reviewer computes it by hand or with a short throwaway script
  against `wide_daily_cache`/`daily_universe` history at that time.
- No outcome from this evaluation grants access to real money — same
  incubator-only ceiling as every strategy in this project
  (docs/superpowers/specs/2026-07-21-promotion-contract.md).

## 6. Decision log

- 2026-07-22: In-sample study (`results_miss_filter_study.txt`) frozen its
  own recommendation: needs its own forward pre-registration before going
  near the live monitor.
- 2026-07-22: This spec frozen; rule, category-match approximation, and the
  60-event forward-evaluation gate fixed before writing any code.
  Implementation (`announcement_filter.py` extension + `monitor.py`
  `check_results_reactions()`) written same day, `py_compile`-clean, smoke
  test passing. Deploy explicitly deferred — reviewer commits and enables
  after market close 2026-07-23.
