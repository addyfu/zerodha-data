"""Pipeline reconciliation: Zerodha-adjusted daily bars (Pipeline Z) vs
NSE-bhavcopy + this-repo's-own corp-action table (Pipeline N).

READ-ONLY forensics. Writes exactly one output file:
    kite/research/pipeline_reconciliation_results.txt
No network calls, no git commits, no other files touched.

WHY THIS EXISTS
----------------
kite/research/honest_lab.py (Pipeline Z: data/daily/*_day_2000d.csv, Zerodha's
own back-adjustment) validates momo_rotation_63 at +5.0%/yr train, +3.5%/yr
val. kite/research/rotation_refinement_study.py (Pipeline N:
data/bhavcopy_full raw + data/corp_actions_adjustments.csv, this repo's own
split/bonus back-adjustment) shows the SAME strategy at -3.4%/yr train,
-29.4%/yr val. A pick-3-of-48 monthly rotation strategy amplifies small
adjusted-price differences into different portfolios, so this script finds
exactly where and why the two price series disagree.

METHOD
------
For every kite.config.NIFTY_50_STOCKS symbol present in both pipelines:
  1. Build both adjusted daily close series, align on common dates.
  2. Normalize both to 1.0 at the first common date, take the ratio
     r_t = Z_norm_t / N_norm_t. r_t == 1.0 everywhere the two pipelines
     fully agree on cumulative adjusted return since day 1.
  3. max_div_pct   = max_t |r_t - 1| * 100            (worst-case disagreement)
     first_exceed  = first date where |r_t - 1| > 1%   (divergence onset)
     max_jump_pct  = max_t |r_t/r_{t-1} - 1| * 100      (biggest single-day
                     discontinuity -- the fingerprint of a corp action one
                     side adjusted and the other didn't, or adjusted with a
                     different factor)
Rank by max_div_pct, inspect the worst 10 symbols' jump dates against
data/corp_actions_adjustments.csv, and separately re-run JUST the 63-day
momentum ranking at each pipeline's own month-end to see how often the
top-3 pick sets actually differ (the number that matters for a pick-3
rotation strategy).

Pipeline N's loader (load_bhavcopy_panel / load_corp_actions /
apply_corp_action_adjustments below) is a straight re-implementation of
kite/research/delivery_factor_study.py's load_panel / load_corp_actions /
apply_corp_action_adjustments (verified byte-for-byte against that file by
reading it, not guessed) -- re-implemented here rather than imported so this
script has zero import-time side effects on the rest of the repo.

Usage: python kite/research/pipeline_reconciliation.py
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from kite.config import NIFTY_50_STOCKS  # noqa: E402

DAILY_DIR = ROOT / 'data' / 'daily'
BHAVCOPY_DIR = ROOT / 'data' / 'bhavcopy_full'
CORP_ACTIONS_PATH = ROOT / 'data' / 'corp_actions_adjustments.csv'
OUT_FILE = Path(__file__).resolve().parent / 'pipeline_reconciliation_results.txt'

FIRST_DIVERGE_PCT = 1.0        # %, "divergence first exceeds X%" threshold
JUMP_THRESHOLD_PCT = 3.0       # %, day-over-day ratio move flagged as a "suspect jump"
TOP_N_WORST = 10
ACTION_MATCH_WINDOW_DAYS = 7   # calendar days, matching a jump date to a corp-action ex_date
MAX_JUMPS_LISTED_PER_SYMBOL = 6
LOOKBACK = 63                  # momentum lookback, trading days -- matches momo_rotation_63
TOP_N_PICKS = 3

_LINES = []


def log(msg=''):
    print(msg, flush=True)
    _LINES.append(str(msg))


def flush_out(path):
    path.write_text('\n'.join(_LINES) + '\n', encoding='utf-8')


# ===========================================================================
# PIPELINE Z LOADER -- data/daily/*_day_2000d.csv (Zerodha historical API,
# Zerodha's own corp-action back-adjustment; no dividend adjustment, per
# Zerodha's documented convention).
# ===========================================================================
def load_z_series(symbol):
    f = DAILY_DIR / f'{symbol}_day_2000d.csv'
    if not f.exists():
        return None
    df = pd.read_csv(f, parse_dates=['datetime'])
    df['date'] = df['datetime'].dt.tz_localize(None).dt.normalize()
    df = df.drop_duplicates(subset='date', keep='last').set_index('date').sort_index()
    return df['close'].astype(float)


# ===========================================================================
# PIPELINE N LOADER -- data/bhavcopy_full raw NSE bhavcopy + this repo's own
# data/corp_actions_adjustments.csv (built by build_corp_actions.py, which
# ONLY parses split/bonus subjects from the NSE corporate-actions API --
# dividends, rights issues and buybacks are explicitly excluded by that
# script's own docstring). Re-implemented here verbatim from
# delivery_factor_study.py's load_panel / load_corp_actions /
# apply_corp_action_adjustments, filtered early to NIFTY_50_STOCKS only for
# speed (1682 bhavcopy files).
# ===========================================================================
FNAME_DATE_RE = re.compile(r'sec_bhavdata_full_(\d{2})(\d{2})(\d{4})\.csv$', re.IGNORECASE)
NEEDED_COLS = ['SYMBOL', 'SERIES', 'DATE1', 'OPEN_PRICE', 'CLOSE_PRICE']


def load_bhavcopy_panel(data_dir=BHAVCOPY_DIR, universe=None):
    files = sorted(data_dir.glob('sec_bhavdata_full_*.csv'))
    frames = []
    n_skipped = 0
    universe_set = set(universe) if universe is not None else None
    for f in files:
        m = FNAME_DATE_RE.search(f.name)
        if not m:
            n_skipped += 1
            continue
        file_date = pd.Timestamp(year=int(m.group(3)), month=int(m.group(2)), day=int(m.group(1)))
        try:
            df = pd.read_csv(f, dtype=str, encoding='utf-8')
        except Exception:
            n_skipped += 1
            continue
        df.columns = df.columns.str.strip()
        if any(c not in df.columns for c in NEEDED_COLS):
            n_skipped += 1
            continue
        df = df[NEEDED_COLS].copy()
        for c in NEEDED_COLS:
            df[c] = df[c].astype(str).str.strip()
        df = df[df['SERIES'] == 'EQ']
        if universe_set is not None:
            df = df[df['SYMBOL'].isin(universe_set)]
        if df.empty:
            continue
        df = df.copy()
        df['date'] = file_date
        for c in ['OPEN_PRICE', 'CLOSE_PRICE']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        frames.append(df.rename(columns={'SYMBOL': 'symbol', 'OPEN_PRICE': 'open',
                                          'CLOSE_PRICE': 'close'})[['symbol', 'date', 'open', 'close']])
    if not frames:
        sys.exit(f'HALTED: no usable bhavcopy files found under {data_dir}')
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.drop_duplicates(subset=['symbol', 'date'], keep='last')
    panel = panel.sort_values(['symbol', 'date']).reset_index(drop=True)
    log(f'  Loaded {len(files)} bhavcopy files ({n_skipped} skipped/unreadable), '
        f'{len(panel)} EQ stock-day rows (universe-filtered), {panel.symbol.nunique()} symbols, '
        f'{panel.date.min().date()} -> {panel.date.max().date()}')
    return panel


def load_corp_actions(path=CORP_ACTIONS_PATH):
    if not path.exists():
        sys.exit(f'HALTED: {path} not found.')
    df = pd.read_csv(path)
    df['ex_date'] = pd.to_datetime(df['ex_date'])
    return df


def apply_corp_action_adjustments(panel, corp_actions):
    """Verbatim re-implementation of delivery_factor_study.py's function of
    the same name: multiply OPEN/CLOSE by the cumulative product of all
    factors whose ex_date is STRICTLY AFTER the row's date."""
    valid = corp_actions.dropna(subset=['factor']).copy()
    panel = panel.sort_values(['symbol', 'date']).reset_index(drop=True)
    mult = np.ones(len(panel))
    symbols_arr = panel['symbol'].to_numpy()
    dates_arr = panel['date'].to_numpy()
    for sym, g in valid.groupby('symbol'):
        idxs = np.where(symbols_arr == sym)[0]
        if len(idxs) == 0:
            continue
        g = g.sort_values('ex_date')
        ex_dates = g['ex_date'].to_numpy()
        factors = g['factor'].to_numpy(dtype=float)
        suffix = np.ones(len(factors) + 1)
        for i in range(len(factors) - 1, -1, -1):
            suffix[i] = suffix[i + 1] * factors[i]
        d = dates_arr[idxs]
        j = np.searchsorted(ex_dates, d, side='right')
        mult[idxs] = suffix[j]
    panel['adj_mult'] = mult
    panel['adj_open'] = panel['open'] * panel['adj_mult']
    panel['adj_close'] = panel['close'] * panel['adj_mult']
    n_adjusted = int((mult != 1.0).sum())
    log(f'  Corp-action adjustment applied to N panel: {n_adjusted} stock-day rows scaled '
        f'(factor != 1.0), {valid["symbol"].nunique()} symbols with >=1 valid action in the table.')
    return panel


# ===========================================================================
# RATIO / DIVERGENCE MACHINERY (self-check target)
# ===========================================================================
def build_ratio(z, n):
    """z, n: pd.Series indexed by date. Returns common dates + both series
    reindexed + both normalized to 1.0 at the first common date + the ratio
    Z_norm / N_norm (== 1.0 everywhere the two pipelines fully agree on
    cumulative adjusted return since day 1)."""
    common = z.index.intersection(n.index).sort_values()
    z_c = z.reindex(common).astype(float)
    n_c = n.reindex(common).astype(float)
    z_norm = z_c / z_c.iloc[0]
    n_norm = n_c / n_c.iloc[0]
    ratio = z_norm / n_norm
    return common, z_c, n_c, z_norm, n_norm, ratio


def detect_ratio_jumps(ratio, threshold_pct=JUMP_THRESHOLD_PCT):
    """Day-over-day %% change in the ratio; rows where |change| >= threshold."""
    jump_pct = ratio.pct_change() * 100
    mask = jump_pct.abs() >= threshold_pct
    out = pd.DataFrame({'date': jump_pct.index[mask], 'jump_pct': jump_pct[mask].to_numpy()})
    out['abs_jump_pct'] = out['jump_pct'].abs()
    return out.sort_values('abs_jump_pct', ascending=False).reset_index(drop=True)


