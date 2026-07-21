"""Short-side intraday probe. Rules pre-registered in
docs/superpowers/specs/2026-07-21-short-intraday-probe-design.md — FROZEN, no tuning.

5 families, long-only-cash constraint respected (all positions closed 15:15):
ORB-down-15/30, first-hour weakness, gap-up fade, failed-breakout fade,
relative weakness. Same costs/samples as the long probe.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'kite'))
sys.path.insert(0, str(Path(__file__).parent))
from intraday_probe import load_csvs, load_db, trade_cost, SLIP, CAPITAL, MAX_POS, RISK_PCT, SQUARE_OFF


def run_day_short(day_bars, entries):
    """entries: (time, sym, entry_px, stop_above, target_below, qty). Short positions."""
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
            cover_px = None
            if row.high >= p['sl']:
                cover_px = max(row.open, p['sl']) * (1 + SLIP)  # gap through stop -> worse
            elif row.low <= p['tp']:
                cover_px = min(row.open, p['tp']) * (1 + SLIP)
            elif t.time() >= SQUARE_OFF:
                cover_px = row.close * (1 + SLIP)
            if cover_px is not None:
                sell_v = p['qty'] * p['entry']   # short entry = sell first
                buy_v = p['qty'] * cover_px      # cover = buy back
                trades.append(sell_v - buy_v - trade_cost(buy_v, sell_v))
                del open_pos[sym]
    return trades


def _qty(entry_px, risk_per_share):
    if risk_per_share <= 0:
        return 0
    return min(int(CAPITAL * RISK_PCT / risk_per_share), int((CAPITAL / MAX_POS) / entry_px))


def orb_down(day_bars, range_min):
    entries = []
    for sym, bars in day_bars.items():
        rng = bars.between_time('09:15', f'09:{15 + range_min - 1}')
        if len(rng) < range_min - 2:
            continue
        hi, lo = rng.high.max(), rng.low.min()
        post = bars[bars.index > rng.index[-1]]
        brk = post[post.close < lo]
        if brk.empty:
            continue
        later = post[post.index > brk.index[0]]
        if later.empty:
            continue
        t = later.index[0]
        px = later.iloc[0].open * (1 - SLIP)
        risk = hi - px
        if risk <= 0 or t.time() >= SQUARE_OFF:
            continue
        entries.append((t, sym, px, hi, px - 2 * risk, _qty(px, risk)))
    return entries


def fhw(day_bars):
    scores = {}
    for sym, bars in day_bars.items():
        fh = bars.between_time('09:15', '10:15')
        if len(fh) < 50:
            continue
        ret = fh.close.iloc[-1] / fh.open.iloc[0] - 1
        if ret < -0.005:
            scores[sym] = (ret, fh.index[-1])
    entries = []
    for sym in sorted(scores, key=lambda s: scores[s][0])[:3]:
        bars = day_bars[sym]
        later = bars[bars.index > scores[sym][1]]
        if later.empty:
            continue
        t = later.index[0]
        px = later.iloc[0].open * (1 - SLIP)
        entries.append((t, sym, px, px * 1.01, px * 0.97, int((CAPITAL / 3) / px)))
    return entries


def gap_fade(day_bars, prev_close):
    entries = []
    for sym, bars in day_bars.items():
        pc = prev_close.get(sym)
        if pc is None or len(bars) < 30:
            continue
        if bars.open.iloc[0] / pc - 1 < 0.015:
            continue
        first15 = bars.between_time('09:15', '09:29')
        if first15.empty:
            continue
        lo15 = first15.low.min()
        post = bars[bars.index > first15.index[-1]]
        brk = post[post.close < lo15]
        if brk.empty:
            continue
        sig_t = brk.index[0]
        later = post[post.index > sig_t]
        if later.empty:
            continue
        t = later.index[0]
        px = later.iloc[0].open * (1 - SLIP)
        day_hi = bars[bars.index <= sig_t].high.max()
        risk = day_hi - px
        if risk <= 0 or t.time() >= SQUARE_OFF:
            continue
        entries.append((t, sym, px, day_hi, px - 2 * risk, _qty(px, risk)))
    return entries


def failed_breakout(day_bars):
    entries = []
    for sym, bars in day_bars.items():
        rng = bars.between_time('09:15', '09:29')
        if len(rng) < 13:
            continue
        hi = rng.high.max()
        post = bars[bars.index > rng.index[-1]]
        above = post[post.close > hi]
        if above.empty:
            continue
        t_break = above.index[0]
        window = post[(post.index > t_break) & (post.index <= t_break + pd.Timedelta(minutes=30))]
        fail = window[window.close < hi]
        if fail.empty:
            continue
        sig_t = fail.index[0]
        later = post[post.index > sig_t]
        if later.empty:
            continue
        t = later.index[0]
        px = later.iloc[0].open * (1 - SLIP)
        day_hi = bars[bars.index <= sig_t].high.max()
        risk = day_hi - px
        if risk <= 0 or t.time() >= SQUARE_OFF:
            continue
        entries.append((t, sym, px, day_hi, px - 2 * risk, _qty(px, risk)))
    return entries


def rel_weakness(day_bars):
    rets = {}
    for sym, bars in day_bars.items():
        fh = bars.between_time('09:15', '10:15')
        if len(fh) < 50:
            continue
        rets[sym] = (fh.close.iloc[-1] / fh.open.iloc[0] - 1, fh.index[-1])
    if len(rets) < 10:
        return []
    univ = np.mean([r for r, _ in rets.values()])
    if univ < 0.003:
        return []
    laggards = sorted((s for s in rets if rets[s][0] < -0.003), key=lambda s: rets[s][0])[:3]
    entries = []
    for sym in laggards:
        bars = day_bars[sym]
        later = bars[bars.index > rets[sym][1]]
        if later.empty:
            continue
        t = later.index[0]
        px = later.iloc[0].open * (1 - SLIP)
        entries.append((t, sym, px, px * 1.01, px * 0.97, int((CAPITAL / 3) / px)))
    return entries


def probe(data, label):
    all_days = sorted({t.date() for df in data.values() for t in df.index})
    daily_close = {}   # date -> {sym: close} built as we go (prev day lookup)
    fams = {'ORBdn-15': lambda db, pc: orb_down(db, 15),
            'ORBdn-30': lambda db, pc: orb_down(db, 30),
            'FHW': lambda db, pc: fhw(db),
            'GapFade': gap_fade,
            'FailedBO': lambda db, pc: failed_breakout(db),
            'RelWeak': lambda db, pc: rel_weakness(db)}
    results = {k: [] for k in fams}
    prev_close = {}
    for d in all_days:
        day_bars = {}
        for sym, df in data.items():
            b = df[df.index.date == d]
            if len(b) > 100:
                day_bars[sym] = b
        if len(day_bars) >= 10:
            for name, fn in fams.items():
                entries = fn(day_bars, prev_close) if name == 'GapFade' else fn(day_bars, None)
                results[name].append(run_day_short(day_bars, entries))
        prev_close = {sym: b.close.iloc[-1] for sym, b in day_bars.items()} or prev_close
    print(f'\n=== SHORT probe: {label} ({len(all_days)} days) ===')
    for name, daily in results.items():
        pnls = [p for day in daily for p in day]
        if not pnls:
            print(f'{name:9}: no trades')
            continue
        day_pnl = pd.Series([sum(day) for day in daily])
        wins = sum(1 for p in pnls if p > 0)
        sharpe = day_pnl.mean() / day_pnl.std() * np.sqrt(252) if day_pnl.std() > 0 else 0
        print(f'{name:9}: {len(pnls):4} trades | total Rs {sum(pnls):+9,.0f} '
              f'({sum(pnls)/CAPITAL*100:+.1f}%) | win {100*wins/len(pnls):.0f}% | '
              f'avg Rs {np.mean(pnls):+6.0f} | ann.Sharpe {sharpe:+.2f}')


if __name__ == '__main__':
    probe(load_csvs(), 'Nov 2025 - Jan 2026 (60d CSVs)')
    db = ROOT / 'data' / 'zerodha_data_latest.db'
    if db.exists():
        probe(load_db(db), 'Jul 13-20 2026 (release DB)')
