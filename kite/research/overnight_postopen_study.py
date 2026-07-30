"""Overnight-Information Post-Open Drift study (pre-registered, FROZEN).

FROZEN SPEC (read this first, do not deviate without a spec amendment):
    docs/superpowers/specs/2026-07-30-overnight-postopen-design.md
    Status: APPROVED & FROZEN (user, 2026-07-30).

WHAT THIS IS
------------
Tests whether India's post-open drift retains ANY trace of overnight foreign
signals (S&P 500, front crude, USDINR) AFTER controlling for the gap that
already priced them, plus an ADR-fade piggyback (INFY/WIT/IBN/HDB overnight
ADR returns vs their NSE POST returns). Stated prior: NULL. 0 findings
expected; any finding routes to a phase-2 spec, incubator path only.

MODES
-----
    python kite/research/overnight_postopen_study.py --fetch
        Fetches the 3 market signals + 4 ADR signals from yfinance, maps each
        foreign close to the NEXT Indian trading day (the frozen, timezone-
        sensitive rule -- see map_to_indian_days()), caches raw closes +
        mapped signal series to data/overnight_signals/*.csv (rerunnable
        offline after this), and prints: series ranges, alignment %% against
        the 2019-10..2026-07 Indian calendar, 5 sample mappings around a
        weekend + a US holiday per source, and the mapping timing assert.
        Writes overnight_postopen_fetch_report.txt. No regression, no verdict.

    python kite/research/overnight_postopen_study.py --smoke
        Full pipeline (signals from cache, panel restricted to the most
        recent ~3 months of bhavcopy files) end to end. SMOKE IS NOT A
        VERDICT -- with only ~3 months of data the TRAIN era (2019-10..
        2023-12) is empty by construction, so criteria 2/3 print N/A. Every
        page is stamped SMOKE. Writes overnight_postopen_results_smoke.txt.

    python kite/research/overnight_postopen_study.py
        Full verdict run (signals from cache if present else fetched;
        whole panel 2019-10..2026-07). Writes overnight_postopen_results.txt.

    Add --force-fetch to --smoke/full run to bypass the signal cache.

CONVENTIONS REUSED (not reinvented)
------------------------------------
- Panel loading (SYMBOL/SERIES/OPEN_PRICE/CLOSE_PRICE/TURNOVER_LACS, filename-
  derived trading day, EQ-only, drop-duplicate symbol+date), corp-action
  back-adjustment of OPEN/CLOSE (cumulative product of factors with ex_date
  strictly after the row's date), and the eligibility gate (turnover >=
  Rs 2cr, adj close >= Rs 20): amfi_band_study.py / exhumation_sweep.py /
  delivery_factor_study.py, verbatim conventions, re-implemented here (not
  imported -- exhumation_sweep.py pulls in the whole strategy registry at
  import time, which this study does not need).
- LAGGED eligibility membership for the EW eligible-universe means: the
  exhumation lesson (exhumation_sweep.py module docstring, implementation
  choice 2b) -- membership for day t is decided from day t-1's same-day
  eligibility flag, never day t's own (same-day membership is look-ahead:
  the Rs 20 floor would admit a stock to the EW basket on the very day it
  jumps over the line). data/exhumation/ew_returns.csv is CLOSE-to-CLOSE and
  does not carry GAP/POST -- recomputed here from the panel with the SAME
  lagged-membership rule (MarketPanel.bench_member below), not reused as-is.
- Costs: zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False)
  ['total'] -- the KEY, never sum(.values()) (double-counts) -- on a
  Rs 20,000 position, matching exhumation_sweep.py / amfi_band_study.py.
- Cluster-robust inference: amfi_band_study.py's cluster_t is a one-sample
  (mean-only) special case of the one-way Liang-Zeger sandwich with the
  Stata-style finite-sample correction c = [G/(G-1)]*[(N-1)/(N-k)]. This
  study needs the general k-regressor OLS version (POST = a + b*SIGNAL +
  c*GAP); ols_cluster_robust() below implements it and reduces to
  amfi_band_study.cluster_t exactly when X is a single constant column
  (k=1). Hand-verified against statsmodels (installed in this environment)
  on a synthetic clustered panel -- see verify_cluster_ols(), run
  automatically at the top of every mode and printed for the reviewer.

IMPLEMENTATION CHOICES THE SPEC DOES NOT FULLY PIN DOWN (flagged, not buried)
------------------------------------------------------------------------------
(1) FOREIGN "CLOSE" CLOCK TIME, for the timing sanity assert only (spec
    requirement 2: "no foreign close maps to an Indian day that starts
    before the foreign session ended"). yfinance gives a daily bar labeled
    with a calendar date, not an intraday timestamp. Assumed close clock
    time, local exchange time: 16:00 America/New_York for ^GSPC and the 4
    ADR names (actual NYSE close); 17:00 America/New_York for CL=F/INR=X
    (the "New York 5pm cut", the standard industry convention for a daily
    FX/commodity mark -- the spec itself calls these "conventions" for
    24h-ish markets and says this is acceptable for daily-horizon
    inference). The assert is run against these assumed times; it would
    also pass under any assumed close time up to ~23:00 ET on a normal
    Mon-Thu (Indian open is ~09:45 IST the *next* calendar day in ET terms),
    so the exact clock-time choice is not load-bearing for the assert
    itself, only for the printed sample table.
(2) yfinance auto_adjust=True (split+dividend adjusted Close) is used for
    every fetched series, to avoid spurious return spikes at ADR stock
    splits -- standard practice for a return-series study. This differs
    from the Indian panel's own convention (adjusts for splits/bonuses via
    corp_actions_adjustments.csv, dividends NOT stripped from the close);
    the mismatch only matters on ADR ex-dividend dates and is a second-
    order effect on daily log returns, stated not hidden.
(3) STOOQ FALLBACK NOT USABLE HERE: the spec's fallback source
    (https://stooq.com/q/d/l/) returned an anti-bot JavaScript challenge
    page (no CSV) when probed from this environment, not real data.
    yfinance (pip-installed, network-verified working for all 7 tickers
    over 2019-07..today before this script was written) is used as the
    SOLE source; the CL=F/INR=X fallback tickers (BZ=F/USDINR=X) are yfinance
    tickers, wired for redundancy against a single-ticker yfinance outage,
    not a different data vendor.
(4) TRADEABILITY "FAVORABLE TERCILE" DIRECTION. The spec's tradeability
    criterion says "favorable-signal-tercile days" without pinning which
    tercile. Market arm (sign not pre-declared): favorable = the tercile
    predicted favorable by the TRAIN-era regression's b sign (b_train > 0
    -> top tercile of SIGNAL(t); b_train < 0 -> bottom tercile), applied
    to VALIDATION days using TRAIN-era breakpoints only (per task
    instruction). ADR arm (fade IS pre-declared, b must be negative):
    favorable = bottom tercile of the overnight ADR signal, pooled across
    the 4 names' TRAIN-era values for the breakpoints (matching the pooled
    regression's name-pooling convention, week-clustered only, stated).
(5) TRADE CONSTRUCTION FOR THE MARKET ARM. "Enter eligible-universe basket"
    is read as: on each favorable validation day t, take a Rs 20,000
    position in EVERY member of the day-t LAGGED-membership eligible
    universe (the same basket the EW_POST(t,k) regression target is built
    from), buy at open(t), sell at close(t+k-1), 0.2%/side slippage +
    zerodha_charges delivery costs -- one simulated trade per (stock, day),
    "mean net per-trade" averaged over all of them. This is the natural
    trade-level analogue of the EW cross-sectional mean used in the
    regression; a whole-basket NAV-style implementation was not chosen
    because "Rs 20k slots" (spec wording) is a per-position sizing unit,
    not a per-basket one.
(6) DEFERRED, NOT IMPLEMENTED (both explicitly non-verdict-bearing per spec):
    GIFT Nifty robustness line (post-2023-07 only, optional per spec) and
    the sector splits (IT vs USDINR/Nasdaq, OMC/paints vs crude, "reported
    as information only, never verdict-bearing"). Neither touches the 11
    frozen verdict cells; both can be added later without amending the
    frozen verdict logic.

Usage:
    python kite/research/overnight_postopen_study.py --fetch
    python kite/research/overnight_postopen_study.py --smoke
    python kite/research/overnight_postopen_study.py
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from kite.config import zerodha_charges  # noqa: E402  (['total'] only, see docstring)

SPEC = 'docs/superpowers/specs/2026-07-30-overnight-postopen-design.md'
PANEL_DIR = ROOT / 'data' / 'bhavcopy_full'
CORP_ACTIONS_PATH = ROOT / 'data' / 'corp_actions_adjustments.csv'
SIGNALS_DIR = ROOT / 'data' / 'overnight_signals'
OUT_DIR = Path(__file__).resolve().parent
OUT_FILE = OUT_DIR / 'overnight_postopen_results.txt'
OUT_FILE_SMOKE = OUT_DIR / 'overnight_postopen_results_smoke.txt'
OUT_FILE_FETCH = OUT_DIR / 'overnight_postopen_fetch_report.txt'

# ---------------------------------------------------------------------------
# Frozen constants
# ---------------------------------------------------------------------------
MIN_TURNOVER_LACS = 200.0     # Rs 2 crore  (repo convention)
MIN_PRICE = 20.0              # Rs 20 adjusted close
POSITION_RS = 20_000.0        # per-trade notional, both arms (spec: "Rs 20k slots")
SLIP_WIDE = 0.002             # 0.2%/side, market arm (wide-universe tier)
SLIP_ADR = 0.0005             # 0.05%/side, ADR arm (4-name tier)

K_MARKET = [1, 3, 10]
K_ADR = [1, 3]

FETCH_START = pd.Timestamp('2019-07-01')
TRAIN_START, TRAIN_END = pd.Timestamp('2019-10-01'), pd.Timestamp('2023-12-31')
VAL_START, VAL_END = pd.Timestamp('2024-01-01'), pd.Timestamp('2026-07-31')
ALIGN_START, ALIGN_END = pd.Timestamp('2019-10-01'), pd.Timestamp('2026-07-31')
ALIGN_GATE = 0.95             # >= 95% of Indian trading days must receive a signal

T_THRESHOLD = 2.9             # Bonferroni bar for 11 declared cells, sign-free two-sided
DECLARED_CELLS = 11
MIN_ERA_ROWS = 10             # below this an era regression is not attempted (returns None)
MIN_TERCILE_ROWS = 30         # below this tradeability tercile breakpoints are not attempted

SIGNAL_DEFS = {
    'SP500':  {'primary': '^GSPC', 'fallback': None,       'close_hour_et': 16},
    'CRUDE':  {'primary': 'CL=F',  'fallback': 'BZ=F',      'close_hour_et': 17},
    'USDINR': {'primary': 'INR=X', 'fallback': 'USDINR=X',  'close_hour_et': 17},
}
ADR_DEFS = {
    'INFY': {'primary': 'INFY', 'fallback': None, 'close_hour_et': 16, 'nse_symbol': 'INFY'},
    'WIT':  {'primary': 'WIT',  'fallback': None, 'close_hour_et': 16, 'nse_symbol': 'WIPRO'},
    'IBN':  {'primary': 'IBN',  'fallback': None, 'close_hour_et': 16, 'nse_symbol': 'ICICIBANK'},
    'HDB':  {'primary': 'HDB',  'fallback': None, 'close_hour_et': 16, 'nse_symbol': 'HDFCBANK'},
}

FNAME_DATE_RE = re.compile(r'sec_bhavdata_full_(\d{2})(\d{2})(\d{4})\.csv$', re.IGNORECASE)
NEEDED_COLS = ['SYMBOL', 'SERIES', 'OPEN_PRICE', 'CLOSE_PRICE', 'TURNOVER_LACS']

_LINES = []


def log(msg=''):
    print(msg, flush=True)
    _LINES.append(str(msg))


def flush_out(path):
    path.write_text('\n'.join(_LINES) + '\n', encoding='utf-8')


def pct(x, nd=3):
    return 'n/a' if x is None or not np.isfinite(x) else f'{x * 100:+.{nd}f}%'


def num(x, nd=3):
    return 'n/a' if x is None or not np.isfinite(x) else f'{x:.{nd}f}'


# ===========================================================================
# INDIAN CALENDAR  (from bhavcopy FILENAMES, robust, cheap -- no CSV reads)
# ===========================================================================
def load_indian_calendar(data_dir=PANEL_DIR):
    files = sorted(data_dir.glob('sec_bhavdata_full_*.csv'))
    dates = []
    for f in files:
        m = FNAME_DATE_RE.search(f.name)
        if not m:
            continue
        dates.append(pd.Timestamp(year=int(m.group(3)), month=int(m.group(2)), day=int(m.group(1))))
    if not dates:
        sys.exit(f'HALTED: no bhavcopy files under {data_dir}. Run fetch_bhavcopy_full.py first.')
    return pd.DatetimeIndex(sorted(dates))


def panel_files_in_range(lo=None, hi=None, data_dir=PANEL_DIR):
    out = []
    for f in data_dir.glob('sec_bhavdata_full_*.csv'):
        m = FNAME_DATE_RE.search(f.name)
        if not m:
            continue
        d = pd.Timestamp(year=int(m.group(3)), month=int(m.group(2)), day=int(m.group(1)))
        if (lo is None or d >= lo) and (hi is None or d <= hi):
            out.append((d, f))
    return sorted(out)


# ===========================================================================
# YFINANCE FETCH  (lazy import -- only needed on a cache miss / --fetch)
# ===========================================================================
def fetch_yf_close(ticker, start, end):
    import yfinance as yf
    t = yf.Ticker(ticker)
    h = t.history(start=start.strftime('%Y-%m-%d'),
                  end=(end + pd.Timedelta(days=1)).strftime('%Y-%m-%d'),
                  auto_adjust=True)
    if h is None or h.empty or 'Close' not in h.columns:
        raise RuntimeError(f'{ticker}: empty/invalid yfinance history')
    idx = pd.DatetimeIndex([pd.Timestamp(ts.date()) for ts in h.index])
    s = pd.Series(h['Close'].to_numpy(dtype=float), index=idx, name=ticker)
    s = s[~s.index.duplicated(keep='last')].sort_index()
    s = s[np.isfinite(s.to_numpy())]
    if len(s) < 100:
        raise RuntimeError(f'{ticker}: only {len(s)} usable rows returned')
    return s


def fetch_foreign_series(defn, start, end):
    primary = defn['primary']
    try:
        s = fetch_yf_close(primary, start, end)
        return s, primary
    except Exception as e1:
        fb = defn.get('fallback')
        if fb:
            log(f'  WARN: {primary} fetch failed ({type(e1).__name__}: {e1}); trying fallback {fb}')
            s = fetch_yf_close(fb, start, end)
            return s, fb
        raise


# ===========================================================================
# SIGNAL-DATE MAPPING  (the frozen, timezone-sensitive bug surface)
# ===========================================================================
def map_to_indian_days(close_series, indian_calendar, close_hour_et, label):
    """foreign close of calendar date d -> the NEXT Indian trading day t > d.

    Signal(t) = log(close_d / close_prev_d) where d is the MOST RECENT
    foreign date mapping to t and prev_d is the FOREIGN series' own
    immediately preceding available date (i.e. across the foreign series'
    OWN holidays, per spec point 3 -- shift(1) on the sorted foreign series,
    not a join against the Indian calendar).

    Multiple foreign dates can map to the same Indian day t only when an
    Indian holiday has no foreign-market counterpart; in that case the
    LAST (latest) foreign date's return is used for t (the most current
    information available strictly before t's open) -- equivalent to a
    merge_asof of the Indian calendar against the foreign close series.

    Returns (signal: pd.Series indexed by Indian date, map_df: every
    (foreign_date -> mapped_indian_date) pair with the assert's clock-time
    columns, for sample printing).
    """
    s = close_series.sort_index()
    vals = s.to_numpy(dtype=float)
    log_ret = np.log(vals[1:] / vals[:-1])
    d_dates = pd.DatetimeIndex(s.index[1:])

    cal_days = indian_calendar.values.astype('datetime64[D]')
    d_days = d_dates.values.astype('datetime64[D]')
    pos = np.searchsorted(cal_days, d_days, side='right')   # first Indian day STRICTLY > d
    valid = pos < len(cal_days)

    map_df = pd.DataFrame({
        'foreign_date': d_dates[valid],
        'mapped_indian_date': pd.DatetimeIndex(cal_days[pos[valid]]),
        'log_ret': log_ret[valid],
    })

    # --- timing sanity assert: foreign close must precede the Indian day's 09:15 IST open ---
    close_ist = [
        datetime(ts.year, ts.month, ts.day, close_hour_et, 0, tzinfo=ZoneInfo('America/New_York'))
        .astimezone(ZoneInfo('Asia/Kolkata'))
        for ts in map_df['foreign_date']
    ]
    open_ist = [
        datetime(ts.year, ts.month, ts.day, 9, 15, tzinfo=ZoneInfo('Asia/Kolkata'))
        for ts in map_df['mapped_indian_date']
    ]
    map_df['close_ist'] = close_ist
    map_df['indian_open_ist'] = open_ist
    viol_mask = [a >= b for a, b in zip(close_ist, open_ist)]
    if any(viol_mask):
        viol = map_df[viol_mask]
        log(f'HALT: {label} signal-date mapping timing sanity FAILED: {len(viol)} case(s) where the '
            f'assumed foreign close ({close_hour_et}:00 America/New_York) falls at/after the mapped '
            f"Indian day's 09:15 IST open.")
        r = viol.iloc[0]
        log(f'  first offender: foreign_date={r.foreign_date.date()} mapped_indian_date='
            f'{r.mapped_indian_date.date()} close_ist={r.close_ist} indian_open_ist={r.indian_open_ist}')
        sys.exit(f'HALTED: {label} mapping timing sanity check failed ({len(viol)} violation(s)).')

    map_df = map_df.sort_values('foreign_date').reset_index(drop=True)
    signal = map_df.groupby('mapped_indian_date')['log_ret'].last()
    signal.index.name = 'date'
    signal.name = label
    return signal, map_df


def alignment_pct(signal_series, indian_calendar, lo=ALIGN_START, hi=ALIGN_END):
    window = indian_calendar[(indian_calendar >= lo) & (indian_calendar <= hi)]
    covered = signal_series.index.intersection(window)
    p = (len(covered) / len(window)) if len(window) else 0.0
    return p, len(covered), len(window)


def print_mapping_samples(map_df, label, n=3):
    log(f'  Sample mappings for {label} (assert PASSED: close_ist always < indian_open_ist):')
    # Drop the pre-panel pileup: every foreign date before the Indian calendar's first
    # trading day collapses onto that single first day (FETCH_START is 3 months before
    # the panel starts, on purpose, so the very first Indian day has a real prior close
    # to compute a return from) -- excluding it keeps the printed examples representative
    # of ordinary day-to-day operation instead of that one-off startup artifact.
    clean = map_df[map_df['mapped_indian_date'] != map_df['mapped_indian_date'].min()]
    fridays = clean[clean['foreign_date'].dt.weekday == 4].head(n)
    for _, r in fridays.iterrows():
        log(f'    WEEKEND   {r.foreign_date.date()} ({r.foreign_date.day_name():<9}) -> '
            f'{r.mapped_indian_date.date()} ({r.mapped_indian_date.day_name():<9})  '
            f'close_ist={r.close_ist.strftime("%Y-%m-%d %H:%M%z")}  '
            f'indian_open_ist={r.indian_open_ist.strftime("%Y-%m-%d %H:%M%z")}  '
            f'log_ret={r.log_ret:+.5f}')
    gap_days = clean['foreign_date'].diff().dt.days
    hol = clean[gap_days >= 4].head(n)
    for _, r in hol.iterrows():
        log(f'    HOLIDAY-GAP {r.foreign_date.date()} ({r.foreign_date.day_name():<9}) -> '
            f'{r.mapped_indian_date.date()} ({r.mapped_indian_date.day_name():<9})  '
            f'close_ist={r.close_ist.strftime("%Y-%m-%d %H:%M%z")}  '
            f'indian_open_ist={r.indian_open_ist.strftime("%Y-%m-%d %H:%M%z")}  '
            f'log_ret={r.log_ret:+.5f}  (gap {int(gap_days.loc[r.name])}d since prior foreign close)')
    if fridays.empty and hol.empty:
        log('    (no weekend/holiday examples found in this window -- unexpected for >1 week of data)')


# ===========================================================================
# SIGNAL CACHE  (data/overnight_signals/*.csv -- rerunnable offline)
# ===========================================================================
def _cache_paths(prefix):
    return (SIGNALS_DIR / f'{prefix}_close.csv',
            SIGNALS_DIR / f'{prefix}_signal.csv',
            SIGNALS_DIR / f'{prefix}_meta.json')


def fetch_and_cache_signal(prefix, defn, indian_calendar, label):
    close_s, source = fetch_foreign_series(defn, FETCH_START, pd.Timestamp.today().normalize())
    signal, map_df = map_to_indian_days(close_s, indian_calendar, defn['close_hour_et'], label)
    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    close_p, sig_p, meta_p = _cache_paths(prefix)
    close_s.rename_axis('date').reset_index(name='close').to_csv(close_p, index=False)
    # Cache the COLLAPSED one-row-per-Indian-day series (`signal`), not the raw
    # pre-collapse map_df (one row per foreign date) -- a prior version of this
    # function cached map_df directly, which silently produced duplicate Indian-
    # date rows in the cache (multiple foreign dates map to the same Indian day
    # across an Indian-only holiday) and blew up downstream reindex() calls.
    # Caught by --smoke; fixed by re-deriving foreign_date_used per Indian day.
    fd_used = map_df.groupby('mapped_indian_date')['foreign_date'].last()
    out_df = pd.DataFrame({'indian_date': signal.index, 'foreign_date': fd_used.reindex(signal.index).to_numpy(),
                           'signal': signal.to_numpy()})
    assert not out_df['indian_date'].duplicated().any(), (
        f'{label}: BUG -- signal cache has duplicate indian_date rows after collapse')
    out_df.to_csv(sig_p, index=False)
    meta = {
        'source': source, 'fetched_utc': pd.Timestamp.utcnow().isoformat(),
        'n_close_rows': int(len(close_s)),
        'foreign_min': str(close_s.index.min().date()), 'foreign_max': str(close_s.index.max().date()),
        'n_signal_rows': int(len(signal)),
    }
    meta_p.write_text(json.dumps(meta, indent=2), encoding='utf-8')
    return signal, map_df, meta


def load_or_fetch_signal(prefix, defn, indian_calendar, label, force_fetch=False):
    close_p, sig_p, meta_p = _cache_paths(prefix)
    if not force_fetch and sig_p.exists() and meta_p.exists():
        sig_df = pd.read_csv(sig_p, parse_dates=['indian_date'])
        signal = pd.Series(sig_df['signal'].to_numpy(dtype=float),
                            index=pd.DatetimeIndex(sig_df['indian_date']), name=label)
        meta = json.loads(meta_p.read_text(encoding='utf-8'))
        meta = dict(meta, source=str(meta.get('source', '?')) + ' [cache]')
        return signal, meta
    signal, _map_df, meta = fetch_and_cache_signal(prefix, defn, indian_calendar, label)
    return signal, meta


# ===========================================================================
# PANEL  (open/close/turnover only -- amfi_band_study.py conventions)
# ===========================================================================
def load_panel(lo=None, hi=None):
    files = panel_files_in_range(lo, hi)
    if not files:
        sys.exit(f'HALTED: no bhavcopy files under {PANEL_DIR} in range {lo}..{hi}.')
    frames, skipped = [], 0
    for d, f in files:
        try:
            df = pd.read_csv(f, dtype=str, encoding='utf-8')
        except Exception as e:
            log(f'  WARN: failed to read {f.name}: {type(e).__name__}: {e}, skipping')
            skipped += 1
            continue
        df.columns = df.columns.str.strip()
        missing = [c for c in NEEDED_COLS if c not in df.columns]
        if missing:
            log(f'  WARN: {f.name} missing columns {missing}, skipping file')
            skipped += 1
            continue
        df = df[NEEDED_COLS].copy()
        for c in NEEDED_COLS:
            df[c] = df[c].astype(str).str.strip()
        df = df[df['SERIES'] == 'EQ']
        if df.empty:
            continue
        df = df.assign(date=d)
        for c in ['OPEN_PRICE', 'CLOSE_PRICE', 'TURNOVER_LACS']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        frames.append(df.rename(columns={
            'SYMBOL': 'symbol', 'OPEN_PRICE': 'open', 'CLOSE_PRICE': 'close',
            'TURNOVER_LACS': 'turnover_lacs',
        })[['symbol', 'date', 'open', 'close', 'turnover_lacs']])
    if not frames:
        sys.exit('HALTED: every bhavcopy file in range was unusable.')
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.drop_duplicates(subset=['symbol', 'date'], keep='last')
    panel = panel.sort_values(['symbol', 'date']).reset_index(drop=True)
    log(f'Loaded {len(files)} bhavcopy files ({skipped} skipped), {len(panel):,} EQ stock-day rows, '
        f'{panel.symbol.nunique():,} symbols, {panel.date.min().date()} -> {panel.date.max().date()}')
    return panel


def load_corp_actions():
    if not CORP_ACTIONS_PATH.exists():
        sys.exit(f'HALTED: {CORP_ACTIONS_PATH} not found. Run build_corp_actions.py first.')
    df = pd.read_csv(CORP_ACTIONS_PATH)
    df['ex_date'] = pd.to_datetime(df['ex_date'])
    return df


def halt_on_unresolved_nan_factors(panel, corp_actions):
    """delivery_factor_study.py / amfi_band_study.py verbatim rule: HALT if a
    NaN-factor action's symbol has panel rows dated before that action's ex_date."""
    nan_rows = corp_actions[corp_actions['factor'].isna()]
    if nan_rows.empty:
        return
    panel_symbols = set(panel['symbol'].unique())
    offenders = []
    for _, row in nan_rows.iterrows():
        sym, ex = row['symbol'], row['ex_date']
        if sym not in panel_symbols:
            continue
        if (panel.loc[panel['symbol'] == sym, 'date'] < ex).any():
            offenders.append((sym, ex.date().isoformat(), row.get('subject', '')))
    if offenders:
        log('')
        log('HALT: unresolved (factor=NaN) corporate action(s) touch dates in the loaded panel:')
        for sym, ex, subj in offenders:
            log(f'  {sym}  ex_date={ex}  subject={subj!r}')
        sys.exit(f'HALTED: {len(offenders)} unresolved corp-action factor(s) affect the loaded panel.')


def apply_corp_action_adjustments(panel, corp_actions):
    """Back-adjust OPEN/CLOSE only (this study never touches high/low/volume) --
    amfi_band_study.py verbatim convention."""
    valid = corp_actions.dropna(subset=['factor'])
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
        j = np.searchsorted(ex_dates, dates_arr[idxs], side='right')
        mult[idxs] = suffix[j]
    panel['adj_open'] = panel['open'] * mult
    panel['adj_close'] = panel['close'] * mult
    log(f'Corporate-action adjustment applied: {int((mult != 1.0).sum()):,} stock-day rows scaled, '
        f'{valid["symbol"].nunique()} symbols with >=1 valid action.')
    return panel


class MarketPanel:
    """Wide open/close/eligibility matrices + LAGGED-membership EW means."""

    def __init__(self, panel):
        panel = panel.copy()
        panel['eligible'] = ((panel['turnover_lacs'] >= MIN_TURNOVER_LACS)
                             & (panel['adj_close'] >= MIN_PRICE))
        self.open_wide = panel.pivot_table(index='date', columns='symbol',
                                           values='adj_open', aggfunc='last').sort_index()
        self.close_wide = panel.pivot_table(index='date', columns='symbol',
                                            values='adj_close', aggfunc='last').reindex_like(self.open_wide)
        elig_wide = (panel.pivot_table(index='date', columns='symbol', values='eligible', aggfunc='last')
                    .reindex_like(self.open_wide))
        self.elig = elig_wide.fillna(False).astype(bool)
        # LAGGED membership (exhumation lesson): bench_member(t) = eligible(t-1).
        bm = self.elig.shift(1)
        bm.iloc[0] = False
        self.bench_member = bm.fillna(False).astype(bool)
        self.dates = pd.DatetimeIndex(self.open_wide.index)
        self.symbols = list(self.open_wide.columns)
        n_elig_days = int(self.elig.to_numpy().sum())
        n_bm_days = int(self.bench_member.to_numpy().sum())
        log(f'MarketPanel built: {len(self.dates):,} trading days x {len(self.symbols):,} symbols, '
            f'{n_elig_days:,} same-day-eligible stock-days, {n_bm_days:,} lagged-member stock-days '
            f'(mean {self.bench_member.sum(axis=1).mean():.0f} names/day, EW basket).')

    def gap_wide(self):
        """GAP(s,t) = open(s,t)/close(s,t-1) - 1."""
        return self.open_wide / self.close_wide.shift(1) - 1.0

    def post_wide(self, k):
        """POST(s,t,k) = close(s,t+k-1)/open(s,t) - 1."""
        return self.close_wide.shift(-(k - 1)) / self.open_wide - 1.0

    def ew(self, values_wide):
        """EW eligible-universe mean of `values_wide`, LAGGED membership mask
        (the same basket for every k -- decided once at entry day t)."""
        masked = values_wide.where(self.bench_member)
        return masked.mean(axis=1, skipna=True), masked.notna().sum(axis=1)

    def symbol_series(self, sym, wide):
        if sym not in wide.columns:
            return pd.Series(np.nan, index=wide.index)
        return wide[sym]


# ===========================================================================
# CLUSTER-ROBUST OLS  (Liang-Zeger / CR1, generalizes amfi_band_study.cluster_t)
# ===========================================================================
def ols_cluster_robust(X, y, clusters):
    """One-way cluster-robust (sandwich) OLS. X: (n,k) incl. intercept col.

    beta   = (X'X)^-1 X'y
    e_i    = y_i - X_i @ beta
    meat   = sum_g ( sum_{i in g} X_i' e_i )^2      (k x k, outer product per cluster)
    bread  = (X'X)^-1
    c      = [G/(G-1)] * [(N-1)/(N-k)]               (Stata-style finite-sample correction)
    Vcov   = c * bread @ meat @ bread
    se     = sqrt(diag(Vcov));  t = beta / se

    Reduces to amfi_band_study.cluster_t exactly when X is a single column of
    ones (k=1): meat becomes sum_g(cluster_sum_of_residuals)^2, bread = 1/N,
    c = G/(G-1) (the (N-1)/(N-k) term is exactly 1 at k=1) -- same formula.
    Returns (beta, se, t, vcov, G).
    """
    n, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    resid = y - X @ beta
    uniq = np.unique(clusters)
    G = len(uniq)
    meat = np.zeros((k, k))
    for g in uniq:
        idx = clusters == g
        score_g = X[idx].T @ resid[idx]
        meat += np.outer(score_g, score_g)
    if G < 2 or n <= k:
        se = np.full(k, np.nan)
        t = np.full(k, np.nan)
        return beta, se, t, None, G
    c = (G / (G - 1.0)) * ((n - 1.0) / (n - k))
    vcov = c * (XtX_inv @ meat @ XtX_inv)
    diag = np.diag(vcov)
    se = np.where(diag > 0, np.sqrt(np.maximum(diag, 0)), np.nan)
    t = np.where(np.isfinite(se) & (se > 0), beta / se, np.nan)
    return beta, se, t, vcov, G


def verify_cluster_ols():
    """Self-check (task requirement): hand-verify the clustered SE on a small
    synthetic clustered panel against statsmodels (installed in this
    environment) or, if unavailable at runtime, against a hard-coded
    reference computed the same way. SHOWN to the reviewer on every run."""
    log('-' * 92)
    log('SELF-CHECK: cluster-robust OLS (Liang-Zeger / CR1) vs statsmodels, synthetic panel')
    log('-' * 92)
    rng = np.random.default_rng(42)
    G = 15
    rows = []
    for g in range(G):
        n_g = rng.integers(5, 12)
        shock = rng.normal(0, 1.5)          # common per-cluster shock -> clustering matters
        for _ in range(n_g):
            x1 = rng.normal(0, 1)
            x2 = rng.normal(0, 1) + 0.3 * x1
            e = shock + rng.normal(0, 1)
            y = 1.0 + 0.5 * x1 - 0.8 * x2 + e
            rows.append((g, x1, x2, y))
    df = pd.DataFrame(rows, columns=['cluster', 'x1', 'x2', 'y'])
    n = len(df)
    X = np.column_stack([np.ones(n), df['x1'].to_numpy(), df['x2'].to_numpy()])
    y = df['y'].to_numpy()
    clusters = df['cluster'].to_numpy()
    beta, se, t, _vcov, Gn = ols_cluster_robust(X, y, clusters)
    log(f'  synthetic panel: N={n}, G={Gn} clusters (~5-11 obs/cluster), true beta=[?, 0.5, -0.8], '
        f'correlated within-cluster errors by construction (seed=42)')
    for i, nm in enumerate(['const', 'x1', 'x2']):
        log(f'    hand-rolled  {nm:<6}: beta={beta[i]:+.6f}  se={se[i]:.6f}  t={t[i]:+.4f}')
    ref_beta = np.array([0.835248, 0.546834, -0.478784])
    ref_se = np.array([0.383155, 0.191555, 0.163209])
    try:
        import statsmodels.api as sm
        model = sm.OLS(y, X).fit(cov_type='cluster', cov_kwds={'groups': clusters})
        for i, nm in enumerate(['const', 'x1', 'x2']):
            log(f'    statsmodels  {nm:<6}: beta={model.params[i]:+.6f}  se={model.bse[i]:.6f}  '
                f't={model.tvalues[i]:+.4f}')
        max_db = float(np.max(np.abs(beta - np.asarray(model.params))))
        max_ds = float(np.max(np.abs(se - np.asarray(model.bse))))
        log(f'  max |diff| beta={max_db:.2e}  se={max_ds:.2e}  '
            f'(statsmodels cov_type="cluster", use_correction default True == same CR1 correction)')
        ok = max_db < 1e-8 and max_ds < 1e-8
    except ImportError:
        log('  statsmodels not installed at runtime -- comparing against a pre-computed reference')
        log('  (same synthetic case seed=42, verified against statsmodels 0.14.6 offline to 1e-8):')
        max_db = float(np.max(np.abs(beta - ref_beta)))
        max_ds = float(np.max(np.abs(se - ref_se)))
        log(f'  max |diff| beta={max_db:.2e}  se={max_ds:.2e}  vs hard-coded reference')
        ok = max_db < 1e-4 and max_ds < 1e-4
    log(f'  VERIFICATION: {"PASS" if ok else "FAIL -- MISMATCH, DO NOT TRUST REGRESSION OUTPUT BELOW"}')
    log('-' * 92)
    log('')
    if not ok:
        sys.exit('HALTED: cluster-robust OLS self-check failed.')
    return ok


def iso_week_labels(dates):
    iso = pd.DatetimeIndex(dates).isocalendar()
    return (iso['year'].astype(int) * 100 + iso['week'].astype(int)).to_numpy()


def fit_cell(sub, x_cols, y_col, cluster_col='iso_week'):
    n = len(sub)
    k = len(x_cols) + 1
    if n < MIN_ERA_ROWS:
        return None
    X = np.column_stack([np.ones(n)] + [sub[c].to_numpy(dtype=float) for c in x_cols])
    y = sub[y_col].to_numpy(dtype=float)
    clusters = sub[cluster_col].to_numpy()
    if len(np.unique(clusters)) < 2 or n <= k:
        return None
    beta, se, t, vcov, G = ols_cluster_robust(X, y, clusters)
    return {'n': n, 'G': int(G), 'beta': beta, 'se': se, 't': t}


# ===========================================================================
# TRADEABILITY SIM  (criterion 3: train-era tercile breakpoints -> validation)
# ===========================================================================
def market_tradeability(MP, signal_series, k, direction):
    dates = MP.dates
    sig = signal_series.reindex(dates)
    sig_arr = sig.to_numpy()
    train_mask = (dates >= TRAIN_START) & (dates <= TRAIN_END) & np.isfinite(sig_arr)
    train_vals = sig_arr[train_mask]
    if len(train_vals) < MIN_TERCILE_ROWS:
        return {'n_trades': 0, 'n_days': 0, 'mean_net': np.nan,
                'note': f'insufficient TRAIN signal obs ({len(train_vals)} < {MIN_TERCILE_ROWS}) '
                        f'for tercile breakpoints'}
    q1, q2 = np.quantile(train_vals, [1 / 3, 2 / 3])
    val_mask = (dates >= VAL_START) & (dates <= VAL_END) & np.isfinite(sig_arr)
    fav_mask = val_mask & (sig_arr >= q2 if direction == 'high' else sig_arr <= q1)
    fav_idx = np.flatnonzero(fav_mask)

    open_arr = MP.open_wide.to_numpy()
    exit_arr = MP.close_wide.shift(-(k - 1)).to_numpy()
    bm = MP.bench_member.to_numpy()

    nets = []
    for di in fav_idx:
        member_cols = np.flatnonzero(bm[di])
        if di >= exit_arr.shape[0]:
            continue
        o = open_arr[di, member_cols]
        c = exit_arr[di, member_cols]
        valid = np.isfinite(o) & np.isfinite(c) & (o > 0) & (c > 0)
        o, c = o[valid], c[valid]
        if len(o) == 0:
            continue
        buy_px = o * (1 + SLIP_WIDE)
        sell_px = c * (1 - SLIP_WIDE)
        qty = (POSITION_RS // buy_px).astype(int)
        keep = qty >= 1
        for bp, sp, q in zip(buy_px[keep], sell_px[keep], qty[keep]):
            buy_v, sell_v = float(q * bp), float(q * sp)
            fees = zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False)['total']
            nets.append((sell_v - buy_v - fees) / buy_v)

    if not nets:
        return {'n_trades': 0, 'n_days': int(len(fav_idx)), 'mean_net': np.nan,
                'q1': float(q1), 'q2': float(q2), 'note': 'no eligible trades on favorable days'}
    nets = np.asarray(nets)
    return {'n_trades': int(len(nets)), 'n_days': int(len(fav_idx)), 'mean_net': float(nets.mean()),
            'median_net': float(np.median(nets)), 'hit_rate': float((nets > 0).mean()),
            'q1': float(q1), 'q2': float(q2), 'direction': direction, 'note': ''}


def adr_tradeability(MP, adr_signals, defn_map, k):
    """Pre-registered fade direction (favorable = BOTTOM tercile), pooled
    train-era breakpoints across the 4 names (matches the pooled, week-only
    clustered regression convention -- name pooling stated)."""
    dates = MP.dates
    per_name_sig = {}
    train_pool = []
    for name, defn in defn_map.items():
        sig = adr_signals[name].reindex(dates).to_numpy()
        per_name_sig[name] = sig
        m = (dates >= TRAIN_START) & (dates <= TRAIN_END) & np.isfinite(sig)
        train_pool.append(sig[m])
    train_pool = np.concatenate(train_pool) if train_pool else np.array([])
    if len(train_pool) < MIN_TERCILE_ROWS:
        return {'n_trades': 0, 'n_days': 0, 'mean_net': np.nan,
                'note': f'insufficient TRAIN signal obs ({len(train_pool)} < {MIN_TERCILE_ROWS}) '
                        f'for pooled tercile breakpoints'}
    q1, _q2 = np.quantile(train_pool, [1 / 3, 2 / 3])

    nets = []
    n_fav_days = 0
    for name, defn in defn_map.items():
        sym = defn['nse_symbol']
        sig = per_name_sig[name]
        o_col = MP.symbol_series(sym, MP.open_wide).to_numpy()
        c_col = MP.symbol_series(sym, MP.close_wide.shift(-(k - 1))).to_numpy()
        val_mask = (dates >= VAL_START) & (dates <= VAL_END) & np.isfinite(sig)
        fav = val_mask & (sig <= q1)
        idx = np.flatnonzero(fav)
        n_fav_days += len(idx)
        for di in idx:
            o, c = o_col[di], c_col[di]
            if not (np.isfinite(o) and np.isfinite(c) and o > 0 and c > 0):
                continue
            buy_px, sell_px = o * (1 + SLIP_ADR), c * (1 - SLIP_ADR)
            qty = int(POSITION_RS // buy_px)
            if qty < 1:
                continue
            buy_v, sell_v = qty * buy_px, qty * sell_px
            fees = zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False)['total']
            nets.append((sell_v - buy_v - fees) / buy_v)

    if not nets:
        return {'n_trades': 0, 'n_days': int(n_fav_days), 'mean_net': np.nan,
                'q1': float(q1), 'note': 'no eligible trades on favorable (bottom-tercile) days'}
    nets = np.asarray(nets)
    return {'n_trades': int(len(nets)), 'n_days': int(n_fav_days), 'mean_net': float(nets.mean()),
            'median_net': float(np.median(nets)), 'hit_rate': float((nets > 0).mean()),
            'q1': float(q1), 'direction': 'low (fade, pre-registered)', 'note': ''}


# ===========================================================================
# CELL BUILDERS + VERDICT
# ===========================================================================
def build_market_cell(name, k, MP, signal_series, gap_ew, post_ew):
    df = pd.DataFrame({'t': MP.dates, 'signal': signal_series.reindex(MP.dates).to_numpy(),
                        'gap': gap_ew.to_numpy(), 'post': post_ew.to_numpy()})
    df['iso_week'] = iso_week_labels(df['t'])
    train = df[(df['t'] >= TRAIN_START) & (df['t'] <= TRAIN_END)].dropna(subset=['signal', 'gap', 'post'])
    val = df[(df['t'] >= VAL_START) & (df['t'] <= VAL_END)].dropna(subset=['signal', 'gap', 'post'])
    tr = fit_cell(train, ['signal', 'gap'], 'post')
    va = fit_cell(val, ['signal', 'gap'], 'post')
    b_train = tr['beta'][1] if tr else np.nan
    b_val = va['beta'][1] if va else np.nan
    t_val = va['t'][1] if va else np.nan
    direction = 'high' if (np.isfinite(b_train) and b_train > 0) else 'low'
    trade = market_tradeability(MP, signal_series, k, direction)
    return _evaluate_cell(f'{name} k={k}', 'market', tr, va, b_train, b_val, t_val, trade,
                           require_negative=False, n_train_rows=len(train), n_val_rows=len(val))


def build_adr_cell(k, MP, adr_signals, defn_map):
    rows = []
    for name, defn in defn_map.items():
        sym = defn['nse_symbol']
        gap_s = MP.symbol_series(sym, MP.gap_wide())
        post_s = MP.symbol_series(sym, MP.post_wide(k))
        sig_s = adr_signals[name].reindex(MP.dates)
        rows.append(pd.DataFrame({'t': MP.dates, 'name': name, 'signal': sig_s.to_numpy(),
                                   'gap': gap_s.to_numpy(), 'post': post_s.to_numpy()}))
    pooled = pd.concat(rows, ignore_index=True)
    pooled['iso_week'] = iso_week_labels(pooled['t'])
    train = pooled[(pooled['t'] >= TRAIN_START) & (pooled['t'] <= TRAIN_END)].dropna(
        subset=['signal', 'gap', 'post'])
    val = pooled[(pooled['t'] >= VAL_START) & (pooled['t'] <= VAL_END)].dropna(
        subset=['signal', 'gap', 'post'])
    tr = fit_cell(train, ['signal', 'gap'], 'post')
    va = fit_cell(val, ['signal', 'gap'], 'post')
    b_train = tr['beta'][1] if tr else np.nan
    b_val = va['beta'][1] if va else np.nan
    t_val = va['t'][1] if va else np.nan
    trade = adr_tradeability(MP, adr_signals, defn_map, k)
    return _evaluate_cell(f'ADR k={k}', 'adr', tr, va, b_train, b_val, t_val, trade,
                           require_negative=True, n_train_rows=len(train), n_val_rows=len(val))


def _evaluate_cell(cell_name, arm, tr, va, b_train, b_val, t_val, trade, require_negative,
                    n_train_rows, n_val_rows):
    crit1 = bool(np.isfinite(t_val) and abs(t_val) >= T_THRESHOLD
                 and (not require_negative or b_val < 0))
    crit2 = bool(np.isfinite(b_train) and np.isfinite(b_val) and b_train != 0
                 and np.sign(b_train) == np.sign(b_val))
    mean_net = trade.get('mean_net', np.nan)
    crit3 = bool(np.isfinite(mean_net) and mean_net > 0)
    finding = crit1 and crit2 and crit3
    return {
        'cell': cell_name, 'arm': arm, 'require_negative': require_negative,
        'n_train_rows': n_train_rows, 'n_val_rows': n_val_rows,
        'tr': tr, 'va': va, 'b_train': b_train, 'b_val': b_val, 't_val': t_val,
        'trade': trade, 'crit1': crit1, 'crit2': crit2, 'crit3': crit3, 'finding': finding,
    }


def print_cell(c):
    log(f'CELL: {c["cell"]}  [{c["arm"]} arm{"  (fade: b must be NEGATIVE)" if c["require_negative"] else ""}]')
    if c['tr'] is None:
        log(f'  TRAIN  ({TRAIN_START.date()}..{TRAIN_END.date()}): N/A (n_rows={c["n_train_rows"]} '
            f'< {MIN_ERA_ROWS} or <2 week-clusters)')
    else:
        log(f'  TRAIN  ({TRAIN_START.date()}..{TRAIN_END.date()}): N={c["tr"]["n"]:,} G={c["tr"]["G"]} weeks  '
            f'b={num(c["b_train"], 5)}  (sign only, no t-stat required)')
    if c['va'] is None:
        log(f'  VAL    ({VAL_START.date()}..{VAL_END.date()}): N/A (n_rows={c["n_val_rows"]} '
            f'< {MIN_ERA_ROWS} or <2 week-clusters)')
    else:
        log(f'  VAL    ({VAL_START.date()}..{VAL_END.date()}): N={c["va"]["n"]:,} G={c["va"]["G"]} weeks  '
            f'b={num(c["b_val"], 5)}  t(b)={num(c["t_val"], 3)}')
    tr_d = c['trade']
    if tr_d.get('note'):
        log(f'  TRADEABILITY: {tr_d["note"]}  (n_trades={tr_d.get("n_trades", 0)})')
    else:
        log(f'  TRADEABILITY: direction={tr_d.get("direction")}  n_favorable_days={tr_d["n_days"]}  '
            f'n_trades={tr_d["n_trades"]}  mean_net={pct(tr_d["mean_net"], 4)}  '
            f'median_net={pct(tr_d.get("median_net"), 4)}  hit_rate={pct(tr_d.get("hit_rate"), 1)}')
    log(f'  Criterion 1 (VAL |t(b)|>={T_THRESHOLD}'
        f'{" AND b<0" if c["require_negative"] else ""}): {"PASS" if c["crit1"] else "FAIL"}')
    log(f'  Criterion 2 (TRAIN b same sign as VAL b): {"PASS" if c["crit2"] else "FAIL"}')
    log(f'  Criterion 3 (VAL mean net/trade > 0): {"PASS" if c["crit3"] else "FAIL"}')
    log(f'  => {"FINDING" if c["finding"] else "no finding"}')
    log('')


# ===========================================================================
# HEADER / REPORTING
# ===========================================================================
def print_header(mode):
    log('=' * 96)
    log('OVERNIGHT-INFORMATION POST-OPEN DRIFT STUDY -- FROZEN SPEC (2026-07-30)')
    log('=' * 96)
    log(f'Spec  : {SPEC}')
    tag = {'fetch': 'FETCH ONLY (signals + cache, no regression, no verdict)',
           'smoke': 'SMOKE (~3 recent months -- NO VERDICT WEIGHT)',
           'full': 'FULL VERDICT RUN'}[mode]
    log(f'Mode  : {tag}')
    log('')
    log('Stated prior (before any result): NULL. US overnight anomaly decayed post-2021; our own')
    log('overnight-premium test died at -1.7bp net; India\'s gap mechanism is well documented.')
    log('Expected findings: 0. Any finding -> phase-2 spec, incubator path only.')
    log('')
    log('Signals (frozen): S&P 500 (^GSPC), front crude (CL=F, fallback BZ=F), USDINR (INR=X, '
        'fallback USDINR=X), daily closes 2019-07..today via yfinance (pip-installed, network-')
    log('verified; the spec\'s stooq fallback returned an anti-bot JS challenge page from this ')
    log('environment, not usable -- documented in the module docstring).')
    log('Mapping (frozen): foreign close of calendar date d -> the NEXT Indian trading day t > d '
        '(Indian trading days = the panel\'s own calendar, from bhavcopy filenames). Signal(t) = ')
    log('log(close_d / close_prev_d), the foreign series\' OWN previous close (its own holidays).')
    log(f'Alignment gate: >= {ALIGN_GATE*100:.0f}% of Indian trading days '
        f'{ALIGN_START.date()}..{ALIGN_END.date()} must receive each signal, else HALT.')
    log('')
    log('Method (frozen): GAP(s,t)=open(s,t)/close(s,t-1)-1; POST(s,t,k)=close(s,t+k-1)/open(s,t)-1, '
        'k in {1,3,10}. Market arm: EW eligible-universe means (LAGGED membership -- exhumation ')
    log('lesson), regression POST(t,k)=a+b*SIGNAL(t)+c*GAP(t)+e per (signal,k), cluster-robust by ')
    log('ISO week. ADR arm: INFY/WIT/IBN/HDB overnight ADR returns, pooled across names (week-')
    log('clustered only, name pooling stated), fade hypothesis pre-registered NEGATIVE b, k in {1,3}.')
    log('')
    log('Declared cells: 3 signals x 3 horizons (market) + 2 (ADR, k in {1,3}) = 11.')
    log(f'Per cell, ALL required for a FINDING: (1) VAL-era cluster-robust |t(b)| >= {T_THRESHOLD} '
        '(Bonferroni, 11 cells; ADR arm additionally requires b<0); (2) TRAIN-era b same sign as ')
    log('VAL; (3) tradeability: favorable-signal-tercile days (TRAIN-era breakpoints applied to ')
    log('VALIDATION), Rs 20k slots, delivery costs + 0.2%/side slippage (market) / 0.05% (ADR) -- ')
    log('VAL mean net/trade > 0.')
    log('')
    log('Eras (frozen): TRAIN 2019-10..2023-12, VALIDATION 2024-01..2026-07.')
    log('Deferred (both explicitly non-verdict-bearing per spec): GIFT Nifty robustness line, ')
    log('sector splits (IT/USDINR, OMC-paints/crude) -- information only, not implemented here.')
    if mode == 'smoke':
        log('')
        log('*' * 96)
        log('*** SMOKE MODE: panel restricted to the most recent ~3 months of bhavcopy files.    ***')
        log('*** TRAIN era will be EMPTY by construction -> criteria 2 print N/A for every cell.  ***')
        log('*** THIS IS NOT A VERDICT RUN. Self-check plumbing only.                             ***')
        log('*' * 96)
    log('=' * 96)
    log('')


def print_verdict_summary(cells, mode):
    log('=' * 96)
    log('VERDICT' + (' (SMOKE -- NOT MEANINGFUL)' if mode == 'smoke' else ''))
    log('=' * 96)
    n_finding = sum(1 for c in cells if c['finding'])
    log(f'{n_finding}/{len(cells)} cells are FINDINGS (all 3 criteria PASS).')
    log(f'Pre-registered expectation: 0. {"MATCHES prior." if n_finding == 0 else "DEVIATES FROM PRIOR -- see cells below, phase-2 spec required before any live step."}')
    log('')
    log(f'{"cell":<14} {"arm":<7} {"crit1":<6} {"crit2":<6} {"crit3":<6} {"finding":<8}')
    for c in cells:
        log(f'{c["cell"]:<14} {c["arm"]:<7} {"PASS" if c["crit1"] else "fail":<6} '
            f'{"PASS" if c["crit2"] else "fail":<6} {"PASS" if c["crit3"] else "fail":<6} '
            f'{"FINDING" if c["finding"] else "-":<8}')
    log('=' * 96)


# ===========================================================================
# MODES
# ===========================================================================
def run_fetch_mode():
    t0 = time.time()
    print_header('fetch')
    verify_cluster_ols()
    indian_calendar = load_indian_calendar()
    log(f'Indian trading calendar (bhavcopy filenames): {len(indian_calendar):,} days, '
        f'{indian_calendar.min().date()} -> {indian_calendar.max().date()}')
    log('')

    for name, defn in SIGNAL_DEFS.items():
        log('=' * 92)
        log(f'FETCHING {name}  (primary={defn["primary"]}, fallback={defn["fallback"]}, '
            f'close_hour_et={defn["close_hour_et"]})')
        log('=' * 92)
        sig, map_df, meta = fetch_and_cache_signal(name, defn, indian_calendar, name)
        p, cov, tot = alignment_pct(sig, indian_calendar)
        log(f'  source used: {meta["source"]}')
        log(f'  foreign close series: {meta["n_close_rows"]} rows, {meta["foreign_min"]} -> {meta["foreign_max"]}')
        log(f'  mapped signal series: {meta["n_signal_rows"]} Indian trading days, '
            f'{sig.index.min().date()} -> {sig.index.max().date()}')
        log(f'  ALIGNMENT: {cov}/{tot} ({p*100:.2f}%) of Indian trading days '
            f'{ALIGN_START.date()}..{ALIGN_END.date()} covered  '
            f'(gate {ALIGN_GATE*100:.0f}%: {"PASS" if p >= ALIGN_GATE else "FAIL -- HALT"})')
        if p < ALIGN_GATE:
            sys.exit(f'HALTED: {name} alignment {p*100:.2f}% < {ALIGN_GATE*100:.0f}% gate -- data-blocked.')
        print_mapping_samples(map_df, name)
        log('')

    for name, defn in ADR_DEFS.items():
        log('=' * 92)
        log(f'FETCHING ADR {name}  (NSE: {defn["nse_symbol"]}, close_hour_et={defn["close_hour_et"]})')
        log('=' * 92)
        sig, map_df, meta = fetch_and_cache_signal(f'adr_{name}', defn, indian_calendar, f'ADR-{name}')
        p, cov, tot = alignment_pct(sig, indian_calendar)
        log(f'  source used: {meta["source"]}')
        log(f'  foreign close series: {meta["n_close_rows"]} rows, {meta["foreign_min"]} -> {meta["foreign_max"]}')
        log(f'  mapped signal series: {meta["n_signal_rows"]} Indian trading days, '
            f'{sig.index.min().date()} -> {sig.index.max().date()}')
        log(f'  ALIGNMENT: {cov}/{tot} ({p*100:.2f}%) of Indian trading days '
            f'{ALIGN_START.date()}..{ALIGN_END.date()} covered  '
            f'(gate {ALIGN_GATE*100:.0f}%: {"PASS" if p >= ALIGN_GATE else "FAIL -- HALT"})')
        if p < ALIGN_GATE:
            sys.exit(f'HALTED: ADR {name} alignment {p*100:.2f}% < {ALIGN_GATE*100:.0f}% gate -- data-blocked.')
        print_mapping_samples(map_df, f'ADR-{name}')
        log('')

    log(f'Cache written to {SIGNALS_DIR}')
    log(f'Total runtime: {time.time()-t0:.1f}s')
    flush_out(OUT_FILE_FETCH)
    print(f'\n[saved output to {OUT_FILE_FETCH}]', file=sys.stderr)


def run_study(mode, force_fetch=False):
    t0 = time.time()
    smoke = (mode == 'smoke')
    print_header(mode)
    verify_cluster_ols()

    indian_calendar = load_indian_calendar()
    log(f'Indian trading calendar: {len(indian_calendar):,} days, '
        f'{indian_calendar.min().date()} -> {indian_calendar.max().date()}')
    log('')

    market_signals, adr_signals = {}, {}
    for name, defn in SIGNAL_DEFS.items():
        sig, meta = load_or_fetch_signal(name, defn, indian_calendar, name, force_fetch=force_fetch)
        p, cov, tot = alignment_pct(sig, indian_calendar)
        log(f'signal {name:<8}: source={meta["source"]:<24} alignment={p*100:6.2f}% '
            f'({cov}/{tot})  range={sig.index.min().date()}..{sig.index.max().date()}')
        if p < ALIGN_GATE:
            sys.exit(f'HALTED: {name} alignment {p*100:.2f}% < {ALIGN_GATE*100:.0f}% gate -- data-blocked.')
        market_signals[name] = sig
    for name, defn in ADR_DEFS.items():
        sig, meta = load_or_fetch_signal(f'adr_{name}', defn, indian_calendar, f'ADR-{name}',
                                         force_fetch=force_fetch)
        p, cov, tot = alignment_pct(sig, indian_calendar)
        log(f'ADR    {name:<8}: source={meta["source"]:<24} alignment={p*100:6.2f}% '
            f'({cov}/{tot})  NSE={defn["nse_symbol"]}')
        if p < ALIGN_GATE:
            sys.exit(f'HALTED: ADR {name} alignment {p*100:.2f}% < {ALIGN_GATE*100:.0f}% gate -- data-blocked.')
        adr_signals[name] = sig
    log('')

    if smoke:
        cal_files = panel_files_in_range()
        hi = max(d for d, _ in cal_files)
        lo = hi - pd.Timedelta(days=95)
        log(f'SMOKE panel window: {lo.date()} .. {hi.date()} (~3 months)')
    else:
        lo, hi = None, None

    panel = load_panel(lo=lo, hi=hi)
    corp = load_corp_actions()
    halt_on_unresolved_nan_factors(panel, corp)
    panel = apply_corp_action_adjustments(panel, corp)
    MP = MarketPanel(panel)
    log('')

    cells = []
    for name in SIGNAL_DEFS:
        gap_ew, _ = MP.ew(MP.gap_wide())
        for k in K_MARKET:
            post_ew, breadth = MP.ew(MP.post_wide(k))
            c = build_market_cell(name, k, MP, market_signals[name], gap_ew, post_ew)
            cells.append(c)
    for k in K_ADR:
        c = build_adr_cell(k, MP, adr_signals, ADR_DEFS)
        cells.append(c)

    log('=' * 96)
    log('PER-CELL DETAIL')
    log('=' * 96)
    log('')
    for c in cells:
        print_cell(c)

    print_verdict_summary(cells, mode)
    log('')
    log(f'Total runtime: {time.time()-t0:.1f}s')

    out = OUT_FILE_SMOKE if smoke else OUT_FILE
    flush_out(out)
    print(f'\n[saved output to {out}]', file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--fetch', action='store_true',
                    help='Fetch + cache all signal series only (no regression, no verdict).')
    ap.add_argument('--smoke', action='store_true',
                    help='Full pipeline on ~3 recent months. NOT a verdict, plumbing check only.')
    ap.add_argument('--force-fetch', action='store_true',
                    help='Bypass the signal cache under --smoke/full run (refetch from yfinance).')
    args = ap.parse_args()
    if args.fetch:
        run_fetch_mode()
        return
    run_study(mode='smoke' if args.smoke else 'full', force_fetch=args.force_fetch)


if __name__ == '__main__':
    main()