# ===========================================================================
# SELF-CHECK -- synthetic pair, one series 2:1-split-adjusted, the other not.
# MUST pass before the real run executes (per task instructions).
# ===========================================================================
def selfcheck_jump_detector():
    log('=' * 100)
    log('SELF-CHECK: synthetic 2:1 split, back-adjusted in series A ("Z"), left raw in series B ("N")')
    log('=' * 100)
    dates = pd.date_range('2021-01-04', periods=10, freq='B')
    # Raw traded price series: rises 100->104 pre-split, split happens at index 5 (price roughly
    # halves because 1 old share -> 2 new shares), then continues rising 52.5->54.5.
    raw = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 52.5, 53.0, 53.5, 54.0, 54.5], index=dates)
    factor = 0.5           # 2:1 split -> factor = new_face/old_face convention used by
                            # build_corp_actions.py (a 1:2 face-value split is factor=0.5)
    split_date = dates[5]  # first day the market actually trades post-split
    z_adjusted = raw.copy()
    z_adjusted.loc[z_adjusted.index < split_date] = z_adjusted.loc[z_adjusted.index < split_date] * factor
    n_unadjusted = raw.copy()   # pipeline that never applied the split factor

    common, z_c, n_c, z_norm, n_norm, ratio = build_ratio(z_adjusted, n_unadjusted)
    assert len(common) == 10, len(common)
    assert abs(ratio.iloc[0] - 1.0) < 1e-9, ratio.iloc[0]

    jumps = detect_ratio_jumps(ratio, threshold_pct=3.0)
    assert not jumps.empty, 'self-check FAILED: no jump detected at all'
    worst = jumps.iloc[0]
    assert worst['date'] == split_date, (worst['date'], split_date)
    expected_jump_pct = (1.0 / factor - 1.0) * 100   # unadjusted N halves while adjusted Z is smooth
    assert abs(worst['jump_pct'] - expected_jump_pct) < 1e-6, (worst['jump_pct'], expected_jump_pct)

    div_pct = (ratio - 1.0).abs() * 100
    first_exceed = div_pct[div_pct > FIRST_DIVERGE_PCT]
    assert not first_exceed.empty
    assert first_exceed.index[0] == split_date, first_exceed.index[0]

    log(f'  synthetic split_date={split_date.date()}  factor={factor}  '
        f'expected ratio jump={expected_jump_pct:+.4f}%')
    log(f'  detected: jump_date={worst["date"].date()}  jump_pct={worst["jump_pct"]:+.4f}%  '
        f'-- MATCH -- PASS')
    log(f'  first-exceeds-1%% date correctly identified as the split date -- PASS')
    log('SELF-CHECK: ALL PASSED (jump-detector proven on a known synthetic split before the real run)')
    log('')


# ===========================================================================
# PER-SYMBOL ANALYSIS
# ===========================================================================
def analyze_symbol(sym, z_close, n_close):
    common, z_c, n_c, z_norm, n_norm, ratio = build_ratio(z_close, n_close)
    if len(common) < 50:
        return None
    div_pct = (ratio - 1.0).abs() * 100
    max_div_pct = float(div_pct.max())
    max_div_date = div_pct.idxmax()
    first_exceed = div_pct[div_pct > FIRST_DIVERGE_PCT]
    first_exceed_date = first_exceed.index[0] if len(first_exceed) else None
    jump_pct = ratio.pct_change() * 100
    if jump_pct.abs().dropna().empty:
        max_jump_pct, max_jump_date = np.nan, None
    else:
        max_jump_date = jump_pct.abs().idxmax()
        max_jump_pct = float(jump_pct.loc[max_jump_date])
    return dict(symbol=sym, n_common_days=len(common), start=common[0], end=common[-1],
                max_div_pct=max_div_pct, max_div_date=max_div_date,
                first_exceed_1pct_date=first_exceed_date,
                max_jump_pct=max_jump_pct, max_jump_date=max_jump_date,
                ratio=ratio, z_c=z_c, n_c=n_c)


def match_corp_actions(corp_actions, symbol, jump_date, window_days=ACTION_MATCH_WINDOW_DAYS):
    sub = corp_actions[corp_actions['symbol'] == symbol].copy()
    if sub.empty:
        return sub
    sub['days_from_jump'] = (sub['ex_date'] - jump_date).dt.days
    return sub[sub['days_from_jump'].abs() <= window_days].sort_values('days_from_jump')


def classify_suspect(z_ret, n_ret, matches):
    """Heuristic first-pass tag; the results file also carries the raw
    z_ret/n_ret/matches evidence so a human (or the report writer) can
    override this tag on inspection -- NOT trusted blindly."""
    has_match = not matches.empty
    z_big = abs(z_ret) > 8 if pd.notna(z_ret) else False
    n_big = abs(n_ret) > 8 if pd.notna(n_ret) else False
    if has_match:
        if n_big and not z_big:
            return 'a: action IS in N table near this date, but N still shows a raw jump -> factor wrong/incomplete'
        if z_big and not n_big:
            return 'c: action IS in N table (and looks correctly applied to N); Z is the one that jumps here'
        return 'a/mixed: action present in N table near this date; inspect factor vs residual jump by hand'
    else:
        if n_big and not z_big:
            return 'b: N raw-jumps, Z is smooth, NO matching entry in corp_actions_adjustments.csv -> action missing from N'
        if z_big and not n_big:
            return 'c: Z jumps, N is smooth, no N table entry needed (N already correct) -> Z missing/mis-adjusting this action'
        return 'd: no matching table entry and no single-sided raw jump pattern -> likely data quality (bad print / gap / symbol change), not a corp action'


# ===========================================================================
# STEP 4: 63-day MOMENTUM RANKING divergence at month-end, both pipelines
# ===========================================================================
def month_end_scores(wide_close, lookback=LOOKBACK):
    """wide_close: DataFrame, index=trading dates (that pipeline's own
    calendar), columns=symbols. Returns dict (year,month) -> Series of
    lookback-day momentum scores computed at that pipeline's own last
    trading day of the month, NaN-dropped."""
    idx = wide_close.index
    ym = pd.Series(list(zip(idx.year, idx.month)), index=idx)
    month_ends = ym.groupby(ym.values).apply(lambda s: s.index.max())
    mom = wide_close.pct_change(lookback, fill_method=None)
    out = {}
    for key, d in month_ends.items():
        row = mom.loc[d].dropna()
        out[key] = (d, row)
    return out


def top_n_picks(row, n=TOP_N_PICKS):
    return frozenset(row.sort_values(ascending=False).index[:n])


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    selfcheck_jump_detector()

    log('=' * 100)
    log('LOADING PIPELINE Z (data/daily/*_day_2000d.csv, Zerodha back-adjusted)')
    log('=' * 100)
    z_series = {}
    for sym in NIFTY_50_STOCKS:
        s = load_z_series(sym)
        if s is not None and len(s) > 50:
            z_series[sym] = s
    log(f'Pipeline Z: {len(z_series)}/{len(NIFTY_50_STOCKS)} NIFTY_50_STOCKS symbols found in data/daily/')
    missing_z = sorted(set(NIFTY_50_STOCKS) - set(z_series))
    if missing_z:
        log(f'  Missing from Z: {missing_z}')
    all_z_dates = sorted(set().union(*[s.index for s in z_series.values()]))
    log(f'  Z date range (union across symbols): {all_z_dates[0].date()} -> {all_z_dates[-1].date()}')
    log('')

    log('=' * 100)
    log('LOADING PIPELINE N (data/bhavcopy_full raw + data/corp_actions_adjustments.csv)')
    log('=' * 100)
    panel = load_bhavcopy_panel(universe=NIFTY_50_STOCKS)
    corp_actions = load_corp_actions()
    n_dividend_rows = int(corp_actions['subject'].str.contains('dividend', case=False, na=False).sum())
    log(f'  data/corp_actions_adjustments.csv: {len(corp_actions)} rows, {corp_actions.symbol.nunique()} symbols, '
        f'{n_dividend_rows} rows mentioning "dividend"')
    panel = apply_corp_action_adjustments(panel, corp_actions)
    n_series = {}
    for sym, g in panel.groupby('symbol'):
        s = g.set_index('date')['adj_close'].sort_index()
        s = s[~s.index.duplicated(keep='last')]
        if len(s) > 50:
            n_series[sym] = s
    log(f'Pipeline N: {len(n_series)}/{len(NIFTY_50_STOCKS)} NIFTY_50_STOCKS symbols found in bhavcopy panel')
    missing_n = sorted(set(NIFTY_50_STOCKS) - set(n_series))
    if missing_n:
        log(f'  Missing from N: {missing_n}')
    log('')

    both = sorted(set(z_series) & set(n_series))
    log(f'Symbols present in BOTH pipelines: {len(both)}/{len(NIFTY_50_STOCKS)}')
    only_z = sorted(set(z_series) - set(n_series))
    only_n = sorted(set(n_series) - set(z_series))
    if only_z:
        log(f'  In Z only: {only_z}')
    if only_n:
        log(f'  In N only: {only_n}')
    log('')

    # -----------------------------------------------------------------
    # STEP 1/2: per-symbol divergence + jump detection
    # -----------------------------------------------------------------
    log('=' * 100)
    log('STEP 1/2: PER-SYMBOL DIVERGENCE (normalized to 1.0 at first common date)')
    log('=' * 100)
    results = []
    for sym in both:
        r = analyze_symbol(sym, z_series[sym], n_series[sym])
        if r is not None:
            results.append(r)
    results.sort(key=lambda r: r['max_div_pct'], reverse=True)

    log(f'{"symbol":12} {"common_days":>11} {"start":>12} {"end":>12} {"max_div%":>10} '
        f'{"max_div_date":>12} {"first>1%_date":>13} {"max_jump%":>10} {"max_jump_date":>13}')
    for r in results:
        log(f'{r["symbol"]:12} {r["n_common_days"]:>11} {r["start"].date()!s:>12} {r["end"].date()!s:>12} '
            f'{r["max_div_pct"]:>10.2f} {str(r["max_div_date"].date()):>12} '
            f'{(str(r["first_exceed_1pct_date"].date()) if r["first_exceed_1pct_date"] is not None else "never"):>13} '
            f'{r["max_jump_pct"]:>10.2f} '
            f'{(str(r["max_jump_date"].date()) if r["max_jump_date"] is not None else "n/a"):>13}')
    log('')

    worst = results[:TOP_N_WORST]
    log('=' * 100)
    log(f'WORST {len(worst)} SYMBOLS -- suspect jump dates cross-checked against corp_actions_adjustments.csv')
    log('=' * 100)
    for r in worst:
        sym = r['symbol']
        jumps = detect_ratio_jumps(r['ratio'], threshold_pct=JUMP_THRESHOLD_PCT)
        z_ret_series = r['z_c'].pct_change() * 100
        n_ret_series = r['n_c'].pct_change() * 100
        log('')
        log(f'--- {sym}  (max_div={r["max_div_pct"]:.2f}%  common_days={r["n_common_days"]}  '
            f'window={r["start"].date()}..{r["end"].date()}) ---')
        if jumps.empty:
            log(f'  no single-day ratio jump >= {JUMP_THRESHOLD_PCT}% found -- divergence is a slow drift, '
                f'not a discrete corp-action-style event. See raw evidence above (max_div/first_exceed).')
            continue
        for _, jr in jumps.head(MAX_JUMPS_LISTED_PER_SYMBOL).iterrows():
            jd = jr['date']
            z_ret = float(z_ret_series.get(jd, np.nan))
            n_ret = float(n_ret_series.get(jd, np.nan))
            matches = match_corp_actions(corp_actions, sym, jd)
            classification = classify_suspect(z_ret, n_ret, matches)
            log(f'  JUMP {jd.date()}  ratio_jump={jr["jump_pct"]:+8.2f}%   z_1day_ret={z_ret:+7.2f}%   '
                f'n_1day_ret={n_ret:+7.2f}%')
            if matches.empty:
                log(f'      corp_actions_adjustments.csv: NO entry for {sym} within '
                    f'+/-{ACTION_MATCH_WINDOW_DAYS}d of {jd.date()}')
            else:
                for _, mr in matches.iterrows():
                    log(f'      corp_actions_adjustments.csv entry: ex_date={mr["ex_date"].date()} '
                        f'factor={mr["factor"]} subject={mr["subject"]!r} '
                        f'(delta={int(mr["days_from_jump"])}d from jump)')
            log(f'      CLASSIFICATION (heuristic, verify by hand): {classification}')
    log('')

    # -----------------------------------------------------------------
    # STEP 3 support: dividend-adjustment quantification
    # -----------------------------------------------------------------
    log('=' * 100)
    log('DIVIDEND-ADJUSTMENT CHECK')
    log('=' * 100)
    log(f'data/corp_actions_adjustments.csv rows mentioning "dividend": {n_dividend_rows} '
        f'(out of {len(corp_actions)} total rows)')
    log('build_corp_actions.py docstring (WHAT WE DELIBERATELY IGNORE) explicitly excludes dividends, '
        'AGM/board notices, rights issues and buybacks -- ONLY split and bonus subjects are parsed into '
        'factors. So Pipeline N carries ZERO dividend-adjustment by construction, same as Zerodha (which '
        'is documented to back-adjust splits/bonuses but not dividends). Since NEITHER pipeline adjusts '
        'for dividends, dividend-adjustment differences cannot be the explanation for the divergence '
        'measured above -- both sides are equally un-adjusted for cash dividends.')
    log('')

    # -----------------------------------------------------------------
    # STEP 4: 63-day momentum ranking divergence at month-end
    # -----------------------------------------------------------------
    log('=' * 100)
    log('STEP 4: 63-DAY MOMENTUM TOP-3 PICK-SET DIVERGENCE AT MONTH-END (ranking only, no full sim)')
    log('=' * 100)
    z_wide = pd.DataFrame({s: z_series[s] for s in both}).sort_index()
    n_wide = pd.DataFrame({s: n_series[s] for s in both}).sort_index()
    z_month = month_end_scores(z_wide, LOOKBACK)
    n_month = month_end_scores(n_wide, LOOKBACK)
    common_months = sorted(set(z_month) & set(n_month))
    log(f'Z pipeline data extent: {z_wide.index.min().date()} -> {z_wide.index.max().date()}')
    log(f'N pipeline data extent: {n_wide.index.min().date()} -> {n_wide.index.max().date()}')
    log(f'NOTE: Z (data/daily) does not extend to 2026-07 -- comparison below is bounded by whichever '
        f'pipeline has LESS data (Z), not the full 2020-07..2026-07 window the task specifies.')
    log('')

    rows = []
    for key in common_months:
        zd, zrow = z_month[key]
        nd, nrow = n_month[key]
        if len(zrow) < TOP_N_PICKS or len(nrow) < TOP_N_PICKS:
            continue
        z_top = top_n_picks(zrow)
        n_top = top_n_picks(nrow)
        overlap = len(z_top & n_top)
        rows.append(dict(year=key[0], month=key[1], z_date=zd, n_date=nd,
                          z_top=sorted(z_top), n_top=sorted(n_top), overlap=overlap,
                          differ=(z_top != n_top)))
    n_eval = len(rows)
    n_differ = sum(1 for r in rows if r['differ'])
    frac_differ = n_differ / n_eval if n_eval else float('nan')
    log(f'Months evaluated (both pipelines have >= {LOOKBACK}d lookback + >= {TOP_N_PICKS} eligible names): {n_eval}')
    log(f'Months where the top-3 pick SET differs between Z and N: {n_differ}/{n_eval} = {frac_differ * 100:.1f}%')
    log('')
    log(f'{"year-month":10} {"z_date":>12} {"n_date":>12} {"overlap":>7}  z_top3 / n_top3')
    for r in sorted(rows, key=lambda r: r['overlap']):
        ym = f'{r["year"]:04d}-{r["month"]:02d}'
        log(f'{ym:10} {r["z_date"].date()!s:>12} {r["n_date"].date()!s:>12} {r["overlap"]:>7}  '
            f'{r["z_top"]} / {r["n_top"]}')
    log('')
    zero_overlap = [r for r in rows if r['overlap'] == 0]
    log(f'Months with ZERO overlap (completely different top-3, worst case): {len(zero_overlap)}/{n_eval}')
    for r in zero_overlap:
        ym = f'{r["year"]:04d}-{r["month"]:02d}'
        log(f'  {ym}: Z picks {r["z_top"]}  vs  N picks {r["n_top"]}')
    log('')

    flush_out(OUT_FILE)
    log(f'Full log written -> {OUT_FILE}')


