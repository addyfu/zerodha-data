"""Re-test ALL registered strategies under honest execution.

Signals: each strategy's own get_trade_signals() (vectorized — valid only for
strategies the walkforward audit proved leak-free; leaky ones are flagged).
Execution (the part the old backtest got wrong):
- Signal on close of day t -> entry at open of day t+1 (+slippage)
- Long-only cash equity: SELL signals close an open long, never open a short
- Strategy's own SL/TP checked against daily high/low, gap-aware
  (open beyond SL fills at open, i.e. worse; SL-vs-TP same bar -> SL wins)
- Delivery (not intraday) charges, shared 100k capital, 5 slots
- Train 2020-07..2024-06 / Validation 2024-07..2026-01

Usage: python kite/research/retest_all.py            # all strategies
       python kite/research/retest_all.py ema_21_55  # subset
"""
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import zerodha_charges
from kite.strategies import STRATEGY_REGISTRY

DATA_DIR = Path(__file__).resolve().parents[2] / 'data' / 'daily'
SLIPPAGE = 0.0005
CAPITAL = 100_000
MAX_SLOTS = 5
TRAIN_END = pd.Timestamp('2024-06-30')
AUDIT_CSV = Path(__file__).resolve().parents[1] / 'reports' / 'walkforward_audit.csv'


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


def gen_signals(strategy_cls, data):
    """Run get_trade_signals per stock. Returns {sym: df} or raises."""
    out = {}
    for sym, df in data.items():
        s = strategy_cls()
        sig = s.get_trade_signals(df.copy())
        out[sym] = sig[['open', 'high', 'low', 'close', 'signal', 'stop_loss', 'take_profit']]
    return out


def simulate(sigs, dates):
    """Portfolio event loop over given dates. Returns equity Series + trades list."""
    cash, positions, trades = CAPITAL, {}, []
    pending_entries, pending_exits = [], []
    equity = {}
    for t in dates:
        # fill pending exits at today's open
        for sym in pending_exits:
            p = positions.pop(sym, None)
            if p is None:
                continue
            o = sigs[sym]['open'].get(t)
            if o is None or np.isnan(o):
                positions[sym] = p
                continue
            px = o * (1 - SLIPPAGE)
            cash += _close(p, px, trades, t, 'signal')
        pending_exits = []
        # fill pending entries at today's open
        for sym, sl, tp in pending_entries:
            if sym in positions or len(positions) >= MAX_SLOTS:
                continue
            o = sigs[sym]['open'].get(t)
            if o is None or np.isnan(o):
                continue
            px = o * (1 + SLIPPAGE)
            slot = min(cash, (cash + _mval(positions, sigs, t)) / MAX_SLOTS)
            qty = int(slot / px)
            if qty <= 0:
                continue
            cash -= qty * px
            positions[sym] = {'qty': qty, 'entry': px, 'entry_date': t,
                              'sl': sl, 'tp': tp}
        pending_entries = []
        # intraday SL/TP on open positions (gap-aware, SL wins ties)
        for sym in list(positions):
            row = sigs[sym].loc[t] if t in sigs[sym].index else None
            if row is None:
                continue
            p = positions[sym]
            if not np.isnan(p['sl']) and row.low <= p['sl']:
                px = min(row.open, p['sl']) * (1 - SLIPPAGE)
                cash += _close(positions.pop(sym), px, trades, t, 'sl')
            elif not np.isnan(p['tp']) and row.high >= p['tp']:
                px = max(row.open, p['tp']) * (1 - SLIPPAGE)
                cash += _close(positions.pop(sym), px, trades, t, 'tp')
        # read today's close signals -> act tomorrow
        for sym, sdf in sigs.items():
            if t not in sdf.index:
                continue
            sig = sdf.loc[t, 'signal']
            if sig == 1 and sym not in positions:
                pending_entries.append((sym, sdf.loc[t, 'stop_loss'], sdf.loc[t, 'take_profit']))
            elif sig == -1 and sym in positions:
                pending_exits.append(sym)
        equity[t] = cash + _mval(positions, sigs, t)
    return pd.Series(equity), trades


def _mval(positions, sigs, t):
    return sum(p['qty'] * sigs[s]['close'].get(t, p['entry']) for s, p in positions.items())


def _close(p, px, trades, t, reason):
    buy_v, sell_v = p['qty'] * p['entry'], p['qty'] * px
    fees = sum(zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False).values())
    trades.append({'pnl': sell_v - buy_v - fees, 'reason': reason,
                   'entry_date': p['entry_date'], 'exit_date': t})
    return sell_v - fees


def metrics(eq, trades):
    if len(eq) < 20:
        return {}
    r = eq.pct_change().dropna()
    yrs = len(eq) / 252
    wins = [x for x in trades if x['pnl'] > 0]
    return {'cagr': round(((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100, 1),
            'sharpe': round(r.mean() / r.std() * np.sqrt(252), 2) if r.std() > 0 else 0,
            'maxdd': round(((eq / eq.cummax()) - 1).min() * 100, 1),
            'trades': len(trades),
            'win': round(100 * len(wins) / len(trades), 1) if trades else 0}


def leak_flags():
    """Strategy -> leak verdict from the walkforward audit (trade-count blowup)."""
    try:
        a = pd.read_csv(AUDIT_CSV)
        flags = {}
        for _, row in a.iterrows():
            v, wf = row.get('v_trades', 0), row.get('wf_trades', 0)
            if v == 0 and wf == 0:
                flags[row['strategy']] = 'no-data'
            elif v > 0 and abs(wf - v) / max(v, 1) > 0.2:
                flags[row['strategy']] = 'LEAK-SUSPECT'
            else:
                flags[row['strategy']] = 'clean'
        return flags
    except Exception:
        return {}


def main():
    only = set(sys.argv[1:])
    data = load_data()
    dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    train, val = dates[dates <= TRAIN_END], dates[dates > TRAIN_END]
    flags = leak_flags()

    rows = []
    names = [n for n in sorted(STRATEGY_REGISTRY) if not only or n in only]
    for i, name in enumerate(names, 1):
        try:
            sigs = gen_signals(STRATEGY_REGISTRY[name], data)
            mt = metrics(*simulate(sigs, train))
            mv = metrics(*simulate(sigs, val))
            row = {'strategy': name, 'leak': flags.get(name, '?'),
                   **{f't_{k}': v for k, v in mt.items()},
                   **{f'v_{k}': v for k, v in mv.items()}}
        except Exception as e:
            row = {'strategy': name, 'leak': flags.get(name, '?'), 'error': repr(e)[:80]}
            traceback.print_exc()
        rows.append(row)
        print(f"[{i}/{len(names)}] {name}: "
              + (f"train {row.get('t_cagr')}% / val {row.get('v_cagr')}% ({row['leak']})"
                 if 'error' not in row else f"ERROR {row['error']}"), flush=True)

    out = Path(__file__).with_name('retest_results.csv')
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f'\nsaved -> {out}')


if __name__ == '__main__':
    main()
