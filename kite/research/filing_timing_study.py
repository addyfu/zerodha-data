"""Filing-Timing Metadata Study (pre-registered, FROZEN).

Frozen spec:
docs/superpowers/specs/2026-07-28-filing-timing-design.md
Status: APPROVED & FROZEN (user, 2026-07-28). No deviations from the spec.

HYPOTHESIS: companies choose WHEN to file. Low-attention timing (after-hours,
Friday afternoon, pre-holiday) marks news management and predicts negative
drift BEYOND the filing's category. Category-CONTENT drift is already dead
here (0/3 on the 2026-07-28 confirmation study); this tests TIMING as an
orthogonal signal, WITHIN-CATEGORY controlled.

TIMING BUCKETS (frozen -- exactly three, no additions):
    B1 AFTER-HOURS : filed 15:30:00-08:59:59 IST (incl. weekends, which map
                     forward to the next trading day's population).
    B2 FRIDAY-PM   : filed Friday 12:00:00-15:29:59 IST.
    B3 PRE-HOLIDAY : filed on the last trading day before a NON-WEEKEND market
                     closure, where closures are DERIVED FROM THE PRICE PANEL'S
                     OWN OBSERVED TRADING CALENDAR (a weekday lying inside the
                     panel's date span with no trading data = a closure).
                     Weekend-only gaps do NOT count. See CONSTRUCTION NOTES (d)
                     -- this instrument is the spec's [AMENDED 2026-07-28]
                     definition, replacing the 2026-only NSE_HOLIDAYS table.
Buckets are assigned from the FILING timestamp (announcements' `sort_date`,
full date+time), never from the event date E.

METHOD (frozen; join/E-date/entry/CAR conventions reused VERBATIM from
event_study.py via direct import -- load_prices / build_universe_returns /
process_symbol, all unmodified):
  1. Same join, same E-date search (E = announcement date advanced to the next
     trading day, or the day after if filed post-15:30 IST), same E+1-open
     entry, same liquidity gate (60d median turnover > 2e7 and close > 20 at
     E), same 20-day forward-data requirement.
  2. excess_5d = event car_5d MINUS the same-era ALL-ANNOUNCEMENT baseline
     (mean car_5d across every joined category's events in that era) --
     construction identical to the 2026-07-27 confirmation study.
     excess_20d likewise; 20d is SECONDARY, reported only, never verdict-bearing.
  3. Eras (by event date E): 2020-01..2021-12 / 2022-01..2023-12 /
     2024-01..2026-07.
  4. The comparison is ALWAYS bucket-vs-control WITHIN the same category and
     era. Control for bucket B = every OTHER filing of the SAME category in
     the SAME era that is not in B. Never bucket-vs-zero (that would
     re-discover the dead category effect through a proxy).
  5. Pooling: across categories with >= 100 events in BOTH arms, weighted by
     event count. See CONSTRUCTION NOTES below for the two decisions this
     sentence leaves open and how they were resolved.
  6. Inference: cluster-robust by ISO calendar week, same formula as the
     confirmation study, applied to a per-week DIFFERENCE series -- see
     weekly_diff_series() and cluster_robust_t() docstrings.

VERDICT (frozen, per bucket, ALL must hold to PASS):
    Criterion 1: pooled bucket-minus-control 5d difference <= -0.10% in EVERY
                 one of the three eras.
    Criterion 2: pooled (all-eras-combined) cluster-corrected t <= -2.4
                 (Bonferroni for the 3 declared buckets).
Declared test count: 3 (one per bucket). A bucket that fails stays failed --
no threshold nudging, no window shopping across alternate cuts.

CONSTRUCTION NOTES (FLAGGED FOR REVIEWER ATTENTION -- the spec fixes the
intent, these three implementation choices resolve what it leaves open):

  (a) CATEGORY-QUALIFICATION SCOPE. The spec's ">= 100 events in both arms"
      screen is applied ONCE on the FULL (all-era) population, per bucket,
      producing a category set that is then FROZEN and used identically in
      every era and in the pooled t. Rationale: applying the screen per era
      would let the category set drift between eras, making criterion 1's
      era-to-era comparison apples-to-oranges, and would silently shrink the
      pool in thin eras. This mirrors event_study.py's practice of freezing
      the category mapping on the joined population before downstream splits.
      A qualifying category with zero bucket events in some era simply
      contributes zero weight to that era.

  (b) POOLING WEIGHT. "Weighted by event count" is implemented as the
      BUCKET-ARM event count of the (category, era) cell. Rationale: the
      precision of a cell's bucket-minus-control difference is governed by
      the scarce arm; weighting by bucket+control totals would let a category
      with a huge control arm and a tiny bucket arm dominate the pool, which
      is plainly wrong. With n_control >> n_bucket (the usual case here) the
      bucket-count weight is approximately the inverse-variance weight.

  (c) THE PER-WEEK DIFFERENCE STATISTIC. The spec requires a cluster-robust t
      "on the DIFFERENCE construction ... for each week, (mean bucket excess
      - mean same-category control excess) pooled". Implemented as, for each
      ISO week w:
          cell   = (week w, era, category c) with >= 1 event in BOTH arms
          d(c,w) = mean(excess_5d | bucket, c, w) - mean(excess_5d | control, c, w)
          D_w    = sum_c n_bucket(c,w) * d(c,w) / sum_c n_bucket(c,w)
      then the confirmation study's formula verbatim on the D_w series:
          t = mean(D_w) / ( std(D_w, ddof=1) / sqrt(n_weeks) ).
      i.e. the unit of observation is the WEEKLY POOLED WITHIN-CATEGORY
      DIFFERENCE, so week-level common shocks (sector news, earnings-season
      clustering, overlapping forward windows against the same universe
      realization) cancel inside the week before any averaging.
      COST, reported explicitly in the output: a bucket event whose (week,
      era, category) cell has NO same-week same-category control is dropped
      from the t (it has no within-week counterfactual). The retention rate
      is printed per bucket so the reviewer can judge.
      REJECTED ALTERNATIVE (not computed, to avoid multiplicity): offsetting
      each bucket event by its category's ERA-level control mean would retain
      100% of bucket events, but it treats the control mean as a known
      constant, ignores its sampling error, and lets week-level common shocks
      leak into the bucket arm uncancelled -> anti-conservative t. The frozen
      spec's wording ("mean bucket excess - mean same-category control excess"
      per week) matches the implemented construction, not the alternative.

  (d) B3's CLOSURE INSTRUMENT [SPEC AMENDMENT 2026-07-28, user-approved BEFORE
      the verdict run -- see the B3 bullet's [AMENDED 2026-07-28] block in
      docs/superpowers/specs/2026-07-28-filing-timing-design.md]. B3 originally
      read its holidays from parity_monitor.NSE_HOLIDAYS. That table registers
      2026 ONLY, so B3 was blind in eras 1-2 and would have auto-failed
      criterion 1 on CALENDAR COVERAGE rather than on evidence. Amended
      instrument: closures are derived from the price panel's own observed
      trading calendar -- a weekday inside the panel's date span with NO
      trading data in ANY universe symbol is a market closure, and B3's
      population is the last observed trading day strictly before each such
      closure. This resolves 158 pre-closure trading days across the panel
      (2015-01-01..2026-07-21) against the 10 visible from NSE_HOLIDAYS.
      Scope of the amendment: DATA-SUFFICIENCY / instrument only. Buckets
      B1/B2, the B3 CONCEPT ("last trading day before a non-weekend closure"),
      thresholds, windows, eras, the within-category control, the category
      screen, the week clustering and every verdict rule are UNTOUCHED.
      Two properties of the derivation worth stating:
        - It is closure-truth, not holiday-list-truth: an unscheduled closure
          (2024-01-22, Ram Mandir) is captured, and a special SATURDAY session
          (2024-01-20) is correctly treated as a trading day, so it -- not the
          preceding Friday -- is the pre-closure day.
        - CENSORING GUARD (retained from the original): a closure at or after
          the panel's last trading day is not observable, so the panel's last
          day is never tagged pre-closure. Under gap derivation every closure
          lies strictly between two observed trading days, which enforces this
          structurally; the guard is kept explicit and asserted.
      NSE_HOLIDAYS is still imported, but ONLY for a non-verdict-bearing
      cross-check diagnostic (does the panel confirm the 2026 table?).

CAVEATS (stated before any results, per spec):
  - Timestamps may reflect exchange dissemination time, not company decision
    time. The tradeable signal is the public timestamp either way.
  - Some categories legitimately cluster after-hours (board-meeting outcomes).
    The within-category control absorbs level differences; a category with
    <100 events in either arm is excluded from the pool (count reported).
  - In-sample exploration on mined announcement data. Any PASS gets the
    forward kill-criterion as its real out-of-sample test -- identical
    mechanism to the results-miss gate. Never an automatic deploy.
  - The same-era all-announcement baseline CANCELS ALGEBRAICALLY inside every
    bucket-minus-control difference (both arms sit in the same era and are
    offset by the same number). It is retained because the spec freezes it and
    because it makes the reported per-arm LEVELS comparable to the
    confirmation study; it moves no verdict. The one exception is an ISO week
    that straddles an era boundary -- handled by including `era` in the weekly
    cell key, so every difference is taken within a single era.

Usage:
    python kite/research/filing_timing_study.py              # full study
    python kite/research/filing_timing_study.py --smoke      # self-check only:
        restricts the announcement population to ONE month (default 2024-01),
        so two of three eras have zero events by construction and criterion 1
        fails trivially -- SMOKE OUTPUT IS NOT A VERDICT, plumbing check only.
        The default 2024-01 exercises B3 too: the panel-derived calendar puts
        two pre-closure days in it (Sat 2024-01-20 before the 2024-01-22
        closure, and Thu 2024-01-25 before Republic Day 2024-01-26).
    python kite/research/filing_timing_study.py --smoke --smoke-month 2026-01
        same, on another month carrying pre-closure days.
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import event_study as es  # noqa: E402  -- reuse load_prices/build_universe_returns/process_symbol VERBATIM

sys.path.insert(0, str(ROOT / 'kite' / 'live_monitor'))
# NSE_HOLIDAYS is NO LONGER B3's definition source (spec amendment 2026-07-28,
# construction note (d)); it is retained solely for a non-verdict-bearing
# cross-check of the panel-derived closure calendar against the 2026 table.
import parity_monitor as pm  # noqa: E402

OUT_TXT = Path(__file__).resolve().parent / 'filing_timing_results.txt'
OUT_TXT_SMOKE = Path(__file__).resolve().parent / 'filing_timing_results_smoke.txt'

# (label, start, end) -- inclusive, by event date E. Frozen.
ERA_BOUNDS = [
    ('2020-01..2021-12', pd.Timestamp('2020-01-01'), pd.Timestamp('2021-12-31')),
    ('2022-01..2023-12', pd.Timestamp('2022-01-01'), pd.Timestamp('2023-12-31')),
    ('2024-01..2026-07', pd.Timestamp('2024-01-01'), pd.Timestamp('2026-07-31')),
]

BUCKETS = ['B1_AFTER_HOURS', 'B2_FRIDAY_PM', 'B3_PRE_HOLIDAY']
BUCKET_DESC = {
    'B1_AFTER_HOURS': 'filed 15:30:00-08:59:59 IST (incl. ALL weekend filings, mapped forward)',
    'B2_FRIDAY_PM': 'filed Friday 12:00:00-15:29:59 IST',
    'B3_PRE_HOLIDAY': 'filed on the last trading day before a non-weekend market closure '
                      '(panel-derived calendar)',
}

DIFF_5D_FLOOR = -0.0010   # -0.10%, criterion 1
CLUSTER_T_THRESH = -2.4   # criterion 2, Bonferroni for 3 declared buckets
MIN_ARM_EVENTS = 100      # category pool screen: >=100 events in BOTH arms

# Bucket clock boundaries, seconds since midnight.
SEC_1530 = 15 * 3600 + 30 * 60   # 15:30:00
SEC_0900 = 9 * 3600              # 09:00:00
SEC_1200 = 12 * 3600             # 12:00:00

OUT_LINES = []


def out(s=''):
    print(s)
    OUT_LINES.append(s)


# --------------------------------------------------------------------------
# Data loading -- announcements loader mirrors event_study.load_announcements()
# exactly (same usecols/dtype/parsing), parametrized only by which files to
# read so --smoke can restrict to a single month without touching event_study.py.
# --------------------------------------------------------------------------

def load_announcements(smoke=False, smoke_month='2024-01'):
    if smoke:
        files = sorted(es.ANN_DIR.glob(f'ann_{smoke_month}.csv'))
    else:
        files = sorted(es.ANN_DIR.glob('ann_*.csv'))
    if not files:
        raise SystemExit(f'no announcement files matched (smoke={smoke}, month={smoke_month})')
    frames = []
    for f in files:
        d = pd.read_csv(f, usecols=['sort_date', 'symbol', 'desc'], dtype={'symbol': str, 'desc': str})
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    df['sort_date'] = pd.to_datetime(df['sort_date'])
    return df


def assign_era(e_date):
    """Vectorized era bucketing on event date E. Returns object Series, None if out of range."""
    conditions = [(e_date >= start) & (e_date <= end) for _, start, end in ERA_BOUNDS]
    choices = [label for label, _, _ in ERA_BOUNDS]
    return pd.Series(np.select(conditions, choices, default=None), index=e_date.index)


# --------------------------------------------------------------------------
# Bucket assignment (on the FILING timestamp, not on E)
# --------------------------------------------------------------------------

def build_preholiday_dates(all_dates):
    """Last observed trading day strictly before each NON-WEEKEND market closure.

    SPEC AMENDMENT 2026-07-28 (construction note (d)): the closure calendar is
    DERIVED FROM THE PRICE PANEL ITSELF, not from parity_monitor.NSE_HOLIDAYS
    (which registers 2026 only and left B3 blind in eras 1-2). Definition:

        closure   = a WEEKDAY lying strictly inside the panel's observed
                    trading-date span that carries no trading data in any
                    universe symbol, i.e. a weekday falling in the gap between
                    two consecutive observed trading days.
        B3 date   = the observed trading day immediately BEFORE such a gap.

    Weekend-only gaps do NOT count (frozen): a Fri->Mon gap contributes
    nothing. A gap containing >= 1 weekday contributes its preceding trading
    day exactly once, however many weekdays the closure spans.

    The panel's own dates are the trading calendar, so an exchange SATURDAY
    session (e.g. the special 2024-01-20 session) is a trading day and can
    itself be a pre-closure day; and an UNSCHEDULED closure absent from any
    published holiday table (e.g. 2024-01-22) is still captured.

    CENSORING GUARD (retained from the pre-amendment implementation): a closure
    at or after the panel's last observed trading day is not observable, so the
    panel's last day must never be tagged pre-closure. Gap derivation enforces
    this structurally (every closure lies strictly between two observed trading
    days); the filter is kept explicit and the invariant asserted.

    Returns (pre:dict[Timestamp -> list[date]], diagnostics:list[str]) mapping
    each pre-closure trading day to the closed weekday(s) it precedes.
    """
    td = pd.DatetimeIndex(all_dates)
    last = td[-1]
    pre = {}
    diags = []
    n_weekend_only_gaps = 0
    n_censored = 0
    for prev, cur in zip(td[:-1], td[1:]):
        if (cur - prev) <= pd.Timedelta(days=1):
            continue
        closed = [m for m in pd.date_range(prev + pd.Timedelta(days=1), cur - pd.Timedelta(days=1))
                  if m.dayofweek < 5]
        if not closed:
            n_weekend_only_gaps += 1
            continue  # weekend-only gap -- does NOT count (frozen)
        closed = [m for m in closed if m < last]  # censoring guard (structurally vacuous here)
        if not closed:
            n_censored += 1
            continue
        pre[pd.Timestamp(prev)] = [m.date() for m in closed]
    assert last not in pre, 'censoring guard violated: panel last day tagged pre-closure'

    n_closures = sum(len(v) for v in pre.values())
    multi = {d: v for d, v in pre.items() if len(v) > 1}
    diags.append(f'    {n_weekend_only_gaps:,} weekend-only gaps in the panel -- excluded per spec '
                 f'(a Fri->Mon gap is not a closure)')
    diags.append(f'    {n_closures} non-weekend closure day(s) resolve to {len(pre)} distinct '
                 f'pre-closure trading day(s)')
    if multi:
        diags.append(f'    {len(multi)} pre-closure day(s) precede a MULTI-DAY closure (counted once):')
        for d in sorted(multi):
            diags.append(f'      {d.date()} -> {", ".join(str(x) for x in multi[d])}')
    if n_censored:
        diags.append(f'    {n_censored} gap(s) dropped by the censoring guard (closure at/after the '
                     f'panel\'s last trading day {last.date()})')
    diags.append(f'    censoring guard OK: {last.date()} (panel last trading day) is NOT tagged '
                 f'pre-closure -- any closure after it is unobservable, not absent')
    return pre, diags


def nse_holiday_crosscheck(all_dates, pre):
    """NON-VERDICT-BEARING sanity check of the panel-derived closure calendar.

    parity_monitor.NSE_HOLIDAYS no longer defines B3 (construction note (d)),
    but where it DOES have coverage it is an independent published source, so
    we report whether the panel agrees with it. A mismatch would mean either a
    stale table or a hole in the price data; agreement is evidence the derived
    calendar is real. Returns a list of output lines.
    """
    td = pd.DatetimeIndex(all_dates)
    observed_closures = {pd.Timestamp(c) for v in pre.values() for c in v}
    lines = [f'  CROSS-CHECK vs parity_monitor.NSE_HOLIDAYS (diagnostic only -- NOT B3\'s source):']
    for year in sorted(pm.NSE_HOLIDAYS):
        entries = [pd.Timestamp(h) for h in sorted(pm.NSE_HOLIDAYS[year])]
        weekday = [h for h in entries if h.dayofweek < 5]
        in_span = [h for h in weekday if td[0] <= h <= td[-1]]
        confirmed = [h for h in in_span if h in observed_closures]
        unconfirmed = [h for h in in_span if h not in observed_closures]
        lines.append(f'    {year}: {len(entries)} table entries, {len(weekday)} on weekdays, '
                     f'{len(in_span)} inside the panel span, {len(confirmed)} confirmed closed '
                     f'by the panel')
        if unconfirmed:
            lines.append(f'      WARN table says holiday but the panel shows trading: '
                         f'{", ".join(str(h.date()) for h in unconfirmed)}')
    return lines


def assign_buckets(events, preholiday_dates):
    """Add boolean columns B1/B2/B3 to `events`, keyed off the filing timestamp.

    B1 AFTER-HOURS : sec_of_day >= 15:30:00 OR sec_of_day < 09:00:00, OR the
                     filing landed on a Saturday/Sunday at ANY clock time.
                     The weekend clause implements the spec's "(incl. weekends
                     mapped to the next trading day's population)": a Saturday
                     11:00 filing is maximally low-attention even though its
                     clock time sits inside market hours. Its E-date is already
                     mapped forward by event_study.process_symbol.
    B2 FRIDAY-PM   : dayofweek == Friday AND 12:00:00 <= sec_of_day < 15:30:00.
                     Disjoint from B1 by construction (the clock band lies
                     strictly inside market hours and Friday is not a weekend).
    B3 PRE-HOLIDAY : filing DATE is the last trading day before a non-weekend
                     market closure (panel-derived calendar, construction note
                     (d)), at any clock time. B3 may overlap B1/B2 -- the spec
                     declares three independent tests, each against its own
                     same-category control, not a partition. (Note the overlap
                     is real for B3: a pre-closure day can itself be a special
                     Saturday session, which also puts the filing in B1.)
    """
    ts = pd.DatetimeIndex(events['ann_ts'])
    sec = ts.hour * 3600 + ts.minute * 60 + ts.second
    dow = ts.dayofweek
    fdate = ts.normalize()

    is_weekend = dow >= 5
    in_clock_band = (sec >= SEC_1530) | (sec < SEC_0900)

    events['sec_of_day'] = sec
    events['file_dow'] = dow
    events['B1_AFTER_HOURS'] = in_clock_band | is_weekend
    events['B2_FRIDAY_PM'] = (dow == 4) & (sec >= SEC_1200) & (sec < SEC_1530)
    events['B3_PRE_HOLIDAY'] = pd.Series(fdate.isin(preholiday_dates), index=events.index).values
    # diagnostics for the weekend clause's marginal contribution
    events['_weekend_only_B1'] = is_weekend & ~in_clock_band
    return events


# --------------------------------------------------------------------------
# Inference
# --------------------------------------------------------------------------

def cluster_robust_t(values):
    """Cluster-robust pooled t on an already-clustered series -- frozen formula.

    `values` is one number per ISO-week cluster (see weekly_diff_series). The
    formula is the confirmation study's verbatim:
        pooled_mean = mean(values)
        pooled_se   = std(values, ddof=1) / sqrt(n)
        t           = pooled_mean / pooled_se
    i.e. a plain one-sample t-test where the unit of observation is the WEEKLY
    CLUSTER value, not the individual event. Rationale (the PEAD lesson, per
    spec): many announcements in the same calendar week are correlated -- they
    are NOT hundreds of independent draws.

    Returns (t, n_weeks); t is NaN if fewer than 2 clusters or zero variance.
    """
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    n = len(v)
    if n < 2:
        return np.nan, n
    sd = v.std(ddof=1)
    if not np.isfinite(sd) or sd == 0:
        return np.nan, n
    return float(v.mean() / (sd / np.sqrt(n))), n


def weekly_diff_series(bucket_ev, control_ev, value_col='excess_5d'):
    """Per-ISO-week pooled WITHIN-CATEGORY bucket-minus-control difference.

    See CONSTRUCTION NOTES (c) in the module docstring -- this is the
    reviewer-flagged construction.

    Cell key is (iso_week, era, category); a cell contributes only if BOTH
    arms have >= 1 event in it, so every difference is taken between events
    that share a week, an era AND a category. Weekly value:
        D_w = sum_c n_bucket(c,w) * (mean_bucket(c,w) - mean_control(c,w))
              / sum_c n_bucket(c,w)
    Returns (D:pd.Series indexed by iso_week, n_bucket_used, n_bucket_total).
    """
    keys = ['iso_week', 'era', 'category']
    n_bucket_total = len(bucket_ev)
    if n_bucket_total == 0 or len(control_ev) == 0:
        return pd.Series(dtype=float), 0, n_bucket_total
    b = bucket_ev.groupby(keys, observed=True)[value_col].agg(['mean', 'size'])
    c = control_ev.groupby(keys, observed=True)[value_col].agg(['mean', 'size'])
    j = b.join(c, how='inner', lsuffix='_b', rsuffix='_c')
    if len(j) == 0:
        return pd.Series(dtype=float), 0, n_bucket_total
    j = j.reset_index()
    j['d'] = j['mean_b'] - j['mean_c']
    j['wd'] = j['d'] * j['size_b']
    g = j.groupby('iso_week')
    D = g['wd'].sum() / g['size_b'].sum()
    return D, int(j['size_b'].sum()), n_bucket_total


def pooled_diff(bucket_ev, control_ev, value_col):
    """Category-pooled bucket-minus-control mean difference, weighted by bucket count.

    See CONSTRUCTION NOTES (b). Returns (diff, n_bucket, n_control, n_cats_used);
    diff is NaN when no category has events in both arms.
    """
    if len(bucket_ev) == 0 or len(control_ev) == 0:
        return np.nan, len(bucket_ev), len(control_ev), 0
    b = bucket_ev.groupby('category', observed=True)[value_col].agg(['mean', 'size'])
    c = control_ev.groupby('category', observed=True)[value_col].agg(['mean', 'size'])
    j = b.join(c, how='inner', lsuffix='_b', rsuffix='_c')
    if len(j) == 0 or j['size_b'].sum() == 0:
        return np.nan, len(bucket_ev), len(control_ev), 0
    diff = float(np.average(j['mean_b'] - j['mean_c'], weights=j['size_b']))
    return diff, len(bucket_ev), len(control_ev), len(j)


# --------------------------------------------------------------------------
# Reporting helpers
# --------------------------------------------------------------------------

def report_timestamp_granularity(ann, label):
    """Spec-required check: how much real intraday resolution do the filing
    timestamps actually carry? Midnight-exact stamps are blind to B1/B2."""
    ts = pd.DatetimeIndex(ann['sort_date'])
    n = len(ts)
    if n == 0:
        out(f'  {label}: N=0')
        return
    sec = ts.hour * 3600 + ts.minute * 60 + ts.second
    n_midnight = int((sec == 0).sum())
    n_nonzero_min = int((ts.minute != 0).sum())
    n_nonzero_sec = int((ts.second != 0).sum())
    out(f'  {label}: N={n:,}')
    out(f'    midnight-exact (00:00:00, blind to B1/B2)... {n_midnight:>9,}  ({n_midnight/n:.4%})')
    out(f'    non-zero minute field (real intraday stamp). {n_nonzero_min:>9,}  ({n_nonzero_min/n:.2%})')
    out(f'    non-zero second field....................... {n_nonzero_sec:>9,}  ({n_nonzero_sec/n:.2%})')
    if n_midnight / n > 0.05:
        out('    *** WARNING: >5% of filings are midnight-only. B1/B2 cannot see their true')
        out('    *** filing time; those events are classified purely by the date part. ***')
    else:
        out('    -> timestamps carry genuine intraday resolution; B1/B2 are not capped by')
        out('       midnight-only stamping.')


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main(smoke=False, smoke_month='2024-01'):
    t0 = time.time()

    out('=' * 88)
    out('FILING-TIMING METADATA STUDY')
    out('=' * 88)
    out('Frozen spec: docs/superpowers/specs/2026-07-28-filing-timing-design.md')
    out('Status: APPROVED & FROZEN (user, 2026-07-28).')
    out('')
    out('HYPOTHESIS: companies choose WHEN to file. Low-attention timing marks news')
    out('  management and predicts negative drift BEYOND the filing category. Category-CONTENT')
    out('  drift is already dead here (0/3, 2026-07-28 confirmation study); this tests TIMING as')
    out('  an orthogonal, within-category-controlled signal.')
    out('')
    out('TIMING BUCKETS (frozen -- exactly three, no additions; assigned from the FILING')
    out('timestamp `sort_date` (date+time), never from the event date E):')
    for b in BUCKETS:
        out(f'  {b:<16} {BUCKET_DESC[b]}')
    out('')
    out('METHOD (frozen):')
    out('  - Join/E-date/entry/liquidity-gate/CAR conventions reused VERBATIM from event_study.py')
    out('    (imported, not reimplemented): E = announcement date advanced to the next trading day')
    out('    (or the day after if filed post-15:30 IST); forward window starts at the E+1 open, one')
    out('    full trading day after E; liquidity gate 60d median turnover>2e7 and close>20 at E.')
    out('  - excess_5d = event car_5d MINUS the same-era ALL-ANNOUNCEMENT baseline (mean car_5d')
    out('    across every joined category event in that era) -- construction identical to the')
    out('    2026-07-27 confirmation study. excess_20d same construction, SECONDARY only.')
    out('  - Comparison is ALWAYS bucket-vs-control WITHIN the same category and era. Control for')
    out('    bucket B = every OTHER filing of the SAME category in the SAME era. NEVER')
    out('    bucket-vs-zero (that would re-discover the dead category effect through a proxy).')
    out(f'  - Pooled across categories with >= {MIN_ARM_EVENTS} events in BOTH arms, weighted by')
    out('    bucket-arm event count. Category screen is applied ONCE on the full all-era')
    out('    population per bucket and then FROZEN across eras (construction note (a)).')
    out('  - Inference: cluster-robust by ISO calendar week on the DIFFERENCE construction --')
    out('    cell=(week,era,category) needing BOTH arms present; D_w = bucket-count-weighted mean')
    out('    of within-cell (mean bucket excess - mean same-category control excess); then')
    out('    t = mean(D_w)/(std(D_w,ddof=1)/sqrt(n_weeks)), the confirmation study formula')
    out('    verbatim. Full rationale + the rejected alternative: construction note (c) in this')
    out('    script\'s module docstring. FLAGGED FOR REVIEWER ATTENTION.')
    out('  - Eras (by event date E): ' + ' / '.join(l for l, _, _ in ERA_BOUNDS))
    out('')
    out('VERDICT (frozen, per bucket, ALL must hold to PASS):')
    out(f'  Criterion 1: pooled bucket-minus-control 5d difference <= {DIFF_5D_FLOOR:.2%} in EVERY era.')
    out(f'  Criterion 2: pooled (all-eras) cluster-corrected t <= {CLUSTER_T_THRESH} '
        f'(Bonferroni, 3 declared buckets).')
    out('  Declared test count: 3 (one per bucket). 20d differences are SECONDARY information,')
    out('  never verdict-bearing. A bucket that fails stays failed -- no threshold nudging.')
    out('')
    out('CAVEATS (stated before results, per spec):')
    out('  - Timestamps may reflect exchange dissemination time, not company decision time. The')
    out('    tradeable signal is the public timestamp either way.')
    out('  - Some categories legitimately cluster after-hours (board-meeting outcomes). The')
    out('    within-category control absorbs level differences; categories with <100 events in')
    out('    either arm are excluded from the pool (counts reported below).')
    out('  - In-sample exploration on mined announcement data. Any PASS gets the forward')
    out('    kill-criterion as its real out-of-sample test -- never an automatic deploy.')
    out('  - The same-era all-announcement baseline cancels algebraically inside every')
    out('    bucket-minus-control difference (same era, same offset, both arms). It is retained')
    out('    because the spec freezes it and it makes per-arm LEVELS comparable to the')
    out('    confirmation study; it moves no verdict here.')
    out('')

    if smoke:
        out('*' * 88)
        out(f'*** SMOKE-TEST MODE (--smoke): announcement population restricted to {smoke_month} only. ***')
        out('*** Two of three eras will show N=0 by construction -> criterion 1 fails trivially. ***')
        out('*** THIS IS NOT A VERDICT RUN. Self-check plumbing only. ***')
        out('*' * 88)
        out('')

    print('Loading price universe...', file=sys.stderr)
    price_data = es.load_prices()
    print(f'  {len(price_data)} symbols loaded ({time.time()-t0:.1f}s)', file=sys.stderr)

    print('Building equal-weight universe daily-return series...', file=sys.stderr)
    all_dates, P = es.build_universe_returns(price_data)
    es.P_GLOBAL = P  # process_symbol reads this module-global from event_study's own namespace
    all_dates_values = all_dates.values
    print(f'  {len(all_dates)} calendar dates spanned ({time.time()-t0:.1f}s)', file=sys.stderr)

    print('Loading announcements...', file=sys.stderr)
    ann = load_announcements(smoke=smoke, smoke_month=smoke_month)
    n_total = len(ann)
    print(f'  {n_total} raw announcement rows ({time.time()-t0:.1f}s)', file=sys.stderr)

    joined = ann[ann['symbol'].isin(price_data.keys())].copy()
    n_joined = len(joined)
    # Category = raw 'desc', UNPOOLED (no >=1000-event OTHER bucket like event_study.py's cell
    # table): the within-category control needs exact category identity, and the all-announcement
    # baseline needs every joined event.
    joined['category'] = joined['desc']

    print('Processing events per symbol (vectorized, reusing event_study.process_symbol)...', file=sys.stderr)
    frames = []
    total_counts = dict(n_events=0, e_not_found=0, insufficient_fwd=0,
                        liquidity_dropped=0, bad_price=0, survivors=0)
    for sym, grp in joined.groupby('symbol', sort=False):
        pdf = price_data.get(sym)
        if pdf is None:
            continue
        out_df, counts = es.process_symbol(sym, grp, pdf, all_dates_values)
        for k in ('n_events', 'e_not_found', 'insufficient_fwd', 'liquidity_dropped', 'bad_price'):
            total_counts[k] += counts.get(k, 0)
        total_counts['survivors'] += counts.get('survivors', 0)
        if out_df is not None:
            frames.append(out_df)

    if frames:
        events = pd.concat(frames, ignore_index=True)
    else:
        events = pd.DataFrame(columns=['symbol', 'ann_ts', 'category', 'E_date', 'entry_date',
                                       'turnover_at_E', 'year', 'car_2d', 'car_5d', 'car_20d'])
    print(f'  {len(events)} final analysis events ({time.time()-t0:.1f}s)', file=sys.stderr)

    out('EVENT FUNNEL:')
    out(f'  raw announcement rows............ {n_total:>10,}')
    out(f'  dropped: symbol not in price universe {n_total - n_joined:>7,}')
    out(f'  joined (symbol matched)........... {n_joined:>10,}')
    out(f'  dropped: E not found within 5 cal days {total_counts["e_not_found"]:>6,}')
    out(f'  dropped: insufficient forward data (need E+1..E+21) {total_counts["insufficient_fwd"]:>6,}')
    out(f'  dropped: liquidity gate (turnover>2e7 & close>20 at E) {total_counts["liquidity_dropped"]:>6,}')
    out(f'  dropped: bad/non-finite price data {total_counts["bad_price"]:>6,}')
    out(f'  FINAL analysis events............. {len(events):>10,}')
    out('')

    out('FILING-TIMESTAMP GRANULARITY (spec check -- what B1/B2 can actually see):')
    report_timestamp_granularity(ann, 'raw announcement population')
    if len(events):
        report_timestamp_granularity(events.rename(columns={'ann_ts': 'sort_date'}),
                                     'final analysis population')
    out('')

    if len(events) == 0:
        out('NO EVENTS SURVIVED THE JOIN -- nothing further to compute.')
        results_path = OUT_TXT_SMOKE if smoke else OUT_TXT
        results_path.write_text('\n'.join(OUT_LINES) + '\n', encoding='utf-8')
        print(f'\n[saved output to {results_path}]', file=sys.stderr)
        return

    events['era'] = assign_era(events['E_date'])
    n_out_of_era = int(events['era'].isna().sum())
    if n_out_of_era:
        out(f'NOTE: {n_out_of_era} events fell outside the three declared eras (E_date out of')
        out('  2020-01..2026-07 range) and are excluded from era-bucketed and baseline stats.')
        out('')
    events = events[events['era'].notna()].copy()

    iso = events['E_date'].dt.isocalendar()
    events['iso_week'] = iso['year'].astype(int) * 100 + iso['week'].astype(int)

    baseline_5d = events.groupby('era')['car_5d'].mean()
    baseline_20d = events.groupby('era')['car_20d'].mean()
    events['excess_5d'] = events['car_5d'] - events['era'].map(baseline_5d)
    events['excess_20d'] = events['car_20d'] - events['era'].map(baseline_20d)

    out('SAME-ERA ALL-ANNOUNCEMENT BASELINE (mean abnormal return, every joined category event):')
    for label, _, _ in ERA_BOUNDS:
        era_all = events[events['era'] == label]
        n = len(era_all)
        if n == 0:
            out(f'  {label}: N=0')
            continue
        out(f'  {label}: N={n:6,d}  baseline_car_5d={era_all["car_5d"].mean():+.3%}  '
            f'baseline_car_20d={era_all["car_20d"].mean():+.3%}')
    out('')

    # ---------------- closure calendar (B3) ----------------
    pre_map, hol_diags = build_preholiday_dates(all_dates)
    td_all = pd.DatetimeIndex(all_dates)
    out('B3 CLOSURE CALENDAR (panel-derived):')
    out('  INSTRUMENT NOTE -- SPEC AMENDMENT 2026-07-28 (user-approved before the verdict run; see')
    out('  the [AMENDED 2026-07-28] block on the B3 bullet of the frozen spec, and construction')
    out('  note (d) in this script). B3 no longer reads parity_monitor.NSE_HOLIDAYS (2026 only,')
    out('  which left B3 blind in eras 1-2). Closures are now derived from the price panel\'s own')
    out('  observed trading calendar: a WEEKDAY inside the panel span with no trading data is a')
    out('  market closure, and B3 = the observed trading day immediately before it. Weekend-only')
    out('  gaps still do not count. DATA-SUFFICIENCY fix only -- the B3 concept, both other')
    out('  buckets, thresholds, windows, eras, controls, screens and clustering are untouched.')
    out(f'  panel trading calendar: {len(td_all):,} trading days spanning '
        f'{td_all[0].date()}..{td_all[-1].date()}')
    n_old_source = sum(1 for y in pm.NSE_HOLIDAYS for h in pm.NSE_HOLIDAYS[y]
                       if pd.Timestamp(h).dayofweek < 5 and td_all[0] <= pd.Timestamp(h) <= td_all[-1])
    out(f'  RESOLVED PRE-CLOSURE TRADING DAYS: {len(pre_map)}   '
        f'(the pre-amendment NSE_HOLIDAYS source could resolve only {n_old_source}, all in 2026)')
    if pre_map:
        by_year = pd.Series(1, index=pd.DatetimeIndex(sorted(pre_map))).groupby(
            lambda d: d.year).size()
        out('  per year: ' + '  '.join(f'{y}:{int(k)}' for y, k in by_year.items()))
        out('  full pre-closure date list (auditable; 8 per line):')
        dates_sorted = sorted(pre_map)
        for i in range(0, len(dates_sorted), 8):
            out('    ' + '  '.join(f'{d.date()}({d.day_name()[:2]})' for d in dates_sorted[i:i + 8]))
    for line in hol_diags:
        out(line)
    for line in nse_holiday_crosscheck(all_dates, pre_map):
        out(line)
    out('')

    # ---------------- bucket assignment ----------------
    events = assign_buckets(events, set(pre_map))

    n_ev = len(events)
    out('BUCKET POPULATIONS (final analysis events, assigned from the filing timestamp):')
    for b in BUCKETS:
        nb = int(events[b].sum())
        out(f'  {b:<16} N={nb:>8,}  ({nb/n_ev:6.2%} of {n_ev:,})   [{BUCKET_DESC[b]}]')
    n_wk_only = int(events['_weekend_only_B1'].sum())
    out(f'  B1 detail: {n_wk_only:,} of the B1 events qualify ONLY via the weekend clause')
    out('    (filed Sat/Sun 09:00:00-15:29:59, i.e. outside the 15:30-08:59 clock band).')
    out('  Bucket overlap (buckets are 3 independent tests, NOT a partition):')
    for i, bi in enumerate(BUCKETS):
        for bj in BUCKETS[i + 1:]:
            ov = int((events[bi] & events[bj]).sum())
            out(f'    {bi} & {bj}: {ov:,}')
    out('')

    # ---------------- per-bucket verdicts ----------------
    out('=' * 88)
    out('PER-BUCKET VERDICTS')
    out('=' * 88)
    out('')

    for b in BUCKETS:
        out(f'BUCKET: {b}  [{BUCKET_DESC[b]}]')
        in_b = events[b].values
        bucket_all = events[in_b]
        control_all = events[~in_b]

        # --- (a) category screen, frozen on the full all-era population ---
        cb = bucket_all['category'].value_counts()
        cc = control_all['category'].value_counts()
        cats = sorted(set(cb[cb >= MIN_ARM_EVENTS].index) & set(cc[cc >= MIN_ARM_EVENTS].index))
        n_cats_all = events['category'].nunique()
        out(f'  Category pool (>= {MIN_ARM_EVENTS} events in BOTH arms, frozen on the all-era '
            f'population):')
        out(f'    qualifying categories: {len(cats)} of {n_cats_all} present   '
            f'excluded: {n_cats_all - len(cats)}')
        if not cats:
            out('    NO CATEGORY QUALIFIES -> the pooled difference is undefined.')
            out(f'  Criterion 1 (diff <= {DIFF_5D_FLOOR:.2%} in EVERY era): FAIL (no pool)')
            out(f'  Criterion 2 (pooled cluster t <= {CLUSTER_T_THRESH}): FAIL (no pool)')
            out(f'  BUCKET VERDICT: FAIL')
            out('')
            continue

        catset = set(cats)
        bucket_p = bucket_all[bucket_all['category'].isin(catset)].copy()
        control_p = control_all[control_all['category'].isin(catset)].copy()
        out(f'    pooled events: bucket N={len(bucket_p):,}  control N={len(control_p):,}   '
            f'(dropped by the screen: bucket {len(bucket_all)-len(bucket_p):,}, '
            f'control {len(control_all)-len(control_p):,})')
        top = cb[cb.index.isin(catset)].head(10)
        out('    top qualifying categories by bucket count:')
        for cat, k in top.items():
            out(f'      {int(k):>7,}  bucket / {int(cc[cat]):>7,} control   {cat}')
        if len(cats) > 10:
            out(f'      ... and {len(cats)-10} more')

        # --- criterion 1: per-era pooled difference ---
        crit1_pass = True
        out('  PER-ERA POOLED WITHIN-CATEGORY DIFFERENCE (bucket minus same-category control):')
        for label, _, _ in ERA_BOUNDS:
            be = bucket_p[bucket_p['era'] == label]
            ce = control_p[control_p['era'] == label]
            d5, nb, nc, ncat = pooled_diff(be, ce, 'excess_5d')
            d20, _, _, _ = pooled_diff(be, ce, 'excess_20d')
            if not np.isfinite(d5):
                out(f'    Era {label}: N_bucket={nb:>6,} N_control={nc:>7,}  '
                    f'diff_5d=N/A  (no category with events in both arms -- criterion 1 cannot pass)')
                crit1_pass = False
                continue
            ok = d5 <= DIFF_5D_FLOOR
            crit1_pass = crit1_pass and ok
            out(f'    Era {label}: N_bucket={nb:>6,} N_control={nc:>7,} cats={ncat:>3}  '
                f'diff_5d={d5:+.3%}  diff_20d={d20:+.3%}  '
                f'(<= {DIFF_5D_FLOOR:.2%} ? {"yes" if ok else "no"})')
        out(f'  Criterion 1 (5d diff <= {DIFF_5D_FLOOR:.2%} in EVERY era): '
            f'{"PASS" if crit1_pass else "FAIL"}')

        # --- criterion 2: cluster-robust t on the weekly difference series ---
        D, n_used, n_tot = weekly_diff_series(bucket_p, control_p, 'excess_5d')
        t_pooled, n_weeks = cluster_robust_t(D.values)
        retention = (n_used / n_tot) if n_tot else float('nan')
        out('  CLUSTER-ROBUST t ON THE WEEKLY DIFFERENCE SERIES (construction note (c)):')
        out(f'    weekly clusters used: {n_weeks:,}   bucket events retained: {n_used:,}/{n_tot:,} '
            f'({retention:.1%})')
        out('    (a bucket event is dropped only if its (week, era, category) cell has NO')
        out('     same-week same-category control -- it then has no within-week counterfactual)')
        if np.isnan(t_pooled):
            out(f'    pooled cluster-robust t: N/A (n_weeks={n_weeks} -- insufficient clusters or '
                f'zero variance)')
            crit2_pass = False
        else:
            out(f'    mean weekly diff={D.mean():+.4%}  sd={D.std(ddof=1):.4%}  '
                f't={t_pooled:+.3f}')
            crit2_pass = t_pooled <= CLUSTER_T_THRESH
        # secondary, non-verdict-bearing
        D20, _, _ = weekly_diff_series(bucket_p, control_p, 'excess_20d')
        t20, nw20 = cluster_robust_t(D20.values)
        out(f'    SECONDARY (never verdict-bearing): 20d weekly-diff t='
            f'{"N/A" if np.isnan(t20) else f"{t20:+.3f}"} (n_weeks={nw20:,})')
        out(f'  Criterion 2 (pooled cluster t <= {CLUSTER_T_THRESH}): '
            f'{"PASS" if crit2_pass else "FAIL"}')

        overall = crit1_pass and crit2_pass
        out(f'  BUCKET VERDICT: {"PASS" if overall else "FAIL"}')
        if overall:
            out('    -> per spec: becomes a CANDIDATE avoid-filter rule requiring a design doc plus a')
            out('       forward kill-criterion (like the results-miss gate), via a separate reviewed')
            out('       deploy. NEVER automatic.')
        out('')

    if smoke:
        out('*' * 88)
        out('*** SMOKE-TEST MODE -- verdicts above are NOT meaningful (one-month population). ***')
        out('*** Full study writes to filing_timing_results.txt instead. ***')
        out('*' * 88)

    out('')
    out(f'Total runtime: {time.time()-t0:.1f}s')

    results_path = OUT_TXT_SMOKE if smoke else OUT_TXT
    results_path.write_text('\n'.join(OUT_LINES) + '\n', encoding='utf-8')
    print(f'\n[saved output to {results_path}]', file=sys.stderr)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Filing-timing metadata study (frozen spec).')
    parser.add_argument('--smoke', action='store_true',
                        help='Self-check only: restrict to one month of announcements.')
    parser.add_argument('--smoke-month', default='2024-01', metavar='YYYY-MM',
                        help='Month used by --smoke (default 2024-01). Plumbing knob only; the '
                             'full study never reads it.')
    args = parser.parse_args()
    main(smoke=args.smoke, smoke_month=args.smoke_month)
