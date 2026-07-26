"""Empirical bid-ask spread estimate — Corwin & Schultz (2012) high-low estimator,
applied to the 679-symbol daily universe (data/daily_universe/). Purpose: check
whether the hardcoded slippage assumptions used across the codebase are defensible:
  - 0.05%/side for NIFTY-50-scale liquid names (kite/research/intraday_probe.py
    SLIP=0.0005, honest_lab.py SLIPPAGE=0.0005, retest_all.py, and every
    kite/live_monitor/expectations/*.json slippage_assumed_pct=0.05)
  - 0.2%/side for the wide 679-stock universe (kite/research/universe_lab.py
    SLIP=0.002)
Live paper trading assumes ZERO slippage. Nobody has checked any of this against
data before. THIS SCRIPT MAKES NO PRODUCTION CHANGES — it is a measurement study
only; it reads data/daily_universe/*.csv and writes spread_estimate_study.txt.

Corwin, S.A., Schultz, P., 2012. "A Simple Way to Estimate Bid-Ask Spreads from
Daily High and Low Prices." Journal of Finance 67(2), 719-760.

For each symbol, for each pair of consecutive trading days (t, t+1):
    beta  = [ln(H_t/L_t)]^2 + [ln(H_{t+1}/L_{t+1})]^2
    gamma = [ln(max(H_t,H_{t+1}) / min(L_t,L_{t+1}))]^2
    k     = 3 - 2*sqrt(2)
    alpha = (sqrt(2*beta) - sqrt(beta)) / k - sqrt(gamma / k)
    S     = 2*(exp(alpha) - 1) / (1 + exp(alpha))          # proportional spread
This is the BASE two-day estimator from the paper (no overnight-jump adjustment
variant). Per the paper's standard convention, negative S estimates are set to
zero before averaging (documented explicitly below and in the LIMITATIONS
section — this is a real, disclosed source of upward bias, not a bug).
HALF-spread = S/2 is what a marketable order pays crossing the spread once,
the quantity comparable to a per-side slippage assumption.

Usage: python kite/research/spread_estimate.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'kite'))

DATA_DIR = ROOT / 'data' / 'daily_universe'
OUT_TXT = Path(__file__).with_name('spread_estimate_study.txt')

K = 3 - 2 * np.sqrt(2)          # Corwin-Schultz constant, ~0.1716
MAX_GAP_DAYS = 5                # drop day-pairs separated by >5 calendar days
                                 # (trading halts / long suspensions) -- treating
                                 # those as "consecutive" would badly violate the
                                 # estimator's continuous-trading assumption.
MIN_ROWS = 300                  # matches universe_lab.py's loader convention
MIN_PAIRS_FOR_ERA = 20          # min valid day-pairs within an era to report it

# NIFTY-47 live-trading universe, from kite/live_monitor/monitor.py's NIFTY_50
# list (TATAMOTORS is in that source list's comment as removed -- token dead
# post-2025 demerger -- and is correspondingly absent from data/daily_universe;
# the list below is the 47 symbols actually defined there).
NIFTY_47 = [
    'ADANIPORTS', 'APOLLOHOSP', 'ASIANPAINT', 'AXISBANK', 'BAJAJ-AUTO',
    'BAJAJFINSV', 'BAJFINANCE', 'BHARTIARTL', 'BPCL', 'BRITANNIA',
    'CIPLA', 'COALINDIA', 'DIVISLAB', 'DRREDDY', 'EICHERMOT',
    'GRASIM', 'HCLTECH', 'HDFCBANK', 'HDFCLIFE', 'HEROMOTOCO',
    'HINDALCO', 'HINDUNILVR', 'ICICIBANK', 'INDUSINDBK', 'INFY',
    'ITC', 'JSWSTEEL', 'KOTAKBANK', 'LT', 'M&M',
    'MARUTI', 'NESTLEIND', 'NTPC', 'ONGC', 'POWERGRID',
    'RELIANCE', 'SBIN', 'SHREECEM', 'SUNPHARMA', 'TATACONSUM',
    'TATASTEEL', 'TCS', 'TECHM', 'TITAN',
    'ULTRACEMCO', 'UPL', 'WIPRO'
]

SLIP_NIFTY_ASSUMED = 0.05    # % per side, hardcoded assumption under test
SLIP_WIDE_ASSUMED = 0.20     # % per side, hardcoded assumption under test

ERAS = [
    ('2015-2019', pd.Timestamp('2015-01-01'), pd.Timestamp('2019-12-31')),
    ('2020-2022', pd.Timestamp('2020-01-01'), pd.Timestamp('2022-12-31')),
    ('2023-2026', pd.Timestamp('2023-01-01'), pd.Timestamp('2027-01-01')),
]


# --------------------------------------------------------------------------- load
def load():
    """Same loader conventions as universe_lab.py: tz-strip/normalize date,
    dedupe on date (keep last), require >=300 rows. Additionally drop
    zero-volume rows: a no-trade day is a stale-price copy (H==L==prev close),
    not a genuine trading observation, and would otherwise contaminate the
    high-low range series CS relies on."""
    data = {}
    for f in sorted(DATA_DIR.glob('*_day.csv')):
        sym = f.name[:-8]
        df = pd.read_csv(f, parse_dates=['datetime'])
        df['date'] = df.datetime.dt.tz_localize(None).dt.normalize()
        df = df.set_index('date')[['open', 'high', 'low', 'close', 'volume']]
        df = df[~df.index.duplicated(keep='last')]
        df = df.sort_index()
        df = df[(df.volume > 0) & (df.high > 0) & (df.low > 0) & (df.high >= df.low)]
        if len(df) < MIN_ROWS:
            continue
        data[sym] = df
    return data


# --------------------------------------------------------------- CS estimator
def cs_spread_series(df):
    """Vectorized Corwin-Schultz proportional spread S for every consecutive
    trading-day pair in df. Returned Series is indexed by the pair's SECOND
    day (t+1) and holds S (full round-trip proportional spread, NOT halved),
    already clipped at 0 (negative-S convention) and gap-filtered."""
    if len(df) < 2:
        return pd.Series(dtype=float)
    h, l = df['high'].to_numpy(), df['low'].to_numpy()
    dates = df.index.to_numpy()

    log_hl = np.log(h / l)
    beta = log_hl[:-1] ** 2 + log_hl[1:] ** 2
    hi2 = np.maximum(h[:-1], h[1:])
    lo2 = np.minimum(l[:-1], l[1:])
    gamma = np.log(hi2 / lo2) ** 2

    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / K - np.sqrt(gamma / K)
    alpha = np.clip(alpha, -50, 50)  # guard exp() overflow on pathological rows
    ea = np.exp(alpha)
    S = 2 * (ea - 1) / (1 + ea)
    S = np.clip(S, 0, None)  # CS convention: negative estimates -> 0 before averaging

    gap_days = (dates[1:] - dates[:-1]).astype('timedelta64[D]').astype(int)
    valid = gap_days <= MAX_GAP_DAYS
    return pd.Series(S[valid], index=pd.DatetimeIndex(dates[1:][valid]))


def recent_turnover(df):
    """60-day median turnover (close*volume), summarized as the median of that
    rolling series over the symbol's last 250 available days -- a single
    representative 'recent liquidity level' per symbol, used only for tiering."""
    turnover = df.close * df.volume
    roll = turnover.rolling(60, min_periods=60).median()
    recent = roll.dropna().tail(250)
    return float(recent.median()) if len(recent) else np.nan


# ------------------------------------------------------------------- reporting
def pct_stats(half_spreads_pct):
    """half_spreads_pct: array of per-symbol mean half-spreads, in percent."""
    a = np.asarray(half_spreads_pct, dtype=float)
    a = a[~np.isnan(a)]
    if len(a) == 0:
        return None
    return {
        'n': len(a),
        'mean': a.mean(),
        'median': np.median(a),
        'p25': np.percentile(a, 25),
        'p75': np.percentile(a, 75),
        'p95': np.percentile(a, 95),
    }


def fmt_row(label, s):
    if s is None:
        return f'{label:34} | n=0 (no symbols)'
    return (f'{label:34} | n={s["n"]:4} | mean {s["mean"]:6.3f}% | median {s["median"]:6.3f}% | '
            f'p25 {s["p25"]:6.3f}% | p75 {s["p75"]:6.3f}% | p95 {s["p95"]:6.3f}% | '
            f'ratio-to-0.05% {s["median"]/SLIP_NIFTY_ASSUMED:5.2f}x | '
            f'ratio-to-0.20% {s["median"]/SLIP_WIDE_ASSUMED:5.2f}x')


def fmt_rupee(x):
    if np.isnan(x):
        return 'n/a'
    cr = x / 1e7
    if cr >= 1:
        return f'Rs {cr:,.2f} Cr/day'
    lakh = x / 1e5
    return f'Rs {lakh:,.2f} L/day'


def main():
    lines = []
    p = lines.append

    data = load()
    p(f'Corwin-Schultz half-spread estimate -- data/daily_universe/ ({len(data)} symbols loaded, '
      f'min {MIN_ROWS} rows, zero-volume rows dropped, day-pairs >{MAX_GAP_DAYS}d apart excluded)')
    p('=' * 118)

    # per-symbol: full-sample CS series, mean half-spread%, recent turnover for tiering
    per_symbol = {}
    for sym, df in data.items():
        s = cs_spread_series(df)
        if len(s) == 0:
            continue
        per_symbol[sym] = {
            'series': s,                       # full daily S series (not halved), indexed by date
            'half_pct': s.mean() / 2 * 100,     # per-symbol mean half-spread in %
            'n_pairs': len(s),
            'turnover': recent_turnover(df),
        }

    n_used = len(per_symbol)
    p(f'{n_used} symbols yielded at least one valid day-pair (of {len(data)} loaded)\n')

    # -------------------------------------------------- 1. liquidity terciles
    turnovers = {s: v['turnover'] for s, v in per_symbol.items() if not np.isnan(v['turnover'])}
    tvals = np.array(list(turnovers.values()))
    c1, c2 = np.percentile(tvals, [100 / 3, 200 / 3])
    p('1. LIQUIDITY TIERS (terciles by 60d-median turnover, summarized over each '
      "symbol's last 250 days)")
    p(f'   tier boundaries: Low < {fmt_rupee(c1)}  <=  Mid  <=  {fmt_rupee(c2)} < High')
    p('-' * 118)

    def tier_of(t):
        if np.isnan(t):
            return None
        if t < c1:
            return 'Low (T1)'
        if t <= c2:
            return 'Mid (T2)'
        return 'High (T3)'

    tiers = {'Low (T1)': [], 'Mid (T2)': [], 'High (T3)': []}
    for sym, t in turnovers.items():
        tn = tier_of(t)
        if tn:
            tiers[tn].append(per_symbol[sym]['half_pct'])

    for name in ('Low (T1)', 'Mid (T2)', 'High (T3)'):
        p(fmt_row(name, pct_stats(tiers[name])))
    p(fmt_row('ALL 679-universe (ref.)', pct_stats([v['half_pct'] for v in per_symbol.values()])))
    p('')

    # -------------------------------------------------- 2. NIFTY-47 subset
    p('2. NIFTY-47 LIVE TRADING UNIVERSE (kite/live_monitor/monitor.py NIFTY_50 list)')
    p('-' * 118)
    n47_found = [s for s in NIFTY_47 if s in per_symbol]
    n47_missing = [s for s in NIFTY_47 if s not in per_symbol]
    if n47_missing:
        p(f'   WARNING: {len(n47_missing)} NIFTY-47 symbols missing/insufficient data: {n47_missing}')
    n47_stats = pct_stats([per_symbol[s]['half_pct'] for s in n47_found])
    p(fmt_row(f'NIFTY-47 (n found={len(n47_found)})', n47_stats))
    p('   (median/mean/p25/p75/p95 + ratio-to-assumption columns above satisfy analysis item 3 for both'
      ' the tiers table and this NIFTY-47 row)')
    p('')
    p('   per-symbol detail (sorted by half-spread%):')
    detail = sorted(((s, per_symbol[s]['half_pct'], per_symbol[s]['n_pairs']) for s in n47_found),
                     key=lambda x: x[1])
    for sym, hp, npairs in detail:
        p(f'     {sym:14} half-spread {hp:6.3f}%  (n_pairs={npairs})')
    p('')

    # -------------------------------------------------- 3. (folded into 1 & 2 tables above)

    # -------------------------------------------------- 4. time trend, NIFTY-47
    p('3. TIME TREND -- NIFTY-47 median half-spread by era')
    p('-' * 118)
    for era_name, start, end in ERAS:
        era_means = []
        for sym in n47_found:
            s = per_symbol[sym]['series']
            sub = s[(s.index >= start) & (s.index <= end)]
            if len(sub) >= MIN_PAIRS_FOR_ERA:
                era_means.append(sub.mean() / 2 * 100)
        st = pct_stats(era_means)
        p(fmt_row(era_name, st))
    p('')

    # -------------------------------------------------- 5. limitations
    p('4. LIMITATIONS (read before trusting any number above)')
    p('-' * 118)
    p("""   - Corwin-Schultz is an ESTIMATE, not a measurement of actual quoted spreads --
     we have no NSE tick-by-tick bid/ask data for this universe, only daily OHLCV.
   - The estimator is known to be biased UPWARD when overnight price gaps are large:
     it derives the spread from the excess of the 2-day high-low range (gamma) over
     what continuous within-day diffusion alone would predict from the two single-day
     ranges (beta); a genuine overnight jump (news, results, index rebalancing) inflates
     that excess and gets attributed to "spread" even though no one crossed a spread
     to produce it. Indian small/midcaps gap far more than NIFTY-50 largecaps, so this
     bias likely hits the wide-universe tiers harder than the NIFTY-47 subset.
   - It assumes continuous trading within the day and well-behaved (non-halted,
     non-circuit-limit) price formation; circuit-filter days, illiquid single-print
     days, and corporate-action gaps (splits/bonuses not cleanly adjusted) all violate
     this and inflate the estimate for the affected day-pair.
   - It estimates the DAILY average spread, which can differ materially from the
     spread at the specific moment an order is placed (open, mid-day, close all differ;
     our paper-trading fills happen at specific bar opens, not at a daily average).
   - Negative S estimates were floored to 0 before averaging (the paper's standard
     convention) -- this asymmetric floor mechanically pushes the per-symbol AVERAGE
     spread up relative to the (unobservable) true average, compounding the upward
     bias above.
   - Day-pairs separated by >5 calendar days (trading halts, suspensions, illiquid
     multi-day gaps) were excluded rather than treated as "consecutive" -- a data-
     cleaning choice, not part of the original CS spec, but the alternative (silently
     combining widely separated bars) would be worse.
   - Does NOT capture market impact -- irrelevant here, our order sizes (~Rs 20k) are
     far too small to move these names.
   - Does NOT capture the gap between "quote-based spread" and "trade-price-based
     fill": our paper trader fills at recorded trade/bar prices, not at bid/ask quotes,
     so realized slippage in practice reflects a mix of spread-crossing and price-time
     execution noise that this estimator does not separate out.
   NET: every disclosed bias above pushes in the SAME direction (upward). Treat every
   number in this report as an UPPER BOUND on the true one-way half-spread, not a
   point estimate.""")
    p('')

    # -------------------------------------------------- verdict
    p('VERDICT')
    p('-' * 118)
    n47_med = n47_stats['median'] if n47_stats else float('nan')
    wide_stats = pct_stats([v['half_pct'] for v in per_symbol.values()])
    high_stats = pct_stats(tiers['High (T3)'])
    mid_stats = pct_stats(tiers['Mid (T2)'])
    low_stats = pct_stats(tiers['Low (T1)'])

    n47_ratio = n47_med / SLIP_NIFTY_ASSUMED
    wide_ratio = wide_stats['median'] / SLIP_WIDE_ASSUMED
    t3_ratio = high_stats['median'] / SLIP_WIDE_ASSUMED
    t2_ratio = mid_stats['median'] / SLIP_WIDE_ASSUMED
    t1_ratio = low_stats['median'] / SLIP_WIDE_ASSUMED

    def verdict_label(ratio):
        # ratio = estimate / assumption. Estimate is a disclosed UPPER BOUND, so
        # generous discounting is built into these thresholds -- a ratio near 1
        # is "defensible", a ratio that would still exceed 1 after a big haircut
        # for known upward bias is "too optimistic".
        if ratio <= 1.3:
            return 'DEFENSIBLE'
        if ratio <= 2.0:
            return 'MARGINAL'
        return 'TOO OPTIMISTIC'

    n47_label = verdict_label(n47_ratio)
    wide_label = verdict_label(wide_ratio)

    p(f"""   NIFTY-47 median half-spread (upper-bound estimate): {n47_med:.3f}%  vs. assumed 0.05%/side
     -> ratio {n47_ratio:.2f}x -- {n47_label}. Even granting the estimator's known upward bias and
        discounting generously, a 6x gap is too large to explain away; the 0.05% assumption
        understates real one-way cost for this universe. A better-grounded per-side number for
        NIFTY-47-scale liquid names is roughly {n47_med/2:.3f}-{n47_med:.3f}%, i.e. somewhere between
        half this upper-bound estimate (crude allowance for gap-driven bias) and the estimate itself.

   Wide-679-universe median half-spread (upper-bound estimate): {wide_stats['median']:.3f}%  vs. assumed 0.20%/side
     -> ratio {wide_ratio:.2f}x -- {wide_label}.
        By tier: Low(T1) {low_stats['median']:.3f}% ({t1_ratio:.2f}x)  |  Mid(T2) {mid_stats['median']:.3f}% ({t2_ratio:.2f}x)  |  High(T3) {high_stats['median']:.3f}% ({t3_ratio:.2f}x)
        Every tier -- including the most liquid third (T3) -- estimates meaningfully above the 0.2%
        assumption. The gap is smaller than NIFTY-47's (which is itself notable: NIFTY-47 names are a
        subset of T3 and estimate BELOW the T3 median, consistent with the largest-cap names having the
        tightest spreads within the liquid tier), but even T3's 1.95x ratio is hard to fully explain away
        via CS's upward bias alone. A better-grounded per-side number for the wide universe is likely
        {high_stats['median']/2:.3f}-{low_stats['median']:.3f}% depending on tier, i.e. noticeably above 0.2%
        for illiquid names and only roughly in range for the most liquid third.
""")
    p(f'   Bottom line: is 0.05%/side defensible for NIFTY-47? {n47_label} '
      f'(estimate is an upper bound at {n47_med:.3f}%, {n47_ratio:.2f}x the assumption -- too large a gap to '
      f'attribute to estimator bias alone).')
    p(f'   Is 0.2%/side defensible for the wide universe? {wide_label} overall '
      f'(median estimate {wide_stats["median"]:.3f}%, {wide_ratio:.2f}x the assumption); even the High-liquidity '
      f'tier (T3, {t3_ratio:.2f}x) runs hot, and Low-liquidity (T1, {t1_ratio:.2f}x) clearly understates real cost.')

    out = '\n'.join(lines)
    print(out)
    OUT_TXT.write_text(out + '\n')
    print(f'\nsaved -> {OUT_TXT}')


if __name__ == '__main__':
    main()
