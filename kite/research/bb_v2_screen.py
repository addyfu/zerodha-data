"""bb_mean_reversion_v2 head-to-head screen. Pre-registered spec (FROZEN, no
tuning): docs/superpowers/specs/2026-07-23-bb-v2-design.md.

Signal source: the ACTUAL BBMeanReversionStrategy (STRATEGY_REGISTRY['bb_mean_reversion']),
run on 5-min resampled bars (its live timeframe) with trailing warmup history,
via its own get_trade_signals(). Two execution variants over IDENTICAL signals:

  ORIGINAL - strategy's own stop/target as-is, no cooldown.
  V2       - stop widened to max(original band-based stop, 0.5% of entry),
             target unchanged; signal REJECTED if reward:risk < 1.5 after
             widening (mirrors kite/live_monitor/signal_detector.py's gate:
             risk_pct = |entry-stop|/entry*100, reward_pct = |tp-entry|/entry*100,
             rr = reward_pct/risk_pct, reject if rr < 1.5); plus a 60-minute
             per-symbol cool-down after any stop-loss exit (no new v2 entry in
             that symbol until the cool-down clears).

Execution mechanics adapted from kite/research/intraday_probe.py (run_day) and
kite/research/short_probe.py (run_day_short): 1-min bars, next-bar entry after
the signal is known, SL/TP checked gap-aware against the bar's high/low,
15:15 square-off, intraday Zerodha costs + 0.05% slippage/side, max 5
concurrent positions. Both variants simulated independently, same days/signals.

Samples: (1) data/*_minute_60d.csv (Nov 2025 - Jan 2026, load_csvs), (2)
data/zerodha_data_latest.db (Jul 2026 release week, load_db). Both variants on
both samples.

Usage: python -W ignore kite/research/bb_v2_screen.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'kite'))
sys.path.insert(0, str(Path(__file__).parent))

from intraday_probe import load_csvs, load_db, trade_cost, SLIP, CAPITAL, MAX_POS, RISK_PCT, SQUARE_OFF
from kite.strategies import STRATEGY_REGISTRY

STRATEGY_NAME = 'bb_mean_reversion'
WARMUP_DAYS = 10          # trailing trading days of 5-min history fed for indicator warmup
COOLDOWN_MIN = 60         # v2: minutes after a stop-loss exit before the symbol can re-enter
MIN_RR = 1.5              # v2 rejection gate (mirrors live signal_detector.py's min_rr_ratio)
STOP_FLOOR_PCT = 0.005    # v2: stop must be >= 0.5% from entry

OUT_LINES = []


def out(msg=''):
    print(msg)
    OUT_LINES.append(str(msg))


# --------------------------------------------------------------------------
# Data loading (with volume - needed by BBMeanReversionStrategy.validate_data
# and for 5-min volume aggregation; the probe's own load_csvs/load_db strip
# volume since its ORB/FHM rules don't need it).
# --------------------------------------------------------------------------

def load_csvs_full():
    data = {}
    for f in sorted((ROOT / 'data').glob('*_minute_60d.csv')):
        sym = f.name.split('_minute_')[0]
        df = pd.read_csv(f, parse_dates=['datetime'])
        df['datetime'] = df.datetime.dt.tz_localize(None)
        data[sym] = df.set_index('datetime')[['open', 'high', 'low', 'close', 'volume']].sort_index()
    return data


def load_db_full(path):
    import sqlite3
    con = sqlite3.connect(path)
    syms = tuple(load_csvs().keys())
    q = (f"SELECT symbol, datetime, open, high, low, close, volume FROM ohlcv "
         f"WHERE interval='minute' AND symbol IN {syms}")
    df = pd.read_sql(q, con, parse_dates=['datetime'])
    con.close()
    df['datetime'] = pd.to_datetime(df.datetime, utc=True).dt.tz_convert('Asia/Kolkata').dt.tz_localize(None)
    return {s: g.set_index('datetime')[['open', 'high', 'low', 'close', 'volume']].sort_index()
            for s, g in df.groupby('symbol')}


def resample_5min(df):
    """Resample 1-min OHLCV to 5-min, per calendar day (so the overnight gap
    never creates a spurious bin), then concatenated into one continuous
    series per symbol so the indicators carry trailing history across days."""
    parts = []
    for _, g in df.groupby(df.index.date):
        r = g.resample('5min', label='left', closed='left').agg(
            {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
        ).dropna(subset=['open'])
        if not r.empty:
            parts.append(r)
    if not parts:
        return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])
    return pd.concat(parts).sort_index()


# --------------------------------------------------------------------------
# Signal generation - the ACTUAL strategy class, on 5-min bars, per trading
# day, fed a trailing ~10-trading-day window of 5-min history for warmup.
# --------------------------------------------------------------------------

def build_raw_signals(five_min, sym_dates, warmup_days=WARMUP_DAYS):
    """Returns list of dicts: day, sym, sig_time (bar-close-known time),
    direction ('BUY'/'SELL'), entry_price, stop_loss, take_profit - all as
    computed by the strategy's own get_trade_signals() on that day's window."""
    signals = []
    for sym, df5 in five_min.items():
        dates = sym_dates[sym]
        if df5.empty or not dates:
            continue
        for i, d in enumerate(dates):
            window_dates = set(dates[max(0, i - warmup_days):i + 1])
            window = df5[np.isin(df5.index.date, list(window_dates))]
            if window.empty:
                continue
            strategy = STRATEGY_REGISTRY[STRATEGY_NAME]()
            try:
                sig_df = strategy.get_trade_signals(window.copy())
            except Exception:
                continue
            day_rows = sig_df[(sig_df.index.date == d) & (sig_df['signal'] != 0)]
            for idx, row in day_rows.iterrows():
                if pd.isna(row['stop_loss']) or pd.isna(row['take_profit']) or pd.isna(row['entry_price']):
                    continue
                signals.append({
                    'day': d,
                    'sym': sym,
                    'sig_time': idx + pd.Timedelta(minutes=5),  # bar covers [idx, idx+5min); known at idx+5min
                    'direction': 'BUY' if row['signal'] == 1 else 'SELL',
                    'entry_price': float(row['entry_price']),
                    'stop_loss': float(row['stop_loss']),
                    'take_profit': float(row['take_profit']),
                })
    return signals


# --------------------------------------------------------------------------
# V2 stop-widening + reward:risk gate (mirrors kite/live_monitor/signal_detector.py)
# --------------------------------------------------------------------------

def widen_and_gate(sig):
    entry, sl, tp = sig['entry_price'], sig['stop_loss'], sig['take_profit']
    orig_dist = abs(entry - sl)
    min_dist = STOP_FLOOR_PCT * entry
    new_dist = max(orig_dist, min_dist)
    new_sl = entry - new_dist if sig['direction'] == 'BUY' else entry + new_dist
    risk_pct = new_dist / entry * 100 if entry else 0
    reward_pct = abs(tp - entry) / entry * 100 if entry else 0
    rr = reward_pct / risk_pct if risk_pct > 0 else 0
    return new_sl, rr, (rr >= MIN_RR)


# --------------------------------------------------------------------------
# Signal -> executable entry (actual fill on next 1-min bar, gap/slippage aware)
# --------------------------------------------------------------------------

def to_entry(sig, day_bars, stop_loss, take_profit):
    bars = day_bars.get(sig['sym'])
    if bars is None:
        return None
    post = bars[bars.index >= sig['sig_time']]
    if post.empty:
        return None
    t = post.index[0]
    if t.time() >= SQUARE_OFF:
        return None
    row = post.iloc[0]
    if sig['direction'] == 'BUY':
        entry_px = row.open * (1 + SLIP)
        risk = entry_px - stop_loss
        direction = 'long'
    else:
        entry_px = row.open * (1 - SLIP)
        risk = stop_loss - entry_px
        direction = 'short'
    if risk <= 0:
        return None
    qty = min(int(CAPITAL * RISK_PCT / risk), int((CAPITAL / MAX_POS) / entry_px))
    if qty <= 0:
        return None
    return {'time': t, 'sym': sig['sym'], 'direction': direction,
            'entry': entry_px, 'sl': stop_loss, 'tp': take_profit, 'qty': qty}


# --------------------------------------------------------------------------
# Execution engine - adapted from intraday_probe.run_day / short_probe.run_day_short:
# same next-bar-entry / gap-aware SL-TP / 15:15 square-off / intraday-cost
# mechanics, generalized to handle long AND short positions in one pass, with
# an optional per-symbol post-stop-loss cool-down (v2 only).
# --------------------------------------------------------------------------

def run_day_exec(day_bars, entries, cooldown_min=None):
    trades = []
    open_pos = {}
    last_sl_exit = {}
    cooldown_suppressed = 0
    minutes = sorted({t for bars in day_bars.values() for t in bars.index})
    entry_map = {}
    for e in entries:
        entry_map.setdefault(e['time'], []).append(e)
    for t in minutes:
        for e in entry_map.get(t, []):
            sym = e['sym']
            if sym in open_pos or len(open_pos) >= MAX_POS or e['qty'] <= 0:
                continue
            if cooldown_min is not None and sym in last_sl_exit and \
                    (t - last_sl_exit[sym]) < pd.Timedelta(minutes=cooldown_min):
                cooldown_suppressed += 1
                continue
            open_pos[sym] = dict(e)
        for sym in list(open_pos):
            bars = day_bars.get(sym)
            if bars is None or t not in bars.index:
                continue
            row, p = bars.loc[t], open_pos[sym]
            exit_px, reason = None, None
            if p['direction'] == 'long':
                if row.low <= p['sl']:
                    exit_px, reason = min(row.open, p['sl']) * (1 - SLIP), 'SL'
                elif row.high >= p['tp']:
                    exit_px, reason = max(row.open, p['tp']) * (1 - SLIP), 'TP'
                elif t.time() >= SQUARE_OFF:
                    exit_px, reason = row.close * (1 - SLIP), 'EOD'
            else:
                if row.high >= p['sl']:
                    exit_px, reason = max(row.open, p['sl']) * (1 + SLIP), 'SL'
                elif row.low <= p['tp']:
                    exit_px, reason = min(row.open, p['tp']) * (1 + SLIP), 'TP'
                elif t.time() >= SQUARE_OFF:
                    exit_px, reason = row.close * (1 + SLIP), 'EOD'
            if exit_px is not None:
                if p['direction'] == 'long':
                    buy_v, sell_v = p['qty'] * p['entry'], p['qty'] * exit_px
                else:
                    sell_v, buy_v = p['qty'] * p['entry'], p['qty'] * exit_px
                pnl = sell_v - buy_v - trade_cost(buy_v, sell_v)
                trades.append({'sym': sym, 'pnl': pnl, 'reason': reason,
                                'direction': p['direction'], 'exit_time': t})
                if reason == 'SL' and cooldown_min is not None:
                    last_sl_exit[sym] = t
                del open_pos[sym]
    return trades, cooldown_suppressed


# --------------------------------------------------------------------------
# Per-sample simulation of both variants over identical signals
# --------------------------------------------------------------------------

def simulate(data, label):
    days = sorted({t.date() for df in data.values() for t in df.index})
    five_min = {sym: resample_5min(df) for sym, df in data.items()}
    sym_dates = {sym: sorted(set(df5.index.date)) for sym, df5 in five_min.items()}

    raw_signals = build_raw_signals(five_min, sym_dates)
    by_day = {}
    for s in raw_signals:
        by_day.setdefault(s['day'], []).append(s)

    orig_trades, v2_trades = [], []
    rejected_rr = 0
    cooldown_suppressed_total = 0
    n_days_used = 0

    for d in days:
        day_bars = {}
        for sym, df in data.items():
            b = df[df.index.date == d]
            if len(b) > 100:
                day_bars[sym] = b
        if len(day_bars) < 10:
            continue
        n_days_used += 1

        day_signals = sorted((s for s in by_day.get(d, []) if s['sym'] in day_bars),
                              key=lambda s: s['sig_time'])

        # ORIGINAL: strategy's own stop/target as-is, no gate, no cooldown.
        orig_entries = []
        for s in day_signals:
            e = to_entry(s, day_bars, s['stop_loss'], s['take_profit'])
            if e:
                orig_entries.append(e)
        trades, _ = run_day_exec(day_bars, orig_entries, cooldown_min=None)
        orig_trades.extend(trades)

        # V2: widen stop to floor, reject on RR<1.5, then 60-min post-SL cooldown.
        v2_entries = []
        for s in day_signals:
            new_sl, rr, passed = widen_and_gate(s)
            if not passed:
                rejected_rr += 1
                continue
            e = to_entry(s, day_bars, new_sl, s['take_profit'])
            if e:
                v2_entries.append(e)
        trades, cds = run_day_exec(day_bars, v2_entries, cooldown_min=COOLDOWN_MIN)
        v2_trades.extend(trades)
        cooldown_suppressed_total += cds

    return {
        'label': label, 'n_days': n_days_used, 'n_signals': len(raw_signals),
        'orig': orig_trades, 'v2': v2_trades,
        'rejected_rr': rejected_rr, 'cooldown_suppressed': cooldown_suppressed_total,
    }


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def stats(trades):
    pnls = [t['pnl'] for t in trades]
    if not pnls:
        return None
    wins = sum(1 for p in pnls if p > 0)
    return {
        'n': len(pnls),
        'total': sum(pnls),
        'win_rate': 100 * wins / len(pnls),
        'avg': np.mean(pnls),
        'max_loss': min(pnls),
    }


def print_variant(name, trades):
    s = stats(trades)
    if s is None:
        out(f'  {name:9}: no trades')
        return None
    out(f'  {name:9}: {s["n"]:4} trades | total Rs {s["total"]:+10,.0f} | '
        f'win {s["win_rate"]:5.1f}% | avg/trade Rs {s["avg"]:+7.0f} | '
        f'max single-trade loss Rs {s["max_loss"]:+9,.0f}')
    return s


def run_sample(data, label):
    out(f'\n=== {label} ===')
    res = simulate(data, label)
    out(f'Trading days used: {res["n_days"]} | raw signals generated: {res["n_signals"]}')
    orig_stats = print_variant('ORIGINAL', res['orig'])
    v2_stats = print_variant('V2', res['v2'])
    out(f'  V2 rejected-by-RR (RR<{MIN_RR} after widening): {res["rejected_rr"]}')
    out(f'  V2 cooldown-suppressed (60-min post-SL): {res["cooldown_suppressed"]}')
    return {'label': label, 'orig': orig_stats, 'v2': v2_stats}


def frozen_verdict(sample_results):
    out('\n' + '=' * 78)
    out('FROZEN VERDICT (docs/superpowers/specs/2026-07-23-bb-v2-design.md)')
    out('=' * 78)
    overall_pass = True

    # Criterion 1: v2 total net P&L > original's on BOTH samples
    out('\nCriterion 1: v2 total net P&L > original\'s on BOTH samples')
    c1_pass = True
    for r in sample_results:
        o, v = r['orig'], r['v2']
        o_total = o['total'] if o else 0.0
        v_total = v['total'] if v else 0.0
        ok = v_total > o_total
        c1_pass &= ok
        out(f'  [{r["label"]}] orig Rs {o_total:+10,.0f}  vs  v2 Rs {v_total:+10,.0f}  -> {"PASS" if ok else "FAIL"}')
    out(f'  Criterion 1: {"PASS" if c1_pass else "FAIL"}')
    overall_pass &= c1_pass

    # Criterion 2: v2 max single-trade loss no worse than original's on both samples
    out('\nCriterion 2: v2 max single-trade loss no worse than original\'s on BOTH samples')
    c2_pass = True
    for r in sample_results:
        o, v = r['orig'], r['v2']
        o_loss = o['max_loss'] if o else 0.0
        v_loss = v['max_loss'] if v else 0.0
        ok = v_loss >= o_loss
        c2_pass &= ok
        out(f'  [{r["label"]}] orig worst Rs {o_loss:+9,.0f}  vs  v2 worst Rs {v_loss:+9,.0f}  -> {"PASS" if ok else "FAIL"}')
    out(f'  Criterion 2: {"PASS" if c2_pass else "FAIL"}')
    overall_pass &= c2_pass

    # Criterion 3: v2 trade count >= 40% of original's, on both samples
    out('\nCriterion 3: v2 trade count >= 40% of original\'s (floor+cooldown must not kill it), BOTH samples')
    c3_pass = True
    for r in sample_results:
        o, v = r['orig'], r['v2']
        o_n = o['n'] if o else 0
        v_n = v['n'] if v else 0
        if o_n == 0:
            ok = v_n == 0
            pct_str = 'n/a (orig had 0 trades)'
        else:
            pct = 100 * v_n / o_n
            ok = v_n >= 0.4 * o_n
            pct_str = f'{pct:.0f}% of original'
        c3_pass &= ok
        out(f'  [{r["label"]}] orig {o_n} trades  vs  v2 {v_n} trades  ({pct_str})  -> {"PASS" if ok else "FAIL"}')
    out(f'  Criterion 3: {"PASS" if c3_pass else "FAIL"}')
    overall_pass &= c3_pass

    out('\n' + '-' * 78)
    out(f'OVERALL: {"PASS - v2 earns an incubator seat" if overall_pass else "FAIL - v2 is discarded"}')
    out('-' * 78)
    if not overall_pass:
        out('Per spec: any failure means v2 is discarded, the observation is recorded as')
        out('"tight stops appear load-bearing (or floor too blunt)", and the original\'s')
        out('process grades get a written correction. No threshold changes after results seen.')
    return overall_pass


if __name__ == '__main__':
    sample_results = []
    sample_results.append(run_sample(load_csvs_full(), 'Sample 1: Nov 2025 - Jan 2026 (60d CSVs)'))
    db_path = ROOT / 'data' / 'zerodha_data_latest.db'
    if db_path.exists():
        sample_results.append(run_sample(load_db_full(db_path), 'Sample 2: Jul 13-20 2026 (release DB)'))
    else:
        out(f'\nSample 2 DB not found at {db_path}, skipping.')

    frozen_verdict(sample_results)

    results_path = Path(__file__).parent / 'bb_v2_screen_results.txt'
    results_path.write_text('\n'.join(OUT_LINES) + '\n', encoding='utf-8')
    print(f'\n[saved output to {results_path}]')
