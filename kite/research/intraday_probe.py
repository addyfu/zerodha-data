"""Intraday probe: ORB + first-hour momentum on 1-min data. NO parameter tuning —
rules are fixed a priori; this is a falsification probe on two independent samples
(Nov 2025-Jan 2026 CSVs, and the July 2026 week from the release DB).

Rules (long-only cash intraday, square-off 15:15):
- ORB-15 / ORB-30: opening range 9:15+N min. First 1-min close above range high
  -> buy next bar open. Stop = range low. Target = entry + 2*(entry-stop).
  One trade per stock per day, max 5 concurrent, risk 1% of capital per trade.
- FHM: at 10:15 rank stocks by return since 9:15 open; buy top 3 (if > +0.5%)
  at next bar open, stop -1%, square-off 15:15.

Costs: real intraday Zerodha charges + 0.05% slippage per side.
"""
import sys
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'kite'))
from config import zerodha_charges

SLIP = 0.0005
CAPITAL = 100_000
MAX_POS = 5
RISK_PCT = 0.01
SQUARE_OFF = pd.Timestamp('15:15').time()


def load_csvs():
    data = {}
    for f in sorted((ROOT / 'data').glob('*_minute_60d.csv')):
        sym = f.name.split('_minute_')[0]
        df = pd.read_csv(f, parse_dates=['datetime'])
        df['datetime'] = df.datetime.dt.tz_localize(None)
        data[sym] = df.set_index('datetime')[['open', 'high', 'low', 'close']]
    return data


def load_db(path):
    con = sqlite3.connect(path)
    syms = tuple(load_csvs().keys())
    q = f"SELECT symbol, datetime, open, high, low, close FROM ohlcv WHERE interval='minute' AND symbol IN {syms}"
    df = pd.read_sql(q, con, parse_dates=['datetime'])
    con.close()
    df['datetime'] = pd.to_datetime(df.datetime, utc=True).dt.tz_convert('Asia/Kolkata').dt.tz_localize(None)
    return {s: g.set_index('datetime')[['open', 'high', 'low', 'close']].sort_index()
            for s, g in df.groupby('symbol')}


def trade_cost(buy_v, sell_v):
    return sum(zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=True).values())


def run_day(day_bars, entries):
    """entries: list of (entry_time_idx position in bars, sym, entry_px, stop, target).
    Walk bars minute by minute, manage exits. Returns trade pnls."""
    trades = []
    open_pos = {}
    minutes = sorted({t for bars in day_bars.values() for t in bars.index})
    entry_map = {}
    for t, sym, px, sl, tp, qty in entries:
        entry_map.setdefault(t, []).append((sym, px, sl, tp, qty))
    for t in minutes:
        for sym, px, sl, tp, qty in entry_map.get(t, []):
            if sym not in open_pos and len(open_pos) < MAX_POS and qty > 0:
                open_pos[sym] = {'entry': px, 'sl': sl, 'tp': tp, 'qty': qty}
        for sym in list(open_pos):
            bars = day_bars.get(sym)
            if bars is None or t not in bars.index:
                continue
            row, p = bars.loc[t], open_pos[sym]
            exit_px = None
            if row.low <= p['sl']:
                exit_px = min(row.open, p['sl']) * (1 - SLIP)
            elif row.high >= p['tp']:
                exit_px = max(row.open, p['tp']) * (1 - SLIP)
            elif t.time() >= SQUARE_OFF:
                exit_px = row.close * (1 - SLIP)
            if exit_px is not None:
                buy_v, sell_v = p['qty'] * p['entry'], p['qty'] * exit_px
                trades.append(sell_v - buy_v - trade_cost(buy_v, sell_v))
                del open_pos[sym]
    return trades


def orb_entries(day_bars, range_min):
    entries = []
    for sym, bars in day_bars.items():
        rng = bars.between_time('09:15', f'09:{15 + range_min - 1}')
        if len(rng) < range_min - 2:
            continue
        hi, lo = rng.high.max(), rng.low.min()
        post = bars[bars.index > rng.index[-1]]
        brk = post[post.close > hi]
        if brk.empty:
            continue
        sig_t = brk.index[0]
        later = post[post.index > sig_t]
        if later.empty:
            continue
        t = later.index[0]
        px = later.iloc[0].open * (1 + SLIP)
        risk = px - lo
        if risk <= 0 or t.time() >= SQUARE_OFF:
            continue
        qty = min(int(CAPITAL * RISK_PCT / risk), int((CAPITAL / MAX_POS) / px))
        entries.append((t, sym, px, lo, px + 2 * risk, qty))
    return entries


def fhm_entries(day_bars):
    scores = {}
    for sym, bars in day_bars.items():
        fh = bars.between_time('09:15', '10:15')
        if len(fh) < 50:
            continue
        ret = fh.close.iloc[-1] / fh.open.iloc[0] - 1
        if ret > 0.005:
            scores[sym] = (ret, fh.index[-1])
    entries = []
    for sym in sorted(scores, key=lambda s: scores[s][0], reverse=True)[:3]:
        bars = day_bars[sym]
        later = bars[bars.index > scores[sym][1]]
        if later.empty:
            continue
        t = later.index[0]
        px = later.iloc[0].open * (1 + SLIP)
        qty = int((CAPITAL / 3) / px)
        entries.append((t, sym, px, px * 0.99, px * 1.03, qty))
    return entries


def probe(data, label):
    days = sorted({t.date() for df in data.values() for t in df.index})
    results = {'ORB-15': [], 'ORB-30': [], 'FHM': []}
    for d in days:
        day_bars = {}
        for sym, df in data.items():
            b = df[df.index.date == d]
            if len(b) > 100:
                day_bars[sym] = b
        if len(day_bars) < 10:
            continue
        results['ORB-15'].append(run_day(day_bars, orb_entries(day_bars, 15)))
        results['ORB-30'].append(run_day(day_bars, orb_entries(day_bars, 30)))
        results['FHM'].append(run_day(day_bars, fhm_entries(day_bars)))
    print(f'\n=== {label} ({len(days)} days) ===')
    for name, daily in results.items():
        pnls = [p for day in daily for p in day]
        if not pnls:
            print(f'{name}: no trades')
            continue
        day_pnl = pd.Series([sum(day) for day in daily])
        wins = sum(1 for p in pnls if p > 0)
        sharpe = day_pnl.mean() / day_pnl.std() * np.sqrt(252) if day_pnl.std() > 0 else 0
        print(f'{name:7}: {len(pnls):4} trades | total Rs {sum(pnls):+9,.0f} '
              f'({sum(pnls)/CAPITAL*100:+.1f}% on 100k) | win {100*wins/len(pnls):.0f}% | '
              f'avg/trade Rs {np.mean(pnls):+6.0f} | ann.Sharpe {sharpe:+.2f}')


if __name__ == '__main__':
    probe(load_csvs(), 'Nov 2025 - Jan 2026 (60d CSVs)')
    db = ROOT / 'data' / 'zerodha_data_latest.db'
    if db.exists():
        probe(load_db(db), 'Jul 13-20 2026 (release DB)')
