"""Announcement-Category Excess-Drift Confirmation study (pre-registered, FROZEN).

Frozen spec:
docs/superpowers/specs/2026-07-27-announcement-drift-confirmation-design.md
Status: APPROVED & FROZEN (user, 2026-07-28). No deviations from the spec below.

ORIGIN: kite/research/category_drift_map.txt (2026-07-22) exploratorily mined
event_study.py's cell table across all 40 categories on the full 2020-2026
history and flagged three categories whose EXCESS 5d drift (category CAR minus
the all-announcement baseline CAR) was consistently negative and >=0.20-0.25%
in magnitude: 'Monitoring Agency Report', 'Cessation', 'Related Party
Transactions'. The map's own note #5 says a rerun on the same data cannot
"confirm" anything -- this script adds the two genuinely new things the map
never computed: (1) per-era consistency with (2) cluster-robust (by ISO week)
inference, instead of the map's pooled naive t-stats.

CANDIDATES (fixed from the map, no additions permitted after the spec froze):
    Monitoring Agency Report, Cessation, Related Party Transactions
Dividend also cleared the map's excess screen but is explicitly EXCLUDED by
the frozen spec (ex-date mechanics contaminate the return window) -- it is
NOT evaluated here and must not be added later without a new spec.

METHOD (frozen, reusing event_study.py's join/E-date/entry/CAR conventions
VERBATIM via direct import -- see load_prices/build_universe_returns/
process_symbol below, all imported unmodified from event_study.py):
  1. Same join: announcement joined to the daily price panel (data/announcements
     x data/daily_universe), same E-date search, same E+1-open entry, same
     liquidity gate (60d median turnover > 2e7 and close > 20 at E), same
     20-day forward-data requirement. Leak hygiene: event day E = announcement
     date advanced to the next trading day (or the day after, if the
     announcement lands after 15:30 IST); the forward window ALWAYS starts at
     the E+1 open, one full trading day after E -- copied verbatim from
     event_study.py, not reimplemented.
  2. Per event: 5-day forward abnormal return = stock cumulative return vs the
     equal-weight universe cumulative return over the same span (car_5d from
     process_symbol). This MINUS the same-era all-announcement baseline (mean
     car_5d across every joined category's events in that era, not just the
     three candidates) = excess_5d. Same construction for car_20d -> excess_20d
     (20d is SECONDARY, reported only, never verdict-bearing per spec).
  3. Eras (frozen, by event date E): 2020-01..2021-12 / 2022-01..2023-12 /
     2024-01..2026-07.
  4. Inference: cluster-robust by calendar (ISO) week -- see cluster_robust_t()
     for the exact formula, documented in its docstring per spec requirement.
  5. Verdict per category (ALL must hold to PASS):
       Criterion 1: mean excess_5d <= -0.15% in EVERY one of the three eras.
       Criterion 2: pooled (all-eras-combined) cluster-robust t <= -2.4.
     A category that fails stays failed -- no threshold nudging after the
     fact, no window shopping across alternate cuts.

CAVEATS (stated before any results, per spec):
  - This is an in-sample robustness gate on data the exploratory map already
    saw in full. A PASS here is NOT out-of-sample confirmation; the forward
    kill-criterion after deployment (60 live blocks, realized 5d excess must
    stay negative or the category self-removes) carries the actual
    out-of-sample weight -- identical mechanism to the results-miss gate.
  - Dividend is excluded (see CANDIDATES above); not evaluated, not addable
    without a new pre-registered spec.

Usage:
    python kite/research/announcement_drift_confirmation.py            # full study
    python kite/research/announcement_drift_confirmation.py --smoke    # self-check only:
        restricts the announcement population to 2024-01 (one month), so two of
        the three eras have zero events by construction and criterion 1 fails
        trivially -- SMOKE OUTPUT IS NOT A VERDICT, self-check plumbing only.
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

OUT_TXT = Path(__file__).resolve().parent / 'announcement_drift_confirmation_results.txt'
OUT_TXT_SMOKE = Path(__file__).resolve().parent / 'announcement_drift_confirmation_results_smoke.txt'

CATEGORIES = ['Monitoring Agency Report', 'Cessation', 'Related Party Transactions']

# (label, start, end) -- inclusive, by event date E. Frozen.
ERA_BOUNDS = [
    ('2020-01..2021-12', pd.Timestamp('2020-01-01'), pd.Timestamp('2021-12-31')),
    ('2022-01..2023-12', pd.Timestamp('2022-01-01'), pd.Timestamp('2023-12-31')),
    ('2024-01..2026-07', pd.Timestamp('2024-01-01'), pd.Timestamp('2026-07-31')),
]

EXCESS_5D_FLOOR = -0.0015   # -0.15%, criterion 1
CLUSTER_T_THRESH = -2.4     # criterion 2, ~Bonferroni for 3 declared tests

OUT_LINES = []


def out(s=''):
    print(s)
    OUT_LINES.append(s)


# --------------------------------------------------------------------------
# Data loading -- announcements loader mirrors event_study.load_announcements()
# exactly (same usecols/dtype/parsing), parametrized only by which files to
# read so --smoke can restrict to a single month without touching event_study.py.
# --------------------------------------------------------------------------

def load_announcements(smoke=False):
    if smoke:
        files = sorted(es.ANN_DIR.glob('ann_2024-01.csv'))
    else:
        files = sorted(es.ANN_DIR.glob('ann_*.csv'))
    frames = []
    for f in files:
        d = pd.read_csv(f, usecols=['sort_date', 'symbol', 'desc'], dtype={'symbol': str, 'desc': str})
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    df['sort_date'] = pd.to_datetime(df['sort_date'])
    return df


def assign_era(e_date):
    """Vectorized era bucketing on event date E. Returns object array, None if out of range."""
    conditions = [(e_date >= start) & (e_date <= end) for _, start, end in ERA_BOUNDS]
    choices = [label for label, _, _ in ERA_BOUNDS]
    return pd.Series(np.select(conditions, choices, default=None), index=e_date.index)


def cluster_robust_t(sub, value_col):
    """Cluster-robust (by ISO calendar week) pooled t-stat -- frozen formula.

    Rationale (the PEAD lesson, per spec): many announcements in the same
    calendar week are correlated (sector news, earnings-season clustering,
    overlapping forward windows against the same universe realization) --
    they are NOT hundreds of independent draws. Treating each ISO week as one
    cluster and testing on the CLUSTER MEANS (not the raw events) is the
    frozen fix.

    Formula:
        cluster_mean_w = mean(value_col) over events whose E_date falls in
                          ISO week w
        pooled_mean     = mean(cluster_mean_w) across all n_weeks weeks
        pooled_se       = std(cluster_mean_w, ddof=1) / sqrt(n_weeks)
        t               = pooled_mean / pooled_se

    i.e. a plain one-sample t-test where the unit of observation is the
    WEEKLY CLUSTER MEAN, not the individual event. Returns (t, n_weeks);
    t is NaN if fewer than 2 clusters or zero cluster-mean variance.
    """
    wk_means = sub.groupby('iso_week')[value_col].mean()
    n_weeks = len(wk_means)
    if n_weeks < 2:
        return np.nan, n_weeks
    pooled_mean = wk_means.mean()
    pooled_std = wk_means.std(ddof=1)
    if not np.isfinite(pooled_std) or pooled_std == 0:
        return np.nan, n_weeks
    t = pooled_mean / (pooled_std / np.sqrt(n_weeks))
    return t, n_weeks


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main(smoke=False):
    t0 = time.time()

    out('=' * 88)
    out('ANNOUNCEMENT-CATEGORY EXCESS-DRIFT CONFIRMATION STUDY')
    out('=' * 88)
    out('Frozen spec: docs/superpowers/specs/2026-07-27-announcement-drift-confirmation-design.md')
    out('Status: APPROVED & FROZEN (user, 2026-07-28).')
    out('')
    out('CANDIDATES (fixed from category_drift_map.txt exploratory scan, no additions after freeze):')
    out(f'  {", ".join(CATEGORIES)}')
    out('  All three were WEAK on the exploratory map (<0.30%/5d excess -- below any tradeable')
    out('  edge after costs). The only deployment on the table is an addition to the announcement')
    out('  red-flag AVOID filter (zero trading cost, skip-the-stock semantics), never a trade.')
    out('  Dividend also cleared the map screen but is EXCLUDED by spec (ex-date contamination);')
    out('  not evaluated below, not addable without a new pre-registered spec.')
    out('')
    out('METHOD (frozen):')
    out('  - Join/E-date/entry/liquidity-gate/CAR conventions reused VERBATIM from event_study.py')
    out('    (imported, not reimplemented): E = announcement date advanced to next trading day')
    out('    (or the day after if announced post-15:30 IST); forward window starts at the E+1 open,')
    out('    one full trading day after E; liquidity gate 60d median turnover>2e7 and close>20 at E.')
    out('  - excess_5d = event car_5d MINUS same-era ALL-ANNOUNCEMENT baseline (mean car_5d across')
    out('    every joined category event in that era, not just the 3 candidates). excess_20d is the')
    out('    same construction, reported as SECONDARY info only, no verdict weight.')
    out('  - Eras (by event date E): 2020-01..2021-12 / 2022-01..2023-12 / 2024-01..2026-07.')
    out('  - Inference: cluster-robust by ISO calendar week (see cluster_robust_t() docstring in')
    out('    this script for the exact formula: pooled mean of weekly cluster means, se = std of')
    out('    weekly cluster means / sqrt(n_weeks)).')
    out('')
    out('VERDICT (frozen, per category, ALL must hold to PASS):')
    out(f'  Criterion 1: mean excess_5d <= {EXCESS_5D_FLOOR:.2%} in EVERY one of the three eras.')
    out(f'  Criterion 2: pooled (all-eras) cluster-robust t <= {CLUSTER_T_THRESH}.')
    out('  A category that fails stays failed -- no threshold nudging, no window shopping.')
    out('')
    out('CAVEATS (stated before results, per spec):')
    out('  - In-sample robustness gate on data the exploratory map already saw in full. A PASS')
    out('    here is NOT out-of-sample confirmation -- the post-deployment forward kill-criterion')
    out('    (60 live blocks, realized 5d excess must stay negative or the category self-removes)')
    out('    carries the actual out-of-sample weight, identical mechanism to the results-miss gate.')
    out('')

    if smoke:
        out('*' * 88)
        out('*** SMOKE-TEST MODE (--smoke): announcement population restricted to 2024-01 only. ***')
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
    ann = load_announcements(smoke=smoke)
    n_total = len(ann)
    print(f'  {n_total} raw announcement rows ({time.time()-t0:.1f}s)', file=sys.stderr)

    joined = ann[ann['symbol'].isin(price_data.keys())].copy()
    n_joined = len(joined)
    # Category = raw 'desc', UNPOOLED (no >=1000-event OTHER bucket like event_study.py's cell
    # table -- the all-announcement baseline needs every joined event, and the 3 candidates are
    # matched by their exact desc string per category_drift_map.txt).
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
    dt_proc = time.time() - t0
    print(f'  {len(events)} final analysis events ({dt_proc:.1f}s)', file=sys.stderr)

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

    out('=' * 88)
    out('PER-CATEGORY VERDICTS')
    out('=' * 88)
    out('')

    for cat in CATEGORIES:
        sub = events[events['category'] == cat].copy()
        out(f'CATEGORY: {cat}')
        crit1_pass = True
        for label, _, _ in ERA_BOUNDS:
            era_sub = sub[sub['era'] == label]
            n = len(era_sub)
            if n == 0:
                out(f'  Era {label}: N=0  (NO EVENTS -- criterion 1 cannot pass for this era)')
                crit1_pass = False
                continue
            m5 = era_sub['excess_5d'].mean()
            m20 = era_sub['excess_20d'].mean()
            ok = m5 <= EXCESS_5D_FLOOR
            crit1_pass = crit1_pass and ok
            out(f'  Era {label}: N={n:5,d}  mean excess_5d={m5:+.3%}  mean excess_20d={m20:+.3%}  '
                f'(<= {EXCESS_5D_FLOOR:.2%} ? {"yes" if ok else "no"})')
        out(f'  Criterion 1 (excess_5d <= {EXCESS_5D_FLOOR:.2%} in EVERY era): '
            f'{"PASS" if crit1_pass else "FAIL"}')

        t_pooled, n_weeks = cluster_robust_t(sub, 'excess_5d')
        crit2_pass = (not np.isnan(t_pooled)) and (t_pooled <= CLUSTER_T_THRESH)
        if np.isnan(t_pooled):
            out(f'  Pooled cluster-robust t: N/A (n_weeks={n_weeks}, n_events={len(sub)} -- '
                f'insufficient clusters)')
        else:
            out(f'  Pooled cluster-robust t (all eras, n_weeks={n_weeks}, n_events={len(sub)}): '
                f't={t_pooled:+.3f}')
        out(f'  Criterion 2 (pooled cluster t <= {CLUSTER_T_THRESH}): '
            f'{"PASS" if crit2_pass else "FAIL"}')

        overall = crit1_pass and crit2_pass
        out(f'  CATEGORY VERDICT: {"PASS" if overall else "FAIL"}')
        out('')

    if smoke:
        out('*' * 88)
        out('*** SMOKE-TEST MODE -- verdicts above are NOT meaningful (partial-era population). ***')
        out('*** Full study writes to announcement_drift_confirmation_results.txt instead. ***')
        out('*' * 88)

    out('')
    out(f'Total runtime: {time.time()-t0:.1f}s')

    results_path = OUT_TXT_SMOKE if smoke else OUT_TXT
    results_path.write_text('\n'.join(OUT_LINES) + '\n', encoding='utf-8')
    print(f'\n[saved output to {results_path}]', file=sys.stderr)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke', action='store_true',
                         help='Self-check only: restrict to 2024-01 announcements (one month).')
    args = parser.parse_args()
    main(smoke=args.smoke)
