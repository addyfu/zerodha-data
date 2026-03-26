"""
Intraday Strategy Backtest (5-minute candles)
Fetches 60 days of 5-min data from Zerodha, runs all strategies, ranks results.
"""
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env
_env = Path(__file__).parent.parent / '.env'
if _env.exists():
    for line in open(_env):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, _, v = line.partition('=')
            v = v.strip()
            if v.startswith(('"', "'")) and v.endswith(v[0]):
                v = v[1:-1]
            else:
                v = v.split('#')[0].strip()
            os.environ.setdefault(k.strip(), v)

import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time
import sqlite3
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

from kite.strategies import STRATEGY_REGISTRY
from kite.backtesting.engine import BacktestEngine
from kite.config import NIFTY_50_STOCKS

CAPITAL = 100_000
OUTPUT = Path(__file__).parent / 'reports' / 'intraday_backtest_results.csv'
DB_PATH = Path(__file__).parent.parent / 'data' / 'zerodha_data.db'


def load_from_db(symbols=None, resample='5min'):
    """Load 1-minute data from SQLite DB and resample."""
    import sqlite3
    db = sqlite3.connect(DB_PATH)

    where = ""
    if symbols:
        placeholders = ','.join('?' * len(symbols))
        where = f"WHERE symbol IN ({placeholders})"

    query = f"SELECT symbol, datetime, open, high, low, close, volume FROM ohlcv {where} ORDER BY symbol, datetime"
    params = symbols if symbols else []

    df_all = pd.read_sql(query, db, params=params)
    db.close()

    stock_data = {}
    for symbol, grp in df_all.groupby('symbol'):
        grp = grp.copy()
        grp['datetime'] = pd.to_datetime(grp['datetime']).dt.tz_localize(None)
        grp = grp.set_index('datetime')[['open', 'high', 'low', 'close', 'volume']]
        if resample and resample != '1min':
            grp = grp.resample(resample).agg({
                'open': 'first', 'high': 'max', 'low': 'min',
                'close': 'last', 'volume': 'sum'
            }).dropna()
        if len(grp) >= 60:
            stock_data[symbol] = grp
    return stock_data


def run_backtest(strategy_name, strategy_cls, stock_data):
    results = []
    for symbol, df in stock_data.items():
        try:
            strategy = strategy_cls()
            engine = BacktestEngine(initial_capital=CAPITAL)
            result = engine.run(strategy, df, symbol)  # correct signature: (strategy, df, symbol)
            if result and result.total_trades > 0:
                results.append(result)
        except Exception:
            pass

    if not results:
        return None

    total_trades = sum(r.total_trades for r in results)
    if total_trades == 0:
        return None

    wins = sum(r.winning_trades for r in results)
    total_return = np.mean([r.total_return_pct for r in results])
    sharpe = np.mean([r.sharpe_ratio for r in results if r.sharpe_ratio is not None and np.isfinite(r.sharpe_ratio)])
    max_dd = np.mean([r.max_drawdown_pct for r in results])
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    pf_vals = [r.profit_factor for r in results if r.profit_factor is not None and np.isfinite(r.profit_factor)]
    profit_factor = np.mean(pf_vals) if pf_vals else 0

    return {
        'strategy': strategy_name,
        'timeframe': '5minute',
        'total_return_pct': round(total_return, 4),
        'sharpe_ratio': round(float(sharpe), 4),
        'win_rate_pct': round(win_rate, 4),
        'max_drawdown_pct': round(max_dd, 4),
        'total_trades': total_trades,
        'profit_factor': round(float(profit_factor), 4),
    }


def main():
    logger.info("=== Intraday Strategy Backtest (5-minute, from local DB) ===")
    logger.info(f"DB: {DB_PATH}")

    # Load NIFTY 50 stocks from DB, resampled to 5-min
    nifty_symbols = [s for s in NIFTY_50_STOCKS if s in
                     pd.read_sql("SELECT DISTINCT symbol FROM ohlcv", sqlite3.connect(DB_PATH))['symbol'].values]
    logger.info(f"Loading 5-min data for {len(nifty_symbols)} NIFTY 50 stocks from DB...")
    stock_data = load_from_db(symbols=nifty_symbols if nifty_symbols else None, resample='5min')
    logger.info(f"Loaded {len(stock_data)} stocks")

    # Run all strategies
    logger.info(f"Running {len(STRATEGY_REGISTRY)} strategies...")
    rows = []
    for i, (name, cls) in enumerate(STRATEGY_REGISTRY.items()):
        try:
            result = run_backtest(name, cls, stock_data)
            if result:
                rows.append(result)
                logger.info(f"  [{i+1}/{len(STRATEGY_REGISTRY)}] {name}: return={result['total_return_pct']:.1f}% trades={result['total_trades']}")
            else:
                logger.info(f"  [{i+1}/{len(STRATEGY_REGISTRY)}] {name}: no trades")
        except Exception as e:
            logger.warning(f"  [{i+1}/{len(STRATEGY_REGISTRY)}] {name}: ERROR {e}")

    if not rows:
        logger.error("No results!")
        return

    df_results = pd.DataFrame(rows)
    df_results = df_results.sort_values('sharpe_ratio', ascending=False)
    OUTPUT.parent.mkdir(exist_ok=True)
    df_results.to_csv(OUTPUT, index=False)
    logger.info(f"\nSaved to {OUTPUT}")

    # Print top 10
    print("\n=== TOP 10 STRATEGIES (5-minute intraday) ===")
    print(f"{'Strategy':<25} {'Return%':>8} {'Sharpe':>7} {'Win%':>7} {'DrawDown%':>10} {'Trades':>7}")
    print("-" * 70)
    for _, r in df_results.head(10).iterrows():
        print(f"{r['strategy']:<25} {r['total_return_pct']:>8.1f} {r['sharpe_ratio']:>7.3f} {r['win_rate_pct']:>7.1f} {r['max_drawdown_pct']:>10.1f} {r['total_trades']:>7}")


if __name__ == '__main__':
    main()
