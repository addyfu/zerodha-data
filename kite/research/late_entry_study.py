"""Late-entry study. Pre-registered measurement, backtest only (no production
changes).

FROZEN QUESTION: do intraday trades ENTERED in the 14:45-15:05 window show
negative after-cost expectancy, and does excluding that window improve total
P&L on BOTH samples? Decision rule: recommend moving the live entry cutoff
15:05 -> 14:45 ONLY IF (a) the 14:45-15:05 entry bucket's mean P&L/trade < 0
on both samples AND (b) total P&L excluding that bucket >= total P&L
including it, on both samples. Otherwise 15:05 stands. No threshold changes
after results are seen.

Strategies: the four live intraday incubator candidates —
'bb_mean_reversion', 'cci_divergence', 'choppiness_filter', 'adx_filter'
(STRATEGY_REGISTRY). Signal generation identical to bb_v2_screen.py's
ORIGINAL variant: the ACTUAL strategy class's own get_trade_signals(), run on
5-min resampled bars (its live timeframe) with a trailing ~10-trading-day
warmup window, strategy's own stop-loss/take-profit as-is — no v2-style
stop widening, RR gate, or cooldown.

Execution: identical machinery to bb_v2_screen.py (itself adapted from
intraday_probe.py/short_probe.py) — next-1-min-bar entry after the signal is
known, gap-aware SL/TP checked against the bar's high/low, 15:15 square-off,
intraday Zerodha costs + 0.05% slippage/side, max 5 concurrent positions,
one position per symbol at a time, PER STRATEGY (each of the four strategies
simulated independently over the same days/symbols).

Live entry cutoff mirrored: kite/live_monitor/entry_pipeline.py blocks any
fresh INTRADAY entry at/after 15:05 (INTRADAY_ENTRY_CUTOFF). This sim
enforces the same cutoff on the fill time (next 1-min bar open) — a signal
whose fill would land at/after 15:05 is NOT executed; it is only counted as
a "cutoff-blocked" sanity stat, mirroring what already happens in production.

Every EXECUTED trade is bucketed by its ENTRY (fill) time into:
  [09:15-10:00), [10:00-12:00), [12:00-14:00), [14:00-14:45), [14:45-15:05)

Samples: (1) data/*_minute_60d.csv (Nov 2025 - Jan 2026, load_csvs_full), (2)
data/zerodha_data_latest.db (Jul 2026 release week, load_db_full). Both the
same as bb_v2_screen.py's two samples.

Usage: python -W ignore kite/research/late_entry_study.py
Output: kite/research/late_entry_study_results.txt
"""
import sys
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'kite'))
sys.path.insert(0, str(Path(__file__).parent))

# Reused unmodified from the existing, already-solved machinery.
from intraday_probe import trade_cost, SLIP, CAPITAL, MAX_POS, RISK_PCT, SQUARE_OFF
from bb_v2_screen import load_csvs_full, load_db_full, resample_5min
from kite.strategies import STRATEGY_REGISTRY

STRATEGIES = ['bb_mean_reversion', 'cci_divergence', 'choppiness_filter', 'adx_filter']
WARMUP_DAYS = 10                  # trailing trading days of 5-min history fed for indicator warmup
ENTRY_CUTOFF = dtime(15, 5)       # mirrors kite/live_monitor/entry_pipeline.py INTRADAY_ENTRY_CUTOFF

# Half-open entry-time buckets, per spec. Coverage is complete over
# [09:15, 15:05) since the cutoff above guarantees no executed trade enters
# at/after 15:05.
BUCKETS = [
    ('09:15-10:00', dtime(9, 15), dtime(10, 0)),
    ('10:00-12:00', dtime(10, 0), dtime(12, 0)),
    ('12:00-14:00', dtime(12, 0), dtime(14, 0)),
    ('14:00-14:45', dtime(14, 0), dtime(14, 45)),
    ('14:45-15:05', dtime(14, 45), dtime(15, 5)),
]
LAST_BUCKET = BUCKETS[-1][0]

OUT_LINES = []


def out(msg=''):
    print(msg)
    OUT_LINES.append(str(msg))


