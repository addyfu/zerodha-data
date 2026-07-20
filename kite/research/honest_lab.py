"""Honest strategy research lab.

Rules baked in (non-negotiable):
- Signals computed on close of day t, executed at open of day t+1.
- Long-only NSE cash equity, delivery charges (is_intraday=False) + slippage both sides.
- Shared portfolio capital, max 5 slots, equal-weight slots.
- Train: 2020-07 .. 2024-06.  Validation: 2024-07 .. 2026-01. No peeking: pick on train, report val once.

Usage: python kite/research/honest_lab.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import zerodha_charges

DATA_DIR = Path(__file__).resolve().parents[2] / 'data' / 'daily'
SLIPPAGE = 0.0005  # 0.05% per side, conservative for NIFTY-50 large caps
CAPITAL = 100_000
MAX_SLOTS = 5
TRAIN_END = '2024-06-30'


# ---------------------------------------------------------------- indicators
def rsi(close, n):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn)


def atr(df, n=14):
    tr = pd.concat([df.high - df.low,
                    (df.high - df.close.shift()).abs(),
                    (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, min_periods=n).mean()


def adx(df, n=14):
    up, dn = df.high.diff(), -df.low.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    trn = atr(df, n)
    pdi = 100 * pd.Series(plus, index=df.index).ewm(alpha=1 / n, min_periods=n).mean() / trn
    mdi = 100 * pd.Series(minus, index=df.index).ewm(alpha=1 / n, min_periods=n).mean() / trn
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi)
    return dx.ewm(alpha=1 / n, min_periods=n).mean()


def load_data():
    data = {}
    for f in sorted(DATA_DIR.glob('*_day_2000d.csv')):
        sym = f.name.split('_day_')[0]
        df = pd.read_csv(f, parse_dates=['datetime'])
        df['date'] = df.datetime.dt.tz_localize(None).dt.normalize()
        df = df.set_index('date')[['open', 'high', 'low', 'close', 'volume']]
        if len(df) > 300:
            data[sym] = df
    return data


def add_indicators(df):
    c = df.close
    df['ema20'] = c.ewm(span=20).mean()
    df['ema50'] = c.ewm(span=50).mean()
    df['ema200'] = c.ewm(span=200).mean()
    df['sma5'] = c.rolling(5).mean()
    df['sma200'] = c.rolling(200).mean()
    df['rsi2'] = rsi(c, 2)
    df['atr'] = atr(df)
    df['adx'] = adx(df)
    for lb in (63, 126, 252):
        df[f'mom{lb}'] = c.pct_change(lb)
    return df


# ---------------------------------------------------------------- engine
class Sim:
    """Event-loop portfolio sim. Strategy sees rows <= t, orders fill at t+1 open."""

    def __init__(self, data, dates):
        self.data, self.dates = data, dates

    def run(self, strategy):
        cash, positions, trades = CAPITAL, {}, []  # sym -> dict(qty, entry, entry_date, bars, trail)
        equity_curve = []
        pending = None  # orders decided at close t, filled at open t+1
        for t in self.dates:
            # 1. fill pending orders at today's open
            if pending:
                for sym in pending['exits']:
                    if sym not in positions:
                        continue
                    p, o = positions.pop(sym), self.data[sym].open.get(t)
                    if o is None or np.isnan(o):
                        positions[sym] = p
                        continue
                    px = o * (1 - SLIPPAGE)
                    buy_v, sell_v = p['qty'] * p['entry'], p['qty'] * px
                    fees = sum(zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False).values())
                    cash += sell_v - fees
                    trades.append({'sym': sym, 'entry_date': p['entry_date'], 'exit_date': t,
                                   'pnl': sell_v - buy_v - fees})
                for sym in pending['entries']:
                    if sym in positions or len(positions) >= MAX_SLOTS:
                        continue
                    o = self.data[sym].open.get(t)
                    if o is None or np.isnan(o):
                        continue
                    px = o * (1 + SLIPPAGE)
                    slot = min(cash, (cash + self._mkt_value(positions, t)) / MAX_SLOTS)
                    qty = int(slot / px)
                    if qty <= 0:
                        continue
                    cash -= qty * px
                    positions[sym] = {'qty': qty, 'entry': px, 'entry_date': t, 'bars': 0, 'trail': -np.inf}
                pending = None
            # 2. compute signals at today's close
            for p in positions.values():
                p['bars'] += 1
            pending = strategy(t, positions)
            equity_curve.append((t, cash + self._mkt_value(positions, t)))
        eq = pd.Series(dict(equity_curve))
        return self._metrics(eq, trades)

    def _mkt_value(self, positions, t):
        return sum(p['qty'] * self.data[s].close.get(t, p['entry']) for s, p in positions.items())

    @staticmethod
    def _metrics(eq, trades):
        r = eq.pct_change().dropna()
        yrs = len(eq) / 252
        cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else 0
        sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0
        dd = (eq / eq.cummax() - 1).min()
        wins = [t for t in trades if t['pnl'] > 0]
        return {'cagr%': round(cagr * 100, 1), 'sharpe': round(sharpe, 2),
                'maxdd%': round(dd * 100, 1), 'trades': len(trades),
                'win%': round(100 * len(wins) / len(trades), 1) if trades else 0,
                'final': int(eq.iloc[-1])}


# ---------------------------------------------------------------- strategies
def make_momo(data, dates, lookback, top_n, regime):
    month = pd.Series(dates, index=dates).dt.month
    rebalance = set(dates[np.r_[True, month.values[1:] != month.values[:-1]]])

    def strat(t, positions):
        if t not in rebalance:
            return {'entries': [], 'exits': []}
        if regime is not None and not regime.get(t, False):
            return {'entries': [], 'exits': list(positions)}
        scores = {}
        for sym, df in data.items():
            row = df[f'mom{lookback}'].get(t)
            if row is not None and not np.isnan(row):
                scores[sym] = row
        top = sorted(scores, key=scores.get, reverse=True)[:top_n]
        return {'entries': [s for s in top if s not in positions],
                'exits': [s for s in positions if s not in top]}
    return strat


def make_trend(data, adx_min):
    def strat(t, positions):
        entries, exits = [], []
        for sym, df in data.items():
            if t not in df.index:
                continue
            row = df.loc[t]
            if sym in positions:
                p = positions[sym]
                p['trail'] = max(p['trail'], row.close - 3 * row.atr)
                if row.close < row.ema50 or row.close < p['trail']:
                    exits.append(sym)
            elif (row.ema50 > row.ema200 and row.close > row.ema20
                  and row.adx > adx_min and not np.isnan(row.ema200)):
                entries.append(sym)
        return {'entries': entries, 'exits': exits}
    return strat


def make_pullback(data, rsi_buy, max_hold):
    def strat(t, positions):
        entries, exits = [], []
        for sym, df in data.items():
            if t not in df.index:
                continue
            row = df.loc[t]
            if sym in positions:
                if row.close > row.sma5 or positions[sym]['bars'] >= max_hold:
                    exits.append(sym)
            elif row.close > row.sma200 and row.rsi2 < rsi_buy and not np.isnan(row.sma200):
                entries.append(sym)
        return {'entries': entries, 'exits': exits}
    return strat


# ---------------------------------------------------------------- run
def main():
    data = {s: add_indicators(df) for s, df in load_data().items()}
    all_dates = sorted(set().union(*[df.index for df in data.values()]))
    all_dates = pd.DatetimeIndex(all_dates)

    # regime: equal-weight index of universe vs its 200SMA
    idx = pd.DataFrame({s: df.close for s, df in data.items()}).reindex(all_dates)
    proxy = (idx / idx.iloc[0]).mean(axis=1, skipna=True)
    regime = (proxy > proxy.rolling(200).mean())

    train = all_dates[all_dates <= TRAIN_END]
    val = all_dates[all_dates > TRAIN_END]

    grids = []
    for lb in (63, 126, 252):
        for n in (3, 5):
            for rg in (True, False):
                grids.append((f'momo lb={lb} n={n} regime={rg}',
                              lambda d=None, lb=lb, n=n, rg=rg: make_momo(
                                  data, d, lb, n, regime if rg else None)))
    for adx_min in (0, 20, 25):
        grids.append((f'trend adx>{adx_min}', lambda d=None, a=adx_min: make_trend(data, a)))
    for rb in (5, 10):
        for mh in (7, 10):
            grids.append((f'pullback rsi<{rb} hold<={mh}',
                          lambda d=None, rb=rb, mh=mh: make_pullback(data, rb, mh)))

    print(f'{"strategy":34} | {"TRAIN cagr% shrp dd% trds win%":32} | VAL same')
    rows = []
    for name, factory in grids:
        res_t = Sim(data, train).run(factory(train))
        res_v = Sim(data, val).run(factory(val))
        rows.append((name, res_t, res_v))
        print(f'{name:34} | {res_t["cagr%"]:6} {res_t["sharpe"]:5} {res_t["maxdd%"]:6} '
              f'{res_t["trades"]:5} {res_t["win%"]:5} | {res_v["cagr%"]:6} {res_v["sharpe"]:5} '
              f'{res_v["maxdd%"]:6} {res_v["trades"]:5} {res_v["win%"]:5}')

    out = Path(__file__).with_name('lab_results.csv')
    pd.DataFrame([{'name': n, **{f't_{k}': v for k, v in t.items()},
                   **{f'v_{k}': v for k, v in vv.items()}} for n, t, vv in rows]).to_csv(out, index=False)
    print(f'\nsaved -> {out}')


if __name__ == '__main__':
    main()
