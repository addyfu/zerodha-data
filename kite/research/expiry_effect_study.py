"""Pre-registered falsification study: NSE monthly F&O expiry effect on the
equity universe, per regime era. FROZEN QUESTION (see task spec) — do not
re-cut eras or redefine expiry after seeing results.

Universe daily-return series: equal-weight, clipped +/-25%/day, built exactly
like kite/research/universe_lab.py's `proxy` (same load/dedupe conventions).

Monthly expiry definition (approximation, documented):
  - 2015-01 .. 2025-08 (inclusive): last THURSDAY of the calendar month.
  - 2025-09 onward: last TUESDAY of the calendar month (NSE's Sept-2025 switch).
  - Holiday adjustment: if the calendar last-Thursday/Tuesday is not a trading
    day, expiry is approximated as the latest trading day ON OR BEFORE that
    calendar date (mirrors NSE's real "expiry moves to previous trading day"
    holiday rule, using the actual observed trading calendar from the data
    as ground truth for which days trade).

Eras (frozen):
  E1 2015-01-01 .. 2019-12-31   (Thursday expiry)
  E2 2020-01-01 .. 2022-12-31   (Thursday expiry)
  E3 2023-01-01 .. 2025-08-31   (Thursday expiry)
  E4 2025-09-01 .. last date    (Tuesday expiry)
  First 3 eras (E1-E3) are the ones the frozen interpretation rule checks.

Frozen interpretation rule: an effect is "present" only if |t| >= 2.5 in at
least 2 of E1/E2/E3 with the SAME sign. Weekly test is exploratory context,
not part of the frozen daily-effect verdict.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / 'data' / 'daily_universe'
OUT_TXT = ROOT / 'kite' / 'research' / 'expiry_effect_study.txt'

ERA3_END = pd.Timestamp('2025-08-31')
ERA4_START = pd.Timestamp('2025-09-01')

ERAS = [
    ('2015-2019',      pd.Timestamp('2015-01-01'), pd.Timestamp('2019-12-31'), 3),  # Thu
    ('2020-2022',      pd.Timestamp('2020-01-01'), pd.Timestamp('2022-12-31'), 3),  # Thu
    ('2023-Aug2025',   pd.Timestamp('2023-01-01'), ERA3_END, 3),                    # Thu
    ('Sep2025-Jul2026',ERA4_START, pd.Timestamp('2026-12-31'), 1),                  # Tue
]
FIRST3 = {'2015-2019', '2020-2022', '2023-Aug2025'}


def load_ew_returns():
    """Equal-weight universe daily return series, clipped +/-25%. Mirrors
    universe_lab.load()/main() loader conventions (dedupe on datetime,
    tz-naive normalized date index, clip to tame bad ticks/splits)."""
    closes = {}
    for f in sorted(DATA_DIR.glob('*_day.csv')):
        sym = f.name[:-8]
        df = pd.read_csv(f, parse_dates=['datetime'])
        df['date'] = df.datetime.dt.tz_localize(None).dt.normalize()
        df = df.set_index('date')[['close']]
        df = df[~df.index.duplicated(keep='last')]
        if len(df) < 300:
            continue
        closes[sym] = df['close']
    print(f'universe loaded: {len(closes)} symbols', flush=True)
    all_dates = pd.DatetimeIndex(sorted(set().union(*[s.index for s in closes.values()])))
    idx = pd.DataFrame({s: c for s, c in closes.items()}).reindex(all_dates)
    ret = idx.pct_change().clip(-0.25, 0.25).mean(axis=1, skipna=True)
    ret = ret.dropna()
    return ret  # Series indexed by trading date (the observed trading calendar)


def last_calendar_weekday_of_month(year, month, weekday):
    """weekday: 0=Mon .. 3=Thu, 1=Tue"""
    next_month = pd.Timestamp(year=year, month=month, day=28) + pd.Timedelta(days=4)
    last_day = next_month - pd.Timedelta(days=next_month.day)
    offset = (last_day.weekday() - weekday) % 7
    return last_day - pd.Timedelta(days=offset)


def build_expiry_calendar(trading_days):
    """Returns dict date->era_name for expiry days, plus expiry-1/+1 sets,
    keyed by era, using the OBSERVED trading calendar as ground truth."""
    start, end = trading_days[0], trading_days[-1]
    months = pd.period_range(start, end, freq='M')
    expiries = []  # (calendar_target, actual_expiry_date, weekday_used)
    for p in months:
        y, m = p.year, p.month
        target = (last_calendar_weekday_of_month(y, m, 3) if p.to_timestamp('M') < ERA4_START
                  else last_calendar_weekday_of_month(y, m, 1))
        pos = trading_days.searchsorted(target, side='right') - 1
        if pos < 0:
            continue
        actual = trading_days[pos]
        if actual.year != y or actual.month != m:
            # rolled back out of the month entirely (long holiday cluster) -- skip, log
            continue
        expiries.append((target, actual, pos))
    return expiries  # list of (calendar_target, actual_trading_date, position_in_trading_days)


def era_of(date):
    for name, s, e, _ in ERAS:
        if s <= date <= e:
            return name
    return None


def tstat_2samp(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    t, p = stats.ttest_ind(a, b, equal_var=False)
    return t, p


def fmt_pct(x):
    return f'{x*100:6.3f}'


def main():
    lines = []

    def emit(s=''):
        print(s)
        lines.append(s)

    ret = load_ew_returns()
    trading_days = ret.index
    emit('=' * 100)
    emit('NSE MONTHLY F&O EXPIRY EFFECT -- PRE-REGISTERED FALSIFICATION STUDY')
    emit('=' * 100)
    emit(f'Universe: {DATA_DIR.name} equal-weight daily-return proxy, clipped +/-25%/day')
    emit(f'Trading days observed: {len(trading_days)}  ({trading_days[0].date()} .. {trading_days[-1].date()})')
    emit('Expiry def: last Thursday of month through Aug-2025; last Tuesday from Sep-2025 (NSE switch).')
    emit('Holiday adjustment: if calendar last-Thu/Tue is not a trading day, roll back to the latest')
    emit('  trading day on/before it (approximation of NSE\'s real prior-day expiry-shift rule).')
    emit('')

    expiries = build_expiry_calendar(trading_days)
    emit(f'Monthly expiries resolved: {len(expiries)} (expected ~{len(pd.period_range(trading_days[0], trading_days[-1], freq="M"))})')
    n_holiday_shifted = sum(1 for tgt, act, _ in expiries if tgt != act)
    emit(f'  of which holiday-shifted off the calendar Thu/Tue: {n_holiday_shifted}')
    emit('')

    # tag every trading day
    label = pd.Series('other', index=trading_days)
    expiry_era_tag = {}  # date -> era name (of the month it belongs to)
    n = len(trading_days)
    for tgt, act, pos in expiries:
        e = era_of(act)
        if e is None:
            continue
        label.loc[act] = 'expiry'
        expiry_era_tag[act] = e
        if pos - 1 >= 0:
            d1 = trading_days[pos - 1]
            if label.loc[d1] == 'other':
                label.loc[d1] = 'expiry-1'
        if pos + 1 < n:
            d2 = trading_days[pos + 1]
            if label.loc[d2] == 'other':
                label.loc[d2] = 'expiry+1'

    era_tag = pd.Series([era_of(d) for d in trading_days], index=trading_days)

    # ---------------- Section 1: daily categories per era ----------------
    emit('-' * 100)
    emit('SECTION 1: daily returns by category, per era  (mean%/day, std%/day, N)')
    emit('-' * 100)
    header = f'{"Era":18} | {"Category":9} | {"N":5} | {"Mean%":8} | {"Std%":8}'
    emit(header)
    emit('-' * len(header))

    cat_order = ['expiry', 'expiry-1', 'expiry+1', 'other']
    era_names = [e[0] for e in ERAS]
    stored = {}  # (era,cat) -> series of returns
    for name in era_names + ['POOLED']:
        if name == 'POOLED':
            mask_era = pd.Series(True, index=trading_days)
        else:
            mask_era = era_tag == name
        for cat in cat_order:
            m = mask_era & (label == cat)
            vals = ret[m]
            stored[(name, cat)] = vals
            if len(vals) == 0:
                emit(f'{name:18} | {cat:9} | {0:5} | {"n/a":>8} | {"n/a":>8}')
                continue
            emit(f'{name:18} | {cat:9} | {len(vals):5} | {fmt_pct(vals.mean()):>8} | {fmt_pct(vals.std()):>8}')
        emit('')

    # ---------------- Section 2: weekly ----------------
    emit('-' * 100)
    emit('SECTION 2: expiry WEEK (Mon->expiry day) vs non-expiry week, per era')
    emit('  weekly return = compounded daily return over the window; daily vol = std of daily rets in window')
    emit('-' * 100)
    iso = pd.Series([d.isocalendar()[:2] for d in trading_days], index=trading_days)
    expiry_dates_set = set(act for _, act, _ in expiries)

    weekly_rows = {name: {'exp': [], 'exp_vol': [], 'oth': [], 'oth_vol': []} for name in era_names + ['POOLED']}
    for wk, idxs in pd.Series(trading_days, index=trading_days).groupby(iso):
        days = idxs.values
        days = pd.DatetimeIndex(sorted(days))
        exp_in_week = [d for d in days if d in expiry_dates_set]
        # era assignment for the week: era of its first day (weeks don't cross frozen era
        # boundaries except possibly at the 3 era-boundary weeks, negligible edge case)
        wk_era = era_of(days[0])
        if wk_era is None:
            continue
        if exp_in_week:
            edate = exp_in_week[0]
            window = days[days <= edate]
            if len(window) < 2:
                continue
            r = ret.loc[window]
            wk_ret = (1 + r).prod() - 1
            wk_vol = r.std()
            weekly_rows[wk_era]['exp'].append(wk_ret)
            weekly_rows[wk_era]['exp_vol'].append(wk_vol)
            weekly_rows['POOLED']['exp'].append(wk_ret)
            weekly_rows['POOLED']['exp_vol'].append(wk_vol)
        else:
            if len(days) < 2:
                continue
            r = ret.loc[days]
            wk_ret = (1 + r).prod() - 1
            wk_vol = r.std()
            weekly_rows[wk_era]['oth'].append(wk_ret)
            weekly_rows[wk_era]['oth_vol'].append(wk_vol)
            weekly_rows['POOLED']['oth'].append(wk_ret)
            weekly_rows['POOLED']['oth_vol'].append(wk_vol)

    header2 = (f'{"Era":18} | {"N_exp_wk":8} | {"N_oth_wk":8} | {"MeanWk%_exp":11} | {"MeanWk%_oth":11} '
               f'| {"t_wk":7} | {"p":7} | {"vol%_exp":8} | {"vol%_oth":8}')
    emit(header2)
    emit('-' * len(header2))
    weekly_t = {}
    for name in era_names + ['POOLED']:
        e, o = weekly_rows[name]['exp'], weekly_rows[name]['oth']
        ev, ov = weekly_rows[name]['exp_vol'], weekly_rows[name]['oth_vol']
        if len(e) < 2 or len(o) < 2:
            emit(f'{name:18} | {len(e):8} | {len(o):8} | {"n/a":>11} | {"n/a":>11} | {"n/a":>7} | {"n/a":>7} | {"n/a":>8} | {"n/a":>8}')
            continue
        t, p = tstat_2samp(e, o)
        weekly_t[name] = (t, p)
        emit(f'{name:18} | {len(e):8} | {len(o):8} | {fmt_pct(np.mean(e)):>11} | {fmt_pct(np.mean(o)):>11} '
             f'| {t:7.3f} | {p:7.4f} | {fmt_pct(np.mean(ev)):>8} | {fmt_pct(np.mean(ov)):>8}')
    emit('')

    # ---------------- Section 3: t-tests expiry-day vs other days ----------------
    emit('-' * 100)
    emit('SECTION 3: t-test, expiry DAY vs OTHER days (Welch, unequal var) -- PRIMARY frozen test')
    emit('-' * 100)
    header3 = f'{"Era":18} | {"N_exp":6} | {"N_oth":7} | {"Mean%_exp":9} | {"Mean%_oth":9} | {"t":8} | {"p":8}'
    emit(header3)
    emit('-' * len(header3))
    day_t = {}
    for name in era_names + ['POOLED']:
        e = stored[(name, 'expiry')]
        o = stored[(name, 'other')]
        if len(e) < 2 or len(o) < 2:
            emit(f'{name:18} | {len(e):6} | {len(o):7} | {"n/a":>9} | {"n/a":>9} | {"n/a":>8} | {"n/a":>8}')
            continue
        t, p = tstat_2samp(e.values, o.values)
        day_t[name] = (t, p)
        emit(f'{name:18} | {len(e):6} | {len(o):7} | {fmt_pct(e.mean()):>9} | {fmt_pct(o.mean()):>9} | {t:8.3f} | {p:8.4f}')
    emit('')

    # supplementary (not part of frozen rule): expiry-1 and expiry+1 vs other
    emit('SUPPLEMENTARY (exploratory, NOT part of frozen verdict): expiry-1 / expiry+1 vs other')
    header4 = f'{"Era":18} | {"Cat":9} | {"N":6} | {"Mean%":9} | {"t vs other":11} | {"p":8}'
    emit(header4)
    for name in era_names + ['POOLED']:
        o = stored[(name, 'other')]
        for cat in ('expiry-1', 'expiry+1'):
            v = stored[(name, cat)]
            if len(v) < 2 or len(o) < 2:
                continue
            t, p = tstat_2samp(v.values, o.values)
            emit(f'{name:18} | {cat:9} | {len(v):6} | {fmt_pct(v.mean()):>9} | {t:11.3f} | {p:8.4f}')
    emit('')

    # ---------------- Verdict ----------------
    emit('=' * 100)
    emit('VERDICT (frozen rule: effect "present" iff |t| >= 2.5 in >=2 of the first 3 eras, same sign)')
    emit('=' * 100)

    def verdict(tdict, label_txt):
        first3 = [(name, tdict[name]) for name in era_names if name in FIRST3 and name in tdict]
        hits = [(name, t) for name, (t, p) in first3 if abs(t) >= 2.5]
        signs = set(np.sign(t) for _, t in hits)
        present = len(hits) >= 2 and len(signs) == 1
        emit(f'{label_txt}:')
        for name, (t, p) in [(n, tdict[n]) for n in era_names if n in tdict]:
            flag = ' <-- |t|>=2.5' if abs(t) >= 2.5 else ''
            emit(f'    {name:18}: t={t:7.3f}  p={p:7.4f}{flag}')
        emit(f'  -> effect PRESENT: {present}  (hits in first-3 eras: {len(hits)}, signs: {signs})')
        emit('')
        return present

    d_present = verdict(day_t, 'Daily expiry-day mean-return effect (expiry vs other days)')
    w_present = verdict(weekly_t, 'Weekly expiry-week mean-return effect (expiry-week vs other weeks)')

    emit('Prior-literature expectation: volatility differences plausible, directional mean-return')
    emit('edge NOT expected to survive post-2023 regime changes (Bank Nifty Thu->2023 shift,')
    emit('Sep-2025 Tue-expiry switch). Compare std% columns above (Section 1) across eras for the')
    emit('volatility question; the frozen |t|>=2.5 rule above addresses the MEAN-return question only.')
    emit('')
    emit(f'Daily mean-return expiry effect across study: {"PRESENT" if d_present else "NOT PRESENT (falsified)"}')
    emit(f'Weekly mean-return expiry-week effect across study: {"PRESENT" if w_present else "NOT PRESENT (falsified)"}')

    OUT_TXT.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'\n[saved] {OUT_TXT}')


if __name__ == '__main__':
    main()