def bucket_for(t):
    tt = t.time()
    for name, start, end in BUCKETS:
        if start <= tt < end:
            return name
    return None  # should not happen; cutoff enforces entry < 15:05


# --------------------------------------------------------------------------
# Signal generation — same pattern as bb_v2_screen.build_raw_signals, but
# parameterized by strategy_name so it can run any of the four candidates.
# --------------------------------------------------------------------------

def build_raw_signals(strategy_name, five_min, sym_dates, warmup_days=WARMUP_DAYS):
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
            strategy = STRATEGY_REGISTRY[strategy_name]()
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
# Signal -> executable entry: identical to bb_v2_screen.to_entry (next 1-min
# bar fill, gap/slippage aware) PLUS the live 15:05 entry cutoff. A signal
# whose fill would land at/after 15:05 is not executed; it is reported back
# as cutoff-blocked (sanity stat only).
# --------------------------------------------------------------------------

def to_entry_capped(sig, day_bars):
    bars = day_bars.get(sig['sym'])
    if bars is None:
        return None, False
    post = bars[bars.index >= sig['sig_time']]
    if post.empty:
        return None, False
    t = post.index[0]
    if t.time() >= SQUARE_OFF:
        return None, False
    if t.time() >= ENTRY_CUTOFF:
        return None, True  # would have entered live production blocks this -> sanity stat
    row = post.iloc[0]
    entry_stop, take_profit = sig['stop_loss'], sig['take_profit']
    if sig['direction'] == 'BUY':
        entry_px = row.open * (1 + SLIP)
        risk = entry_px - entry_stop
        direction = 'long'
    else:
        entry_px = row.open * (1 - SLIP)
        risk = entry_stop - entry_px
        direction = 'short'
    if risk <= 0:
        return None, False
    qty = min(int(CAPITAL * RISK_PCT / risk), int((CAPITAL / MAX_POS) / entry_px))
    if qty <= 0:
        return None, False
    return {'time': t, 'sym': sig['sym'], 'direction': direction,
            'entry': entry_px, 'sl': entry_stop, 'tp': take_profit, 'qty': qty}, False


# --------------------------------------------------------------------------
# Execution engine — same mechanics as bb_v2_screen.run_day_exec (next-bar
# entry / gap-aware SL-TP / 15:15 square-off / intraday costs), with no
# cooldown (ORIGINAL variant only, per spec) and entry_time/entry recorded on
# each closed trade so trades can be bucketed by ENTRY time (bb_v2_screen only
# needed exit info for its P&L comparison).
# --------------------------------------------------------------------------

def run_day_exec(day_bars, entries):
    trades = []
    open_pos = {}
    minutes = sorted({t for bars in day_bars.values() for t in bars.index})
    entry_map = {}
    for e in entries:
        entry_map.setdefault(e['time'], []).append(e)
    for t in minutes:
        for e in entry_map.get(t, []):
            sym = e['sym']
            if sym in open_pos or len(open_pos) >= MAX_POS or e['qty'] <= 0:
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
                                'direction': p['direction'],
                                'entry_time': p['time'], 'exit_time': t})
                del open_pos[sym]
    return trades


# --------------------------------------------------------------------------
# Per-strategy simulation over a sample's days
# --------------------------------------------------------------------------

