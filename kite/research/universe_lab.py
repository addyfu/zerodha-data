"""Breadth momentum lab — cross-sectional momentum over the top-800 liquid NSE
universe (data/daily_universe/). The one hypothesis untested by the NIFTY-50 work:
does momentum pay when the pond is 800 stocks instead of 47?

Honest rules (matching prior labs, harsher costs for smallcaps):
- Signals on close, fills next day open. Slippage 0.2%/side (smallcap-honest).
- Delivery charges via config.zerodha_charges(is_intraday=False).
- Long-only. Monthly rebalance (first trading day). Regime filter: equal-weight
  universe proxy > 200SMA else cash.
- Liquidity gate at signal time: 60d median turnover > 2cr AND close > 20.
- Grid (frozen): lookback in {63, 126, '12-1'}, top_n in {10, 20}, regime on/off.
- Train 2015-2021, validation 2022-2026. Benchmarks: universe EW B&H, and the
  same-universe top-N random check is implicit via regime-off rows.

Usage: python kite/research/universe_lab.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'kite'))
from config import zerodha_charges

DATA_DIR = ROOT / 'data' / 'daily_universe'
SLIP = 0.002
CAPITAL = 100_000
TRAIN_END = pd.Timestamp('2021-12-31')
MIN_TURNOVER = 2e7
MIN_PRICE = 20.0


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
        for lb in (63, 126):
            df[f'mom{lb}'] = df.close.pct_change(lb)
        df['mom12_1'] = df.close.shift(21) / df.close.shift(252) - 1
        data[sym] = df
    return data


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


def make_strat(data, dates, mom_col, top_n, regime):
    month = pd.Series(dates, index=dates).dt.month
    reb = set(dates[np.r_[True, month.values[1:] != month.values[:-1]]])

    def strat(t, positions):
        if t not in reb:
            return {'entries': [], 'exits': []}
        if regime is not None and not regime.get(t, False):
            return {'entries': [], 'exits': list(positions)}
        scores = {}
        for sym, df in data.items():
            if t not in df.index:
                continue
            row = df.loc[t]
            m = row.get(mom_col)
            if (m is None or np.isnan(m) or np.isnan(row.turn_med)
                    or row.turn_med < MIN_TURNOVER or row.close < MIN_PRICE):
                continue
            scores[sym] = m
        top = sorted(scores, key=scores.get, reverse=True)[:top_n]
        return {'entries': [s for s in top if s not in positions],
                'exits': [s for s in positions if s not in top]}
    return strat


def main():
    data = load()
    if '--pre2015' in sys.argv:
        data = {s: df for s, df in data.items() if df.index[0] <= pd.Timestamp('2015-06-30')}
        print('SURVIVORSHIP-BOUNDED RUN: pre-2015 listings only')
    print(f'universe loaded: {len(data)} symbols')
    all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    idx = pd.DataFrame({s: df.close for s, df in data.items()}).reindex(all_dates)
    # daily-rebalanced EW index: handles mid-sample listings without level jumps.
    # Clip daily returns to +/-25%: junk rows (bad ticks, unadjusted splits) otherwise
    # poison the cumulative product into inf.
    proxy = (1 + idx.pct_change().clip(-0.25, 0.25).mean(axis=1, skipna=True).fillna(0)).cumprod()
    regime = proxy > proxy.rolling(200).mean()
    train = all_dates[all_dates <= TRAIN_END]
    val = all_dates[all_dates > TRAIN_END]

    for nm, seg in [('B&H universe EW train', proxy.reindex(train).dropna()),
                    ('B&H universe EW val', proxy.reindex(val).dropna())]:
        yrs = len(seg) / 252
        cagr = ((seg.iloc[-1] / seg.iloc[0]) ** (1 / yrs) - 1) * 100
        dd = ((seg / seg.cummax()) - 1).min() * 100
        print(f'{nm:34}: cagr {cagr:5.1f}% dd {dd:5.1f}%')

    print(f'\n{"config":30} | {"TRAIN cagr shrp dd% trd":26} | VAL same')
    for mom_col in ('mom63', 'mom126', 'mom12_1'):
        for top_n in (10, 20):
            for rg in (True, False):
                name = f'{mom_col} n={top_n} rg={rg}'
                rt = USim(data, train, top_n).run(make_strat(data, train, mom_col, top_n, regime if rg else None))
                rv = USim(data, val, top_n).run(make_strat(data, val, mom_col, top_n, regime if rg else None))
                print(f'{name:30} | {rt["cagr"]:6} {rt["sharpe"]:5} {rt["maxdd"]:6} {rt["trades"]:4} '
                      f'| {rv["cagr"]:6} {rv["sharpe"]:5} {rv["maxdd"]:6} {rv["trades"]:4}', flush=True)


if __name__ == '__main__':
    main()