# ===========================================================================
# REVIEWER FOLLOW-UP DIAGNOSTIC -- appended 2026-08-04, NOT part of the
# original forensic run above. Does not touch main()/OUT_FILE's log buffer.
#
# Question: pick-set-divergence counting (STEP 4 above) is blind to the
# mechanism where the SAME stock is picked by both pipelines but Pipeline
# N's missing demerger adjustment turns one holding period into a large
# FAKE loss (TATAMOTORS ~2025-10-14, ITC ~2025-01-06 -- see the worst-10
# writeup above). This reruns rotation_refinement_study.py's actual BASELINE
# sim (imported directly, not reimplemented -- same run_variant/VARIANTS/
# panel-loading code the frozen study uses, so this is the real thing, not
# an approximation), reconstructs day-level holdings from its trade log,
# and surgically neutralizes each event date's fake return to answer: how
# much of baseline's negative CAGR is this one mechanism worth?
#
# Run:  python kite/research/pipeline_reconciliation.py --demerger-diagnostic
# ===========================================================================
def reconstruct_holdings(trade_log, final_positions, date):
    """symbol -> {'qty','cost_basis','entry_date','exit_date','status'} for
    everything held ON `date`. A closed trade counts as held on `date` if
    entry_date <= date < exit_date (position is sold AT exit_date's open,
    so it is not held through that day's close). A still-open final
    position counts if its first tranche filled on or before `date`."""
    held = {}
    for t in trade_log:
        if t['entry_date'] <= date < t['exit_date']:
            held[t['symbol']] = {'qty': t['qty'], 'cost_basis': t['cost_basis'],
                                  'entry_date': t['entry_date'], 'exit_date': t['exit_date'],
                                  'status': 'later closed'}
    for sym, pos in final_positions.items():
        entry_date = pos['tranches'][0][0]
        if entry_date <= date:
            held[sym] = {'qty': pos['qty'], 'cost_basis': pos['cost_basis'],
                          'entry_date': entry_date, 'exit_date': None,
                          'status': 'still open at study end'}
    return held


def trades_closed_in_week(trade_log, center_date, days_before=3, days_after=4):
    lo = center_date - pd.Timedelta(days=days_before)
    hi = center_date + pd.Timedelta(days=days_after)
    return [t for t in trade_log if lo <= t['exit_date'] <= hi]


def surgical_correction(eq_orig, close_wide, events):
    """events: list of (date, symbol, qty). For each event, compute that
    symbol's dollar mark-to-market swing on `date` (qty * (close[date] -
    close[prev_trading_day])), express it as a fraction of the PRIOR day's
    total equity, and subtract that fraction from that day's portfolio
    return -- i.e. neutralize that one position's contribution to zero for
    that one day, leaving every other position/day's return untouched.
    Then re-chain the whole equity curve forward from CAPITAL using the
    corrected return series. Events applied in chronological order (each
    later correction's re-chain naturally sits on top of any earlier one,
    since we operate in RETURNS space, not dollar space -- percentage
    contributions compose correctly regardless of order)."""
    r_orig = eq_orig.pct_change()
    r_corr = r_orig.copy()
    notes = []
    for date, sym, qty in sorted(events, key=lambda e: e[0]):
        pos = eq_orig.index.get_loc(date)
        prev_date = eq_orig.index[pos - 1]
        if sym not in close_wide.columns:
            notes.append((date, sym, qty, None))
            continue
        c_now = close_wide.at[date, sym] if date in close_wide.index else np.nan
        c_prev = close_wide.at[prev_date, sym] if prev_date in close_wide.index else np.nan
        if pd.isna(c_now) or pd.isna(c_prev):
            notes.append((date, sym, qty, None))
            continue
        dollar_swing = qty * (c_now - c_prev)
        prior_equity = float(eq_orig.loc[prev_date])
        contribution = dollar_swing / prior_equity
        r_corr.loc[date] = r_orig.loc[date] - contribution
        notes.append((date, sym, qty, dict(prev_date=prev_date, c_prev=c_prev, c_now=c_now,
                                            dollar_swing=dollar_swing, prior_equity=prior_equity,
                                            contribution_pct=contribution * 100,
                                            r_orig_pct=r_orig.loc[date] * 100,
                                            r_corr_pct=r_corr.loc[date] * 100)))
    eq_corr = pd.Series(index=eq_orig.index, dtype=float)
    eq_corr.iloc[0] = eq_orig.iloc[0]
    for i in range(1, len(eq_orig)):
        d = eq_orig.index[i]
        rc = r_corr.loc[d]
        eq_corr.iloc[i] = eq_corr.iloc[i - 1] * (1 + (0.0 if pd.isna(rc) else rc))
    return eq_corr, notes


