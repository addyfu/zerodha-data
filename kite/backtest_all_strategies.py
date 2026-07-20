"""
Comprehensive Backtest Script for All Trading Strategies
Runs parallel backtests on daily, hourly, and minute data
Outputs results to CSV file

Optimizations:
- Parallel data loading with ThreadPoolExecutor
- Batch processing by stock (reduces serialization overhead)
- Command-line flags for quick testing
- Timing instrumentation
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime
from multiprocessing import Pool, cpu_count
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from tqdm import tqdm
import warnings
import argparse
import time

warnings.filterwarnings('ignore')

from kite.strategies import STRATEGY_REGISTRY
from kite.backtesting.engine import BacktestEngine
from kite.utils.data_loader import DataLoader


# Configuration
INITIAL_CAPITAL = 100000
ALL_TIMEFRAMES = ['daily', 'hourly', 'minute']
OUTPUT_FILE = Path(__file__).parent / 'reports' / 'all_strategies_backtest_results.csv'

# Quick mode uses fewer stocks for faster testing
QUICK_MODE_STOCKS = 10


def load_single_stock(args):
    """Load a single stock's data (for parallel loading)."""
    symbol, timeframe, loader = args
    try:
        df = loader.load_stock(symbol, timeframe)
        if df is not None and len(df) > 0:
            return symbol, df
    except Exception:
        pass
    return symbol, None


def load_data_parallel(timeframe: str, max_stocks: int = None) -> dict:
    """Load data for a specific timeframe using parallel I/O."""
    loader = DataLoader()
    
    # Get available symbols for this timeframe
    symbols = loader.get_available_symbols(timeframe)
    
    if not symbols:
        return {}
    
    # Limit stocks if specified
    if max_stocks and len(symbols) > max_stocks:
        symbols = symbols[:max_stocks]
    
    # Parallel loading with ThreadPoolExecutor (I/O bound)
    data = {}
    
    def load_single(symbol):
        try:
            return symbol, loader.load_stock(symbol, timeframe)
        except Exception:
            return symbol, None
    
    with ThreadPoolExecutor(max_workers=min(8, len(symbols))) as executor:
        results = list(tqdm(
            executor.map(load_single, symbols),
            total=len(symbols),
            desc=f"Loading {timeframe} data"
        ))
    
    for symbol, df in results:
        if df is not None and len(df) > 0:
            data[symbol] = df
    
    return data


def run_all_strategies_for_stock(args):
    """Run ALL strategies for a single stock - reduces serialization overhead."""
    symbol, df, strategies_dict, timeframe = args
    
    results = []
    
    # Skip if not enough data
    if df is None or len(df) < 100:
        return results
    
    for strategy_name, strategy_class in strategies_dict.items():
        try:
            # Initialize strategy
            strategy = strategy_class()
            
            # Run backtest
            engine = BacktestEngine(initial_capital=INITIAL_CAPITAL)
            result = engine.run(strategy, df)
            
            if result is None or result.total_trades == 0:
                continue
            
            results.append({
                'strategy': strategy_name,
                'symbol': symbol,
                'timeframe': timeframe,
                'total_return_pct': result.total_return_pct,
                'sharpe_ratio': result.sharpe_ratio if hasattr(result, 'sharpe_ratio') else 0,
                'win_rate_pct': result.win_rate,
                'max_drawdown_pct': result.max_drawdown_pct,
                'total_trades': result.total_trades,
                'profit_factor': result.profit_factor if hasattr(result, 'profit_factor') else 0,
                'avg_trade_pct': result.total_return_pct / result.total_trades if result.total_trades > 0 else 0,
            })
        except Exception:
            continue
    
    return results


