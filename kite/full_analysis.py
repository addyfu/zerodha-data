"""
Full Strategy Analysis - All timeframes, optimization, and combined strategies
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from typing import Dict, List, Any
from tqdm import tqdm
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

from kite.utils.data_loader import DataLoader
from kite.backtesting.engine import BacktestEngine
from kite.strategies import STRATEGY_REGISTRY
from kite.strategies.combined_strategy import CombinedStrategy


def run_single_backtest(strategy_class, df: pd.DataFrame, params: Dict = None, symbol: str = "UNKNOWN") -> Dict:
    """Run a single backtest and return metrics."""
    try:
        strategy = strategy_class(params or {})
        engine = BacktestEngine()
        result = engine.run(strategy, df, symbol)
        
        if result and result.total_trades > 0:
            return {
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


def test_strategies_on_timeframe(loader: DataLoader, strategies: Dict, timeframe: str, num_stocks: int = 10):
    """Test all strategies on a specific timeframe."""
    print(f"\n{'='*70}")
    print(f"TESTING ON {timeframe.upper()} DATA")
    print(f"{'='*70}")
    
    try:
        symbols = loader.get_available_symbols(timeframe)[:num_stocks]
    except Exception as e:
        print(f"Error getting symbols: {e}")
        return {}
    
    if not symbols:
        print("No symbols found!")
        return {}
    
    print(f"Testing {len(strategies)} strategies on {len(symbols)} stocks")
    print(f"Stocks: {', '.join(symbols[:5])}...")
    
    results = {}
    
    for strat_name, strat_key in tqdm(strategies.items(), desc="Strategies"):
        if strat_key not in STRATEGY_REGISTRY:
            print(f"  {strat_key} not in registry!")
            continue
        
        strat_class = STRATEGY_REGISTRY[strat_key]
        strat_results = []
        
        for symbol in symbols:
            try:
                df = loader.load_stock(symbol, timeframe)
                if len(df) < 50:  # Need minimum data
                    continue
                
                metrics = run_single_backtest(strat_class, df, symbol=symbol)
                if metrics:
                    strat_results.append(metrics)
            except Exception as e:
                continue
        
        if strat_results:
            results[strat_name] = {
                'sharpe': np.mean([r['sharpe'] for r in strat_results]),
                'return': np.mean([r['return'] for r in strat_results]),
                'win_rate': np.mean([r['win_rate'] for r in strat_results]),
                'trades': np.mean([r['trades'] for r in strat_results]),
                'max_dd': np.mean([r['max_dd'] for r in strat_results]),
                'profit_factor': np.mean([r['profit_factor'] for r in strat_results]),
                'stocks_tested': len(strat_results),
            }
    
    # Print results
    if results:
        print(f"\n{'-'*70}")
        print(f"{timeframe.upper()} RESULTS (sorted by Sharpe)")
        print(f"{'-'*70}")
        print(f"{'Rank':<5} {'Strategy':<22} {'Sharpe':>8} {'Return%':>10} {'Win%':>8} {'Trades':>8} {'MaxDD%':>10}")
        print("-"*75)
        
        sorted_results = sorted(results.items(), key=lambda x: x[1]['sharpe'], reverse=True)
        for rank, (name, m) in enumerate(sorted_results, 1):
            print(f"{rank:<5} {name:<22} {m['sharpe']:>8.2f} {m['return']:>10.2f} {m['win_rate']:>8.1f} {m['trades']:>8.0f} {m['max_dd']:>10.2f}")
    else:
        print("No results generated!")
    
    return results


def optimize_strategy(loader: DataLoader, strat_key: str, param_sets: List[Dict], num_stocks: int = 5):
    """Optimize a strategy's parameters."""
    if strat_key not in STRATEGY_REGISTRY:
        return None
    
    strat_class = STRATEGY_REGISTRY[strat_key]
    symbols = loader.get_available_symbols('daily')[:num_stocks]
    
    best_params = None
    best_sharpe = -999
    
    for params in param_sets:
        sharpes = []
        for symbol in symbols:
            try:
                df = loader.load_stock(symbol, 'daily')
                if len(df) < 200:
                    continue
                metrics = run_single_backtest(strat_class, df, params, symbol)
                if metrics:
                    sharpes.append(metrics['sharpe'])
            except:
                continue
        
        if sharpes:
            avg_sharpe = np.mean(sharpes)
            if avg_sharpe > best_sharpe:
                best_sharpe = avg_sharpe
                best_params = params
    
    return {'params': best_params, 'sharpe': best_sharpe}