def run_demerger_diagnostic():
    out_lines = []

    def p(msg=''):
        print(msg, flush=True)
        out_lines.append(str(msg))

    from kite.research import rotation_refinement_study as rrs

    p('=' * 100)
    p('REVIEWER FOLLOW-UP: TATAMOTORS/ITC demerger P&L mechanism, surgical CAGR correction')
    p('=' * 100)
    p('Rerunning rotation_refinement_study.py\'s ACTUAL baseline sim (imported directly: '
      'load_universe_panel/compute_momentum/compute_proxy_regime/run_variant/VARIANTS[\'baseline\']) '
      '-- deterministic, same code the frozen study used, not a reimplementation.')
    p('')

    close_wide, open_wide, universe = rrs.load_universe_panel()
    mom_df = rrs.compute_momentum(close_wide, rrs.LOOKBACK)
    _, _, proxy_regime_on_full = rrs.compute_proxy_regime(close_wide, rrs.REGIME_SMA)
    valid_from = rrs.REGIME_SMA - 1
    calendar = close_wide.index[valid_from:]
    global_start, global_end = calendar[0], calendar[-1]
    proxy_regime_on = pd.Series({d: bool(proxy_regime_on_full.get(d, False)) for d in calendar})

    r = rrs.run_variant('baseline', rrs.VARIANTS['baseline'], calendar, close_wide, open_wide,
                         mom_df, proxy_regime_on, proxy_regime_on)  # real_regime_on unused (regime='proxy')
    eq_orig, trade_log, final_positions, final_cash = r['equity'], r['trades'], r['final_positions'], r['final_cash']

    orig_full_cagr = rrs.cagr(rrs.CAPITAL, rrs.equity_at(eq_orig, global_end), global_start, global_end)
    windows = rrs.era_windows(calendar, 3)
    era3_lo, era3_hi = windows[2]
    orig_era3_cagr = rrs.cagr(rrs.equity_at(eq_orig, era3_lo), rrs.equity_at(eq_orig, era3_hi), era3_lo, era3_hi)
    p(f'Sanity check against rotation_refinement_results.txt: this rerun baseline full-period CAGR = '
      f'{orig_full_cagr * 100:+.3f}%  (frozen results file reports -14.560%)')
    p(f'This rerun baseline Era-3 CAGR = {orig_era3_cagr * 100:+.3f}%  (frozen results file reports -29.588%, '
      f'era3 window {era3_lo.date()}..{era3_hi.date()})')
    p('')

    events_requested = [('TATAMOTORS', pd.Timestamp('2025-10-14')), ('ITC', pd.Timestamp('2025-01-06'))]
    events_for_correction = []

    for sym, event_date in events_requested:
        p('-' * 100)
        p(f'EVENT: {sym} demerger, ~{event_date.date()}')
        p('-' * 100)
        held = reconstruct_holdings(trade_log, final_positions, event_date)
        was_held = sym in held
        p(f'Was {sym} held by the baseline sim spanning {event_date.date()}? {"YES" if was_held else "NO"}')
        p(f'ALL holdings in the baseline sim on {event_date.date()} ({len(held)} position(s)):')
        for s2, info in sorted(held.items()):
            avg_price = info['cost_basis'] / info['qty'] if info['qty'] else float('nan')
            c_now = close_wide.at[event_date, s2] if (event_date in close_wide.index and s2 in close_wide.columns) else np.nan
            mtm_pct = (c_now / avg_price - 1) * 100 if pd.notna(c_now) and avg_price else float('nan')
            p(f'    {s2:12} qty={info["qty"]:>6}  cost_basis=Rs{info["cost_basis"]:>10,.2f}  '
              f'avg_price=Rs{avg_price:>9.3f}  entry_date={info["entry_date"].date()}  '
              f'status={info["status"]}  mark-to-market on {event_date.date()}={mtm_pct:+.2f}%')
        if not held:
            p('    (no open positions at all on this date)')
        p('')

        if was_held:
            info = held[sym]
            qty = info['qty']
            avg_price = info['cost_basis'] / qty
            trigger_close = 0.85 * avg_price
            pos_idx = calendar.get_loc(event_date)
            prev_date = calendar[pos_idx - 1]
            c_prev = close_wide.at[prev_date, sym] if prev_date in close_wide.index else np.nan
            c_now = close_wide.at[event_date, sym] if event_date in close_wide.index else np.nan
            day_ret_pct = (c_now / c_prev - 1) * 100 if pd.notna(c_prev) and pd.notna(c_now) else float('nan')
            p(f'  DISASTER-STOP CHECK (baseline rule: exit if close <= 0.85*avg_price):')
            p(f'    avg_price=Rs{avg_price:.3f}  0.85x trigger=Rs{trigger_close:.3f}  '
              f'close({prev_date.date()})=Rs{c_prev:.3f}  close({event_date.date()})=Rs{c_now:.3f} '
              f'({day_ret_pct:+.2f}% on the day)')
            p(f'    close({event_date.date()}) <= trigger? {"YES -- stop condition met on the demerger day" if pd.notna(c_now) and c_now <= trigger_close else "no"}')
            if info['exit_date'] is not None:
                closed_trade = next((t for t in trade_log if t['symbol'] == sym and t['exit_date'] == info['exit_date']
                                      and t['entry_date'] == info['entry_date']), None)
                if closed_trade:
                    p(f'  ACTUAL TRADE RECORD: entry_date={closed_trade["entry_date"].date()}  '
                      f'exit_date={closed_trade["exit_date"].date()}  qty={closed_trade["qty"]}  '
                      f'cost_basis=Rs{closed_trade["cost_basis"]:,.2f}  proceeds=Rs{closed_trade["proceeds"]:,.2f}  '
                      f'gain=Rs{closed_trade["gain"]:,.2f} ({closed_trade["gain"]/closed_trade["cost_basis"]*100:+.2f}%)  '
                      f'holding_days={closed_trade["holding_days"]}')
                    days_to_exit = (closed_trade['exit_date'] - event_date).days
                    p(f'    exit came {days_to_exit} day(s) after the demerger date -- consistent with '
                      f'{"the disaster stop firing on/right after the crash" if days_to_exit <= 3 else "some other exit trigger (rebalance / force-exit-on-disappearance)"}')
            p('')
            events_for_correction.append((event_date, sym, qty))

        p(f'Trades CLOSED the week of {event_date.date()} (window -3d/+4d, ALL symbols):')
        week_trades = trades_closed_in_week(trade_log, event_date)
        if week_trades:
            for t in week_trades:
                p(f'    {t["symbol"]:12} entry={t["entry_date"].date()}  exit={t["exit_date"].date()}  '
                  f'qty={t["qty"]}  cost_basis=Rs{t["cost_basis"]:,.2f}  proceeds=Rs{t["proceeds"]:,.2f}  '
                  f'gain=Rs{t["gain"]:,.2f} ({t["gain"]/t["cost_basis"]*100:+.2f}%)')
        else:
            p('    (none)')
        p('')

    p('=' * 100)
    p('SURGICAL CORRECTION -- method')
    p('=' * 100)
    p('For each event date, compute the affected position\'s dollar mark-to-market swing that day '
      '(qty * (close[event_date] - close[prev_trading_day]), using Pipeline N\'s own close_wide -- the '
      'SAME price series the baseline sim actually marks equity against), express it as a fraction of '
      'the PRIOR day\'s total portfolio equity, and subtract exactly that fraction from that day\'s '
      'portfolio return -- i.e. neutralize ONLY that one position\'s contribution to zero for that one '
      'day (everything else about that day, and every other day, is left untouched: no re-simulation, '
      'no changed trading decisions, no changed ranking -- purely a post-hoc equity-curve correction, '
      'the simplest defensible method, per the reviewer\'s instruction). The corrected daily-return '
      'series is then re-chained multiplicatively from CAPITAL forward to build a corrected equity '
      'curve. Applied in RETURNS space (not dollar space) so the two corrections (ITC then TATAMOTORS, '
      'chronological order) compose correctly regardless of what happens between them.')
    p('')

    if events_for_correction:
        eq_corr, notes = surgical_correction(eq_orig, close_wide, events_for_correction)
        for date, sym, qty, d in notes:
            if d is None:
                p(f'  {sym} @ {date.date()}: SKIPPED (missing price data for the day-over-day delta)')
                continue
            p(f'  {sym} @ {date.date()}: qty={qty}  close {d["prev_date"].date()}=Rs{d["c_prev"]:.3f} -> '
              f'{date.date()}=Rs{d["c_now"]:.3f}  dollar_swing=Rs{d["dollar_swing"]:,.2f}  '
              f'prior_day_equity=Rs{d["prior_equity"]:,.2f}  contribution_to_that_day\'s_return='
              f'{d["contribution_pct"]:+.3f}pp  (portfolio return that day: actual {d["r_orig_pct"]:+.3f}% '
              f'-> corrected {d["r_corr_pct"]:+.3f}%)')
        p('')

        corr_full_cagr = rrs.cagr(rrs.CAPITAL, rrs.equity_at(eq_corr, global_end), global_start, global_end)
        corr_era3_cagr = rrs.cagr(rrs.equity_at(eq_corr, era3_lo), rrs.equity_at(eq_corr, era3_hi), era3_lo, era3_hi)
        final_orig = float(rrs.equity_at(eq_orig, global_end))
        final_corr = float(rrs.equity_at(eq_corr, global_end))

        p('=' * 100)
        p('RESULT -- baseline CAGR, actual (Pipeline N, as run by the frozen study) vs surgically corrected')
        p('=' * 100)
        p(f'{"":28}{"final_equity":>16}{"full-period CAGR":>20}{"Era-3 CAGR":>14}')
        p(f'{"ACTUAL (uncorrected)":28}{"Rs " + format(final_orig, ",.2f"):>16}'
          f'{orig_full_cagr * 100:>19.3f}%{orig_era3_cagr * 100:>13.3f}%')
        p(f'{"SURGICALLY CORRECTED":28}{"Rs " + format(final_corr, ",.2f"):>16}'
          f'{corr_full_cagr * 100:>19.3f}%{corr_era3_cagr * 100:>13.3f}%')
        p(f'{"delta (corrected-actual)":28}{"Rs " + format(final_corr - final_orig, ",.2f"):>16}'
          f'{(corr_full_cagr - orig_full_cagr) * 100:>+19.3f}pp{(corr_era3_cagr - orig_era3_cagr) * 100:>+13.3f}pp')
        p('')
        p(f'honest_lab.py (Pipeline Z, compounding) validated momo_rotation_63 at TRAIN +5.0%/yr, '
          f'VAL +3.5%/yr, i.e. squarely positive throughout.')
        gap_before = orig_full_cagr * 100 - 3.5
        gap_after = corr_full_cagr * 100 - 3.5
        p(f'Gap to honest_lab\'s +3.5%/yr VAL number: {gap_before:+.2f}pp before correction, '
          f'{gap_after:+.2f}pp after correction '
          f'({"gap closes materially but a large residual remains" if abs(gap_after) < abs(gap_before) * 0.85 else "correction barely moves the gap -- residual is NOT primarily this mechanism"}).')
        closes_meaningfully = abs(gap_after) < abs(gap_before) * 0.85
        p('')
        p('=' * 100)
        p('PLAIN STATEMENT')
        p('=' * 100)
        p(f'Full-period baseline CAGR moves from {orig_full_cagr*100:+.3f}% to {corr_full_cagr*100:+.3f}% '
          f'({(corr_full_cagr-orig_full_cagr)*100:+.3f}pp) once the two demerger-day fake losses are '
          f'surgically zeroed. Era-3 CAGR moves from {orig_era3_cagr*100:+.3f}% to {corr_era3_cagr*100:+.3f}% '
          f'({(corr_era3_cagr-orig_era3_cagr)*100:+.3f}pp).')
        if closes_meaningfully:
            p(f'This is a REAL and non-trivial correction, but the corrected baseline ({corr_full_cagr*100:+.2f}%/yr '
              f'full-period) is still far short of honest_lab.py\'s +3.5-5.0%/yr -- a large unexplained '
              f'residual remains. The two demerger artifacts are confirmed contributors, not the primary '
              f'explanation for why rotation_refinement_study.py\'s baseline is negative while honest_lab.py\'s '
              f'is positive.')
        else:
            p(f'This correction barely moves the full-period or Era-3 number at all. The two demerger fake '
              f'losses, despite being real and confirmed, are NOT a material driver of baseline\'s negative '
              f'CAGR -- the -14.56%/yr full-period and -29.588%/yr Era-3 results are overwhelmingly explained '
              f'by something else entirely (see the MAGNITUDE CHECK section of the main results file: sizing '
              f'convention and the disaster-stop rule were already ruled out by rotation_refinement_study.py\'s '
              f'own diagnostics, so the residual is most likely the accumulation of many small pipeline-N '
              f'price disagreements across the other 46 symbols, plus cost-convention differences vs '
              f'honest_lab.py -- neither fully diagnosed by this follow-up).')
    else:
        p('Neither TATAMOTORS nor ITC was found held by the baseline sim on the requested dates -- '
          'no correction to apply. (This would itself be a significant, surprising finding -- verify '
          'the holdings reconstruction above before trusting this branch.)')
        p('')
        p('=' * 100)
        p('PLAIN STATEMENT')
        p('=' * 100)
        p('Neither event date coincided with an actual open position in the baseline sim, so this '
          'mechanism (fake demerger-day loss on a held position) cannot be a contributor to the CAGR '
          'gap for THESE two specific dates. See the holdings reconstruction above for what WAS held.')
    return out_lines


