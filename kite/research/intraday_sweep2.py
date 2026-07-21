"""Intraday sweep round 2 — the remaining documented retail intraday playbook.
Rules FROZEN before first run (pre-registration). Both samples. Real costs.

Families (all square-off 15:15, max 5 concurrent, one trade/stock/day/family):
1. VWAPfade-L : after 10:00, price < VWAP*(1-1.2%) -> buy next bar; target VWAP,
   stop entry-0.6%.
2. VWAPfade-S : after 10:00, price > VWAP*(1+1.2%) -> short next bar; target VWAP,
   stop entry+0.6%.
3. ClimaxFade-L : 1-min volume > 5x avg20 AND bar range > 3x avg20 range AND close
   in bottom 20% of bar (panic flush), after 09:45 -> buy next bar; stop bar low,
   target 2R.
4. ClimaxFade-S : mirror (blowoff top, close in top 20%) -> short; stop bar high,
   target 2R.
5. Burst-L : rolling 5-min return > +0.75% AND 5-min volume > 3x avg -> buy next
   bar (continuation); stop = 5-min low, target 2R.
6. LunchBO-L / LunchBO-S : 12:00-13:30 range < 0.35% of price -> first close
   outside range after 13:30 -> trade breakout direction; stop = other side,
   target 2R.
7. LastHour-L : at 14:30 rank day return since open; buy top 3 if > +1%;
   stop -0.75%, exit 15:15.

Sizing: risk 1% of 100k where a structural stop exists, else slot capital/5.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'kite'))
sys.path.insert(0, str(Path(__file__).parent))
from intraday_probe import run_day, trade_cost, SLIP, CAPITAL, MAX_POS, RISK_PCT, SQUARE_OFF
from short_probe import run_day_short, _qty
import sqlite3


def load_csvs_v():
    data = {}
    for f in sorted((ROOT / 'data').glob('*_minute_60d.csv')):
        sym = f.name.split('_minute_')[0]
        df = pd.read_csv(f, parse_dates=['datetime'])
        df['datetime'] = df.datetime.dt.tz_localize(None)
        data[sym] = df.set_index('datetime')[['open', 'high', 'low', 'close', 'volume']]
    return data


def load_db_v(path):
    con = sqlite3.connect(path)
    syms = tuple(load_csvs_v().keys())
    q = (f"SELECT symbol, datetime, open, high, low, close, volume FROM ohlcv "
         f"WHERE interval='minute' AND symbol IN {syms}")
    df = pd.read_sql(q, con, parse_dates=['datetime'])
    con.close()
    df['datetime'] = pd.to_datetime(df.datetime, utc=True).dt.tz_convert('Asia/Kolkata').dt.tz_localize(None)
    return {s: g.set_index('datetime')[['open', 'high', 'low', 'close', 'volume']].sort_index()
            for s, g in df.groupby('symbol')}


def prep(bars):
    tp = (bars.high + bars.low + bars.close) / 3
    v = bars.volume.replace(0, np.nan)
    bars = bars.assign(
        vwap=(tp * bars.volume).cumsum() / bars.volume.cumsum().replace(0, np.nan),
        vol_avg=v.rolling(20).mean(),
        rng=bars.high - bars.low)
    bars['rng_avg'] = bars.rng.rolling(20).mean()
    bars['ret5'] = bars.close.pct_change(5)
    bars['vol5'] = bars.volume.rolling(5).sum()
    bars['vol5_avg'] = bars['vol5'].rolling(20).mean()
    return bars


def next_bar(bars, sig_t):
    later = bars[bars.index > sig_t]
    return (later.index[0], later.iloc[0].open) if len(later) else (None, None)


def vwap_fade(day_bars, side):
    entries = []
    for sym, b in day_bars.items():
        b = b[b.index.time >= pd.Timestamp('10:00').time()]
        if b.empty:
            continue
        if side == 'L':
            hit = b[b.close < b.vwap * 0.988]
        else:
            hit = b[b.close > b.vwap * 1.012]
        if hit.empty:
            continue
        sig_t = hit.index[0]
        t, o = next_bar(day_bars[sym], sig_t)
        if t is None or t.time() >= SQUARE_OFF:
            continue
        target = float(hit.iloc[0].vwap)
        if side == 'L':
            px = o * (1 + SLIP)
            sl, tp_ = px * 0.994, target
            if tp_ <= px:
                continue
            entries.append((t, sym, px, sl, tp_, _qty(px, px - sl)))
        else:
            px = o * (1 - SLIP)
            sl, tp_ = px * 1.006, target
            if tp_ >= px:
                continue
            entries.append((t, sym, px, sl, tp_, _qty(px, sl - px)))
    return entries


def climax_fade(day_bars, side):
    entries = []
    for sym, b in day_bars.items():
        b2 = b[b.index.time >= pd.Timestamp('09:45').time()]
        big = b2[(b2.volume > 5 * b2.vol_avg) & (b2.rng > 3 * b2.rng_avg) & b2.rng.gt(0)]
        if big.empty:
            continue
        for sig_t, row in big.iterrows():
            pos_in_bar = (row.close - row.low) / row.rng
            if side == 'L' and pos_in_bar > 0.2:
                continue
            if side == 'S' and pos_in_bar < 0.8:
                continue
            t, o = next_bar(b, sig_t)
            if t is None or t.time() >= SQUARE_OFF:
                break
            if side == 'L':
                px = o * (1 + SLIP)
                risk = px - row.low
                if risk <= 0:
                    break
                entries.append((t, sym, px, row.low, px + 2 * risk, _qty(px, risk)))
            else:
                px = o * (1 - SLIP)
                risk = row.high - px
                if risk <= 0:
                    break
                entries.append((t, sym, px, row.high, px - 2 * risk, _qty(px, risk)))
            break  # one per stock per day
    return entries


def burst(day_bars):
    entries = []
    for sym, b in day_bars.items():
        hit = b[(b.ret5 > 0.0075) & (b.vol5 > 3 * b.vol5_avg)]
        if hit.empty:
            continue
        sig_t = hit.index[0]
        t, o = next_bar(b, sig_t)
        if t is None or t.time() >= SQUARE_OFF:
            continue
        px = o * (1 + SLIP)
        low5 = b.low.rolling(5).min().loc[sig_t]
        risk = px - low5
        if risk <= 0:
            continue
        entries.append((t, sym, px, low5, px + 2 * risk, _qty(px, risk)))
    return entries


def lunch_bo(day_bars, side):
    entries = []
    for sym, b in day_bars.items():
        lunch = b.between_time('12:00', '13:30')
        if len(lunch) < 60:
            continue
        hi, lo = lunch.high.max(), lunch.low.min()
        mid = (hi + lo) / 2
        if (hi - lo) / mid > 0.0035:
            continue
        post = b[b.index > lunch.index[-1]]
        brk = post[post.close > hi] if side == 'L' else post[post.close < lo]
        if brk.empty:
            continue
        t, o = next_bar(b, brk.index[0])
        if t is None or t.time() >= SQUARE_OFF:
            continue
        if side == 'L':
            px = o * (1 + SLIP)
            risk = px - lo
            entries.append((t, sym, px, lo, px + 2 * risk, _qty(px, risk)))
        else:
            px = o * (1 - SLIP)
            risk = hi - px
            entries.append((t, sym, px, hi, px - 2 * risk, _qty(px, risk)))
    return entries


def last_hour(day_bars):
    scores = {}
    for sym, b in day_bars.items():
        upto = b[b.index.time <= pd.Timestamp('14:30').time()]
        if len(upto) < 200:
            continue
        ret = upto.close.iloc[-1] / upto.open.iloc[0] - 1
        if ret > 0.01:
            scores[sym] = (ret, upto.index[-1])
    entries = []
    for sym in sorted(scores, key=lambda s: scores[s][0], reverse=True)[:3]:
        t, o = next_bar(day_bars[sym], scores[sym][1])
        if t is None:
            continue
        px = o * (1 + SLIP)
        entries.append((t, sym, px, px * 0.9925, px * 1.05, int((CAPITAL / 3) / px)))
    return entries


FAMS = [('VWAPfade-L', 'L', lambda db: vwap_fade(db, 'L')),
        ('VWAPfade-S', 'S', lambda db: vwap_fade(db, 'S')),
        ('ClimaxFade-L', 'L', lambda db: climax_fade(db, 'L')),
        ('ClimaxFade-S', 'S', lambda db: climax_fade(db, 'S')),
        ('Burst-L', 'L', burst),
        ('LunchBO-L', 'L', lambda db: lunch_bo(db, 'L')),
        ('LunchBO-S', 'S', lambda db: lunch_bo(db, 'S')),
        ('LastHour-L', 'L', last_hour)]


def probe(data, label):
    days = sorted({t.date() for df in data.values() for t in df.index})
    results = {name: [] for name, _, _ in FAMS}
    for d in days:
        day_bars = {}
        for sym, df in data.items():
            b = df[df.index.date == d]
            if len(b) > 100:
                day_bars[sym] = prep(b)
        if len(day_bars) < 10:
            continue
        for name, side, fn in FAMS:
            entries = fn(day_bars)
            runner = run_day if side == 'L' else run_day_short
            results[name].append(runner(day_bars, entries))
    print(f'\n=== sweep2: {label} ({len(days)} days) ===')
    for name, daily in results.items():
        pnls = [p for day in daily for p in day]
        if not pnls:
            print(f'{name:13}: no trades')
            continue
        day_pnl = pd.Series([sum(day) for day in daily])
        wins = sum(1 for p in pnls if p > 0)
        sharpe = day_pnl.mean() / day_pnl.std() * np.sqrt(252) if day_pnl.std() > 0 else 0
        print(f'{name:13}: {len(pnls):4} trades | Rs {sum(pnls):+9,.0f} '
              f'({sum(pnls)/CAPITAL*100:+.1f}%) | win {100*wins/len(pnls):.0f}% | '
              f'avg {np.mean(pnls):+6.0f} | Shp {sharpe:+.2f}')


if __name__ == '__main__':
    probe(load_csvs_v(), 'Nov 2025 - Jan 2026')
    db = ROOT / 'data' / 'zerodha_data_latest.db'
    if db.exists():
        probe(load_db_v(db), 'Jul 13-20 2026')