def test_combined_strategy(loader: DataLoader, config: Dict, num_stocks: int = 10):
    """Test a combined strategy."""
    symbols = loader.get_available_symbols('daily')[:num_stocks]
    results = []
    
    for symbol in symbols:
        try:
            df = loader.load_stock(symbol, 'daily')
            if len(df) < 200:
                continue
            
            combo = CombinedStrategy(config)
            engine = BacktestEngine()
            result = engine.run(combo, df, symbol)
            
            if result and result.total_trades > 0:
                results.append({
                    'sharpe': result.sharpe_ratio,
                    'return': result.total_return_pct,
                    'win_rate': result.win_rate,
                    'trades': result.total_trades,
                    'max_dd': result.max_drawdown_pct,
                    'profit_factor': result.profit_factor,
                })
        except Exception as e:
            continue
    
    if results:
        return {
            'sharpe': np.mean([r['sharpe'] for r in results]),
            'return': np.mean([r['return'] for r in results]),
            'win_rate': np.mean([r['win_rate'] for r in results]),
            'trades': np.mean([r['trades'] for r in results]),
            'max_dd': np.mean([r['max_dd'] for r in results]),
            'profit_factor': np.mean([r['profit_factor'] for r in results]),
        }
    return None


def main():
    print("\n" + "="*70)
    print("COMPREHENSIVE STRATEGY ANALYSIS")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    
    loader = DataLoader()
    
    # All strategies to test
    all_strategies = {
        # Batch 2 - Underrated
        'Ascending_Triangle': 'ascending_triangle',
        'StochRSI_MACD': 'stochrsi_macd',
        'GMMA': 'gmma',
        'CCI_Divergence': 'cci_divergence',
        'TDI': 'tdi',
        'ADX_DMI_OBV': 'adx_dmi_obv',
        'MA_Envelopes': 'ma_envelopes',
        'Momentum_Zero': 'momentum_zero',
        # Batch 1 - Original
        'EMA_21_55': 'ema_21_55',
        'RSI_Divergence': 'rsi_divergence',
        'VWAP_Pullback': 'vwap_pullback',
        'BB_Squeeze': 'bb_squeeze',
        'Fib_3Wave': 'fib_3wave',
        # More from Batch 1
        'CPR': 'cpr',
        'Chandelier_Exit': 'chandelier_exit',
        'Donchian_Turtle': 'donchian_turtle',
        'Hull_Slope': 'hull_slope',
        'PSAR_Ichimoku': 'psar_ichimoku',
    }
    
    all_results = {}
    
    # ========================================
    # PHASE 1: Multi-Timeframe Testing
    # ========================================
    print("\n" + "="*70)
    print("PHASE 1: MULTI-TIMEFRAME ANALYSIS")
    print("="*70)
    
    for tf in ['daily', 'hourly', 'minute']:
        tf_results = test_strategies_on_timeframe(loader, all_strategies, tf, num_stocks=10)
        all_results[tf] = tf_results
    
    # ========================================
    # PHASE 2: Parameter Optimization
    # ========================================
    print("\n" + "="*70)
    print("PHASE 2: PARAMETER OPTIMIZATION (Top 3 Strategies)")
    print("="*70)
    
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
            {},  # Default
            {'trend_strength_threshold': 0.01},
            {'trend_strength_threshold': 0.02},
        ],
    }
    
    opt_results = {}
    for strat_key, param_sets in optimization_configs.items():
        print(f"\nOptimizing {strat_key}...")
        result = optimize_strategy(loader, strat_key, param_sets, num_stocks=5)
        if result and result['params']:
            opt_results[strat_key] = result
            print(f"  Best params: {result['params']}")
            print(f"  Best Sharpe: {result['sharpe']:.3f}")
        else:
            print(f"  No improvement found")
    
    # ========================================
    # PHASE 3: Combined Strategies
    # ========================================
    print("\n" + "="*70)
    print("PHASE 3: COMBINED MULTI-STRATEGY SYSTEMS")
    print("="*70)
    
    combined_configs = {
        'TopPerformers_Majority': {
            'strategies': [
                {'name': 'ascending_triangle', 'params': {}},
                {'name': 'stochrsi_macd', 'params': {}},
                {'name': 'gmma', 'params': {}},
            ],
            'combination_method': 'majority',
            'min_signals_for_majority': 2,
        },
        'Momentum_Any': {
            'strategies': [
                {'name': 'stochrsi_macd', 'params': {}},
                {'name': 'tdi', 'params': {}},
                {'name': 'momentum_zero', 'params': {}},
            ],
            'combination_method': 'any',
        },
        'Conservative_All': {
            'strategies': [
                {'name': 'ascending_triangle', 'params': {}},
                {'name': 'stochrsi_macd', 'params': {}},
                {'name': 'gmma', 'params': {}},
            ],
            'combination_method': 'all',
        },
        'Trend_Volume': {
            'strategies': [
                {'name': 'ema_21_55', 'params': {}},
                {'name': 'adx_dmi_obv', 'params': {}},
                {'name': 'hull_slope', 'params': {}},
            ],
            'combination_method': 'majority',
            'min_signals_for_majority': 2,
        },
        'AllStars_Majority': {
            'strategies': [
                {'name': 'ascending_triangle', 'params': {}},
                {'name': 'stochrsi_macd', 'params': {}},
                {'name': 'gmma', 'params': {}},
                {'name': 'ema_21_55', 'params': {}},
                {'name': 'bb_squeeze', 'params': {}},
            ],
            'combination_method': 'majority',
            'min_signals_for_majority': 3,
        },
    }
    
    combo_results = {}
    for combo_name, config in tqdm(combined_configs.items(), desc="Combined"):
        result = test_combined_strategy(loader, config, num_stocks=10)
        if result:
            combo_results[combo_name] = result
    
    if combo_results:
        print(f"\n{'-'*70}")
        print("COMBINED STRATEGY RESULTS")
        print(f"{'-'*70}")
        print(f"{'Strategy':<25} {'Sharpe':>8} {'Return%':>10} {'Win%':>8} {'Trades':>8} {'PF':>8}")
        print("-"*70)
        
        sorted_combos = sorted(combo_results.items(), key=lambda x: x[1]['sharpe'], reverse=True)
        for name, m in sorted_combos:
            print(f"{name:<25} {m['sharpe']:>8.2f} {m['return']:>10.2f} {m['win_rate']:>8.1f} {m['trades']:>8.0f} {m['profit_factor']:>8.2f}")
    
    # ========================================
    # FINAL SUMMARY
    # ========================================
    print("\n" + "="*70)
    print("FINAL SUMMARY - BEST STRATEGIES BY TIMEFRAME")
    print("="*70)
    
    for tf in ['daily', 'hourly', 'minute']:
        if tf in all_results and all_results[tf]:
            best = max(all_results[tf].items(), key=lambda x: x[1]['sharpe'])
            print(f"\n{tf.upper():>10}: {best[0]:<25} (Sharpe: {best[1]['sharpe']:.2f}, Return: {best[1]['return']:.2f}%)")
    
    if combo_results:
        best_combo = max(combo_results.items(), key=lambda x: x[1]['sharpe'])
        print(f"\n{'COMBINED':>10}: {best_combo[0]:<25} (Sharpe: {best_combo[1]['sharpe']:.2f}, Return: {best_combo[1]['return']:.2f}%)")
    
    # Save results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Combine all results for CSV
    all_data = []
    for tf, results in all_results.items():
        for name, metrics in results.items():
            all_data.append({
                'timeframe': tf,
                'strategy': name,
                'type': 'individual',
                **metrics
            })
    
    for name, metrics in combo_results.items():
        all_data.append({
            'timeframe': 'daily',
            'strategy': name,
            'type': 'combined',
            **metrics
        })
    
    if all_data:
        df_results = pd.DataFrame(all_data)
        csv_file = f'full_analysis_{timestamp}.csv'
        df_results.to_csv(csv_file, index=False)
        print(f"\nResults saved to {csv_file}")
    
    print("\n" + "="*70)
    print("ANALYSIS COMPLETE!")
    print("="*70)


if __name__ == '__main__':
    main()