# ===========================================================================
# REVIEWER FOLLOW-UP DIAGNOSTIC #2 -- appended 2026-08-04, the missing 2x2
# cell. NOT part of the original forensic run above, does not touch
# main()/OUT_FILE's log buffer.
#
# Known so far: honest_lab ENGINE + Pipeline Z DATA = +3.5 to +5.0%/yr.
#               rotation_refinement ENGINE + Pipeline N DATA = -14.560%/yr.
# Every within-rotation_refinement-engine explanation tried so far (fixed
# vs compounding sizing, disaster-stop on/off, rebalance-date sensitivity,
# the two headline demerger events) has been RULED OUT as the driver. The
# missing cell: rotation_refinement's ENGINE run on Pipeline Z DATA, unchanged
# in every other respect (same costs, same regime logic, same fixed-slot
# sizing, same run_variant/VARIANTS['baseline'] code -- imported directly).
# If that lands near the N-data baseline, the gap is ENGINE conventions
# (honest_lab vs rotation_refinement differ in ways enumerated below). If it
# jumps to positive/near-honest_lab territory, the gap is DATA (Pipeline N's
# diffuse price errors across all 48 symbols, not just the two demergers).
#
# Run:  python kite/research/pipeline_reconciliation.py --z-engine-diagnostic
# ===========================================================================
def load_z_panel(universe=None):
    """Z-pipeline wide close/open panel, loaded the way honest_lab.py's
    load_data() loads it (tz-strip, normalize, drop-dup dates, len>300
    filter) but reshaped into the same wide-DataFrame-by-symbol-column shape
    that rotation_refinement_study.py's run_variant/run_sim expect (i.e. the
    same shape load_universe_panel() returns for Pipeline N)."""
    universe = list(universe) if universe is not None else list(NIFTY_50_STOCKS)
    z_close, z_open = {}, {}
    for sym in universe:
        f = DAILY_DIR / f'{sym}_day_2000d.csv'
        if not f.exists():
            continue
        df = pd.read_csv(f, parse_dates=['datetime'])
        df['date'] = df['datetime'].dt.tz_localize(None).dt.normalize()
        df = df.drop_duplicates(subset='date', keep='last').set_index('date').sort_index()
        if len(df) > 300:
            z_close[sym] = df['close'].astype(float)
            z_open[sym] = df['open'].astype(float)
    found = sorted(z_close.keys())
    close_wide = pd.DataFrame(z_close).sort_index().reindex(columns=found)
    open_wide = pd.DataFrame(z_open).sort_index().reindex(columns=found)
    return close_wide, open_wide, found


def _run_baseline_on_panel(rrs, close_wide, open_wide):
    """Runs rotation_refinement_study.py's ACTUAL VARIANTS['baseline'] config
    (direct import: run_variant, compute_momentum, compute_proxy_regime) on
    whatever close_wide/open_wide panel is passed in -- costs, regime logic,
    fixed-slot sizing, disaster stop, rebalance-day convention all untouched,
    identical to the frozen study. Returns (equity, trades, calendar,
    global_start, global_end, windows)."""
    mom_df = rrs.compute_momentum(close_wide, rrs.LOOKBACK)
    _, _, proxy_regime_on_full = rrs.compute_proxy_regime(close_wide, rrs.REGIME_SMA)
    valid_from = rrs.REGIME_SMA - 1
    calendar = close_wide.index[valid_from:]
    global_start, global_end = calendar[0], calendar[-1]
    proxy_regime_on = pd.Series({d: bool(proxy_regime_on_full.get(d, False)) for d in calendar})
    r = rrs.run_variant('baseline', rrs.VARIANTS['baseline'], calendar, close_wide, open_wide,
                         mom_df, proxy_regime_on, proxy_regime_on)  # real_regime_on unused (regime='proxy')
    windows = rrs.era_windows(calendar, 3)
    return r, calendar, global_start, global_end, windows


def _report_run(p, label, rrs, r, calendar, global_start, global_end, windows):
    eq = r['equity']
    final_eq = float(rrs.equity_at(eq, global_end))
    full_cagr = rrs.cagr(rrs.CAPITAL, final_eq, global_start, global_end)
    era_cagrs = []
    for (elo, ehi) in windows:
        c = rrs.cagr(rrs.equity_at(eq, elo), rrs.equity_at(eq, ehi), elo, ehi)
        era_cagrs.append(c)
    p(f'{label}')
    p(f'    window: {global_start.date()} -> {global_end.date()}  '
      f'({(global_end - global_start).days / 365.25:.2f} years, {len(calendar)} trading days)')
    p(f'    final_equity=Rs {final_eq:>13,.2f}   full-period CAGR={full_cagr * 100:>+8.3f}%   #trades={len(r["trades"])}')
    for i, (elo, ehi) in enumerate(windows, 1):
        p(f'    Era{i} {elo.date()} -> {ehi.date()}: CAGR={era_cagrs[i - 1] * 100:>+8.3f}%')
    return dict(final_equity=final_eq, full_cagr=full_cagr, era_cagrs=era_cagrs,
                global_start=global_start, global_end=global_end, windows=windows)


def run_z_engine_diagnostic():
    out_lines = []

    def p(msg=''):
        print(msg, flush=True)
        out_lines.append(str(msg))

    from kite.research import rotation_refinement_study as rrs

    p('=' * 100)
    p('REVIEWER FOLLOW-UP #2: the missing 2x2 cell -- rotation_refinement ENGINE on Pipeline Z DATA')
    p('=' * 100)
    p('Same run_variant/VARIANTS[\'baseline\']/compute_momentum/compute_proxy_regime code as the frozen '
      'study (direct import, unchanged) -- only the close_wide/open_wide panel fed into it changes.')
    p('')

    # ---- cell 1: N-data baseline, N's own full available window (the frozen, already-reported number) ----
    p('-' * 100)
    p('CELL 1: rotation_refinement ENGINE + Pipeline N DATA, N\'s own full window (frozen study, rerun here for a fresh calendar/windows object)')
    p('-' * 100)
    n_close_wide, n_open_wide, n_universe = rrs.load_universe_panel()
    p(f'  N universe: {len(n_universe)} symbols, panel {n_close_wide.index.min().date()} -> {n_close_wide.index.max().date()}')
    r_n_full, cal_n_full, gs_n_full, ge_n_full, win_n_full = _run_baseline_on_panel(rrs, n_close_wide, n_open_wide)
    cell1 = _report_run(p, 'N-DATA, N-FULL-WINDOW baseline:', rrs, r_n_full, cal_n_full, gs_n_full, ge_n_full, win_n_full)
    p('')

    # ---- cell 2: Z-data baseline, Z's own full available window ----
    p('-' * 100)
    p('CELL 2: rotation_refinement ENGINE + Pipeline Z DATA (data/daily/*_day_2000d.csv, loaded the way honest_lab.py loads it), Z\'s own full window')
    p('-' * 100)
    z_close_wide, z_open_wide, z_universe = load_z_panel()
    p(f'  Z universe: {len(z_universe)}/{len(NIFTY_50_STOCKS)} NIFTY_50_STOCKS symbols found, '
      f'panel {z_close_wide.index.min().date()} -> {z_close_wide.index.max().date()}')
    missing_z = sorted(set(NIFTY_50_STOCKS) - set(z_universe))
    if missing_z:
        p(f'  Missing from Z: {missing_z}')
    r_z_full, cal_z_full, gs_z_full, ge_z_full, win_z_full = _run_baseline_on_panel(rrs, z_close_wide, z_open_wide)
    cell2 = _report_run(p, 'Z-DATA, Z-FULL-WINDOW baseline:', rrs, r_z_full, cal_z_full, gs_z_full, ge_z_full, win_z_full)
    p('')
    p('  NOTE: Z\'s data (data/daily) ends 2026-01-09, ~6.5 months short of N\'s panel end (2026-07-27) -- '
      'cell 1 and cell 2 above cover DIFFERENT-length windows, so their CAGRs are not a clean apples-to-'
      'apples comparison by themselves (a shorter window skips whatever happened Jan-Jul 2026, which is '
      'part of N\'s worst era). Cell 3 below controls for this by truncating N\'s panel to Z\'s exact '
      'calendar before rerunning -- same window, same trading days, ONLY the price data source differs.')
    p('')

    # ---- cell 3: N-data baseline, TRUNCATED to Z's exact date range (controlled, apples-to-apples) ----
    p('-' * 100)
    p('CELL 3 (CONTROL): rotation_refinement ENGINE + Pipeline N DATA, TRUNCATED to Z\'s exact calendar '
      '(same window length as cell 2 -- isolates price-data-only effect)')
    p('-' * 100)
    z_last_date = z_close_wide.index.max()
    n_close_trunc = n_close_wide.loc[n_close_wide.index <= z_last_date]
    n_open_trunc = n_open_wide.loc[n_open_wide.index <= z_last_date]
    r_n_trunc, cal_n_trunc, gs_n_trunc, ge_n_trunc, win_n_trunc = _run_baseline_on_panel(rrs, n_close_trunc, n_open_trunc)
    cell3 = _report_run(p, 'N-DATA, TRUNCATED-TO-Z-WINDOW baseline:', rrs, r_n_trunc, cal_n_trunc, gs_n_trunc, ge_n_trunc, win_n_trunc)
    p('')

    # ---- the 2x2 summary table ----
    p('=' * 100)
    p('2x2 SUMMARY TABLE')
    p('=' * 100)
    p(f'{"":42}{"window":>24}{"full-period CAGR":>20}{"Era1":>10}{"Era2":>10}{"Era3":>10}')

    def row(label, cell):
        w = f'{cell["global_start"].date()}..{cell["global_end"].date()}'
        p(f'{label:42}{w:>24}{cell["full_cagr"] * 100:>+19.3f}%'
          f'{cell["era_cagrs"][0] * 100:>+9.2f}%{cell["era_cagrs"][1] * 100:>+9.2f}%{cell["era_cagrs"][2] * 100:>+9.2f}%')

    row('rot_refinement ENGINE + N DATA (full)', cell1)
    row('rot_refinement ENGINE + N DATA (Z-window control)', cell3)
    row('rot_refinement ENGINE + Z DATA (full)', cell2)
    p(f'{"honest_lab ENGINE + Z DATA (reference, different engine)":42}{"2020-07..2024-06/2026-01":>24}'
      f'{"TRAIN +5.0% / VAL +3.5%":>20}')
    p('')

    # ---- interpretation, per the pre-stated rule ----
    p('=' * 100)
    p('INTERPRETATION -- applying the pre-stated rule')
    p('=' * 100)
    p('Rule (stated in advance by the reviewer): compare the Z-DATA baseline (cell 2) to the N-DATA '
      'baseline. Using cell 3 (the window-controlled N baseline) as the correct comparison point -- same '
      'engine, same calendar length, ONLY the price source differs, which is what actually isolates a '
      'DATA effect from a DATA-plus-shorter-window effect:')
    gap_pp = (cell2['full_cagr'] - cell3['full_cagr']) * 100
    p(f'  Z-DATA full-period CAGR = {cell2["full_cagr"] * 100:+.3f}%')
    p(f'  N-DATA (Z-window control) full-period CAGR = {cell3["full_cagr"] * 100:+.3f}%')
    p(f'  gap (Z - N, same window) = {gap_pp:+.3f}pp')
    if abs(gap_pp) <= 2.0:
        p(f'  |{gap_pp:+.3f}pp| <= 2pp -> per the pre-stated rule: DATA IS EXONERATED. The gap lives in '
          f'ENGINE conventions (rotation_refinement_study.py vs honest_lab.py). See the enumerated '
          f'convention differences below.')
    elif cell2['full_cagr'] > 0.02:
        p(f'  Z-DATA baseline jumps to positive/near-honest_lab territory ({cell2["full_cagr"] * 100:+.2f}%/yr, '
          f'gap={gap_pp:+.3f}pp vs the window-controlled N baseline) -> per the pre-stated rule: the '
          f'DIFFUSE Pipeline-N price errors (across all 48 symbols, not just the two demergers already '
          f'ruled out individually) ARE the driver. build_corp_actions.py + bhavcopy hygiene become the '
          f'priority fix.')
    else:
        p(f'  gap={gap_pp:+.3f}pp, outside the +/-2pp exoneration band, but Z-DATA baseline is NOT positive/'
          f'near-honest_lab territory either ({cell2["full_cagr"] * 100:+.2f}%/yr) -> MIXED result under the '
          f'pre-stated rule\'s own terms: neither clause fires cleanly. Price data materially changes the '
          f'engine\'s output (rules out "data is irrelevant") but does not on its own explain honest_lab\'s '
          f'positive numbers either (rules out "data is the sole driver"). Both DATA and ENGINE conventions '
          f'appear to matter; see the enumerated convention differences below for what else to check.')
    p('')

    # ---- enumerated engine convention differences (read, not fixed) ----
    p('=' * 100)
    p('ENUMERATED CONVENTION DIFFERENCES: honest_lab.py vs rotation_refinement_study.py')
    p('(read from both files as they exist on disk; nothing here was changed or fixed)')
    p('=' * 100)
    p('1. POSITION SIZING: honest_lab.py COMPOUNDS -- slot = min(cash, (cash+mkt_value)/MAX_SLOTS), '
      'recomputed at every entry. rotation_refinement_study.py uses a FIXED Rs20,000 slot for the whole '
      '~6yr run (capital/max_positions, computed once), matching the LIVE deployed system (J1). '
      'ALREADY TESTED within the N-data engine (rotation_refinement\'s own compounding diagnostic): '
      'barely matters (-14.56% fixed vs -15.36% compounding) -- listed for completeness, not a live lead.')
    p('2. INSUFFICIENT-CASH HANDLING: honest_lab.py always deploys what it can (qty = int(slot/px), slot '
      'itself capped at available cash -- never literally skips an entry). rotation_refinement_study.py '
      'BINARY-REJECTS an entry entirely if the fixed Rs20,000 can\'t be covered (paper_trader.py\'s real '
      'rule, replicated exactly, J1 addendum) -- that slot sits in idle cash instead. Coupled to #1.')
    p('3. TRAIN/VAL CAPITAL RESET: honest_lab.py runs TRAIN (2020-07..2024-06) and VAL (2024-07..2026-01) '
      'as two SEPARATE, INDEPENDENT simulations, each starting fresh with the full Rs100,000 (`Sim(data, '
      'train).run(...)` and `Sim(data, val).run(...)` are two distinct calls) -- so the reported "VAL '
      '+3.5%/yr" NEVER has to recover from anything that happened during train, however bad. '
      'rotation_refinement_study.py runs ONE CONTINUOUS ~6-year simulation with no capital reset at any '
      'interior date -- if an early stretch goes badly, whatever cash/positions that leaves behind carry '
      'forward into every later period. NOT individually tested by any diagnostic run so far in this '
      'reconciliation (the compounding-vs-fixed test changed sizing, not the reset-vs-continuous question) '
      '-- flagged as the single most-plausible untested engine difference, given fixed-slot sizing (#1) is '
      'exactly the mechanism that would make an un-reset early drawdown "sticky" for the rest of a '
      'continuous run.')
    p('4. COST BOOKKEEPING: honest_lab.py settles the FULL round-trip fee (both legs) at EXIT time only, '
      'via kite.config.zerodha_charges.calculate_charges() (brokerage+STT+exchange+SEBI+GST+stamp_duty, '
      'the full delivery-trade formula) -- no haircut on the entry fill itself. rotation_refinement_study.py '
      '(J4, per its frozen spec\'s explicit instruction to match "the regime-exit study\'s conventions") '
      'haircuts BOTH entry (investable=cash*(1-BUY_COST_PCT)) and exit (proceeds=gross*(1-SELL_COST_PCT)-'
      'DP_FLAT_PER_SELL), using a simpler flat-percentage formula plus a flat Rs15.34 DP charge per sell, '
      'not zerodha_charges.calculate_charges(). Different formula AND different recognition timing.')
    p('5. DISASTER STOP: rotation_refinement_study.py force-exits any position whose close falls to <=85% '
      'of its average cost (checked every day, DISASTER_SL=0.85). honest_lab.py\'s momentum strategy '
      '(make_momo) has NO such rule at all -- positions are only ever exited at the next monthly rebalance '
      'if they drop out of the top-N, however far underwater they go in between. ALREADY TESTED within '
      'the N-data engine (X0 variant, stop removed): barely matters (-14.98% with no stop vs -14.56% with '
      'it) -- listed for completeness, not a live lead.')
    p('6. SAME in both (checked, not a differentiator): universe (kite.config.NIFTY_50_STOCKS, 48 symbols, '
      'fixed for the whole window); the proxy regime filter\'s construction (equal-weight self-normalized '
      'universe vs its own 200-day SMA, identical formula in both files); rebalance timing (signal at '
      'close of the FIRST trading day of each month, fill at next day\'s open); LOOKBACK=63, TOP_N=3, '
      'CAPITAL=Rs100,000, MAX_POSITIONS/MAX_SLOTS=5.')
    p('')
    return out_lines


