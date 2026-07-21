"""Test A -- Surprise-Conditioned PEAD (frozen pre-registered spec).

Spec: docs/superpowers/specs/2026-07-22-anomaly-batch2-design.md
      (Test A + section 0.1 common methodology). Implemented faithfully,
      no parameter tuning -- whatever prints is the answer.

Reuses kite/research/event_study.py's verified conventions directly
(imported, not re-derived): price loading (load_prices), the E-day mapping
with the after-15:30 rule, the equal-weight universe return series with
+/-25% daily clipping (build_universe_returns), the prefix-product market
leg helper (market_leg), and the era bucketing (era_of).

Method summary (frozen):
1. Events = announcements whose desc/category field == 'Financial Result
   Updates', joined to the 679-symbol price universe (data/daily_universe).
   (The announcements CSVs have no separate 'category' column -- 'desc' IS
   the category field, exactly as in event_study.py.)
2. E = first trading day on/after the announcement date; if the
   announcement timestamp is after 15:30 IST, E = first trading day
   strictly after the announcement date (identical rule to event_study.py).
   E must be found within 5 calendar days of the announcement (same bound
   event_study.py uses), and E-1 must exist in that symbol's price series.
3. Liquidity gate AT E: 60d median turnover (close*volume) > Rs 2cr and
   close > Rs 20 (identical thresholds to event_study.py / spec 0.1).
4. Reaction (price-SUE proxy), using ONLY data through close[E]:
     R = (close[E]/close[E-1] - 1) - (universe EW return on E's date)
   The market term here is the single-day universe return on date E (not
   compounded), since R is itself a single-day reaction measure.
5. THE LEAKAGE WALL: the signal (R) is fully determined by close[E] and
   earlier. The holding window begins at open[E+1] and never touches E.
     CAR_20 = (close[E+20]/open[E+1] - 1) - universe compounded return over
              the SAME E+1..E+20 span (prefix-product approach, byte-for-
              byte the same market_leg() helper event_study.py uses).
     CAR_60 likewise, computed ONLY where E+60 exists in that symbol's
     price series (recent events near the end of the sample may lack 60
     forward trading days -- N_60 is reported separately from N_20).
   E never appears inside a drift window: the drift stock leg starts at
   open[E+1], and the drift market leg is market_leg(P, g[E+1]-1, g[E+k]),
   i.e. compounds from the close-of-E+1-minus-one-day forward -- it does
   not include E's own daily return.
6. Buckets -- FIXED absolute thresholds, NOT sample-relative ranks:
     POSITIVE: R > +0.02   NEGATIVE: R < -0.02   MIDDLE: otherwise.
7. Costs: net CAR_20 = CAR_20 - 0.009 (round-trip delivery+slippage, spec
   0.1), computed ONLY for the tradeable POSITIVE-bucket long. NEGATIVE is
   untradeable (no overnight retail shorts) and MIDDLE is excluded from
   trading by construction -- neither gets a net figure.
8. Clustering: events are grouped into calendar-week cohorts by the ISO
   (year, week) of E. Primary inference = t-stat computed on COHORT MEAN
   CAR_20 (each cohort is one observation, equally weighted). The naive
   per-event t-stat is also reported, labeled 'optimistic'.
9. Era = E's calendar year, bucketed 2020-2022 / 2023-2024 / 2025-2026
   (identical era_of() convention to event_study.py, imported directly).

KNOWN DATA LIMITATION (found during implementation; NOT corrected, since the
spec is frozen and amendments require a dated decision-log entry): the
announcements archive's desc label 'Financial Result Updates' effectively
disappears after 2025-Q1 (1663-2149 rows/quarter every quarter 2020-2024,
then 2147 in 2025-Q1, then ~0 every quarter after). This looks like an NSE/
data-pipeline taxonomy change -- quarterly-result disclosures appear to
migrate to other desc labels (e.g. 'Outcome of Board Meeting', 'Clarification
- Financial Results') from 2025-Q2 onward. Those labels are NOT the
pre-registered category and are deliberately NOT included here. Consequently
the 2025-2026 era has very few (in practice, ~zero to a handful) surviving
events under the literal, frozen filter -- reported as-is below.

Usage: python -W ignore kite/research/pead_conditioned.py
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kite.research.event_study import load_prices, build_universe_returns, market_leg, era_of  # noqa: E402

ANN_DIR = ROOT / 'data' / 'announcements'
OUT_CSV = Path(__file__).resolve().parent / 'pead_events.csv'

CATEGORY = 'Financial Result Updates'
MIN_TURNOVER = 2e7
MIN_PRICE = 20.0
LATE_CUTOFF_SEC = 15 * 3600 + 30 * 60  # 15:30:00 IST, identical to event_study.py
MAX_CAL_DAYS_TO_E = 5                   # identical to event_study.py
POS_THRESH = 0.02
NEG_THRESH = -0.02
ROUND_TRIP_COST = 0.009                 # spec 0.1: delivery + 0.2%/side slippage
POS_CAR_THRESH = 0.01                   # criterion 1
POS_N_THRESH = 300                      # criterion 3
COHORT_T_THRESH = 2.0                   # criterion 5
ERAS = ['2020-2022', '2023-2024', '2025-2026']
BUCKETS = ['POSITIVE', 'MIDDLE', 'NEGATIVE']


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def load_announcements_filtered():
    files = sorted(ANN_DIR.glob('ann_*.csv'))
    frames = []
    for f in files:
        d = pd.read_csv(f, usecols=['sort_date', 'symbol', 'desc'], dtype={'symbol': str, 'desc': str})
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    df['sort_date'] = pd.to_datetime(df['sort_date'])
    n_total = len(df)
    fin = df[df['desc'] == CATEGORY].copy()
    fin = fin.rename(columns={'sort_date': 'ann_ts'})
    fin['category'] = CATEGORY
    return fin.drop(columns=['desc']), n_total


# --------------------------------------------------------------------------
# Per-symbol vectorized event processing
# --------------------------------------------------------------------------

def process_symbol(sym, grp, pdf, all_dates_values, u_ret_values, P):
    dates = pdf.index.values
    open_ = pdf['open'].values
    close_ = pdf['close'].values
    turn_med = pdf['turn_med'].values
    n = len(dates)
    sym_to_global = np.searchsorted(all_dates_values, dates)  # exact-match positions

    sd = grp['ann_ts']
    ann_date = sd.dt.normalize().values
    sec_of_day = (sd.dt.hour * 3600 + sd.dt.minute * 60 + sd.dt.second).values
    late = sec_of_day > LATE_CUTOFF_SEC
    lower_bound = ann_date + late.astype('timedelta64[D]')

    pos = np.searchsorted(dates, lower_bound, side='left')
    found = pos < n
    e_date_candidate = np.where(found, dates[np.minimum(pos, n - 1)], np.datetime64('NaT'))
    within5 = found & (e_date_candidate <= ann_date + np.timedelta64(MAX_CAL_DAYS_TO_E, 'D'))

    n_events = len(grp)
    n_e_not_found = int((~within5).sum())

    has_prev = within5 & (pos >= 1)                # E-1 must exist
    n_no_prev = int((within5 & ~has_prev).sum())

    has_fwd20 = has_prev & (pos + 20 < n)           # need E+1 .. E+20 to exist
    n_insufficient_fwd = int((has_prev & ~has_fwd20).sum())

    safe_e = np.clip(pos, 0, n - 1)
    liquidity_ok = has_fwd20 & (turn_med[safe_e] > MIN_TURNOVER) & (close_[safe_e] > MIN_PRICE)
    n_liquidity_dropped = int((has_fwd20 & ~liquidity_ok).sum())

    survivors = np.where(liquidity_ok)[0]
    counts = dict(n_events=n_events, e_not_found=n_e_not_found, no_prev_day=n_no_prev,
                  insufficient_fwd=n_insufficient_fwd, liquidity_dropped=n_liquidity_dropped,
                  survivors=len(survivors))

    if len(survivors) == 0:
        return None, counts

    ep = pos[survivors]
    prev_close = close_[ep - 1]
    close_E = close_[ep]
    entry_open = open_[ep + 1]
    close20 = close_[ep + 20]

    finite = (np.isfinite(prev_close) & (prev_close > 0) & np.isfinite(close_E) &
              np.isfinite(entry_open) & (entry_open > 0) & np.isfinite(close20))
    n_bad_price = int((~finite).sum())
    if not finite.all():
        survivors = survivors[finite]
        ep = ep[finite]
        prev_close = prev_close[finite]
        close_E = close_E[finite]
        entry_open = entry_open[finite]
        close20 = close20[finite]
    counts['bad_price'] = n_bad_price
    counts['survivors'] = len(survivors)
    if len(survivors) == 0:
        return None, counts

    # --- Reaction R: uses only data through close[E] ---
    stock_ret_E = close_E / prev_close - 1.0
    g_E = sym_to_global[ep]
    u_on_E = u_ret_values[g_E]
    R = stock_ret_E - u_on_E

    # --- Drift CAR_20: signal ends at close[E]; holding begins open[E+1] ---
    stock20 = close20 / entry_open - 1.0
    g1 = sym_to_global[ep + 1]
    g20 = sym_to_global[ep + 20]
    g1_minus1 = g1 - 1
    mkt20 = market_leg(P, g1_minus1, g20)
    car20 = stock20 - mkt20

    # --- Drift CAR_60, only where E+60 exists ---
    car60 = np.full(len(survivors), np.nan)
    has60 = (ep + 60) < n
    if has60.any():
        idx60 = np.where(has60)[0]
        close60 = close_[ep[idx60] + 60]
        fin60 = np.isfinite(close60)
        idx60 = idx60[fin60]
        if len(idx60):
            stock60 = close_[ep[idx60] + 60] / entry_open[idx60] - 1.0
            g60 = sym_to_global[ep[idx60] + 60]
            mkt60 = market_leg(P, g1_minus1[idx60], g60)
            car60[idx60] = stock60 - mkt60

    e_dates = dates[ep]
    entry_dates = dates[ep + 1]
    years = pd.DatetimeIndex(e_dates).year.values

    out = pd.DataFrame({
        'symbol': sym,
        'ann_ts': grp['ann_ts'].values[survivors],
        'category': grp['category'].values[survivors],
        'E_date': e_dates,
        'entry_date': entry_dates,
        'turnover_at_E': turn_med[ep],
        'year': years,
        'R': R,
        'car_20d': car20,
        'car_60d': car60,
    })
    return out, counts


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------

def bucket_of(r):
    return np.where(r > POS_THRESH, 'POSITIVE', np.where(r < NEG_THRESH, 'NEGATIVE', 'MIDDLE'))


def cohort_tstat(sub, car_col):
    d = sub.dropna(subset=[car_col])
    if len(d) == 0:
        return np.nan, 0
    cohort_means = d.groupby('week_cohort')[car_col].mean()
    n_cohorts = len(cohort_means)
    if n_cohorts < 2:
        return np.nan, n_cohorts
    m = cohort_means.mean()
    s = cohort_means.std(ddof=1)
    if not np.isfinite(s) or s == 0:
        return np.nan, n_cohorts
    t = m / (s / np.sqrt(n_cohorts))
    return t, n_cohorts


def naive_tstat(sub, car_col):
    x = sub[car_col].dropna().values
    n = len(x)
    if n < 2:
        return np.nan
    s = np.std(x, ddof=1)
    if s == 0:
        return np.nan
    return np.mean(x) / (s / np.sqrt(n))


def row_stats(sub, bucket):
    n20 = len(sub)
    car20 = sub['car_20d'].values
    mean20 = np.mean(car20) if n20 else np.nan
    median20 = np.median(car20) if n20 else np.nan
    pct_pos = 100.0 * np.mean(car20 > 0) if n20 else np.nan

    car60 = sub['car_60d'].dropna().values
    n60 = len(car60)
    mean60 = np.mean(car60) if n60 else np.nan

    t_cohort, n_cohorts = cohort_tstat(sub, 'car_20d')
    t_naive = naive_tstat(sub, 'car_20d')

    net_mean20 = (mean20 - ROUND_TRIP_COST) if (bucket == 'POSITIVE' and n20) else np.nan

    return dict(N=n20, N_cohorts=n_cohorts, N_60=n60,
                mean_car20=mean20, median_car20=median20, net_car20=net_mean20,
                mean_car60=mean60, pct_pos=pct_pos,
                t_cohort=t_cohort, t_naive_optimistic=t_naive)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    t0 = time.time()
    print('Loading price universe...')
    price_data = load_prices()
    print(f'  {len(price_data)} symbols loaded ({time.time()-t0:.1f}s)')

    print('Building equal-weight universe daily-return series (+/-25% clip)...')
    all_dates, P = build_universe_returns(price_data)
    all_dates_values = all_dates.values
    # Recover the raw (uncompounded) daily universe return from the prefix
    # product built by build_universe_returns -- exactly the same clipped
    # series, no re-derivation: u_ret[0] = P[0]-1, u_ret[i] = P[i]/P[i-1]-1.
    u_ret_values = np.empty_like(P)
    u_ret_values[0] = P[0] - 1.0
    u_ret_values[1:] = P[1:] / P[:-1] - 1.0
    print(f'  {len(all_dates)} calendar dates spanned ({time.time()-t0:.1f}s)')

    print(f"Loading announcements, filtering category == '{CATEGORY}'...")
    fin, n_total = load_announcements_filtered()
    n_cat = len(fin)
    print(f'  {n_total:,} raw announcement rows -> {n_cat:,} in category ({time.time()-t0:.1f}s)')

    joined = fin[fin['symbol'].isin(price_data.keys())].copy()
    n_joined = len(joined)
    n_not_priced = n_cat - n_joined
    print(f'  {n_joined:,} joined to price universe ({time.time()-t0:.1f}s)')

    print('Processing events per symbol (vectorized)...')
    frames = []
    total_counts = dict(n_events=0, e_not_found=0, no_prev_day=0, insufficient_fwd=0,
                         liquidity_dropped=0, bad_price=0, survivors=0)
    for sym, grp in joined.groupby('symbol', sort=False):
        pdf = price_data.get(sym)
        if pdf is None:
            continue
        out, counts = process_symbol(sym, grp, pdf, all_dates_values, u_ret_values, P)
        for k in ('n_events', 'e_not_found', 'no_prev_day', 'insufficient_fwd',
                  'liquidity_dropped', 'bad_price'):
            total_counts[k] += counts.get(k, 0)
        total_counts['survivors'] += counts.get('survivors', 0)
        if out is not None:
            frames.append(out)

    events = pd.concat(frames, ignore_index=True)
    print(f'  {len(events):,} final analysis events ({time.time()-t0:.1f}s)')

    events['era'] = events['year'].apply(era_of)
    events['bucket'] = bucket_of(events['R'].values)
    iso = pd.DatetimeIndex(events['E_date']).isocalendar()
    iso_year = iso['year'].values
    iso_week = iso['week'].values
    events['week_cohort'] = [f'{y}-W{w:02d}' for y, w in zip(iso_year, iso_week)]
    events['net_car_20d'] = np.where(events['bucket'] == 'POSITIVE',
                                      events['car_20d'] - ROUND_TRIP_COST, np.nan)

    events = events.sort_values(['E_date', 'symbol']).reset_index(drop=True)
    events.to_csv(OUT_CSV, index=False)

    # --- Report table: bucket x era, and bucket x ALL ---
    rows = []
    for bucket in BUCKETS:
        for era in ERAS + ['ALL']:
            if era == 'ALL':
                sub = events[events['bucket'] == bucket]
            else:
                sub = events[(events['bucket'] == bucket) & (events['era'] == era)]
            st = row_stats(sub, bucket)
            rows.append(dict(bucket=bucket, era=era, **st))
    table = pd.DataFrame(rows)

    dt = time.time() - t0
    print()
    print('=' * 100)
    print('TEST A -- SURPRISE-CONDITIONED PEAD -- RESULTS')
    print('=' * 100)
    print(f'Runtime: {dt:.1f}s')
    print()
    print('METHODOLOGY NOTES:')
    print(f"  - category filter: desc == '{CATEGORY}' (exact match, the announcements CSVs have no")
    print("    separate 'category' column; 'desc' IS the category field, as in event_study.py).")
    print('  - E-day mapping, 5-calendar-day search bound, and liquidity gate are reused unchanged')
    print('    from event_study.py. Universe benchmark is the same +/-25%-clipped EW daily series.')
    print('  - R (reaction) uses ONLY data through close[E]: close[E]/close[E-1]-1 minus the single-')
    print('    day universe EW return on date E.')
    print('  - LEAKAGE WALL: CAR_20/CAR_60 stock leg starts at open[E+1]; the market leg compounds')
    print('    from E+1 through E+k via the prefix-product market_leg() helper -- E never enters the')
    print('    drift window on either leg.')
    print('  - Buckets are FIXED thresholds (R>+2%/R<-2%), not sample-relative ranks.')
    print('  - Net CAR_20 (cost = 0.9% round-trip) is reported ONLY for the POSITIVE bucket (the sole')
    print('    tradeable long); MIDDLE/NEGATIVE show no net figure (untradeable / excluded by design).')
    print('  - Cohort = ISO (year, week) of E. Primary t-stat is computed on cohort MEAN CAR_20 (one')
    print("    observation per cohort); 'optimistic' is the naive per-event t-stat, for contrast only.")
    print()
    print('EVENT FUNNEL:')
    print(f'  raw announcement rows.................... {n_total:>10,}')
    print(f"  category == '{CATEGORY}'....... {n_cat:>10,}")
    print(f'  dropped: symbol not in price universe.... {n_not_priced:>10,}')
    print(f'  joined (symbol matched)................... {n_joined:>10,}')
    print(f'  dropped: E not found within 5 cal days... {total_counts["e_not_found"]:>10,}')
    print(f'  dropped: no E-1 (prior trading day)...... {total_counts["no_prev_day"]:>10,}')
    print(f'  dropped: insufficient fwd data (need E+1..E+20) {total_counts["insufficient_fwd"]:>6,}')
    print(f'  dropped: liquidity gate (turnover>2e7 & close>20 at E) {total_counts["liquidity_dropped"]:>6,}')
    print(f'  dropped: bad/non-finite price data........ {total_counts["bad_price"]:>10,}')
    print(f'  FINAL analysis events..................... {len(events):>10,}')
    print()

    fmt_cols = ['bucket', 'era', 'N', 'N_cohorts', 'mean_car20', 'median_car20', 'net_car20',
                'N_60', 'mean_car60', 'pct_pos', 't_cohort', 't_naive_optimistic']
    disp = table[fmt_cols].copy()
    for c in ['mean_car20', 'median_car20', 'net_car20', 'mean_car60']:
        disp[c] = disp[c].map(lambda v: f'{v:+.4f}' if pd.notna(v) else '   n/a')
    for c in ['pct_pos']:
        disp[c] = disp[c].map(lambda v: f'{v:.1f}%' if pd.notna(v) else ' n/a')
    for c in ['t_cohort', 't_naive_optimistic']:
        disp[c] = disp[c].map(lambda v: f'{v:+.2f}' if pd.notna(v) else '  n/a')
    print('RESULTS TABLE (bucket x era, and bucket x ALL eras pooled):')
    print(disp.to_string(index=False))
    print()
    print(f'Full per-event rows saved to: {OUT_CSV}')
    print()

    # --- Verdict ---
    def get_row(bucket, era):
        r = table[(table['bucket'] == bucket) & (table['era'] == era)]
        return r.iloc[0]

    pos_all = get_row('POSITIVE', 'ALL')
    mid_all = get_row('MIDDLE', 'ALL')
    neg_all = get_row('NEGATIVE', 'ALL')

    # Criterion 1: POSITIVE-bucket mean abnormal CAR_20, net of costs, >= +1.0% (pooled across eras)
    c1_value = pos_all['net_car20']
    c1_pass = pd.notna(c1_value) and (c1_value >= POS_CAR_THRESH)

    # Criterion 2: gross mean CAR_20 positive in >=2 of 3 eras (see decision log below: gross, not
    # net -- criterion 1 is the only criterion that names "net of costs" explicitly).
    era_gross = {}
    for era in ERAS:
        r = get_row('POSITIVE', era)
        era_gross[era] = r['mean_car20']
    n_era_positive = sum(1 for v in era_gross.values() if pd.notna(v) and v > 0)
    c2_pass = n_era_positive >= 2

    # Criterion 3: N(positive bucket) >= 300, pooled across eras
    c3_value = pos_all['N']
    c3_pass = c3_value >= POS_N_THRESH

    # Criterion 4: monotonicity of gross mean CAR_20, pooled across eras
    c4_pass = (pd.notna(pos_all['mean_car20']) and pd.notna(mid_all['mean_car20']) and
               pd.notna(neg_all['mean_car20']) and
               pos_all['mean_car20'] > mid_all['mean_car20'] > neg_all['mean_car20'])

    # Criterion 5: cohort-level t-stat >= 2.0, POSITIVE bucket, pooled across eras
    c5_value = pos_all['t_cohort']
    c5_pass = pd.notna(c5_value) and (c5_value >= COHORT_T_THRESH)

    overall_pass = c1_pass and c2_pass and c3_pass and c4_pass and c5_pass

    print('=' * 100)
    print('FROZEN VERDICT (PASS requires ALL 5; criteria per '
          'docs/superpowers/specs/2026-07-22-anomaly-batch2-design.md Test A):')
    print('=' * 100)
    print(f"1. POSITIVE net CAR_20 (pooled, all eras) >= +1.0%: "
          f"{c1_value:+.4f} -> {'PASS' if c1_pass else 'FAIL'}")
    era_str = ', '.join(f"{e}: {'n/a' if pd.isna(v) else f'{v:+.4f}'}" for e, v in era_gross.items())
    print(f"2. Positive (gross) in >=2 of 3 eras: {n_era_positive}/3 eras positive ({era_str}) "
          f"-> {'PASS' if c2_pass else 'FAIL'}")
    print(f"3. N(positive bucket) >= 300 (pooled, all eras): {c3_value} "
          f"-> {'PASS' if c3_pass else 'FAIL'}")
    print(f"4. Monotonicity mean_CAR(POS) > mean_CAR(MID) > mean_CAR(NEG): "
          f"{pos_all['mean_car20']:+.4f} > {mid_all['mean_car20']:+.4f} > {neg_all['mean_car20']:+.4f} "
          f"-> {'PASS' if c4_pass else 'FAIL'}")
    print(f"5. Cohort t-stat (POSITIVE, pooled) >= 2.0: "
          f"{'n/a' if pd.isna(c5_value) else f'{c5_value:+.2f}'} -> {'PASS' if c5_pass else 'FAIL'}")
    print()
    print(f"OVERALL: {'PASS' if overall_pass else 'FAIL'} "
          f"({'all 5 criteria met' if overall_pass else 'at least one criterion failed'})")
    if not overall_pass:
        print('Per spec: failure -> tombstone. Any anomaly here is subject to the batch-2 meta-guard')
        print('(4 tests run together => >=1 lucky survivor expected by chance alone).')
    else:
        print('Per spec: survivors go to the incubator under the October Contract, full paper trial,')
        print('no exceptions -- a PASS here is NOT access to real money.')
    print()
    print(f'Total runtime: {time.time()-t0:.1f}s')


if __name__ == '__main__':
    main()
