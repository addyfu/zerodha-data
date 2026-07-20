"""
Walk-forward leak audit.

Runs each strategy twice (vectorized vs walk_forward) on a small sample of
stocks, compares trade counts and returns. Strategies whose numbers collapse
under walk_forward had look-ahead leak — those numbers were unreachable live.

Output: kite/reports/walkforward_audit.csv
"""
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import warnings
warnings.filterwarnings('ignore')

import sqlite3
import logging
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger(__name__)

from kite.strategies import STRATEGY_REGISTRY
from kite.backtesting.engine import BacktestEngine
from kite.config import NIFTY_50_STOCKS

CAPITAL = 100_000
DB_PATH = Path(__file__).parent.parent / 'data' / 'zerodha_data.db'
OUT = Path(__file__).parent / 'reports' / 'walkforward_audit.csv'
SAMPLE_SIZE = 5  # stocks per strategy — keep audit fast; full sweep later


def load_db(symbols, resample='5min'):
    con = sqlite3.connect(DB_PATH)
    placeholders = ','.join('?' * len(symbols))
    q = (f"SELECT symbol, datetime, open, high, low, close, volume "
         f"FROM ohlcv WHERE symbol IN ({placeholders}) "
         f"AND interval='minute' ORDER BY symbol, datetime")
    df_all = pd.read_sql(q, con, params=symbols)
    con.close()

    out = {}
    for sym, grp in df_all.groupby('symbol'):
        grp = grp.copy()
        grp['datetime'] = pd.to_datetime(grp['datetime']).dt.tz_localize(None)
        grp = grp.set_index('datetime')[['open', 'high', 'low', 'close', 'volume']]
        if resample and resample != '1min':
            grp = grp.resample(resample).agg({
                'open': 'first', 'high': 'max', 'low': 'min',
                'close': 'last', 'volume': 'sum'
            }).dropna()
        if len(grp) >= 100:
            out[sym] = grp
    return out


def run_mode(strategy_cls, stock_data, walk_forward):
    trades = 0
    rets = []
    for sym, df in stock_data.items():
        try:
            eng = BacktestEngine(initial_capital=CAPITAL)
            res = eng.run(strategy_cls(), df, sym, walk_forward=walk_forward)
            if res:
                trades += res.total_trades
                rets.append(res.total_return_pct)
        except Exception as e:
            log.debug(f"  {sym} {strategy_cls.__name__} wf={walk_forward}: {e}")
    return trades, (np.mean(rets) if rets else 0.0)


def main():
    log.info(f"=== Walk-forward leak audit (sample={SAMPLE_SIZE} stocks) ===")
    avail = pd.read_sql("SELECT DISTINCT symbol FROM ohlcv",
                        sqlite3.connect(DB_PATH))['symbol'].tolist()
    pool = [s for s in NIFTY_50_STOCKS if s in avail][:SAMPLE_SIZE]
    log.info(f"Loading 5-min data for: {pool}")
    data = load_db(pool, '5min')
    log.info(f"Loaded {len(data)} stocks, ~{len(next(iter(data.values())))} bars each")

    rows = []
    for i, (name, cls) in enumerate(STRATEGY_REGISTRY.items(), 1):
        log.info(f"[{i}/{len(STRATEGY_REGISTRY)}] {name} — vectorized…")
        v_trades, v_ret = run_mode(cls, data, walk_forward=False)
        log.info(f"  vectorized: {v_trades} trades, {v_ret:+.2f}% avg return")
        log.info(f"[{i}/{len(STRATEGY_REGISTRY)}] {name} — walk_forward…")
        w_trades, w_ret = run_mode(cls, data, walk_forward=True)
        log.info(f"  walk_forward: {w_trades} trades, {w_ret:+.2f}% avg return")
        rows.append({
            'strategy': name,
            'v_trades': v_trades,
            'wf_trades': w_trades,
            'trade_delta_pct': round((w_trades - v_trades) / v_trades * 100, 1) if v_trades else 0,
            'v_return_pct': round(v_ret, 2),
            'wf_return_pct': round(w_ret, 2),
            'return_delta_pct': round(w_ret - v_ret, 2),
        })

    df = pd.DataFrame(rows).sort_values('wf_return_pct', ascending=False)
    OUT.parent.mkdir(exist_ok=True)
    df.to_csv(OUT, index=False)

    print("\n=== AUDIT (sorted by walk-forward return) ===")
    print(df.to_string(index=False))
    print(f"\nSaved: {OUT}")
    print("\nLeak signal: large negative trade_delta_pct or return_delta_pct = "
          "strategy depended on look-ahead.")


if __name__ == '__main__':
    main()