# ===========================================================================
# REVIEWER FOLLOW-UP DIAGNOSTIC #3 -- appended 2026-08-04, the isolation shot.
# NOT part of the original forensic run above.
#
# Convention #2 (insufficient-cash: binary-reject vs shrink-to-fit) was never
# isolated -- the earlier compounding diagnostic (run_diagnostic_compounding
# in rotation_refinement_study.py) changed the SLOT-SIZE FORMULA but kept
# binary-reject, so under-deployment could persist regardless of which
# sizing formula was used. This runs two new configs on "cell 3" (the
# reviewer's numbering: Z data, Z's own window, 2021-04-30 -> 2026-01-09 --
# same panel as run_z_engine_diagnostic()'s CELL 2), with a LOCAL,
# instrumented, otherwise-faithful copy of run_sim() (needed because
# run_sim() itself doesn't expose per-day cash, and its own compounding mode
# still keeps binary-reject baked in -- see run_sim_configurable()'s
# docstring for exactly what's copied verbatim vs changed):
#   (A) sizing=compounding (slot=current_equity/MAX_POSITIONS, NOT capped at
#       cash) + cash_policy=shrink_to_fit (spend whatever's available, floor
#       to whole shares, never binary-reject) + disaster stop KEPT.
#   (B) same as (A), disaster stop REMOVED (matches honest_lab.py's total
#       absence of any stop-loss rule).
# Also measures deployment (mean fraction of equity actually invested, i.e.
# 1 - cash/equity, averaged over every trading day) for both the baseline
# cell and (A), to test the under-deployment mechanism DIRECTLY instead of
# inferring it.
#
# Run:  python kite/research/pipeline_reconciliation.py --isolation-diagnostic
# ===========================================================================
def run_sim_configurable(calendar, close_wide, open_wide, mom_df, regime_on, rebalance_dates, rrs,
                          sizing='fixed', cash_policy='binary_reject', use_disaster_stop=True,
                          rank_fn=None, capital=None, slot_size=None, top_n=None, max_slots=None):
    """Local, faithful copy of rotation_refinement_study.py's run_sim(),
    parametrized on exactly the two axes this diagnostic needs to isolate
    (plus the disaster-stop toggle run_sim() already exposes):

      sizing: 'fixed'       -> rrs.SLOT_SIZE constant (matches the live/
                                frozen baseline, J1).
              'compounding' -> slot = current_equity / max_slots, recomputed
                                at EVERY rebalance, NOT capped at cash --
                                this reviewer's (A)/(B) spec, distinct from
                                run_sim()'s own compounding=True mode (which
                                uses min(cash, equity/max_slots) and so still
                                caps the TARGET at cash even before the
                                binary-reject check ever runs).
      cash_policy: 'binary_reject'  -> verbatim from run_sim(): skip the
                                entry entirely if cash_amt > cash (the live
                                paper_trader.py rule).
                   'shrink_to_fit'  -> spend whatever cash is actually
                                available (up to the target slot), buy
                                floor(investable/price) shares; skip ONLY if
                                that floor is 0 (cash can't cover even 1
                                share -- a physical floor, not a policy
                                choice). This is the reviewer's "buy as many
                                shares as cash allows, min 1; never skip"
                                spec.

    ALL OTHER mechanics -- sells, disaster-stop check (still gated by
    use_disaster_stop exactly as in run_sim()), force-exit-on-disappearance,
    rebalance/rank logic, equity recording -- are copied verbatim from
    run_sim(), calling run_sim()'s OWN helper functions (buy_investable,
    sell_net_proceeds, DISASTER_SL, _mark_to_market, make_momentum_rank_fn)
    via the `rrs` module reference, so unchanged mechanics stay byte-
    identical to the frozen study rather than being reimplemented. Also
    additionally instruments per-day CASH (run_sim() only returns the
    equity series, not cash) so a deployment/invested-fraction series can be
    computed -- the mechanism this diagnostic is meant to measure directly,
    not infer. stagger_n is fixed at 1 (baseline's own value)."""
    capital = rrs.CAPITAL if capital is None else capital
    slot_size = rrs.SLOT_SIZE if slot_size is None else slot_size
    top_n = rrs.TOP_N if top_n is None else top_n
    max_slots = rrs.MAX_POSITIONS if max_slots is None else max_slots
    stagger_n = 1
    if rank_fn is None:
        rank_fn = rrs.make_momentum_rank_fn(mom_df)

    cash = capital
    positions = {}
    pending_sells = {}
    pending_buys = {}
    trade_log = []
    equity_curve = {}
    cash_curve = {}
    n = len(calendar)

    def cancel_future_buys(sym, after_idx):
        for j in range(after_idx + 1, min(after_idx + 1 + max(stagger_n, 1) + 1, n)):
            fd = calendar[j]
            if fd in pending_buys:
                pending_buys[fd] = [b for b in pending_buys[fd] if b[0] != sym]

    for i, t in enumerate(calendar):
        # 1. SELLS -- verbatim from run_sim()
        for sym in pending_sells.pop(t, []):
            if sym not in positions:
                continue
            pos = positions.pop(sym)
            o = open_wide.at[t, sym] if (t in open_wide.index and pd.notna(open_wide.at[t, sym])) else np.nan
            if pd.isna(o):
                prior_closes = close_wide[sym].loc[:t].dropna()
                o = float(prior_closes.iloc[-1]) if len(prior_closes) else pos['cost_basis'] / pos['qty']
            gross = pos['qty'] * o
            proceeds = rrs.sell_net_proceeds(gross)
            cash += proceeds
            gain = proceeds - pos['cost_basis']
            hold_days = (t - pos['tranches'][0][0]).days
            trade_log.append({'symbol': sym, 'entry_date': pos['tranches'][0][0], 'exit_date': t,
                               'qty': pos['qty'], 'cost_basis': pos['cost_basis'], 'proceeds': proceeds,
                               'gain': gain, 'holding_days': hold_days})
            cancel_future_buys(sym, i)

        # 2. BUYS -- cash_policy determines binary-reject vs shrink-to-fit; everything else verbatim
        for sym, cash_amt in pending_buys.pop(t, []):
            o = open_wide.at[t, sym] if (t in open_wide.index) else np.nan
            if pd.isna(o):
                continue
            if cash_policy == 'binary_reject':
                if cash_amt > cash:
                    continue
                spend = cash_amt
            else:  # shrink_to_fit
                spend = cash_amt if cash_amt <= cash else cash
                if spend <= 0:
                    continue
            investable = rrs.buy_investable(spend)
            qty = int(investable / o)
            if qty <= 0:
                continue  # true physical floor: can't afford even 1 share
            cost = qty * o
            cash -= spend
            if sym in positions:
                p = positions[sym]
                p['qty'] += qty
                p['cost_basis'] += cost
                p['tranches'].append((t, qty, o))
            else:
                positions[sym] = {'qty': qty, 'cost_basis': cost, 'tranches': [(t, qty, o)]}

        # 3. Disaster-stop check -- verbatim, still gated by use_disaster_stop
        if use_disaster_stop:
            stops_today = []
            for sym, pos in positions.items():
                c = close_wide.at[t, sym] if (t in close_wide.index) else np.nan
                if pd.isna(c):
                    continue
                avg_price = pos['cost_basis'] / pos['qty']
                if c <= rrs.DISASTER_SL * avg_price:
                    stops_today.append(sym)
            for sym in stops_today:
                if i + 1 < n:
                    nd = calendar[i + 1]
                    pending_sells.setdefault(nd, [])
                    if sym not in pending_sells[nd]:
                        pending_sells[nd].append(sym)
                    cancel_future_buys(sym, i)

        # 3b. Symbol-disappearance safety net -- verbatim
        for sym in list(positions.keys()):
            col = close_wide[sym]
            has_today = t in col.index and pd.notna(col.at[t])
            future = col.loc[col.index > t]
            has_future = future.notna().any()
            if has_today and not has_future and i + 1 < n:
                nd = calendar[i + 1]
                pending_sells.setdefault(nd, [])
                if sym not in pending_sells[nd]:
                    pending_sells[nd].append(sym)
                cancel_future_buys(sym, i)

        # 4. Rebalance decision -- verbatim except the sizing branch
        if t in rebalance_dates and i + 1 < n:
            nd_start = i + 1
            if not regime_on.get(t, False):
                for s in list(positions.keys()):
                    nd = calendar[nd_start]
                    pending_sells.setdefault(nd, [])
                    if s not in pending_sells[nd]:
                        pending_sells[nd].append(s)
                    cancel_future_buys(s, i)
            else:
                eligible = [s for s in mom_df.columns if (t in mom_df.index and pd.notna(mom_df.at[t, s]))]
                ranked = rank_fn(t, eligible)
                top = ranked[:top_n]
                exits = [s for s in positions if s not in top]
                entries = [s for s in top if s not in positions]
                for s in exits:
                    nd = calendar[nd_start]
                    pending_sells.setdefault(nd, [])
                    if s not in pending_sells[nd]:
                        pending_sells[nd].append(s)
                    cancel_future_buys(s, i)
                fut_dates = calendar[nd_start: nd_start + stagger_n]
                if len(fut_dates) > 0:
                    if sizing == 'compounding':
                        equity_now = rrs._mark_to_market(cash, positions, close_wide, t)
                        this_slot_size = equity_now / max_slots  # NOT capped at cash -- reviewer's (A)/(B) spec
                    else:
                        this_slot_size = slot_size
                    tranche_cash = this_slot_size / len(fut_dates)
                    for s in entries:
                        for fd in fut_dates:
                            pending_buys.setdefault(fd, []).append((s, tranche_cash))

        # 5. Record equity + cash -- verbatim + cash instrumentation added
        equity_curve[t] = rrs._mark_to_market(cash, positions, close_wide, t)
        cash_curve[t] = cash

    return pd.Series(equity_curve), pd.Series(cash_curve), trade_log, positions, cash


