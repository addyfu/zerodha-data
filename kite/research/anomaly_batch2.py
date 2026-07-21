"""Anomaly Batch 2 -- Tests B, C, D (pre-registered, frozen spec).

Spec: docs/superpowers/specs/2026-07-22-anomaly-batch2-design.md
  Test B: 52-week-high momentum (George & Hwang 2004).
  Test C: low-volatility long-only tilt (Frazzini-Pedersen 2014 / Agarwalla et al 2014).
  Test D: overnight vs intraday return decomposition (Cooper et al 2008 / Lou-Polk-Skouras 2019).

REUSES kite/research/universe_lab.py conventions verbatim where the spec says to:
  - loader: data/daily_universe/*_day.csv, tz-naive date index, dedupe on date,
    turn_med = (close*volume).rolling(60).median(), MIN_TURNOVER=2e7, MIN_PRICE=20.
  - USim: next-day-open fills, SLIP=0.002 (0.2%/side), delivery charges via
    config.zerodha_charges(is_intraday=False), monthly rebalance (first trading day).
  - Benchmark: daily-rebalanced EW universe proxy, clipped +/-25% daily returns.
  - Split: train 2015-2021, validation 2022-2026.

No parameter tuning. Whatever prints is the answer.

Usage: python -W ignore kite/research/anomaly_batch2.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'kite'))
from config import zerodha_charges

DATA_DIR = ROOT / 'data' / 'daily_universe'
OUT_FILE = ROOT / 'kite' / 'research' / 'anomaly_batch2_results.txt'
SLIP = 0.002
CAPITAL = 100_000
TRAIN_END = pd.Timestamp('2021-12-31')
MIN_TURNOVER = 2e7
MIN_PRICE = 20.0
TOP_N = 20

# Test D flat cost assumption (stated explicitly per spec instruction).
OVERNIGHT_COST_PER_DAY = 0.0025   # ~0.2% slippage (round trip) + delivery STT/charges, flat/day
OVERNIGHT_BAR = 0.0002            # frozen +2bp/day tradeability bar

_LINES = []


def log(s=''):
    print(s, flush=True)
    _LINES.append(str(s))


def flush_out():
    OUT_FILE.write_text('\n'.join(_LINES) + '\n', encoding='utf-8')


# ---------------------------------------------------------------------------
# Loader -- same conventions as universe_lab.load(), extended with the two
# extra signal columns this batch needs (ratio_52wh, vol126). mom63 kept too
# because Test B needs it for the rank-correlation side-check.
# ---------------------------------------------------------------------------
def load():
    data = {}
    for f in sorted(DATA_DIR.glob('*_day.csv')):
        sym = f.name[:-8]
        df = pd.read_csv(f, parse_dates=['datetime'])
        df['date'] = df.datetime.dt.tz_localize(None).dt.normalize()
        df = df.set_index('date')[['open', 'high', 'low', 'close', 'volume']]
        df = df[~df.index.duplicated(keep='last')]
        if len(df) < 300:
            continue
        df['turn_med'] = (df.close * df.volume).rolling(60).median()
        df['mom63'] = df.close.pct_change(63)
        df['ratio_52wh'] = df.close / df.high.rolling(252).max()
        df['vol126'] = df.close.pct_change().rolling(126).std()
        data[sym] = df
    return data


# ---------------------------------------------------------------------------
# USim -- copied verbatim from universe_lab.py (spec: "Engine reuse: portfolio
# tests (B, C) run through the universe_lab USim pattern"). Not touched.
# ---------------------------------------------------------------------------
class USim:
    def __init__(self, data, dates, top_n):
        self.data, self.dates, self.top_n = data, dates, top_n

    def run(self, strategy):
        cash, positions, trades = CAPITAL, {}, []
        eq = []
        pending = None
        for t in self.dates:
            if pending:
                for sym in pending['exits']:
                    p = positions.pop(sym, None)
                    if p is None:
                        continue
                    o = self.data[sym].open.get(t)
                    if o is None or np.isnan(o):
                        positions[sym] = p
                        continue
                    px = o * (1 - SLIP)
                    sell_v, buy_v = p['qty'] * px, p['qty'] * p['entry']
                    fees = sum(zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False).values())
                    cash += sell_v - fees
                    trades.append(sell_v - buy_v - fees)
                for sym in pending['entries']:
                    if sym in positions or len(positions) >= self.top_n:
                        continue
                    o = self.data[sym].open.get(t)
                    if o is None or np.isnan(o):
                        continue
                    px = o * (1 + SLIP)
                    slot = min(cash, (cash + self._mval(positions, t)) / self.top_n)
                    qty = int(slot / px)
                    if qty <= 0:
                        continue
                    cash -= qty * px
                    positions[sym] = {'qty': qty, 'entry': px}
                pending = None
            pending = strategy(t, positions)
            eq.append((t, cash + self._mval(positions, t)))
        s = pd.Series(dict(eq))
        r = s.pct_change().dropna()
        yrs = len(s) / 252
        wins = sum(1 for x in trades if x > 0)
        return {'cagr': round(((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1) * 100, 1),
                'sharpe': round(r.mean() / r.std() * np.sqrt(252), 2) if r.std() > 0 else 0,
                'maxdd': round(((s / s.cummax()) - 1).min() * 100, 1),
                'trades': len(trades),
                'win': round(100 * wins / max(len(trades), 1), 1)}

    def _mval(self, positions, t):
        return sum(p['qty'] * self.data[s].close.get(t, p['entry']) for s, p in positions.items())


def make_strat(data, dates, score_col, top_n, ascending=False):
    """Monthly rebalance (first trading day), liquid-gated, rank by score_col.
    ascending=False -> descending rank, highest score wins (Test B).
    ascending=True  -> ascending rank, lowest score wins (Test C, low-vol)."""
    month = pd.Series(dates, index=dates).dt.month
    reb = set(dates[np.r_[True, month.values[1:] != month.values[:-1]]])

    def strat(t, positions):
        if t not in reb:
            return {'entries': [], 'exits': []}
        scores = {}
        for sym, df in data.items():
            if t not in df.index:
                continue
            row = df.loc[t]
            sc = row.get(score_col)
            if (sc is None or np.isnan(sc) or np.isnan(row.turn_med)
                    or row.turn_med < MIN_TURNOVER or row.close < MIN_PRICE):
                continue
            scores[sym] = sc
        top = sorted(scores, key=scores.get, reverse=not ascending)[:top_n]
        return {'entries': [s for s in top if s not in positions],
                'exits': [s for s in positions if s not in top]}
    return strat


# ---------------------------------------------------------------------------
# Benchmark: universe_lab's daily-rebalanced, clipped +/-25%, EW proxy.
# ---------------------------------------------------------------------------
def build_proxy(data, all_dates):
    idx = pd.DataFrame({s: df.close for s, df in data.items()}).reindex(all_dates)
    return (1 + idx.pct_change().clip(-0.25, 0.25).mean(axis=1, skipna=True).fillna(0)).cumprod()


def bh_stats(seg):
    yrs = len(seg) / 252
    r = seg.pct_change().dropna()
    cagr = ((seg.iloc[-1] / seg.iloc[0]) ** (1 / yrs) - 1) * 100
    sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0
    dd = ((seg / seg.cummax()) - 1).min() * 100
    return {'cagr': round(cagr, 1), 'sharpe': round(sharpe, 2), 'maxdd': round(dd, 1)}


def print_strategy_vs_bh(rt, rv, bh_train, bh_val):
    log(f'{"":16} {"cagr%":>8} {"sharpe":>8} {"maxdd%":>8} {"trades":>8}')
    log(f'{"strategy train":16} {rt["cagr"]:8.1f} {rt["sharpe"]:8.2f} {rt["maxdd"]:8.1f} {rt["trades"]:8}')
    log(f'{"strategy val":16} {rv["cagr"]:8.1f} {rv["sharpe"]:8.2f} {rv["maxdd"]:8.1f} {"":>8}')
    log(f'{"B&H EW train":16} {bh_train["cagr"]:8.1f} {bh_train["sharpe"]:8.2f} {bh_train["maxdd"]:8.1f} {"":>8}')
    log(f'{"B&H EW val":16} {bh_val["cagr"]:8.1f} {bh_val["sharpe"]:8.2f} {bh_val["maxdd"]:8.1f} {"":>8}')


# ---------------------------------------------------------------------------
# Test B side-check: Spearman rank corr between ratio_52wh and mom63, at each
# monthly rebalance date, over the liquid-gated cross-section, then averaged.
# ---------------------------------------------------------------------------
def spearman_ratio_vs_mom(data, dates):
    if len(dates) == 0:
        return float('nan'), 0
    month = pd.Series(dates, index=dates).dt.month
    reb = dates[np.r_[True, month.values[1:] != month.values[:-1]]]
    corrs = []
    for t in reb:
        a, b = [], []
        for sym, df in data.items():
            if t not in df.index:
                continue
            row = df.loc[t]
            rr, mm = row.get('ratio_52wh'), row.get('mom63')
            if (rr is None or mm is None or np.isnan(rr) or np.isnan(mm) or np.isnan(row.turn_med)
                    or row.turn_med < MIN_TURNOVER or row.close < MIN_PRICE):
                continue
            a.append(rr)
            b.append(mm)
        if len(a) < 10:
            continue
        c = pd.Series(a).corr(pd.Series(b), method='spearman')
        if not np.isnan(c):
            corrs.append(c)
    return (float(np.mean(corrs)) if corrs else float('nan')), len(corrs)


# ---------------------------------------------------------------------------
# Test B
# ---------------------------------------------------------------------------
def test_B(data, train, val, bh_train, bh_val):
    log('')
    log('=' * 78)
    log('TEST B -- 52-WEEK-HIGH MOMENTUM')
    log('signal: ratio_52wh = close / rolling-252-trading-day max(high)')
    log('monthly rebalance, top 20 by ratio_52wh descending, EW, USim engine')
    log('=' * 78)

    rt = USim(data, train, TOP_N).run(make_strat(data, train, 'ratio_52wh', TOP_N, ascending=False))
    rv = USim(data, val, TOP_N).run(make_strat(data, val, 'ratio_52wh', TOP_N, ascending=False))
    print_strategy_vs_bh(rt, rv, bh_train, bh_val)

    corr_train, n_train = spearman_ratio_vs_mom(data, train)
    corr_val, n_val = spearman_ratio_vs_mom(data, val)
    corr_all, n_all = spearman_ratio_vs_mom(data, np.r_[train, val] if len(val) else train)
    log('')
    log('Signal distinctness check -- Spearman rank corr(ratio_52wh, mom63), avg over rebalance dates:')
    log(f'  train (2015-2021)     : {corr_train:6.3f}  (n_rebalance_dates={n_train})')
    log(f'  val   (2022-2026)     : {corr_val:6.3f}  (n_rebalance_dates={n_val})')
    log(f'  full  (2015-2026)     : {corr_all:6.3f}  (n_rebalance_dates={n_all})')
    if not np.isnan(corr_all):
        verdict_txt = ('highly overlapping with momentum (>0.7)' if corr_all > 0.7 else
                        'moderately related to momentum (0.4-0.7)' if corr_all > 0.4 else
                        'largely distinct from mom63 (<=0.4)')
        log(f'  -> {verdict_txt}')

    log('')
    log('Frozen verdict (validation 2022-2026, PASS requires ALL 3):')
    c1 = rv['sharpe'] >= bh_val['sharpe'] + 0.10
    log(f'  1. Sharpe >= B&H Sharpe + 0.10        : {rv["sharpe"]:.2f} >= {bh_val["sharpe"] + 0.10:.2f}  -> {"PASS" if c1 else "FAIL"}')
    c2 = rv['cagr'] >= bh_val['cagr'] - 2.0
    log(f'  2. CAGR >= B&H CAGR - 2pts             : {rv["cagr"]:.1f} >= {bh_val["cagr"] - 2.0:.1f}  -> {"PASS" if c2 else "FAIL"}')
    edge_train = rt['sharpe'] - bh_train['sharpe']
    edge_val = rv['sharpe'] - bh_val['sharpe']
    c3 = (edge_train > 0) == (edge_val > 0)
    log(f'  3. Same-direction train (no sign flip) : train edge(sharpe) {edge_train:+.2f}, val edge(sharpe) {edge_val:+.2f}  -> {"PASS" if c3 else "FAIL"}')
    overall = c1 and c2 and c3
    log(f'  TEST B OVERALL: {"PASS -> survivor, to incubator per October Contract" if overall else "FAIL -> tombstone"}')
    return overall


# ---------------------------------------------------------------------------
# Test C
# ---------------------------------------------------------------------------
def test_C(data, train, val, bh_train, bh_val):
    log('')
    log('=' * 78)
    log('TEST C -- LOW-VOLATILITY LONG-ONLY TILT')
    log('signal: vol126 = rolling-126d std of daily returns')
    log('monthly rebalance, bottom 20 by vol126 (lowest vol), EW, USim engine')
    log('=' * 78)

    rt = USim(data, train, TOP_N).run(make_strat(data, train, 'vol126', TOP_N, ascending=True))
    rv = USim(data, val, TOP_N).run(make_strat(data, val, 'vol126', TOP_N, ascending=True))
    print_strategy_vs_bh(rt, rv, bh_train, bh_val)

    log('')
    log('Frozen verdict (validation 2022-2026, PASS requires ALL 4; graded risk-adjusted per spec):')
    c1 = rv['sharpe'] >= bh_val['sharpe'] + 0.10
    log(f'  1. Sharpe >= B&H Sharpe + 0.10         : {rv["sharpe"]:.2f} >= {bh_val["sharpe"] + 0.10:.2f}  -> {"PASS" if c1 else "FAIL"}')
    c2 = abs(rv['maxdd']) <= abs(bh_val['maxdd']) * 0.75
    log(f'  2. MaxDD >=25% shallower (relative)    : |{rv["maxdd"]:.1f}| <= |{bh_val["maxdd"]:.1f}|*0.75={abs(bh_val["maxdd"]) * 0.75:.1f}  -> {"PASS" if c2 else "FAIL"}')
    c3 = rv['cagr'] >= bh_val['cagr'] - 3.0
    log(f'  3. CAGR >= B&H CAGR - 3pts             : {rv["cagr"]:.1f} >= {bh_val["cagr"] - 3.0:.1f}  -> {"PASS" if c3 else "FAIL"}')
    edge_train = rt['sharpe'] - bh_train['sharpe']
    edge_val = rv['sharpe'] - bh_val['sharpe']
    c4 = (edge_train > 0) == (edge_val > 0)
    log(f'  4. Same-direction train (no sign flip) : train edge(sharpe) {edge_train:+.2f}, val edge(sharpe) {edge_val:+.2f}  -> {"PASS" if c4 else "FAIL"}')
    overall = c1 and c2 and c3 and c4
    log(f'  TEST C OVERALL: {"PASS -> survivor, to incubator per October Contract" if overall else "FAIL -> tombstone"}')
    return overall


# ---------------------------------------------------------------------------
# Test D -- overnight/intraday decomposition, pure accounting + tradeable check
# ---------------------------------------------------------------------------
def test_D(data, all_dates):
    log('')
    log('=' * 78)
    log('TEST D -- OVERNIGHT ANOMALY (decomposition + tradeable check)')
    log('overnight_ret[t] = mean over liquid universe of (open_t/close_{t-1} - 1), clipped +/-25% per stock')
    log('intraday_ret[t]  = mean over liquid universe of (close_t/open_t - 1), clipped +/-25% per stock')
    log('liquidity gate: 60d median turnover > 2cr AND close > 20 (same-day, contemporaneous)')
    log('=' * 78)

    on_dict, io_dict = {}, {}
    for sym, df in data.items():
        prev_close = df.close.shift(1)
        liquid = (df.turn_med > MIN_TURNOVER) & (df.close > MIN_PRICE)
        on = ((df.open / prev_close - 1).clip(-0.25, 0.25)).where(liquid)
        io = ((df.close / df.open - 1).clip(-0.25, 0.25)).where(liquid)
        on_dict[sym] = on
        io_dict[sym] = io
    on_df = pd.DataFrame(on_dict).reindex(all_dates)
    io_df = pd.DataFrame(io_dict).reindex(all_dates)
    overnight_ret = on_df.mean(axis=1, skipna=True)
    intraday_ret = io_df.mean(axis=1, skipna=True)
    n_liquid = on_df.notna().sum(axis=1)
    # dates with zero liquid names (pre-history) contribute 0 to the compounded leg
    overnight_ret_c = overnight_ret.fillna(0)
    intraday_ret_c = intraday_ret.fillna(0)

    total_on = ((1 + overnight_ret_c).prod() - 1) * 100
    total_io = ((1 + intraday_ret_c).prod() - 1) * 100
    log('')
    log(f'Cumulative compounded totals, full sample ({all_dates.min().date()} -> {all_dates.max().date()}):')
    log(f'  overnight leg (close->open) : {total_on:10.1f}%')
    log(f'  intraday leg  (open->close) : {total_io:10.1f}%')

    eras = [('2015-19', '2015-01-01', '2019-12-31'),
            ('2020-22', '2020-01-01', '2022-12-31'),
            ('2023-26', '2023-01-01', str(all_dates.max().date()))]
    log('')
    log('Per-era cumulative compounded totals:')
    for name, start, end in eras:
        seg_on = overnight_ret_c.loc[start:end]
        seg_io = intraday_ret_c.loc[start:end]
        if len(seg_on) == 0:
            continue
        tot_on = ((1 + seg_on).prod() - 1) * 100
        tot_io = ((1 + seg_io).prod() - 1) * 100
        n_liq_avg = n_liquid.loc[start:end].mean()
        log(f'  era {name} ({len(seg_on):4} days, avg {n_liq_avg:5.1f} liquid names/day): '
            f'overnight {tot_on:9.1f}%   intraday {tot_io:9.1f}%')

    log('')
    log('Tradeable check (buy-at-close / sell-at-next-open, full delivery costs):')
    log(f'  ASSUMPTION (stated explicitly per spec): flat cost of {OVERNIGHT_COST_PER_DAY * 100:.2f}%/day applied to the')
    log('  overnight leg, approximating one full delivery round trip (0.2%/side slippage x2 sides')
    log('  ~= 0.4%, netted against typical delivery brokerage/STT/charges being near-zero on the')
    log('  buy side and ~0.1% STT + minor exchange/GST charges on the sell side; 0.25%/day is the')
    log('  frozen approximation from the spec, not re-derived per trade via the USim engine here.')
    raw_mean = overnight_ret.mean()  # mean over days with at least one liquid name (skipna via .mean())
    net_mean = raw_mean - OVERNIGHT_COST_PER_DAY
    log(f'  raw overnight mean/day   : {raw_mean * 10000:8.2f} bp')
    log(f'  net overnight mean/day   : {net_mean * 10000:8.2f} bp  (raw - {OVERNIGHT_COST_PER_DAY * 10000:.0f}bp)')
    log(f'  frozen tradeable bar     : {OVERNIGHT_BAR * 10000:8.2f} bp/day (~+5%/yr)')
    tradeable = net_mean >= OVERNIGHT_BAR
    log(f'  TEST D VERDICT: {"TRADEABLE (survives costs)" if tradeable else "TOMBSTONE (dies on costs, decomposition kept as reference knowledge)"}')
    return tradeable


def main():
    log('ANOMALY BATCH 2 -- Tests B, C, D')
    log(f'Spec: docs/superpowers/specs/2026-07-22-anomaly-batch2-design.md')
    log('')
    data = load()
    log(f'universe loaded: {len(data)} symbols')
    all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    train = all_dates[all_dates <= TRAIN_END]
    val = all_dates[all_dates > TRAIN_END]
    log(f'train: {train.min().date()} -> {train.max().date()} ({len(train)} days)')
    log(f'val  : {val.min().date()} -> {val.max().date()} ({len(val)} days)')

    proxy = build_proxy(data, all_dates)
    bh_train = bh_stats(proxy.reindex(train).dropna())
    bh_val = bh_stats(proxy.reindex(val).dropna())
    flush_out()

    test_B(data, train, val, bh_train, bh_val)
    flush_out()

    test_C(data, train, val, bh_train, bh_val)
    flush_out()

    test_D(data, all_dates)
    flush_out()

    log('')
    log('=' * 78)
    log('Meta-guard reminder: 4 tests run this batch. Family-wise, >=1 lucky survivor')
    log('is statistically expected even if all anomalies are dead. Any PASS above goes')
    log('to the incubator (October Contract) for a full paper trial -- no exceptions,')
    log('no direct-to-real-money promotion from this script\'s output alone.')
    log('=' * 78)
    flush_out()
    print(f'\nFull output saved to {OUT_FILE}')


if __name__ == '__main__':
    main()
