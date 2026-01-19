"""
Parallel Strategy Analysis - Uses all CPU cores for faster backtesting
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Any
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

from multiprocessing import Pool, cpu_count
from functools import partial
import time

from kite.utils.data_loader import DataLoader
from kite.backtesting.engine import BacktestEngine
from kite.strategies import STRATEGY_REGISTRY
from kite.strategies.combined_strategy import CombinedStrategy


def run_single_backtest(args: Tuple) -> Dict:
    """Run a single backtest - designed for parallel execution."""
    strat_key, symbol, timeframe, params = args
    
    try:
        # Each process needs its own loader
        loader = DataLoader()
        df = loader.load_stock(symbol, timeframe)
        
        if len(df) < 50:
            return None
        
        if strat_key in STRATEGY_REGISTRY:
            strategy = STRATEGY_REGISTRY[strat_key](params or {})
        else:
            return None
        
        engine = BacktestEngine()
        result = engine.run(strategy, df, symbol)
        
        if result and result.total_trades > 0:
            return {
                'strategy': strat_key,
                'symbol': symbol,
                'timeframe': timeframe,
                'return': result.total_return_pct,
                'sharpe': result.sharpe_ratio,
                'win_rate': result.win_rate,
                'max_dd': result.max_drawdown_pct,
                'trades': result.total_trades,
                'profit_factor': result.profit_factor,
            }
    except Exception as e:
        pass
    
    return None


def run_combined_backtest(args: Tuple) -> Dict:
    """Run a combined strategy backtest - designed for parallel execution."""
    combo_name, strategy_keys, method, symbol = args
    
    try:
        loader = DataLoader()
        df = loader.load_stock(symbol, 'daily')
        
        if len(df) < 200:
            return None
        
        # Create strategy instances
        from kite.strategies.combined_strategy import CombinationMethod
        strategies = []
        for key in strategy_keys:
            if key in STRATEGY_REGISTRY:
                strategies.append(STRATEGY_REGISTRY[key]({}))
        
        if len(strategies) < 2:
            return None
        
        combo = CombinedStrategy(strategies, method=CombinationMethod(method))
        engine = BacktestEngine()
        result = engine.run(combo, df, symbol)
        
        if result and result.total_trades > 0:
            return {
                'strategy': combo_name,
                'symbol': symbol,
                'return': result.total_return_pct,
                'sharpe': result.sharpe_ratio,
                'win_rate': result.win_rate,
                'max_dd': result.max_drawdown_pct,
                'trades': result.total_trades,
                'profit_factor': result.profit_factor,
            }
    except Exception as e:
        pass
    
    return None


def aggregate_results(results: List[Dict], group_by: str = 'strategy') -> Dict:
    """Aggregate results by strategy or timeframe."""
    if not results:
        return {}
    
    df = pd.DataFrame(results)
    
    aggregated = {}
    for name, group in df.groupby(group_by):
        aggregated[name] = {
            'sharpe': group['sharpe'].mean(),
            'return': group['return'].mean(),
            'win_rate': group['win_rate'].mean(),
            'trades': group['trades'].mean(),
            'max_dd': group['max_dd'].mean(),
            'profit_factor': group['profit_factor'].mean(),
            'stocks_tested': len(group),
        }
    
    return aggregated


def print_results(results: Dict, title: str):
    """Print results in a formatted table."""
    if not results:
        print(f"\n{title}: No results")
        return
    
    print(f"\n{'-'*75}")
    print(f"{title}")
    print(f"{'-'*75}")
    print(f"{'Rank':<5} {'Strategy':<22} {'Sharpe':>8} {'Return%':>10} {'Win%':>8} {'Trades':>8} {'MaxDD%':>10}")
    print("-"*75)
    
    sorted_results = sorted(results.items(), key=lambda x: x[1]['sharpe'], reverse=True)
    for rank, (name, m) in enumerate(sorted_results, 1):
        print(f"{rank:<5} {name:<22} {m['sharpe']:>8.2f} {m['return']:>10.2f} {m['win_rate']:>8.1f} {m['trades']:>8.0f} {m['max_dd']:>10.2f}")


def main():
    start_time = time.time()
    
    num_cores = cpu_count()
    print(f"\n{'='*75}")
    print(f"PARALLEL STRATEGY ANALYSIS")
    print(f"Using {num_cores} CPU cores for maximum speed!")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*75}")
    
    loader = DataLoader()
    
    # All strategies to test
    strategies = {
        # Batch 2 - Underrated
        'ascending_triangle': {},
        'stochrsi_macd': {},
        'gmma': {},
        'cci_divergence': {},
        'tdi': {},
        'adx_dmi_obv': {},
        'ma_envelopes': {},
        'momentum_zero': {},
        # Batch 1 - Original
        'ema_21_55': {},
        'rsi_divergence': {},
        'vwap_pullback': {},
        'bb_squeeze': {},
        'fib_3wave': {},
        'cpr': {},
        'chandelier_exit': {},
        'donchian_turtle': {},
        'hull_slope': {},
        'psar_ichimoku': {},
    }
    
    # Get symbols for each timeframe
    timeframes = ['daily', 'hourly', 'minute']
    symbols_by_tf = {}
    for tf in timeframes:
        try:
            symbols_by_tf[tf] = loader.get_available_symbols(tf)[:10]
        except:
            symbols_by_tf[tf] = []
    
    # ========================================
    # PHASE 1: Parallel Multi-Timeframe Testing
    # ========================================
    print(f"\n{'='*75}")
    print("PHASE 1: MULTI-TIMEFRAME ANALYSIS (PARALLEL)")
    print(f"{'='*75}")
    
    all_results = {}
    
    for tf in timeframes:
        symbols = symbols_by_tf.get(tf, [])
        if not symbols:
            print(f"\n{tf.upper()}: No data available")
            continue
        
        print(f"\n{tf.upper()}: Testing {len(strategies)} strategies x {len(symbols)} stocks = {len(strategies) * len(symbols)} backtests")
        
        # Create all task combinations
        tasks = []
        for strat_key, params in strategies.items():
            for symbol in symbols:
                tasks.append((strat_key, symbol, tf, params))
        
        # Run in parallel
        tf_start = time.time()
        with Pool(processes=num_cores) as pool:
            results = pool.map(run_single_backtest, tasks)
        
        # Filter None results
        valid_results = [r for r in results if r is not None]
        tf_time = time.time() - tf_start
        
        print(f"  Completed in {tf_time:.1f}s ({len(valid_results)} valid results)")
        
        # Aggregate by strategy
        aggregated = aggregate_results(valid_results, 'strategy')
        all_results[tf] = aggregated
        
        # Print results
        print_results(aggregated, f"{tf.upper()} RESULTS (by Sharpe)")
    
    # ========================================
    # PHASE 2: Parallel Parameter Optimization
    # ========================================
    print(f"\n{'='*75}")
    print("PHASE 2: PARAMETER OPTIMIZATION (PARALLEL)")
    print(f"{'='*75}")
    
    optimization_configs = {
        'ascending_triangle': [
            {'lookback': 15, 'breakout_threshold': 0.005},
            {'lookback': 20, 'breakout_threshold': 0.01},
            {'lookback': 25, 'breakout_threshold': 0.008},
            {'lookback': 30, 'breakout_threshold': 0.015},
        ],
        'stochrsi_macd': [
            {'stoch_period': 10, 'rsi_period': 12},
            {'stoch_period': 14, 'rsi_period': 14},
            {'stoch_period': 21, 'rsi_period': 21},
            {'stoch_period': 7, 'rsi_period': 7},
        ],
        'gmma': [
            {},
            {'trend_strength_threshold': 0.01},
            {'trend_strength_threshold': 0.02},
        ],
    }
    
    symbols = symbols_by_tf.get('daily', [])[:5]
    
    for strat_key, param_sets in optimization_configs.items():
        print(f"\nOptimizing {strat_key}...")
        
        # Create tasks for all param combinations
        tasks = []
        for params in param_sets:
            for symbol in symbols:
                tasks.append((strat_key, symbol, 'daily', params))
        
        # Run in parallel
        with Pool(processes=num_cores) as pool:
            results = pool.map(run_single_backtest, tasks)
        
        # Find best params
        valid_results = [r for r in results if r is not None]
        if valid_results:
            # Group by params (using string representation)
            param_sharpes = {}
            for i, params in enumerate(param_sets):
                param_key = str(params)
                param_results = [r for j, r in enumerate(results) if r is not None and j // len(symbols) == i]
                if param_results:
                    param_sharpes[param_key] = np.mean([r['sharpe'] for r in param_results])
            
            if param_sharpes:
                best_param_key = max(param_sharpes, key=param_sharpes.get)
                print(f"  Best params: {best_param_key}")
                print(f"  Best Sharpe: {param_sharpes[best_param_key]:.3f}")
    
    # ========================================
    # PHASE 3: Parallel Combined Strategies
    # ========================================
    print(f"\n{'='*75}")
    print("PHASE 3: COMBINED STRATEGIES (PARALLEL)")
    print(f"{'='*75}")
    
    # Combined configs: (name, strategy_keys, method)
    combined_configs = [
        ('TopPerformers_Majority', ['ascending_triangle', 'stochrsi_macd', 'gmma'], 'majority'),
        ('Momentum_TwoOfThree', ['stochrsi_macd', 'tdi', 'momentum_zero'], 'two_of_three'),
        ('Conservative_Unanimous', ['ascending_triangle', 'stochrsi_macd', 'gmma'], 'unanimous'),
        ('Trend_Volume', ['ema_21_55', 'adx_dmi_obv', 'hull_slope'], 'majority'),
        ('AllStars_Majority', ['ascending_triangle', 'stochrsi_macd', 'gmma', 'ema_21_55', 'fib_3wave'], 'majority'),
    ]
    
    symbols = symbols_by_tf.get('daily', [])[:10]
    
    # Create tasks
    combo_tasks = []
    for combo_name, strat_keys, method in combined_configs:
        for symbol in symbols:
            combo_tasks.append((combo_name, strat_keys, method, symbol))
    
    print(f"Testing {len(combined_configs)} combined strategies x {len(symbols)} stocks = {len(combo_tasks)} backtests")
    
    # Run in parallel
    combo_start = time.time()
    with Pool(processes=num_cores) as pool:
        combo_results = pool.map(run_combined_backtest, combo_tasks)
    
    valid_combo_results = [r for r in combo_results if r is not None]
    combo_time = time.time() - combo_start
    print(f"Completed in {combo_time:.1f}s ({len(valid_combo_results)} valid results)")
    
    # Aggregate
    combo_aggregated = aggregate_results(valid_combo_results, 'strategy')
    print_results(combo_aggregated, "COMBINED STRATEGY RESULTS")
    
    # ========================================
    # FINAL SUMMARY
    # ========================================
    print(f"\n{'='*75}")
    print("FINAL SUMMARY - BEST STRATEGIES")
    print(f"{'='*75}")
    
    for tf in timeframes:
        if tf in all_results and all_results[tf]:
            best = max(all_results[tf].items(), key=lambda x: x[1]['sharpe'])
            print(f"\n{tf.upper():>10}: {best[0]:<25} (Sharpe: {best[1]['sharpe']:.2f}, Return: {best[1]['return']:.2f}%)")
    
    if combo_aggregated:
        best_combo = max(combo_aggregated.items(), key=lambda x: x[1]['sharpe'])
        print(f"\n{'COMBINED':>10}: {best_combo[0]:<25} (Sharpe: {best_combo[1]['sharpe']:.2f}, Return: {best_combo[1]['return']:.2f}%)")
    
    # Save results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    all_data = []
    for tf, results in all_results.items():
        for name, metrics in results.items():
            all_data.append({
                'timeframe': tf,
                'strategy': name,
                'type': 'individual',
                **metrics
            })
    
    for name, metrics in combo_aggregated.items():
        all_data.append({
            'timeframe': 'daily',
            'strategy': name,
            'type': 'combined',
            **metrics
        })
    
    if all_data:
        df_results = pd.DataFrame(all_data)
        csv_file = f'parallel_results_{timestamp}.csv'
        df_results.to_csv(csv_file, index=False)
        print(f"\nResults saved to {csv_file}")
    
    total_time = time.time() - start_time
    print(f"\n{'='*75}")
    print(f"ANALYSIS COMPLETE! Total time: {total_time:.1f} seconds")
    print(f"{'='*75}")


if __name__ == '__main__':
    main()