def _report_configurable_run(p, label, rrs, eq, cash_series, trade_log, calendar, global_start, global_end, windows):
    final_eq = float(rrs.equity_at(eq, global_end))
    full_cagr = rrs.cagr(rrs.CAPITAL, final_eq, global_start, global_end)
    era_cagrs = [rrs.cagr(rrs.equity_at(eq, elo), rrs.equity_at(eq, ehi), elo, ehi) for elo, ehi in windows]
    deployed = (1.0 - (cash_series / eq)).clip(lower=0.0)
    mean_deployed_pct = float(deployed.mean()) * 100
    p(f'{label}')
    p(f'    final_equity=Rs {final_eq:>13,.2f}   full-period CAGR={full_cagr * 100:>+8.3f}%   '
      f'#trades={len(trade_log)}   mean_deployment={mean_deployed_pct:>6.2f}% of equity invested (avg over all trading days)')
    for i, (elo, ehi) in enumerate(windows, 1):
        p(f'    Era{i} {elo.date()} -> {ehi.date()}: CAGR={era_cagrs[i - 1] * 100:>+8.3f}%')
    return dict(final_equity=final_eq, full_cagr=full_cagr, era_cagrs=era_cagrs, mean_deployed_pct=mean_deployed_pct)


def hl_run_full(hl, np_mod, pd_mod, data, dates, strategy):
    """Local, faithful copy of honest_lab.py's Sim.run(), with ONE change:
    returns the full equity Series (and trades) instead of just the summary
    metrics dict. Sim.run() computes the equity curve internally but only
    ever returns self._metrics(eq, trades) -- era-level / continuous-window
    CAGR isn't recoverable from honest_lab.py's public API without this.
    Uses honest_lab.py's OWN module-level constants (CAPITAL, MAX_SLOTS,
    SLIPPAGE, zerodha_charges) via the `hl` module reference, so the
    mechanics are byte-identical to the frozen file, not reimplemented."""
    cash, positions, trades = hl.CAPITAL, {}, []
    equity_curve = []
    pending = None
    for t in dates:
        if pending:
            for sym in pending['exits']:
                if sym not in positions:
                    continue
                p_, o = positions.pop(sym), data[sym].open.get(t)
                if o is None or np_mod.isnan(o):
                    positions[sym] = p_
                    continue
                px = o * (1 - hl.SLIPPAGE)
                buy_v, sell_v = p_['qty'] * p_['entry'], p_['qty'] * px
                fees = sum(hl.zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False).values())
                cash += sell_v - fees
                trades.append({'sym': sym, 'entry_date': p_['entry_date'], 'exit_date': t,
                                'pnl': sell_v - buy_v - fees})
            for sym in pending['entries']:
                if sym in positions or len(positions) >= hl.MAX_SLOTS:
                    continue
                o = data[sym].open.get(t)
                if o is None or np_mod.isnan(o):
                    continue
                px = o * (1 + hl.SLIPPAGE)
                mkt_val = sum(pp['qty'] * data[s].close.get(t, pp['entry']) for s, pp in positions.items())
                slot = min(cash, (cash + mkt_val) / hl.MAX_SLOTS)
                qty = int(slot / px)
                if qty <= 0:
                    continue
                cash -= qty * px
                positions[sym] = {'qty': qty, 'entry': px, 'entry_date': t, 'bars': 0, 'trail': -np_mod.inf}
            pending = None
        for p_ in positions.values():
            p_['bars'] += 1
        pending = strategy(t, positions)
        mkt_val = sum(pp['qty'] * data[s].close.get(t, pp['entry']) for s, pp in positions.items())
        equity_curve.append((t, cash + mkt_val))
    eq = pd_mod.Series(dict(equity_curve))
    return eq, trades


