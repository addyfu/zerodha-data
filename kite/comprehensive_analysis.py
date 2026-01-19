"""
Comprehensive Strategy Analysis
- Run strategies on all timeframes (daily, hourly, minute)
- Optimize parameters for top performers
- Create combined multi-strategy systems
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Tuple
from tqdm import tqdm
import argparse
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

from kite.utils.data_loader import DataLoader
from kite.backtesting.engine import BacktestEngine, BacktestResult

# Import all strategies
from kite.strategies import STRATEGY_REGISTRY
from kite.strategies.combined_strategy import (
    CombinedStrategy, CombinationMethod,
    create_trend_momentum_combo, create_volume_price_combo,
    create_breakout_combo, create_best_performers_combo
)

# Batch 2 strategies for optimization (using registry keys)
BATCH2_STRATEGIES = {
    'Ascending_Triangle': 'ascending_triangle',
    'StochRSI_MACD': 'stochrsi_macd', 
    'GMMA': 'gmma',
    'CCI_Divergence': 'cci_divergence',
    'TDI': 'tdi',
    'ADX_DMI_OBV': 'adx_dmi_obv',
    'MA_Envelopes': 'ma_envelopes',
    'Momentum_Zero': 'momentum_zero',
}

# Parameter optimization ranges (using registry keys)
OPTIMIZATION_PARAMS = {
    'ascending_triangle': [
        {'lookback': 15, 'breakout_threshold': 0.005, 'volume_mult': 1.3},
        {'lookback': 20, 'breakout_threshold': 0.01, 'volume_mult': 1.5},
        {'lookback': 25, 'breakout_threshold': 0.008, 'volume_mult': 1.2},
        {'lookback': 30, 'breakout_threshold': 0.015, 'volume_mult': 2.0},
    ],
    'stochrsi_macd': [
        {'stoch_period': 10, 'rsi_period': 12, 'macd_fast': 10, 'macd_slow': 22},
        {'stoch_period': 14, 'rsi_period': 14, 'macd_fast': 12, 'macd_slow': 26},
        {'stoch_period': 21, 'rsi_period': 21, 'macd_fast': 8, 'macd_slow': 21},
        {'stoch_period': 7, 'rsi_period': 7, 'macd_fast': 5, 'macd_slow': 13},
    ],
    'gmma': [
        {'short_periods': [3, 5, 8, 10, 12, 15], 'long_periods': [30, 35, 40, 45, 50, 60]},
        {'short_periods': [2, 4, 6, 8, 10, 12], 'long_periods': [25, 30, 35, 40, 45, 50]},
        {'short_periods': [5, 8, 13, 21, 34, 55], 'long_periods': [55, 89, 144, 233, 377, 610]},  # Fibonacci
    ],
}


def run_backtest(strategy_class, df: pd.DataFrame, params: Dict = None) -> Dict:
    """Run backtest and return metrics."""
    try:
        strategy = strategy_class(params or {})
        engine = BacktestEngine(strategy)
        result = engine.run(df)
        
        if result and result.total_trades > 0:
            return {
                'total_return': result.total_return_pct,
                'sharpe': result.sharpe_ratio,
                'win_rate': result.win_rate,
                'max_dd': result.max_drawdown_pct,
                'trades': result.total_trades,
                'profit_factor': result.profit_factor,
                'avg_profit': result.avg_trade / result.initial_capital * 100 if result.avg_trade else 0,
            }
    except Exception as e:
        pass
    
    return {
        'total_return': 0, 'sharpe': 0, 'win_rate': 0,
        'max_dd': 0, 'trades': 0, 'profit_factor': 0, 'avg_profit': 0
    }


def analyze_timeframes(loader: DataLoader, strategies: Dict, num_stocks: int = 10):
    """Run strategies across all timeframes."""
    print("\n" + "="*70)
    print("PHASE 1: MULTI-TIMEFRAME ANALYSIS")
    print("="*70)
    
    timeframes = ['daily', 'hourly', 'minute']
    results = {tf: {} for tf in timeframes}
    
    for tf in timeframes:
        print(f"\n--- Testing on {tf.upper()} data ---")
        
        try:
            symbols = loader.get_available_symbols(tf)[:num_stocks]
        except:
            print(f"  No {tf} data available")
            continue
            
        if not symbols:
            print(f"  No symbols found for {tf}")
            continue
            
        print(f"  Testing {len(symbols)} stocks: {', '.join(symbols[:5])}...")
        
        for strat_name, strat_class_name in tqdm(strategies.items(), desc=f"  {tf}"):
            if strat_class_name not in STRATEGY_REGISTRY:
                continue
                
            strat_class = STRATEGY_REGISTRY[strat_class_name]
            strat_results = []
            
            for symbol in symbols:
                try:
                    df = loader.load_stock(symbol, tf)
                    if len(df) < 100:
                        continue
                    metrics = run_backtest(strat_class, df)
                    if metrics['trades'] > 0:
                        strat_results.append(metrics)
                except Exception as e:
                    continue
            
            if strat_results:
                avg_metrics = {
                    'sharpe': np.mean([r['sharpe'] for r in strat_results]),
                    'return': np.mean([r['total_return'] for r in strat_results]),
                    'win_rate': np.mean([r['win_rate'] for r in strat_results]),
                    'trades': np.mean([r['trades'] for r in strat_results]),
                    'max_dd': np.mean([r['max_dd'] for r in strat_results]),
                    'profit_factor': np.mean([r['profit_factor'] for r in strat_results]),
                }
                results[tf][strat_name] = avg_metrics
    
    # Print results
    print("\n" + "-"*70)
    print("MULTI-TIMEFRAME RESULTS SUMMARY")
    print("-"*70)
    
    for tf in timeframes:
        if not results[tf]:
            continue
        print(f"\n{tf.upper()} TIMEFRAME:")
        print(f"{'Strategy':<25} {'Sharpe':>8} {'Return%':>10} {'WinRate%':>10} {'Trades':>8}")
        print("-"*65)
        
        sorted_strats = sorted(results[tf].items(), key=lambda x: x[1]['sharpe'], reverse=True)
        for strat_name, metrics in sorted_strats[:10]:
            print(f"{strat_name:<25} {metrics['sharpe']:>8.2f} {metrics['return']:>10.2f} "
                  f"{metrics['win_rate']:>10.1f} {metrics['trades']:>8.0f}")
    
    return results


def optimize_parameters(loader: DataLoader, num_stocks: int = 5):
    """Optimize parameters for top strategies."""
    print("\n" + "="*70)
    print("PHASE 2: PARAMETER OPTIMIZATION")
    print("="*70)
    
    symbols = loader.get_available_symbols('daily')[:num_stocks]
    optimization_results = {}
    
    for strat_class_name, param_sets in OPTIMIZATION_PARAMS.items():
        if strat_class_name not in STRATEGY_REGISTRY:
            continue
            
        strat_class = STRATEGY_REGISTRY[strat_class_name]
        print(f"\nOptimizing {strat_class_name}...")
        
        best_params = None
        best_sharpe = -999
        
        for params in tqdm(param_sets, desc="  Params"):
            param_results = []
            
            for symbol in symbols:
                try:
                    df = loader.load_stock(symbol, 'daily')
                    if len(df) < 200:
                        continue
                    metrics = run_backtest(strat_class, df, params)
                    if metrics['trades'] > 0:
                        param_results.append(metrics['sharpe'])
                except:
                    continue
            
            if param_results:
                avg_sharpe = np.mean(param_results)
                if avg_sharpe > best_sharpe:
                    best_sharpe = avg_sharpe
                    best_params = params
        
        if best_params:
            optimization_results[strat_class_name] = {
                'best_params': best_params,
                'best_sharpe': best_sharpe
            }
            print(f"  Best params: {best_params}")
            print(f"  Best Sharpe: {best_sharpe:.3f}")
    
    return optimization_results


def create_optimized_strategies():
    """Create optimized versions of top strategies."""
    
    # Optimized Ascending Triangle
    class OptimizedAscendingTriangle:
        def __init__(self, params=None):
            from kite.strategies.ascending_triangle import AscendingTriangleStrategy
            optimized_params = {
                'lookback': 20,
                'breakout_threshold': 0.01,
                'volume_mult': 1.5,
                'atr_mult': 1.5,
                'rr_ratio': 2.5
            }
            if params:
                optimized_params.update(params)
            self._strategy = AscendingTriangleStrategy(optimized_params)
        
        def generate_signals(self, df):
            return self._strategy.generate_signals(df)
        
        def calculate_stop_loss(self, df, idx, direction):
            return self._strategy.calculate_stop_loss(df, idx, direction)
        
        def calculate_take_profit(self, df, idx, direction, entry, sl):
            return self._strategy.calculate_take_profit(df, idx, direction, entry, sl)
    
    # Optimized StochRSI MACD
    class OptimizedStochRSIMACD:
        def __init__(self, params=None):
            from kite.strategies.stochrsi_macd import StochRSIMACDStrategy
            optimized_params = {
                'stoch_period': 14,
                'rsi_period': 14,
                'macd_fast': 12,
                'macd_slow': 26,
                'macd_signal': 9,
                'oversold': 20,
                'overbought': 80,
                'atr_mult': 1.5,
                'rr_ratio': 2.0
            }
            if params:
                optimized_params.update(params)
            self._strategy = StochRSIMACDStrategy(optimized_params)
        
        def generate_signals(self, df):
            return self._strategy.generate_signals(df)
        
        def calculate_stop_loss(self, df, idx, direction):
            return self._strategy.calculate_stop_loss(df, idx, direction)
        
        def calculate_take_profit(self, df, idx, direction, entry, sl):
            return self._strategy.calculate_take_profit(df, idx, direction, entry, sl)
    
    return {
        'Optimized_AscTriangle': OptimizedAscendingTriangle,
        'Optimized_StochRSIMACD': OptimizedStochRSIMACD,
    }


def create_combined_strategies():
    """Create combined multi-strategy systems."""
    print("\n" + "="*70)
    print("PHASE 3: COMBINED STRATEGY SYSTEMS")
    print("="*70)
    
    combined_configs = {
        'TopPerformers_Combo': {
            'strategies': [
                {'name': 'ascending_triangle', 'params': {}},
                {'name': 'stochrsi_macd', 'params': {}},
                {'name': 'gmma', 'params': {}},
            ],
            'combination_method': 'majority',
            'min_signals_for_majority': 2,
        },
        'MomentumTrend_Combo': {
            'strategies': [
                {'name': 'stochrsi_macd', 'params': {}},
                {'name': 'tdi', 'params': {}},
                {'name': 'momentum_zero', 'params': {}},
            ],
            'combination_method': 'majority',
            'min_signals_for_majority': 2,
        },
        'PatternVolume_Combo': {
            'strategies': [
                {'name': 'ascending_triangle', 'params': {}},
                {'name': 'adx_dmi_obv', 'params': {}},
                {'name': 'cci_divergence', 'params': {}},
            ],
            'combination_method': 'any',
        },
        'Conservative_Combo': {
            'strategies': [
                {'name': 'ascending_triangle', 'params': {}},
                {'name': 'stochrsi_macd', 'params': {}},
                {'name': 'gmma', 'params': {}},
                {'name': 'cci_divergence', 'params': {}},
            ],
            'combination_method': 'all',  # All must agree - very conservative
        },
        'Aggressive_Combo': {
            'strategies': [
                {'name': 'stochrsi_macd', 'params': {}},
                {'name': 'tdi', 'params': {}},
                {'name': 'momentum_zero', 'params': {}},
                {'name': 'gmma', 'params': {}},
            ],
            'combination_method': 'any',  # Any signal triggers - aggressive
        },
    }
    
    return combined_configs


def test_combined_strategies(loader: DataLoader, combined_configs: Dict, num_stocks: int = 10):
    """Test combined strategies."""
    print("\nTesting combined strategies...")
    
    symbols = loader.get_available_symbols('daily')[:num_stocks]
    results = {}
    
    for combo_name, config in tqdm(combined_configs.items(), desc="Combined"):
        combo_results = []
        
        for symbol in symbols:
            try:
                df = loader.load_stock(symbol, 'daily')
                if len(df) < 200:
                    continue
                
                combo_strategy = CombinedStrategy(config)
                metrics = run_backtest(type(combo_strategy), df, config)
                
                if metrics['trades'] > 0:
                    combo_results.append(metrics)
            except Exception as e:
                continue
        
        if combo_results:
            results[combo_name] = {
                'sharpe': np.mean([r['sharpe'] for r in combo_results]),
                'return': np.mean([r['total_return'] for r in combo_results]),
                'win_rate': np.mean([r['win_rate'] for r in combo_results]),
                'trades': np.mean([r['trades'] for r in combo_results]),
                'max_dd': np.mean([r['max_dd'] for r in combo_results]),
                'profit_factor': np.mean([r['profit_factor'] for r in combo_results]),
            }
    
    return results


def run_final_comparison(loader: DataLoader, num_stocks: int = 10):
    """Run final comparison of all strategies including optimized and combined."""
    print("\n" + "="*70)
    print("PHASE 4: FINAL COMPREHENSIVE COMPARISON")
    print("="*70)
    
    symbols = loader.get_available_symbols('daily')[:num_stocks]
    
    # All strategies to test
    all_strategies = {}
    
    # Add Batch 2 strategies
    all_strategies.update(BATCH2_STRATEGIES)
    
    # Add some Batch 1 strategies for comparison
    batch1_strategies = {
        'EMA_21_55': 'ema_21_55',
        'RSI_Divergence': 'rsi_divergence',
        'VWAP_Pullback': 'vwap_pullback',
        'BB_Squeeze': 'bb_squeeze',
        'Fib_3Wave': 'fib_3wave',
    }
    all_strategies.update(batch1_strategies)
    
    results = {}
    
    print(f"\nTesting {len(all_strategies)} strategies on {len(symbols)} stocks...")
    
    for strat_name, strat_class_name in tqdm(all_strategies.items(), desc="Strategies"):
        if strat_class_name not in STRATEGY_REGISTRY:
            continue
            
        strat_class = STRATEGY_REGISTRY[strat_class_name]
        strat_results = []
        
        for symbol in symbols:
            try:
                df = loader.load_stock(symbol, 'daily')
                if len(df) < 200:
                    continue
                metrics = run_backtest(strat_class, df)
                if metrics['trades'] > 0:
                    strat_results.append(metrics)
            except:
                continue
        
        if strat_results:
            avg_sharpe = np.mean([r['sharpe'] for r in strat_results])
            avg_return = np.mean([r['total_return'] for r in strat_results])
            avg_win = np.mean([r['win_rate'] for r in strat_results])
            avg_trades = np.mean([r['trades'] for r in strat_results])
            results[strat_name] = {
                'sharpe': avg_sharpe,
                'return': avg_return,
                'win_rate': avg_win,
                'trades': avg_trades,
                'max_dd': np.mean([r['max_dd'] for r in strat_results]),
                'profit_factor': np.mean([r['profit_factor'] for r in strat_results]),
            }
    
    # Print final results
    print("\n" + "="*70)
    print("FINAL STRATEGY RANKINGS (by Sharpe Ratio)")
    print("="*70)
    print(f"\n{'Rank':<6} {'Strategy':<25} {'Sharpe':>8} {'Return%':>10} {'WinRate%':>10} {'MaxDD%':>10} {'PF':>8}")
    print("-"*80)
    
    sorted_results = sorted(results.items(), key=lambda x: x[1]['sharpe'], reverse=True)
    for rank, (strat_name, metrics) in enumerate(sorted_results, 1):
        marker = "#1" if rank == 1 else "#2" if rank == 2 else "#3" if rank == 3 else f"#{rank}"
        print(f"{marker:<6} {strat_name:<25} {metrics['sharpe']:>8.2f} {metrics['return']:>10.2f} "
              f"{metrics['win_rate']:>10.1f} {metrics['max_dd']:>10.2f} {metrics['profit_factor']:>8.2f}")
    
    return results


def main():
    parser = argparse.ArgumentParser(description='Comprehensive Strategy Analysis')
    parser.add_argument('--stocks', type=int, default=10, help='Number of stocks to test')
    parser.add_argument('--skip-timeframes', action='store_true', help='Skip multi-timeframe analysis')
    parser.add_argument('--skip-optimization', action='store_true', help='Skip parameter optimization')
    args = parser.parse_args()
    
    print("\n" + "="*70)
    print("COMPREHENSIVE STRATEGY ANALYSIS")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    
    loader = DataLoader()
    
    # Phase 1: Multi-timeframe analysis
    if not args.skip_timeframes:
        tf_results = analyze_timeframes(loader, BATCH2_STRATEGIES, args.stocks)
    
    # Phase 2: Parameter optimization
    if not args.skip_optimization:
        opt_results = optimize_parameters(loader, min(args.stocks, 5))
    
    # Phase 3: Combined strategies
    combined_configs = create_combined_strategies()
    combo_results = test_combined_strategies(loader, combined_configs, args.stocks)
    
    if combo_results:
        print("\n" + "-"*70)
        print("COMBINED STRATEGY RESULTS")
        print("-"*70)
        print(f"{'Strategy':<25} {'Sharpe':>8} {'Return%':>10} {'WinRate%':>10} {'Trades':>8}")
        print("-"*65)
        
        sorted_combos = sorted(combo_results.items(), key=lambda x: x[1]['sharpe'], reverse=True)
        for combo_name, metrics in sorted_combos:
            print(f"{combo_name:<25} {metrics['sharpe']:>8.2f} {metrics['return']:>10.2f} "
                  f"{metrics['win_rate']:>10.1f} {metrics['trades']:>8.0f}")
    
    # Phase 4: Final comparison
    final_results = run_final_comparison(loader, args.stocks)
    
    # Save results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Save to CSV
    if final_results:
        df_results = pd.DataFrame(final_results).T
        df_results.to_csv(f'comprehensive_results_{timestamp}.csv')
        print(f"\nResults saved to comprehensive_results_{timestamp}.csv")
    
    print("\n" + "="*70)
    print("ANALYSIS COMPLETE!")
    print("="*70)


if __name__ == '__main__':
    main()