def run_backtests_batched(strategies: dict, data: dict, timeframe: str, n_workers: int = None):
    """
    Run backtests in parallel, batched by stock.
    
    Instead of creating (strategies x stocks) jobs, we create (stocks) jobs,
    where each job runs all strategies. This dramatically reduces serialization overhead.
    """
    if n_workers is None:
        n_workers = max(1, cpu_count() - 1)
    
    # Prepare arguments - one job per stock
    args_list = [
        (symbol, df, strategies, timeframe)
        for symbol, df in data.items()
    ]
    
    if not args_list:
        return []
    
    # Run in parallel
    all_results = []
    
    with Pool(n_workers) as pool:
        for stock_results in tqdm(
            pool.imap_unordered(run_all_strategies_for_stock, args_list),
            total=len(args_list),
            desc=f"Backtesting {timeframe} ({len(strategies)} strategies x {len(data)} stocks)"
        ):
            all_results.extend(stock_results)
    
    return all_results


def aggregate_results(results: list) -> pd.DataFrame:
    """Aggregate results by strategy and timeframe."""
    if not results:
        return pd.DataFrame()
    
    df = pd.DataFrame(results)
    
    # Aggregate by strategy and timeframe
    agg_df = df.groupby(['strategy', 'timeframe']).agg({
        'total_return_pct': 'mean',
        'sharpe_ratio': 'mean',
        'win_rate_pct': 'mean',
        'max_drawdown_pct': 'mean',
        'total_trades': 'sum',
        'profit_factor': 'mean',
        'avg_trade_pct': 'mean',
    }).reset_index()
    
    # Round values
    for col in ['total_return_pct', 'sharpe_ratio', 'win_rate_pct', 'max_drawdown_pct', 'profit_factor', 'avg_trade_pct']:
        agg_df[col] = agg_df[col].round(4)
    
    return agg_df


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description='Backtest all trading strategies')
    
    parser.add_argument('--quick', action='store_true',
                       help=f'Quick mode: only test on {QUICK_MODE_STOCKS} stocks')
    
    parser.add_argument('--daily-only', action='store_true',
                       help='Only run backtests on daily data')
    
    parser.add_argument('--hourly-only', action='store_true',
                       help='Only run backtests on hourly data')
    
    parser.add_argument('--minute-only', action='store_true',
                       help='Only run backtests on minute data')
    
    parser.add_argument('--max-stocks', type=int, default=None,
                       help='Maximum number of stocks to test')
    
    parser.add_argument('--workers', type=int, default=None,
                       help='Number of parallel workers (default: CPU count - 1)')
    
    parser.add_argument('--output', type=str, default=None,
                       help='Output CSV file path')
    
    return parser.parse_args()