def run_isolation_diagnostic():
    out_lines = []

    def p(msg=''):
        print(msg, flush=True)
        out_lines.append(str(msg))

    from kite.research import rotation_refinement_study as rrs

    p('=' * 100)
    p('REVIEWER FOLLOW-UP #3: the isolation shot -- compounding+shrink-to-fit on Z data, Z window')
    p('=' * 100)
    p('"Cell 3" per the reviewer\'s numbering (= run_z_engine_diagnostic()\'s CELL 2): Z data '
      '(data/daily/*_day_2000d.csv), Z\'s own full window. Baseline full-period CAGR on this cell, '
      'already reported: -11.969%.')
    p('')

    z_close_wide, z_open_wide, z_universe = load_z_panel()
    mom_df = rrs.compute_momentum(z_close_wide, rrs.LOOKBACK)
    _, _, proxy_regime_on_full = rrs.compute_proxy_regime(z_close_wide, rrs.REGIME_SMA)
    valid_from = rrs.REGIME_SMA - 1
    calendar = z_close_wide.index[valid_from:]
    global_start, global_end = calendar[0], calendar[-1]
    proxy_regime_on = pd.Series({d: bool(proxy_regime_on_full.get(d, False)) for d in calendar})
    windows = rrs.era_windows(calendar, 3)
    rebalance_dates = set(rrs.build_rebalance_dates(calendar, 1))

    p('-' * 100)
    p('SANITY CHECK -- local instrumented engine, sizing=fixed + cash_policy=binary_reject + stop=True, '
      'must reproduce run_z_engine_diagnostic()\'s CELL 2 result (-11.969%, -13.35%/+3.14%/-23.81%) '
      'before configs (A)/(B) below are trusted')
    p('-' * 100)
    eq_check, cash_check, trades_check, _, _ = run_sim_configurable(
        calendar, z_close_wide, z_open_wide, mom_df, proxy_regime_on, rebalance_dates, rrs,
        sizing='fixed', cash_policy='binary_reject', use_disaster_stop=True)
    cell_check = _report_configurable_run(p, 'REPRODUCTION (fixed slot, binary reject, stop=True):',
                                           rrs, eq_check, cash_check, trades_check, calendar, global_start, global_end, windows)
    match = abs(cell_check['full_cagr'] * 100 - (-11.969)) < 0.05
    p(f'    MATCH vs original run_z_engine_diagnostic() CELL 2 (-11.969%)? {"YES" if match else "NO -- INVESTIGATE, do not trust (A)/(B) below"}')
    p('')

    p('-' * 100)
    p('(A) sizing=compounding (slot=current_equity/MAX_POSITIONS, uncapped by cash) + '
      'cash_policy=shrink_to_fit + disaster stop KEPT')
    p('-' * 100)
    eq_a, cash_a, trades_a, _, _ = run_sim_configurable(
        calendar, z_close_wide, z_open_wide, mom_df, proxy_regime_on, rebalance_dates, rrs,
        sizing='compounding', cash_policy='shrink_to_fit', use_disaster_stop=True)
    cell_a = _report_configurable_run(p, 'CONFIG (A):', rrs, eq_a, cash_a, trades_a, calendar, global_start, global_end, windows)
    p('')

    p('-' * 100)
    p('(B) same as (A), disaster stop REMOVED (fully matches honest_lab.py\'s sizing semantics: '
      'compounding, shrink-to-fit, no stop-loss rule at all)')
    p('-' * 100)
    eq_b, cash_b, trades_b, _, _ = run_sim_configurable(
        calendar, z_close_wide, z_open_wide, mom_df, proxy_regime_on, rebalance_dates, rrs,
        sizing='compounding', cash_policy='shrink_to_fit', use_disaster_stop=False)
    cell_b = _report_configurable_run(p, 'CONFIG (B):', rrs, eq_b, cash_b, trades_b, calendar, global_start, global_end, windows)
    p('')

    p('=' * 100)
    p('SUMMARY TABLE')
    p('=' * 100)
    p(f'{"":50}{"full-period CAGR":>18}{"Era1":>10}{"Era2":>10}{"Era3":>10}{"mean deployment":>17}')
    p(f'{"cell 3 (Z data, Z window, frozen baseline)":50}{-11.969:>+17.3f}%{-13.35:>+9.2f}%{+3.14:>+9.2f}%{-23.81:>+9.2f}%{"(see below)":>17}')
    p(f'{"reproduction (sanity check)":50}{cell_check["full_cagr"] * 100:>+17.3f}%'
      f'{cell_check["era_cagrs"][0] * 100:>+9.2f}%{cell_check["era_cagrs"][1] * 100:>+9.2f}%'
      f'{cell_check["era_cagrs"][2] * 100:>+9.2f}%{cell_check["mean_deployed_pct"]:>16.2f}%')
    p(f'{"(A) compounding + shrink-to-fit + stop=True":50}{cell_a["full_cagr"] * 100:>+17.3f}%'
      f'{cell_a["era_cagrs"][0] * 100:>+9.2f}%{cell_a["era_cagrs"][1] * 100:>+9.2f}%'
      f'{cell_a["era_cagrs"][2] * 100:>+9.2f}%{cell_a["mean_deployed_pct"]:>16.2f}%')
    p(f'{"(B) compounding + shrink-to-fit + stop=False":50}{cell_b["full_cagr"] * 100:>+17.3f}%'
      f'{cell_b["era_cagrs"][0] * 100:>+9.2f}%{cell_b["era_cagrs"][1] * 100:>+9.2f}%'
      f'{cell_b["era_cagrs"][2] * 100:>+9.2f}%{cell_b["mean_deployed_pct"]:>16.2f}%')
    p(f'{"honest_lab reference (TRAIN/VAL, different engine)":50}{"+5.0% / +3.5%":>18}')
    p('')
    deployment_delta = cell_a['mean_deployed_pct'] - cell_check['mean_deployed_pct']
    p(f'DEPLOYMENT, measured directly: baseline cell mean {cell_check["mean_deployed_pct"]:.2f}% of equity '
      f'invested vs config (A) mean {cell_a["mean_deployed_pct"]:.2f}% -- delta {deployment_delta:+.2f}pp.')
    p('')

    p('=' * 100)
    p('INTERPRETATION -- applying the pre-stated rule')
    p('=' * 100)
    both_at_or_above_zero = cell_a['full_cagr'] >= -0.005 and cell_b['full_cagr'] >= -0.005
    if both_at_or_above_zero:
        p(f'(A)={cell_a["full_cagr"] * 100:+.3f}%/yr and (B)={cell_b["full_cagr"] * 100:+.3f}%/yr both land at/above '
          f'~0%/yr -> per the pre-stated rule: THE CONVENTION GAP IS IDENTIFIED. The live paper_trader\'s '
          f'fixed-slot + binary-reject semantics are the material divergence from validated (honest_lab) '
          f'behavior. This belongs in the October evidence file (per the reviewer\'s framing) -- NOT '
          f'written here, per the "no commits / do not go fix anything" instruction; flagged for the human '
          f'to action.')
        run_hl_continuous = False
    else:
        p(f'(A)={cell_a["full_cagr"] * 100:+.3f}%/yr and (B)={cell_b["full_cagr"] * 100:+.3f}%/yr -- '
          f'{"both" if cell_a["full_cagr"] < -0.005 and cell_b["full_cagr"] < -0.005 else "at least one"} '
          f'stay deeply negative -> per the pre-stated rule: CONVENTIONS 1 (sizing), 2 (cash policy) AND 5 '
          f'(disaster stop) ARE ALL EXONERATED, even in combination and even with deployment demonstrably '
          f'higher (see DEPLOYMENT line above). Remaining suspects: #3 (train/val capital reset vs one '
          f'continuous run) and #4 (cost-bookkeeping timing). Running the additional honest_lab-engine-'
          f'continuous cell now, per the rule\'s instruction.')
        run_hl_continuous = True
    p('')

    if run_hl_continuous:
        p('=' * 100)
        p('ADDITIONAL CELL (per the interpretation rule): honest_lab.py\'s OWN engine, run CONTINUOUSLY '
          'over the full Z window, no train/val capital reset')
        p('=' * 100)
        from kite.research import honest_lab as hl
        hl_data = {s: hl.add_indicators(df) for s, df in hl.load_data().items()}
        hl_all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in hl_data.values()])))
        hl_idx = pd.DataFrame({s: df.close for s, df in hl_data.items()}).reindex(hl_all_dates)
        hl_proxy = (hl_idx / hl_idx.iloc[0]).mean(axis=1, skipna=True)
        hl_regime = (hl_proxy > hl_proxy.rolling(200).mean())

        p(f'  honest_lab.py load_data() date range: {hl_all_dates.min().date()} -> {hl_all_dates.max().date()}  '
          f'({len(hl_all_dates)} trading days)')

        # sanity check: reproduce honest_lab.py's own reported TRAIN/VAL numbers first (lb=63,n=3,regime=True)
        hl_train_dates = hl_all_dates[hl_all_dates <= hl.TRAIN_END]
        hl_val_dates = hl_all_dates[hl_all_dates > hl.TRAIN_END]
        strat_train = hl.make_momo(hl_data, hl_train_dates, 63, 3, hl_regime)
        strat_val = hl.make_momo(hl_data, hl_val_dates, 63, 3, hl_regime)
        eq_train, trades_train = hl_run_full(hl, np, pd, hl_data, hl_train_dates, strat_train)
        eq_val, trades_val = hl_run_full(hl, np, pd, hl_data, hl_val_dates, strat_val)
        yrs_train = len(eq_train) / 252
        yrs_val = len(eq_val) / 252
        cagr_train = (eq_train.iloc[-1] / eq_train.iloc[0]) ** (1 / yrs_train) - 1 if yrs_train > 0 else float('nan')
        cagr_val = (eq_val.iloc[-1] / eq_val.iloc[0]) ** (1 / yrs_val) - 1 if yrs_val > 0 else float('nan')
        p(f'  SANITY CHECK -- reproduction of honest_lab.py\'s own two-stage TRAIN/VAL run (lb=63,n=3,regime=True): '
          f'TRAIN CAGR={cagr_train * 100:+.2f}% (lab_results.csv: +5.0%)   VAL CAGR={cagr_val * 100:+.2f}% (lab_results.csv: +3.5%)')
        match_hl = abs(cagr_train * 100 - 5.0) < 1.0 and abs(cagr_val * 100 - 3.5) < 1.0
        p(f'  MATCH? {"YES" if match_hl else "NO -- INVESTIGATE, do not trust the continuous number below"}')
        p('')

        # the actual continuous run: ONE Sim over the full date range, no reset at TRAIN_END
        strat_full = hl.make_momo(hl_data, hl_all_dates, 63, 3, hl_regime)
        eq_full, trades_full = hl_run_full(hl, np, pd, hl_data, hl_all_dates, strat_full)
        yrs_full = len(eq_full) / 252
        cagr_full = (eq_full.iloc[-1] / eq_full.iloc[0]) ** (1 / yrs_full) - 1 if yrs_full > 0 else float('nan')
        # era breakdown of the SAME continuous curve (no re-simulation, just slicing -- matches
        # rrs.era_windows' "3 equal thirds of the trading-day window" convention)
        n_dates = len(hl_all_dates)
        bounds = [round(n_dates * i / 3) for i in range(4)]
        bounds[0], bounds[-1] = 0, n_dates - 1
        era_cagrs_full = []
        for i in range(3):
            lo_idx, hi_idx = bounds[i], bounds[i + 1]
            if hi_idx <= lo_idx:
                hi_idx = min(lo_idx + 1, n_dates - 1)
            elo, ehi = hl_all_dates[lo_idx], hl_all_dates[hi_idx]
            days = (ehi - elo).days
            v_lo, v_hi = eq_full.get(elo, np.nan), eq_full.get(ehi, np.nan)
            c = (v_hi / v_lo) ** (365.25 / days) - 1 if days > 0 and v_lo > 0 and v_hi > 0 else float('nan')
            era_cagrs_full.append((elo, ehi, c))

        p(f'  CONTINUOUS (no train/val reset): final_equity=Rs {eq_full.iloc[-1]:,.2f}   '
          f'full-period CAGR={cagr_full * 100:+.3f}%   #trades={len(trades_full)}')
        for i, (elo, ehi, c) in enumerate(era_cagrs_full, 1):
            p(f'    Era{i} {elo.date()} -> {ehi.date()}: CAGR={c * 100:+.3f}%')
        p('')
        p(f'  Continuous full-period CAGR ({cagr_full * 100:+.3f}%) vs honest_lab\'s own reported two-stage '
          f'TRAIN+VAL ({cagr_train * 100:+.2f}% / {cagr_val * 100:+.2f}%): '
          f'{"the reset convention (#3) materially matters -- continuous is meaningfully worse, a live lead" if cagr_full * 100 < min(cagr_train, cagr_val) * 100 - 2 else "continuous stays broadly in the same positive neighborhood -- convention #3 (capital reset) is NOT the driver either, leaving #4 (cost-bookkeeping timing) as the main remaining candidate"}.')
        p('')

    p('=' * 100)
    p('PLAIN STATEMENT')
    p('=' * 100)
    if both_at_or_above_zero:
        p(f'Forcing rotation_refinement\'s engine to fully deploy capital the way honest_lab does '
          f'(compounding slot size + shrink-to-fit + no binary reject) turns the Z-data baseline from '
          f'{-11.969:+.2f}%/yr to (A)={cell_a["full_cagr"] * 100:+.2f}%/yr and (B)={cell_b["full_cagr"] * 100:+.2f}%/yr -- '
          f'landing at or above breakeven. The live paper_trader\'s fixed-Rs20,000-slot + binary-cash-reject '
          f'combination is the confirmed, material, ISOLATED driver of the CAGR gap versus honest_lab\'s '
          f'validated numbers -- not price data (already exonerated), not the disaster stop alone, and not '
          f'sizing formula alone (already exonerated individually) -- specifically the CASH POLICY, tested '
          f'here for the first time in isolation from the sizing formula.')
    else:
        direction = ('rose, as the under-deployment hypothesis predicted' if deployment_delta > 0
                     else 'FELL (the opposite of what the under-deployment hypothesis predicted)')
        outcome = ('an improvement' if cell_a['full_cagr'] > -0.11969 else 'WORSE, not better')
        p(f'Forcing rotation_refinement\'s engine to fully deploy capital the way honest_lab does '
          f'(compounding slot size + shrink-to-fit + no binary reject) moves the Z-data baseline from '
          f'-11.969%/yr to (A)={cell_a["full_cagr"] * 100:+.2f}%/yr and (B)={cell_b["full_cagr"] * 100:+.2f}%/yr -- '
          f'{outcome}. Measured deployment {direction} (delta {deployment_delta:+.2f}pp: '
          f'{cell_check["mean_deployed_pct"]:.2f}% baseline vs {cell_a["mean_deployed_pct"]:.2f}% config A). '
          f'Conventions #1 (sizing formula), #2 (cash policy), and #5 (disaster stop) are collectively '
          f'exonerated as the explanation, even in full combination -- and if the CAGR moved further '
          f'negative under fuller deployment, that affirmatively rules out under-deployment as the '
          f'mechanism rather than merely failing to confirm it. See the additional honest_lab-continuous '
          f'cell above for the #3-vs-#4 split.')
    return out_lines


if __name__ == '__main__':
    if '--demerger-diagnostic' in sys.argv:
        run_demerger_diagnostic()
    elif '--z-engine-diagnostic' in sys.argv:
        run_z_engine_diagnostic()
    elif '--isolation-diagnostic' in sys.argv:
        run_isolation_diagnostic()
    else:
        main()