def simulate(strategy_name, data, five_min, sym_dates):
    days = sorted({t.date() for df in data.values() for t in df.index})
    raw_signals = build_raw_signals(strategy_name, five_min, sym_dates)
    by_day = {}
    for s in raw_signals:
        by_day.setdefault(s['day'], []).append(s)

    all_trades = []
    cutoff_blocked_total = 0
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

        entries = []
        for s in day_signals:
            e, blocked = to_entry_capped(s, day_bars)
            if blocked:
                cutoff_blocked_total += 1
            if e:
                entries.append(e)
        trades = run_day_exec(day_bars, entries)
        all_trades.extend(trades)

    return {'trades': all_trades, 'n_days': n_days_used, 'n_signals': len(raw_signals),
            'cutoff_blocked': cutoff_blocked_total}


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def stats(trades):
    if not trades:
        return None
    pnls = [t['pnl'] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    eod = sum(1 for t in trades if t['reason'] == 'EOD')
    return {
        'n': len(pnls),
        'total': float(sum(pnls)),
        'avg': float(np.mean(pnls)),
        'win_rate': 100 * wins / len(pnls),
        'eod_pct': 100 * eod / len(pnls),
    }


def run_sample(label, data):
    out('\n' + '=' * 78)
    out(f'=== {label} ===')
    out('=' * 78)

    five_min = {sym: resample_5min(df) for sym, df in data.items()}
    sym_dates = {sym: sorted(set(df5.index.date)) for sym, df5 in five_min.items()}

    strat_results = {}
    all_trades = []  # pooled across all 4 strategies, each tagged with its strategy
    for sname in STRATEGIES:
        res = simulate(sname, data, five_min, sym_dates)
        strat_results[sname] = res
        for t in res['trades']:
            t2 = dict(t)
            t2['strategy'] = sname
            t2['bucket'] = bucket_for(t['entry_time'])
            all_trades.append(t2)
        out(f'  [{sname:20}] days used {res["n_days"]:3} | raw signals {res["n_signals"]:5} | '
            f'executed trades {len(res["trades"]):4} | '
            f'cutoff-blocked (would-be entry >=15:05) {res["cutoff_blocked"]:3}')

    # Sanity check: enforce that no executed trade actually entered at/after 15:05.
    stray = [t for t in all_trades if t['entry_time'].time() >= ENTRY_CUTOFF]
    if stray:
        out(f'  WARNING: {len(stray)} executed trades have entry_time >= 15:05 '
            f'(cutoff enforcement bug — should be 0)')
    else:
        out(f'  Sanity check OK: 0 executed trades with entry_time >= 15:05.')

    out(f'\n-- Per-bucket P&L (pooled across all 4 strategies, entry-time bucketed) --')
    bucket_stats = {}
    for name, _, _ in BUCKETS:
        bucket_trades = [t for t in all_trades if t['bucket'] == name]
        s = stats(bucket_trades)
        bucket_stats[name] = s
        if s is None:
            out(f'  {name:14}: no trades')
            continue
        out(f'  {name:14}: {s["n"]:4} trades | total Rs {s["total"]:+10,.0f} | '
            f'mean/trade Rs {s["avg"]:+8.1f} | win {s["win_rate"]:5.1f}% | '
            f'EOD-exit {s["eod_pct"]:5.1f}%')

    out(f'\n-- Per-strategy x last-bucket ({LAST_BUCKET}) breakdown --')
    for sname in STRATEGIES:
        strat_last = [t for t in all_trades if t['strategy'] == sname and t['bucket'] == LAST_BUCKET]
        s = stats(strat_last)
        if s is None:
            out(f'  {sname:20}: no trades in last bucket')
            continue
        out(f'  {sname:20}: {s["n"]:4} trades | total Rs {s["total"]:+9,.0f} | '
            f'mean/trade Rs {s["avg"]:+8.1f} | win {s["win_rate"]:5.1f}% | '
            f'EOD-exit {s["eod_pct"]:5.1f}%')

    total_incl = sum(t['pnl'] for t in all_trades)
    excl_trades = [t for t in all_trades if t['bucket'] != LAST_BUCKET]
    total_excl = sum(t['pnl'] for t in excl_trades)
    out(f'\n-- Counterfactual: total P&L with vs without the {LAST_BUCKET} bucket --')
    out(f'  Including last bucket: Rs {total_incl:+10,.0f}  ({len(all_trades)} trades)')
    out(f'  Excluding last bucket: Rs {total_excl:+10,.0f}  ({len(excl_trades)} trades)')
    out(f'  Delta (excl - incl)  : Rs {total_excl - total_incl:+10,.0f}  '
        f'({"improves" if total_excl > total_incl else "worsens" if total_excl < total_incl else "unchanged"} '
        f'by excluding it)')

    total_cutoff_blocked = sum(r['cutoff_blocked'] for r in strat_results.values())
    out(f'\n  Sanity stat: total signals across all 4 strategies that would have entered')
    out(f'  at/after 15:05 if the live cutoff did not exist: {total_cutoff_blocked}')

    last_bucket_stats = bucket_stats.get(LAST_BUCKET)
    return {
        'label': label,
        'last_bucket_mean': last_bucket_stats['avg'] if last_bucket_stats else None,
        'last_bucket_n': last_bucket_stats['n'] if last_bucket_stats else 0,
        'total_incl': total_incl,
        'total_excl': total_excl,
    }


def frozen_verdict(sample_results):
    out('\n' + '=' * 78)
    out('FROZEN VERDICT')
    out('=' * 78)
    out(f'Decision rule: recommend moving the live entry cutoff 15:05 -> 14:45 ONLY IF,')
    out(f'on BOTH samples: (a) the {LAST_BUCKET} bucket\'s mean P&L/trade < 0, AND')
    out(f'(b) total P&L excluding that bucket >= total P&L including it.')
    out(f'Otherwise 15:05 stands. No threshold changes after results seen (frozen).')

    out(f'\nCriterion (a): {LAST_BUCKET} mean P&L/trade < 0, on BOTH samples')
    a_pass = True
    for r in sample_results:
        m = r['last_bucket_mean']
        if m is None:
            ok = False
            out(f'  [{r["label"]}] no trades in last bucket -> cannot confirm negative '
                f'expectancy -> FAIL (insufficient evidence, conservative default)')
        else:
            ok = m < 0
            out(f'  [{r["label"]}] mean/trade Rs {m:+8.1f}  ({r["last_bucket_n"]} trades)  '
                f'-> {"PASS" if ok else "FAIL"}')
        a_pass &= ok
    out(f'  Criterion (a): {"PASS" if a_pass else "FAIL"}')

    out(f'\nCriterion (b): total P&L excluding last bucket >= total including it, on BOTH samples')
    b_pass = True
    for r in sample_results:
        ok = r['total_excl'] >= r['total_incl']
        b_pass &= ok
        out(f'  [{r["label"]}] excl Rs {r["total_excl"]:+10,.0f}  vs  incl Rs {r["total_incl"]:+10,.0f}  '
            f'-> {"PASS" if ok else "FAIL"}')
    out(f'  Criterion (b): {"PASS" if b_pass else "FAIL"}')

    overall_pass = a_pass and b_pass
    out('\n' + '-' * 78)
    if overall_pass:
        out('OVERALL: PASS -> RECOMMENDATION: move the live entry cutoff 15:05 -> 14:45.')
    else:
        out('OVERALL: FAIL -> RECOMMENDATION: 15:05 stands (criteria not met on both samples).')
    out('-' * 78)
    return overall_pass


if __name__ == '__main__':
    out('FROZEN QUESTION: do intraday trades ENTERED in the 14:45-15:05 window show')
    out('negative after-cost expectancy, and does excluding that window improve total')
    out('P&L on BOTH samples? Decision rule: recommend moving the live entry cutoff')
    out('15:05 -> 14:45 ONLY IF (a) the 14:45-15:05 entry bucket\'s mean P&L/trade < 0')
    out('on both samples AND (b) total P&L excluding that bucket >= total including it')
    out('on both samples. Otherwise 15:05 stands.')
    out(f'\nStrategies (ORIGINAL variant, own stops/targets, no v2 modifications): {STRATEGIES}')

    sample_results = []
    sample_results.append(run_sample('Sample 1: Nov 2025 - Jan 2026 (60d CSVs)', load_csvs_full()))
    db_path = ROOT / 'data' / 'zerodha_data_latest.db'
    if db_path.exists():
        sample_results.append(run_sample('Sample 2: Jul 13-20 2026 (release DB)', load_db_full(db_path)))
    else:
        out(f'\nSample 2 DB not found at {db_path}, skipping.')

    frozen_verdict(sample_results)

    results_path = Path(__file__).parent / 'late_entry_study_results.txt'
    results_path.write_text('\n'.join(OUT_LINES) + '\n', encoding='utf-8')
    print(f'\n[saved output to {results_path}]')