def main():
    """Main function to run all backtests."""
    args = parse_args()
    
    # Determine timeframes to test
    if args.daily_only:
        timeframes = ['daily']
    elif args.hourly_only:
        timeframes = ['hourly']
    elif args.minute_only:
        timeframes = ['minute']
    else:
        timeframes = ALL_TIMEFRAMES
    
    # Determine max stocks
    max_stocks = args.max_stocks
    if args.quick and max_stocks is None:
        max_stocks = QUICK_MODE_STOCKS
    
    # Output file
    output_file = Path(args.output) if args.output else OUTPUT_FILE
    
    # Timing
    total_start = time.time()
    
    print("=" * 80)
    print("COMPREHENSIVE STRATEGY BACKTEST (OPTIMIZED)")
    print("=" * 80)
    print(f"Total Strategies: {len(STRATEGY_REGISTRY)}")
    print(f"Timeframes: {timeframes}")
    print(f"Max Stocks: {max_stocks or 'All'}")
    print(f"Workers: {args.workers or 'Auto'}")
    print(f"Initial Capital: Rs {INITIAL_CAPITAL:,}")
    print(f"Quick Mode: {args.quick}")
    print("=" * 80)
    
    all_results = []
    timing_info = {}
    
    for timeframe in timeframes:
        print(f"\n{'='*60}")
        print(f"TIMEFRAME: {timeframe.upper()}")
        print(f"{'='*60}")
        
        # Load data with timing
        load_start = time.time()
        data = load_data_parallel(timeframe, max_stocks)
        load_time = time.time() - load_start
        
        if not data:
            print(f"No {timeframe} data found, skipping...")
            continue
        
        print(f"Loaded {len(data)} stocks in {load_time:.2f}s")
        
        # Run backtests with timing
        backtest_start = time.time()
        results = run_backtests_batched(STRATEGY_REGISTRY, data, timeframe, args.workers)
        backtest_time = time.time() - backtest_start
        
        all_results.extend(results)
        
        timing_info[timeframe] = {
            'load_time': load_time,
            'backtest_time': backtest_time,
            'stocks': len(data),
            'results': len(results)
        }
        
        print(f"Completed {len(results)} backtests in {backtest_time:.2f}s")
        print(f"  ({len(results) / backtest_time:.1f} backtests/second)")
    
    # Aggregate and save results
    print("\n" + "=" * 80)
    print("AGGREGATING RESULTS")
    print("=" * 80)
    
    agg_df = aggregate_results(all_results)
    
    if agg_df.empty:
        print("No results generated!")
        return
    
    # Sort by Sharpe Ratio
    agg_df = agg_df.sort_values(['timeframe', 'sharpe_ratio'], ascending=[True, False])
    
    # Save to CSV
    output_file.parent.mkdir(parents=True, exist_ok=True)
    agg_df.to_csv(output_file, index=False)
    print(f"\nResults saved to: {output_file}")
    
    # Print summary
    print("\n" + "=" * 80)
    print("TOP 10 STRATEGIES BY TIMEFRAME")
    print("=" * 80)
    
    for tf in timeframes:
        tf_df = agg_df[agg_df['timeframe'] == tf].head(10)
        if not tf_df.empty:
            print(f"\n{tf.upper()} - Top 10:")
            print("-" * 70)
            for _, row in tf_df.iterrows():
                print(f"  {row['strategy']:<30} | Return: {row['total_return_pct']:>8.2f}% | "
                      f"Sharpe: {row['sharpe_ratio']:>6.2f} | Win: {row['win_rate_pct']:>5.1f}%")
    
    # Overall best strategies
    print("\n" + "=" * 80)
    print("OVERALL BEST STRATEGIES (Avg across timeframes)")
    print("=" * 80)
    
    overall = agg_df.groupby('strategy').agg({
        'total_return_pct': 'mean',
        'sharpe_ratio': 'mean',
        'win_rate_pct': 'mean',
        'max_drawdown_pct': 'mean',
        'total_trades': 'sum',
    }).reset_index()
    
    overall = overall.sort_values('sharpe_ratio', ascending=False).head(20)
    
    print("\nTop 20 Strategies (by average Sharpe Ratio):")
    print("-" * 90)
    for _, row in overall.iterrows():
        print(f"  {row['strategy']:<35} | Return: {row['total_return_pct']:>8.2f}% | "
              f"Sharpe: {row['sharpe_ratio']:>6.2f} | Win: {row['win_rate_pct']:>5.1f}% | "
              f"DD: {row['max_drawdown_pct']:>6.2f}%")
    
    # Timing summary
    total_time = time.time() - total_start
    
    print("\n" + "=" * 80)
    print("TIMING SUMMARY")
    print("=" * 80)
    for tf, info in timing_info.items():
        print(f"  {tf.upper():<10} | Load: {info['load_time']:>6.2f}s | "
              f"Backtest: {info['backtest_time']:>6.2f}s | "
              f"Stocks: {info['stocks']:>3} | Results: {info['results']:>5}")
    print(f"\n  TOTAL TIME: {total_time:.2f}s")
    
    print("\n" + "=" * 80)
    print("BACKTEST COMPLETE")
    print(f"Total strategies tested: {len(STRATEGY_REGISTRY)}")
    print(f"Total backtests run: {len(all_results)}")
    print(f"Results file: {output_file}")
    print("=" * 80)


if __name__ == '__main__':
    main()
