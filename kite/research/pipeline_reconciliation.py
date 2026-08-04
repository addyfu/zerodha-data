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


if __name__ == '__main__':
    main()
