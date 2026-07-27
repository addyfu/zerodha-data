"""Trailing-stop counterfactual study — research only, no production changes.

MOTIVATION: live trade logs (kite/live_monitor/paper_trader.py) show most intraday
exits are labeled 'trailing_stop', comparatively few 'take_profit'. That pattern is
CONSISTENT WITH a trailing stop cutting winners short, but it has never been
measured. This script measures it: same signals, same entries, four different
exit regimes, for the four live intraday incubator candidates
(kite/live_monitor/monitor.py INCUBATOR_STRATEGIES = ['choppiness_filter',
'cci_divergence', 'bb_mean_reversion', 'adx_filter'], all traded 5-min /
TradeMode.INTRADAY with paper_trader.py's trailing_stop_pct=0.02).

REGIMES (identical signals/entries in all four — see admit_trades() below):
  A) SL/TP only, no trailing               -- the pure backtested rule
  B) SL/TP + 2% trailing (live behaviour)   -- trailing_stop_pct=0.02 in prod
  C) SL/TP + 1% trailing (tighter)
  D) SL/TP + 3% trailing (looser)

TRAILING RATCHET SEMANTICS — copied from paper_trader.py's
PaperTrader._update_trailing_stop (read 2026-07-26), NOT reinvented:
  - trailing_stop is initialized to the position's own stop_loss the moment
    the position opens (PaperTrader.open_position: `position.trailing_stop =
    signal.stop_loss` when use_trailing_stop).
  - Long: track highest_price seen; new_trailing = highest*(1-pct); the stop
    only ever RATCHETS UP (new_trailing > current trailing_stop), never down.
  - Short: mirror, tracks lowest_price, stop only ever ratchets down.
  - check_exits() then compares price against `trailing_stop or stop_loss`,
    and — IMPORTANT, this is the source of the "mostly trailing_stop" log
    pattern — labels EVERY stop-type exit TRAILING_STOP whenever trailing is
    enabled, since trailing_stop is truthy from the instant the position
    opens, REGARDLESS of whether it ever actually moved above the original
    stop. A stop hit at the ORIGINAL level (never ratcheted) is *also*
    logged as "trailing_stop" live. This script reproduces that exact
    labeling convention for the exit-reason mix (so it's comparable to the
    live logs), but ALSO separately tracks, as a diagnostic, what fraction of
    trailing-labeled exits had genuinely ratcheted (moved beyond the original
    stop) before triggering — see 'of which ratcheted' in the report. This
    matters for interpretation: "trailing_stop" in the live logs is not proof
    of a winner being cut short; it's the label for ANY stop-type exit once
    trailing is on.

INTRABAR MODELING CHOICE (this harness runs 1-min bars; live scans every 5 min
on a single last-traded-price, not bar extremes): each bar, the trailing
high/low is updated using THAT bar's own extreme (high for longs, low for
shorts) — including the entry bar itself — before checking whether the bar's
opposite extreme breaches the (possibly just-tightened) stop. This is the
standard "worst case" ordering used for OHLC trailing-stop backtests and is
consistent with the harness's existing SL 001-before-TP convention elsewhere
(bb_v2_screen.py / intraday_probe.py). It is if anything GENEROUS to the
"trailing hurts" hypothesis (more opportunities for the stop to have moved up
and then get clipped within the same bar), which is disclosed here rather than
buried.

WHY ENTRIES ARE FROZEN ACROSS REGIMES: signals -> candidate entries is
regime-independent (build_raw_signals / to_entry, copied verbatim from
bb_v2_screen.py's ORIGINAL variant — the strategy's own stop/target, no v2
widening, no cooldown). But WHICH candidates actually get admitted as trades
also depends on concurrent-position capacity (MAX_POS=5): if a trailing exit
closes a position earlier than a fixed SL would have, a slot frees up sooner
and a later candidate might get admitted under one regime but not another.
To keep the four regimes a clean, controlled comparison ("identical signals
AND entries" per the brief), admission is decided ONCE per day using regime A
(no trailing) as the reference portfolio simulation, and that admitted trade
list (symbol, direction, time, qty, entry price, original SL, TP) is FROZEN
and replayed independently, trade-by-trade, under all four exit regimes.
Concurrency/MAX_POS therefore cannot make regime B/C/D contain different
trades than regime A — only how (and when) each already-admitted trade exits
can differ.

COST BUG NOTE (per task instructions): bb_v2_screen.py imports `trade_cost`
from kite/research/intraday_probe.py, which computes
`sum(zerodha_charges.calculate_charges(...).values())`. calculate_charges()
returns a dict of SIX components (brokerage/stt/exchange/sebi/dp/gst/stamp_duty
-- six, actually) PLUS a `'total'` key that is already `sum(charges.values())`
of those six. Summing .values() therefore adds the 'total' key on top of the
six components it's already the sum of -> costs are counted ~2x. This bug was
caught and fixed in paper_trader.py on 2026-07-26 (its comment: "read ['total'],
never sum(...values())"), but bb_v2_screen.py / intraday_probe.py were NOT
patched. This script does NOT import that trade_cost; it defines its own using
['total'] only. Net P&L below is therefore MORE accurate (lower costs) than
what bb_v2_screen.py would have reported for the same trades.

HONESTY: all four strategies are known net-losers in this harness (140+
backtests, nothing has beaten buy-and-hold). The question here is RELATIVE —
which exit rule loses least / gains most — not whether any of them are
profitable. Do not read a "best regime" as an endorsement to trade it live.

FROZEN INTERPRETATION RULE (stated before any results are computed): a regime
only counts as "better" than another if it wins on BOTH samples (60d CSVs and
release-week DB). Where the two samples disagree, the verdict is
'inconclusive' — no cherry-picking the sample that agrees with the motivating
hypothesis.

Samples: (1) data/*_minute_60d.csv (Nov 2025 - Jan 2026), (2)
data/zerodha_data_latest.db (Jul 2026 release week) — same two samples
bb_v2_screen.py uses.

Usage: python -W ignore kite/research/trailing_stop_study.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'kite'))
sys.path.insert(0, str(Path(__file__).parent))

from intraday_probe import load_csvs, load_db, SLIP, CAPITAL, MAX_POS, RISK_PCT, SQUARE_OFF
from kite.strategies import STRATEGY_REGISTRY
from kite.config import zerodha_charges

STRATEGIES = ['bb_mean_reversion', 'cci_divergence', 'choppiness_filter', 'adx_filter']
WARMUP_DAYS = 10   # trailing trading days of 5-min history fed for indicator warmup (matches bb_v2_screen.py)

# Regime -> trailing pct. None = no trailing (regime A).
REGIMES = [
    ('A_no_trailing', None),
    ('B_trail_2pct_LIVE', 0.02),
    ('C_trail_1pct', 0.01),
    ('D_trail_3pct', 0.03),
]

OUT_LINES = []


def out(msg=''):
    print(msg)
    OUT_LINES.append(str(msg))


# --------------------------------------------------------------------------
# Data loading (with volume — needed by strategy.validate_data and 5-min
# volume aggregation). Copied from bb_v2_screen.py verbatim.
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
    """1-min -> 5-min per calendar day (no overnight-gap bin), concatenated so
    indicators carry trailing history across days. Copied from bb_v2_screen.py."""
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
# Signal generation — the ACTUAL strategy class (by name), on 5-min bars, per
# trading day, fed a trailing ~10-trading-day window of 5-min history for
# warmup. Generalized from bb_v2_screen.py's build_raw_signals (there
# hardcoded to bb_mean_reversion) to take strategy_name as a parameter.
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
# Signal -> executable entry: actual fill on next 1-min bar, gap/slippage
# aware. Copied verbatim from bb_v2_screen.py's to_entry (ORIGINAL variant:
# strategy's own stop/target as-is, no v2 widening).
# --------------------------------------------------------------------------

def to_entry(sig, day_bars):
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
    stop_loss, take_profit = sig['stop_loss'], sig['take_profit']
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
# Cost helper — FIXED (['total'], not sum(.values())). See module docstring.
# --------------------------------------------------------------------------

def trade_cost(buy_v, sell_v):
    return zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=True)['total']


# --------------------------------------------------------------------------
# Admission pass: decide which candidate entries actually become trades, and
# at what time/qty, using MAX_POS concurrency gating and regime A (no
# trailing) as the reference exit rule. This list is then FROZEN and reused
# for all four regimes so "identical signals and entries" is literally true —
# only how each already-admitted trade exits can differ across regimes.
# --------------------------------------------------------------------------

def admit_trades(day_bars, entries):
    admitted = []
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
            admitted.append(dict(e))
        for sym in list(open_pos):
            bars = day_bars.get(sym)
            if bars is None or t not in bars.index:
                continue
            row, p = bars.loc[t], open_pos[sym]
            exit_hit = False
            if p['direction'] == 'long':
                if row.low <= p['sl'] or row.high >= p['tp'] or t.time() >= SQUARE_OFF:
                    exit_hit = True
            else:
                if row.high >= p['sl'] or row.low <= p['tp'] or t.time() >= SQUARE_OFF:
                    exit_hit = True
            if exit_hit:
                del open_pos[sym]
    return admitted


# --------------------------------------------------------------------------
# Single-trade replay under one exit regime. trailing_pct=None => regime A
# (fixed SL/TP only). Ratchet semantics copied from PaperTrader._update_
# trailing_stop — see module docstring for the exact correspondence and the
# documented intrabar modeling choice (bar's own high/low used to update the
# trailing extreme before checking the opposite extreme against the stop).
# --------------------------------------------------------------------------

def simulate_trade(bars, entry, trailing_pct):
    direction = entry['direction']
    sl0 = entry['sl']
    tp = entry['tp']
    qty = entry['qty']
    entry_px = entry['entry']
    t0 = entry['time']

    sym_bars = bars[bars.index >= t0]
    if sym_bars.empty:
        # Shouldn't happen (entry itself came from this day's bars), but be defensive.
        return None

    highest = entry_px
    lowest = entry_px
    trail = sl0 if trailing_pct is not None else None
    ratcheted = False

    for t, row in sym_bars.iterrows():
        exit_px, reason = None, None
        if direction == 'long':
            if row.high > highest:
                highest = row.high
                if trailing_pct is not None:
                    new_trail = highest * (1 - trailing_pct)
                    if trail is None or new_trail > trail:
                        trail = new_trail
            eff_sl = trail if trailing_pct is not None else sl0
            if trailing_pct is not None and eff_sl > sl0:
                ratcheted = True
            if row.low <= eff_sl:
                exit_px = min(row.open, eff_sl) * (1 - SLIP)
                reason = 'trailing' if trailing_pct is not None else 'stop'
            elif row.high >= tp:
                exit_px, reason = max(row.open, tp) * (1 - SLIP), 'target'
            elif t.time() >= SQUARE_OFF:
                exit_px, reason = row.close * (1 - SLIP), 'EOD'
            if exit_px is not None:
                buy_v, sell_v = qty * entry_px, qty * exit_px
                pnl = sell_v - buy_v - trade_cost(buy_v, sell_v)
                return {'sym': entry['sym'], 'pnl': pnl, 'reason': reason,
                        'direction': direction, 'exit_time': t, 'ratcheted': ratcheted}
        else:  # short
            if row.low < lowest:
                lowest = row.low
                if trailing_pct is not None:
                    new_trail = lowest * (1 + trailing_pct)
                    if trail is None or new_trail < trail:
                        trail = new_trail
            eff_sl = trail if trailing_pct is not None else sl0
            if trailing_pct is not None and eff_sl < sl0:
                ratcheted = True
            if row.high >= eff_sl:
                exit_px = max(row.open, eff_sl) * (1 + SLIP)
                reason = 'trailing' if trailing_pct is not None else 'stop'
            elif row.low <= tp:
                exit_px, reason = min(row.open, tp) * (1 + SLIP), 'target'
            elif t.time() >= SQUARE_OFF:
                exit_px, reason = row.close * (1 + SLIP), 'EOD'
            if exit_px is not None:
                sell_v, buy_v = qty * entry_px, qty * exit_px
                pnl = sell_v - buy_v - trade_cost(buy_v, sell_v)
                return {'sym': entry['sym'], 'pnl': pnl, 'reason': reason,
                        'direction': direction, 'exit_time': t, 'ratcheted': ratcheted}

    # Defensive fallback: no bar reached SQUARE_OFF (data gap at day end) — exit at last close.
    last = sym_bars.iloc[-1]
    exit_px = last.close * (1 - SLIP if direction == 'long' else 1 + SLIP)
    if direction == 'long':
        buy_v, sell_v = qty * entry_px, qty * exit_px
    else:
        sell_v, buy_v = qty * entry_px, qty * exit_px
    pnl = sell_v - buy_v - trade_cost(buy_v, sell_v)
    return {'sym': entry['sym'], 'pnl': pnl, 'reason': 'EOD',
            'direction': direction, 'exit_time': last.name, 'ratcheted': ratcheted}


# --------------------------------------------------------------------------
# Per-strategy, per-sample simulation across all four regimes over identical
# admitted trades.
# --------------------------------------------------------------------------

def simulate(strategy_name, data, label):
    days = sorted({t.date() for df in data.values() for t in df.index})
    five_min = {sym: resample_5min(df) for sym, df in data.items()}
    sym_dates = {sym: sorted(set(df5.index.date)) for sym, df5 in five_min.items()}

    raw_signals = build_raw_signals(strategy_name, five_min, sym_dates)
    by_day = {}
    for s in raw_signals:
        by_day.setdefault(s['day'], []).append(s)

    regime_trades = {name: [] for name, _ in REGIMES}
    n_days_used = 0
    n_admitted_total = 0

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

        candidate_entries = []
        for s in day_signals:
            e = to_entry(s, day_bars)
            if e:
                candidate_entries.append(e)

        admitted = admit_trades(day_bars, candidate_entries)
        n_admitted_total += len(admitted)

        for entry in admitted:
            bars = day_bars[entry['sym']]
            for regime_name, trailing_pct in REGIMES:
                trade = simulate_trade(bars, entry, trailing_pct)
                if trade:
                    regime_trades[regime_name].append(trade)

    return {
        'label': label, 'n_days': n_days_used, 'n_signals': len(raw_signals),
        'n_admitted': n_admitted_total, 'regimes': regime_trades,
    }


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def stats(trades):
    if not trades:
        return None
    pnls = [t['pnl'] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    n = len(pnls)
    reason_counts = {}
    for t in trades:
        reason_counts[t['reason']] = reason_counts.get(t['reason'], 0) + 1
    trailing_n = reason_counts.get('trailing', 0)
    ratcheted_n = sum(1 for t in trades if t['reason'] == 'trailing' and t['ratcheted'])
    return {
        'n': n,
        'total': sum(pnls),
        'win_rate': 100 * wins / n,
        'avg': np.mean(pnls),
        'reason_pct': {r: 100 * c / n for r, c in reason_counts.items()},
        'trailing_n': trailing_n,
        'ratcheted_n': ratcheted_n,
    }


def print_regime(name, trades):
    s = stats(trades)
    if s is None:
        out(f'    {name:20}: no trades')
        return None
    rp = s['reason_pct']
    reason_str = (f"stop {rp.get('stop', 0):4.0f}% | target {rp.get('target', 0):4.0f}% | "
                  f"trailing {rp.get('trailing', 0):4.0f}% | EOD {rp.get('EOD', 0):4.0f}%")
    out(f'    {name:20}: {s["n"]:4} trades | total Rs {s["total"]:+10,.0f} | '
        f'win {s["win_rate"]:5.1f}% | avg/trade Rs {s["avg"]:+7.0f} | {reason_str}')
    if s['trailing_n'] > 0:
        out(f'    {"":20}  (of {s["trailing_n"]} trailing-labeled exits, '
            f'{s["ratcheted_n"]} ({100*s["ratcheted_n"]/s["trailing_n"]:.0f}%) had actually '
            f'ratcheted beyond the original stop before triggering)')
    return s


def run_sample(strategy_name, data, label):
    out(f'\n  --- {label} ---')
    res = simulate(strategy_name, data, label)
    out(f'  Trading days used: {res["n_days"]} | raw signals: {res["n_signals"]} | '
        f'admitted trades (frozen across regimes): {res["n_admitted"]}')
    regime_stats = {}
    for regime_name, _ in REGIMES:
        regime_stats[regime_name] = print_regime(regime_name, res['regimes'][regime_name])
    return {'label': label, 'regimes': regime_stats}


def total_or_none(rs):
    return rs['total'] if rs else 0.0


def summarize_strategy(strategy_name, sample_results):
    """Per strategy: which regime wins on BOTH samples (frozen rule), and is
    B (live 2% trailing) better or worse than A (no trailing)?"""
    out(f'\n  Regime comparison for {strategy_name} (frozen rule: must win on BOTH samples):')
    regime_names = [n for n, _ in REGIMES]

    # Best regime by total net P&L, independently per sample.
    per_sample_best = []
    for r in sample_results:
        totals = {rn: total_or_none(r['regimes'][rn]) for rn in regime_names}
        best = max(totals, key=totals.get)
        per_sample_best.append((r['label'], best, totals))
        totals_str = ', '.join(f'{rn}={v:+,.0f}' for rn, v in totals.items())
        out(f'    [{r["label"]}] totals: {totals_str}  -> best this sample: {best}')

    if len(per_sample_best) == 2 and per_sample_best[0][1] == per_sample_best[1][1]:
        overall_best = per_sample_best[0][1]
        out(f'    Best regime overall for {strategy_name}: {overall_best} (wins on BOTH samples)')
    else:
        overall_best = 'inconclusive'
        out(f'    Best regime overall for {strategy_name}: inconclusive (samples disagree)')

    # B vs A, directly.
    b_vs_a = []
    for r in sample_results:
        a_total = total_or_none(r['regimes']['A_no_trailing'])
        b_total = total_or_none(r['regimes']['B_trail_2pct_LIVE'])
        diff = b_total - a_total
        b_vs_a.append((r['label'], diff))
        out(f'    [{r["label"]}] B(live 2% trail) {b_total:+,.0f}  vs  A(no trailing) {a_total:+,.0f}  '
            f'-> B{"better" if diff > 0 else ("worse" if diff < 0 else "tied")} by Rs {diff:+,.0f}')

    signs = [1 if d > 0 else (-1 if d < 0 else 0) for _, d in b_vs_a]
    if len(signs) == 2 and signs[0] == signs[1] and signs[0] != 0:
        verdict = 'B (live) BETTER than A (no trailing)' if signs[0] > 0 else 'B (live) WORSE than A (no trailing)'
    else:
        verdict = 'inconclusive (samples disagree on direction)'
    out(f'    VERDICT — is live (2% trailing) better or worse than no trailing?  {verdict}')

    return {'strategy': strategy_name, 'best_regime': overall_best, 'b_vs_a_verdict': verdict,
            'b_vs_a': b_vs_a}


def final_summary_table(all_verdicts):
    out('\n' + '=' * 88)
    out('SUMMARY TABLE')
    out('=' * 88)
    out(f'{"strategy":22} {"best regime (both samples)":28} {"B(2% live) vs A(no trail)"}')
    out('-' * 88)
    for v in all_verdicts:
        out(f'{v["strategy"]:22} {v["best_regime"]:28} {v["b_vs_a_verdict"]}')
    out('-' * 88)


if __name__ == '__main__':
    out('=' * 88)
    out('TRAILING STOP COUNTERFACTUAL STUDY')
    out('=' * 88)
    out('\nFROZEN INTERPRETATION RULE (stated before any results below were computed):')
    out('  A regime counts as "better" than another ONLY if it wins on BOTH samples')
    out('  (60d CSVs and release-week DB). Where the two samples disagree on direction,')
    out('  the verdict is reported as "inconclusive" -- no picking the sample that')
    out('  happens to agree with the motivating hypothesis.')
    out('\nHONESTY: all four strategies are known net-losers in this harness (140+ prior')
    out('backtests, nothing has beaten buy-and-hold). The question here is RELATIVE --')
    out('which exit rule loses least / gains most -- not whether any of them are profitable.')
    out('\nCOST FIX: this script uses calculate_charges(...)[\'total\'], NOT')
    out('sum(calculate_charges(...).values()) -- the latter (used by bb_v2_screen.py via')
    out('intraday_probe.trade_cost) double-counts because the returned dict already')
    out('contains a \'total\' key equal to the sum of its other six keys.')

    data_csv = load_csvs_full()
    db_path = ROOT / 'data' / 'zerodha_data_latest.db'
    data_db = load_db_full(db_path) if db_path.exists() else None
    if data_db is None:
        out(f'\nSample 2 DB not found at {db_path}, skipping.')

    all_verdicts = []
    for strategy_name in STRATEGIES:
        out('\n' + '#' * 88)
        out(f'# STRATEGY: {strategy_name}')
        out('#' * 88)
        sample_results = []
        sample_results.append(run_sample(strategy_name, data_csv, 'Sample 1: Nov 2025 - Jan 2026 (60d CSVs)'))
        if data_db is not None:
            sample_results.append(run_sample(strategy_name, data_db, 'Sample 2: Jul 2026 (release DB)'))
        verdict = summarize_strategy(strategy_name, sample_results)
        all_verdicts.append(verdict)

    final_summary_table(all_verdicts)

    results_path = Path(__file__).parent / 'trailing_stop_study_results.txt'
    results_path.write_text('\n'.join(OUT_LINES) + '\n', encoding='utf-8')
    print(f'\n[saved output to {results_path}]')
