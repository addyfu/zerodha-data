"""Phase 2 — Deterministic event study on corporate announcements (no LLM).

Pre-registered method: docs/superpowers/specs/2026-07-21-news-event-alpha-design.md
(Phase 2 section). Implemented faithfully, no parameter tuning.

Method summary (frozen):
1. Keep announcements whose symbol has a price file ("joined"). Event day E =
   first trading day (in that symbol's own price index) on/after the
   announcement date; if announcement time is after 15:30 IST, E = first
   trading day strictly after the announcement date. If E is not found within
   5 calendar days, drop.
2. Entry at E+1 open. Need E+1..E+21 to exist (20-day window headroom); drop
   otherwise.
3. Abnormal return = stock cumulative return (close[E+k]/open[E+1] - 1) minus
   equal-weight universe cumulative return over the same E+1..E+k span
   (universe daily returns clipped to +/-25%, same convention as
   universe_lab.py). Windows: E+2/E+5/E+20 close, all measured from the E+1
   open entry. Slight open-vs-close basis mismatch on the market leg for the
   E+1 day itself is accepted uniformly across all events (per spec).
4. Liquidity gate at E: 60d median turnover (close*volume) > 2e7 and close >
   20. Drop otherwise.
5. No market-cap data exists, so market-cap terciles are approximated with
   60d-median-turnover-at-E terciles (t1=smallest .. t3=largest), computed
   across the final analysis population. This substitution is a known
   limitation, noted here and in the printed output.
6. Era: E's calendar year bucketed into 2020-2022 / 2023-2024 / 2025-2026.
7. Cells = category(desc) x turnover-tercile x era. Category kept as its own
   label only if it has >=1000 events in the joined (symbol-matched) 368,480-
   event population; else pooled into 'OTHER'. This mapping is fixed on the
   joined population (before any E/liquidity/data drops) so category
   definitions do not drift with sample attrition.
8. Per cell x window (2d/5d/20d): N, mean CAR, median CAR, std, t-stat
   (mean/(std/sqrt(N))), % positive.
9. Benjamini-Hochberg FDR at q=10% across all cell x window tests (two-sided
   normal-approx p from the t-stat).
10. H1 verdict: FDR-survivor cells whose (category, tercile, 5d-window) mean
    CAR sign is shared by >=2 of the 3 eras, AND whose net edge after costs
    (net5 = |mean CAR_5d| - 0.009 round-trip cost) is >= 0.005, qualify.

Usage: python -W ignore kite/research/event_study.py
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

ROOT = Path(__file__).resolve().parents[2]
ANN_DIR = ROOT / 'data' / 'announcements'
PRICE_DIR = ROOT / 'data' / 'daily_universe'
OUT_CSV = Path(__file__).resolve().parent / 'event_study_results.csv'

MIN_TURNOVER = 2e7
MIN_PRICE = 20.0
LATE_CUTOFF_SEC = 15 * 3600 + 30 * 60  # 15:30:00 in seconds-since-midnight
MAX_CAL_DAYS_TO_E = 5
FWD_DAYS_NEEDED = 21  # need E+1 .. E+21 to all exist
CAT_MIN_COUNT = 1000
FDR_Q = 0.10
ROUND_TRIP_COST = 0.009  # 0.2% slippage x2 legs + ~0.5% delivery both legs
NET5_THRESH = 0.005
WINDOWS = (2, 5, 20)


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def load_prices():
    """Per-symbol OHLCV with 60d rolling median turnover, date-indexed."""
    data = {}
    for f in sorted(PRICE_DIR.glob('*_day.csv')):
        sym = f.name[:-8]
        df = pd.read_csv(f, parse_dates=['datetime'])
        df['date'] = df['datetime'].dt.tz_localize(None).dt.normalize()
        df = df.set_index('date')[['open', 'close', 'volume']]
        df = df[~df.index.duplicated(keep='last')].sort_index()
        if len(df) < FWD_DAYS_NEEDED + 2:
            continue
        df['turn_med'] = (df.close * df.volume).rolling(60).median()
        data[sym] = df
    return data


def load_announcements():
    files = sorted(ANN_DIR.glob('ann_*.csv'))
    frames = []
    for f in files:
        d = pd.read_csv(f, usecols=['sort_date', 'symbol', 'desc'], dtype={'symbol': str, 'desc': str})
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    df['sort_date'] = pd.to_datetime(df['sort_date'])
    return df


def build_universe_returns(price_data):
    """Equal-weight universe daily-return series + prefix compounding array.

    P[k] = prod_{i=0..k} (1 + u_ret[i]), with an implicit P[-1] = 1. So the
    compounded universe return over global date-positions [a, b] inclusive is
    P[b] / P[a-1] - 1 (P[-1] := 1).
    """
    all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in price_data.values()])))
    idx = pd.DataFrame({s: df.close for s, df in price_data.items()}).reindex(all_dates)
    u_ret = idx.pct_change().clip(-0.25, 0.25).mean(axis=1, skipna=True).fillna(0)
    P = (1.0 + u_ret.values).cumprod()
    return all_dates, P


def market_leg(P, g_start_minus1_pos, g_end_pos):
    """Compounded universe return over global positions [g_start_minus1_pos+1, g_end_pos]."""
    denom = np.where(g_start_minus1_pos >= 0, P[np.maximum(g_start_minus1_pos, 0)], 1.0)
    return P[g_end_pos] / denom - 1.0


# --------------------------------------------------------------------------
# Per-symbol vectorized event processing
# --------------------------------------------------------------------------

def process_symbol(sym, grp, pdf, all_dates_values):
    dates = pdf.index.values  # datetime64[ns], sorted ascending
    open_ = pdf['open'].values
    close_ = pdf['close'].values
    turn_med = pdf['turn_med'].values
    n = len(dates)
    sym_to_global = np.searchsorted(all_dates_values, dates)  # exact-match positions

    sd = grp['sort_date']
    ann_date = sd.dt.normalize().values  # datetime64[ns] at midnight
    sec_of_day = (sd.dt.hour * 3600 + sd.dt.minute * 60 + sd.dt.second).values
    late = sec_of_day > LATE_CUTOFF_SEC
    lower_bound = ann_date + late.astype('timedelta64[D]')

    pos = np.searchsorted(dates, lower_bound, side='left')
    found = pos < n
    e_date_candidate = np.where(found, dates[np.minimum(pos, n - 1)], np.datetime64('NaT'))
    within5 = found & (e_date_candidate <= ann_date + np.timedelta64(MAX_CAL_DAYS_TO_E, 'D'))

    n_events = len(grp)
    n_e_not_found = int((~within5).sum())

    e_pos = pos  # only meaningful where within5 True
    has_fwd = within5 & (e_pos + FWD_DAYS_NEEDED < n)
    n_insufficient_fwd = int((within5 & ~has_fwd).sum())

    safe_e = np.clip(e_pos, 0, n - 1)
    liquidity_ok = has_fwd & (turn_med[safe_e] > MIN_TURNOVER) & (close_[safe_e] > MIN_PRICE)
    n_liquidity_dropped = int((has_fwd & ~liquidity_ok).sum())

    survivors = np.where(liquidity_ok)[0]
    counts = dict(n_events=n_events, e_not_found=n_e_not_found,
                  insufficient_fwd=n_insufficient_fwd, liquidity_dropped=n_liquidity_dropped,
                  survivors=len(survivors))

    if len(survivors) == 0:
        return None, counts

    ep = e_pos[survivors]
    entry_open = open_[ep + 1]
    close2 = close_[ep + 2]
    close5 = close_[ep + 5]
    close20 = close_[ep + 20]

    finite = np.isfinite(entry_open) & np.isfinite(close2) & np.isfinite(close5) & np.isfinite(close20) & (entry_open > 0)
    n_bad_price = int((~finite).sum())
    if not finite.all():
        survivors = survivors[finite]
        ep = ep[finite]
        entry_open = entry_open[finite]
        close2 = close2[finite]
        close5 = close5[finite]
        close20 = close20[finite]
    counts['bad_price'] = n_bad_price
    counts['survivors'] = len(survivors)
    if len(survivors) == 0:
        return None, counts

    stock2 = close2 / entry_open - 1.0
    stock5 = close5 / entry_open - 1.0
    stock20 = close20 / entry_open - 1.0

    g1 = sym_to_global[ep + 1]
    g2 = sym_to_global[ep + 2]
    g5 = sym_to_global[ep + 5]
    g20 = sym_to_global[ep + 20]
    g1_minus1 = g1 - 1

    mkt2 = market_leg(P_GLOBAL, g1_minus1, g2)
    mkt5 = market_leg(P_GLOBAL, g1_minus1, g5)
    mkt20 = market_leg(P_GLOBAL, g1_minus1, g20)

    car2 = stock2 - mkt2
    car5 = stock5 - mkt5
    car20 = stock20 - mkt20

    e_dates = dates[ep]
    entry_dates = dates[ep + 1]
    years = pd.DatetimeIndex(e_dates).year.values

    out = pd.DataFrame({
        'symbol': sym,
        'ann_ts': grp['sort_date'].values[survivors],
        'category': grp['category'].values[survivors],
        'E_date': e_dates,
        'entry_date': entry_dates,
        'turnover_at_E': turn_med[safe_e[survivors]],
        'year': years,
        'car_2d': car2,
        'car_5d': car5,
        'car_20d': car20,
    })
    return out, counts


# --------------------------------------------------------------------------
# Stats / FDR / verdict
# --------------------------------------------------------------------------

def era_of(year):
    if 2020 <= year <= 2022:
        return '2020-2022'
    if 2023 <= year <= 2024:
        return '2023-2024'
    if 2025 <= year <= 2026:
        return '2025-2026'
    return 'OTHER_ERA'


def cell_stats(sub, col):
    x = sub[col].values
    n = len(x)
    mean = np.mean(x)
    median = np.median(x)
    std = np.std(x, ddof=1) if n > 1 else np.nan
    if n > 1 and std > 0:
        t = mean / (std / np.sqrt(n))
        p = 2 * norm.sf(abs(t))
    else:
        t, p = np.nan, np.nan
    pct_pos = 100.0 * np.mean(x > 0)
    return n, mean, median, std, t, p, pct_pos


def bh_fdr(pvals, q=FDR_Q):
    """Benjamini-Hochberg step-up. NaN p-values never survive."""
    pvals = np.asarray(pvals, dtype=float)
    m_valid_mask = ~np.isnan(pvals)
    survive = np.zeros(len(pvals), dtype=bool)
    valid_idx = np.where(m_valid_mask)[0]
    if len(valid_idx) == 0:
        return survive
    vp = pvals[valid_idx]
    m = len(vp)
    order = np.argsort(vp)
    sorted_p = vp[order]
    thresh = (np.arange(1, m + 1) / m) * q
    below = sorted_p <= thresh
    if below.any():
        k_max = np.max(np.where(below)[0])
        cutoff_p = sorted_p[k_max]
        survive[valid_idx] = vp <= cutoff_p
    return survive


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    t0 = time.time()
    print('Loading price universe...')
    price_data = load_prices()
    print(f'  {len(price_data)} symbols loaded ({time.time()-t0:.1f}s)')

    print('Building equal-weight universe daily-return series...')
    all_dates, P = build_universe_returns(price_data)
    global P_GLOBAL
    P_GLOBAL = P
    all_dates_values = all_dates.values
    print(f'  {len(all_dates)} calendar dates spanned ({time.time()-t0:.1f}s)')

    print('Loading announcements...')
    ann = load_announcements()
    n_total = len(ann)
    print(f'  {n_total} raw announcement rows ({time.time()-t0:.1f}s)')

    joined = ann[ann['symbol'].isin(price_data.keys())].copy()
    n_joined = len(joined)
    n_not_priced = n_total - n_joined

    # Category label frozen on the joined population (before any downstream drops).
    cat_counts = joined['desc'].value_counts()
    keep_cats = set(cat_counts[cat_counts >= CAT_MIN_COUNT].index)
    joined['category'] = joined['desc'].where(joined['desc'].isin(keep_cats), 'OTHER')

    # --- 5 hand-checkable E/entry examples, computed on the full joined set,
    # independent of later liquidity/data-availability drops. Vectorized per
    # symbol; stops as soon as all target patterns are found. ---
    DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    patterns = [
        ('weekday pre-15:30 -> same-day E',
         lambda ann_wd, late, e_wd: (~late) & (ann_wd < 5) & (e_wd == ann_wd)),
        ('Monday after 15:30 -> E=Tuesday',
         lambda ann_wd, late, e_wd: late & (ann_wd == 0) & (e_wd == 1)),
        ('Friday after 15:30 -> E=Monday',
         lambda ann_wd, late, e_wd: late & (ann_wd == 4) & (e_wd == 0)),
        ('Saturday -> E=Monday',
         lambda ann_wd, late, e_wd: (ann_wd == 5) & (e_wd == 0)),
        ('Sunday -> E=Monday',
         lambda ann_wd, late, e_wd: (ann_wd == 6) & (e_wd == 0)),
    ]
    picked = []
    found_kinds = set()
    for sym, grp in joined.groupby('symbol', sort=False):
        pdf = price_data.get(sym)
        if pdf is None:
            continue
        dates = pdf.index.values
        n = len(dates)
        sd = grp['sort_date']
        ann_date = sd.dt.normalize().values
        sec_of_day = (sd.dt.hour * 3600 + sd.dt.minute * 60 + sd.dt.second).values
        late = sec_of_day > LATE_CUTOFF_SEC
        lower_bound = ann_date + late.astype('timedelta64[D]')
        pos = np.searchsorted(dates, lower_bound, side='left')
        valid = (pos < n) & (pos + 1 < n)
        if not valid.any():
            continue
        ann_wd = pd.DatetimeIndex(ann_date).dayofweek.values
        e_wd = np.full(len(grp), -1)
        e_wd[valid] = pd.DatetimeIndex(dates[pos[valid]]).dayofweek.values

        for kind, fn in patterns:
            if kind in found_kinds:
                continue
            mask = fn(ann_wd, late, e_wd) & valid
            idxs = np.where(mask)[0]
            if len(idxs):
                i = idxs[0]
                p = pos[i]
                picked.append((kind, {
                    'symbol': sym,
                    'ann_ts': pd.Timestamp(sd.values[i]),
                    'E_date': pd.Timestamp(dates[p]),
                    'entry_date': pd.Timestamp(dates[p + 1]),
                }))
                found_kinds.add(kind)
        if len(found_kinds) >= len(patterns):
            break

    # --- Main event processing, grouped by symbol for vectorization ---
    print('Processing events per symbol (vectorized)...')
    frames = []
    total_counts = dict(n_events=0, e_not_found=0, insufficient_fwd=0,
                         liquidity_dropped=0, bad_price=0, survivors=0)
    for sym, grp in joined.groupby('symbol', sort=False):
        pdf = price_data.get(sym)
        if pdf is None:
            continue
        out, counts = process_symbol(sym, grp, pdf, all_dates_values)
        for k in ('n_events', 'e_not_found', 'insufficient_fwd', 'liquidity_dropped', 'bad_price'):
            total_counts[k] += counts.get(k, 0)
        total_counts['survivors'] += counts.get('survivors', 0)
        if out is not None:
            frames.append(out)

    events = pd.concat(frames, ignore_index=True)
    print(f'  {len(events)} final analysis events ({time.time()-t0:.1f}s)')

    events['era'] = events['year'].apply(era_of)
    events['tercile'] = pd.qcut(events['turnover_at_E'], 3, labels=['t1', 't2', 't3'])

    # --- Cells: category x tercile x era, per window ---
    rows = []
    for (cat, terc, era), sub in events.groupby(['category', 'tercile', 'era'], observed=True):
        for w in WINDOWS:
            n, mean, median, std, t, p, pct_pos = cell_stats(sub, f'car_{w}d')
            rows.append(dict(category=cat, tercile=terc, era=era, window=f'{w}d',
                              N=n, mean_car=mean, median_car=median, std_car=std,
                              t_stat=t, p_value=p, pct_positive=pct_pos))
    cells = pd.DataFrame(rows)
    cells['fdr_survivor'] = bh_fdr(cells['p_value'].values, FDR_Q)

    cells = cells.sort_values(['category', 'tercile', 'era', 'window']).reset_index(drop=True)
    cells.to_csv(OUT_CSV, index=False)

    # --- H1 verdict ---
    surv5 = cells[(cells['window'] == '5d') & cells['fdr_survivor']].copy()
    qualifying = []
    for _, row in surv5.iterrows():
        peer = cells[(cells['category'] == row['category']) & (cells['tercile'] == row['tercile']) &
                      (cells['window'] == '5d')]
        signs = np.sign(peer['mean_car'].values)
        signs = signs[signs != 0]
        if len(signs) == 0:
            continue
        this_sign = np.sign(row['mean_car'])
        n_same_sign = int((signs == this_sign).sum())
        era_consistent = n_same_sign >= 2
        net5 = abs(row['mean_car']) - ROUND_TRIP_COST
        qualifies = era_consistent and (net5 >= NET5_THRESH)
        if qualifies:
            era_cars = {r['era']: r['mean_car'] for _, r in peer.iterrows()}
            qualifying.append(dict(category=row['category'], tercile=row['tercile'], era=row['era'],
                                    n_eras_same_sign=n_same_sign, era_cars=era_cars,
                                    mean_car_5d=row['mean_car'], net5=net5, N=row['N']))

    # --- Report ---
    dt = time.time() - t0
    print()
    print('=' * 78)
    print('PHASE 2 EVENT STUDY — RESULTS')
    print('=' * 78)
    print(f'Runtime: {dt:.1f}s')
    print()
    print('METHODOLOGY NOTES:')
    print('  - Market-cap terciles NOT available; substituted with 60d-median-turnover-at-E')
    print('    terciles (t1=smallest..t3=largest), computed on the final analysis population.')
    print('  - Market leg for a window uses universe compounding from E+1 through E+k inclusive')
    print('    (close-to-close daily returns); stock leg uses close[E+k]/open[E+1]-1. The E+1 day')
    print('    therefore mixes an open-basis stock leg with a close-basis market leg for that one')
    print('    day -- a small, uniform mismatch applied identically to every event.')
    print('  - Category = announcement "desc" field, unmodified; categories with <1000 events in')
    print('    the joined (symbol-matched) population are pooled into OTHER. Mapping frozen on the')
    print('    joined population, before liquidity/data-availability drops.')
    print()
    print('EVENT FUNNEL:')
    print(f'  raw announcement rows............ {n_total:>10,}')
    print(f'  dropped: symbol not in price universe {n_not_priced:>7,}')
    print(f'  joined (symbol matched)........... {n_joined:>10,}')
    print(f'  dropped: E not found within 5 cal days {total_counts["e_not_found"]:>6,}')
    print(f'  dropped: insufficient forward data (need E+1..E+21) {total_counts["insufficient_fwd"]:>6,}')
    print(f'  dropped: liquidity gate (turnover>2e7 & close>20 at E) {total_counts["liquidity_dropped"]:>6,}')
    print(f'  dropped: bad/non-finite price data {total_counts["bad_price"]:>6,}')
    print(f'  FINAL analysis events............. {len(events):>10,}')
    print()
    print('HAND-CHECKABLE E / ENTRY EXAMPLES (announcement -> E -> entry):')
    for kind, row in picked[:5]:
        ann_ts = pd.Timestamp(row['ann_ts'])
        print(f'  [{kind}]')
        print(f'    symbol={row["symbol"]}  ann_ts={ann_ts} ({ann_ts.day_name()})'
              f'  -> E={row["E_date"].date()} ({row["E_date"].day_name()})'
              f'  -> entry={row["entry_date"].date()} ({row["entry_date"].day_name()})')
    print()
    n_cells = len(cells)
    n_survivors = int(cells['fdr_survivor'].sum())
    print(f'CELL TABLE: {n_cells} cell x window tests ({cells.groupby(["category","tercile","era"]).ngroups} '
          f'category x tercile x era cells x {len(WINDOWS)} windows)')
    print(f'BH-FDR (q={FDR_Q:.0%}) survivors: {n_survivors} / {n_cells}')
    print(f'Full cell table saved to: {OUT_CSV}')
    print()
    print(f'H1 QUALIFYING CELLS (FDR-survivor at 5d, era-sign-consistent >=2/3, net5 >= {NET5_THRESH:.1%}'
          f' after {ROUND_TRIP_COST:.1%} round-trip cost):')
    if not qualifying:
        print('  NONE. H1 dead by pre-registered criteria -> project ends at Phase 2 (per spec).')
    else:
        for q in qualifying:
            eras_str = ', '.join(f'{e}: {v:+.4f}' for e, v in sorted(q['era_cars'].items()))
            print(f"  category={q['category']!r} tercile={q['tercile']} anchor_era={q['era']} N={q['N']}")
            print(f"    era mean CAR_5d -> {eras_str}")
            print(f"    same-sign eras: {q['n_eras_same_sign']}/3  net5={q['net5']:+.4f}")
    print()
    print(f'Total runtime: {time.time()-t0:.1f}s')


if __name__ == '__main__':
    main()
