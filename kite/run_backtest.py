"""
Main entry point for running backtests.

Usage:
    python run_backtest.py --strategy ema_21_55 --symbol RELIANCE --timeframe daily
    python run_backtest.py --all-strategies --symbol RELIANCE --timeframe daily
    python run_backtest.py --strategy bb_squeeze --all-stocks --timeframe daily
"""
import argparse
import sys
from pathlib import Path
from typing import List, Optional
from tqdm import tqdm

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from kite.utils.data_loader import DataLoader, load_stock_data
from kite.backtesting.engine import BacktestEngine, run_backtest
from kite.backtesting.performance import (
    generate_performance_report, 
    print_comparison_table,
    compare_results,
    export_results_json
)
from kite.utils.plotting import (
    plot_equity_curve,
    plot_drawdown,
    plot_trade_distribution,
    plot_comparison,
    create_full_report
)
from kite.config import NIFTY_50_STOCKS, trading_config

# Import all strategies
from kite.strategies.ema_21_55 import EMA2155Strategy
from kite.strategies.rsi_divergence import RSIDivergenceStrategy
from kite.strategies.vwap_pullback import VWAPPullbackStrategy
from kite.strategies.bb_squeeze import BBSqueezeStrategy
from kite.strategies.ema_3_scalping import EMA3ScalpingStrategy
from kite.strategies.supply_demand import SupplyDemandStrategy
from kite.strategies.stochastic_confluence import StochasticConfluenceStrategy
from kite.strategies.fib_3wave import Fib3WaveStrategy
from kite.strategies.multi_timeframe import MultiTimeframeStrategy


# Strategy registry
STRATEGIES = {
    'ema_21_55': EMA2155Strategy,
    'rsi_divergence': RSIDivergenceStrategy,
    'vwap_pullback': VWAPPullbackStrategy,
    'bb_squeeze': BBSqueezeStrategy,
    'ema_3_scalping': EMA3ScalpingStrategy,
    'supply_demand': SupplyDemandStrategy,
    'stochastic_confluence': StochasticConfluenceStrategy,
    'fib_3wave': Fib3WaveStrategy,
    'multi_timeframe': MultiTimeframeStrategy,
}


def run_single_backtest(strategy_name: str, symbol: str, 
                        timeframe: str = 'daily',
                        show_plots: bool = True,
                        save_report: bool = True):
    """
    Run backtest for a single strategy on a single symbol.
    
    Args:
        strategy_name: Name of the strategy
        symbol: Stock symbol
        timeframe: Data timeframe
        show_plots: Whether to show plots
        save_report: Whether to save report
    """
    print(f"\n{'='*60}")
    print(f"Running {strategy_name} on {symbol} ({timeframe})")
    print('='*60)
    
    # Load data
    try:
        df = load_stock_data(symbol, timeframe)
        print(f"Loaded {len(df)} bars from {df.index[0]} to {df.index[-1]}")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return None
    
    # Create strategy
    strategy_class = STRATEGIES.get(strategy_name)
    if not strategy_class:
        print(f"Error: Unknown strategy '{strategy_name}'")
        print(f"Available strategies: {list(STRATEGIES.keys())}")
        return None
    
    strategy = strategy_class()
    
    # Run backtest
    engine = BacktestEngine(
        initial_capital=trading_config.initial_capital,
        risk_per_trade=trading_config.risk_per_trade,
        allow_short=trading_config.allow_short
    )
    
    result = engine.run(strategy, df, symbol)
    
    # Print report
    print(generate_performance_report(result))
    
    # Show plots
    if show_plots:
        try:
            plot_equity_curve(result, show=True)
            plot_drawdown(result, show=True)
            plot_trade_distribution(result, show=True)
        except Exception as e:
            print(f"Could not show plots: {e}")
    
    # Save report
    if save_report:
        reports_dir = Path(__file__).parent / 'reports'
        reports_dir.mkdir(exist_ok=True)
        
        # Save JSON
        json_path = reports_dir / f"{strategy_name}_{symbol}_{timeframe}.json"
        export_results_json(result, str(json_path))
        print(f"\nReport saved to {json_path}")
    
    return result


def run_all_strategies(symbol: str, timeframe: str = 'daily',
                       show_plots: bool = True):
    """
    Run all strategies on a single symbol and compare.
    
    Args:
        symbol: Stock symbol
        timeframe: Data timeframe
        show_plots: Whether to show comparison plots
    """
    print(f"\n{'='*60}")
    print(f"Running ALL strategies on {symbol} ({timeframe})")
    print('='*60)
    
    # Load data once
    try:
        df = load_stock_data(symbol, timeframe)
        print(f"Loaded {len(df)} bars from {df.index[0]} to {df.index[-1]}")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return []
    
    results = []
    
    for strategy_name, strategy_class in tqdm(STRATEGIES.items(), desc="Strategies"):
        try:
            strategy = strategy_class()
            engine = BacktestEngine(
                initial_capital=trading_config.initial_capital,
                risk_per_trade=trading_config.risk_per_trade,
                allow_short=trading_config.allow_short
            )
            result = engine.run(strategy, df, symbol)
            results.append(result)
        except Exception as e:
            print(f"\nError running {strategy_name}: {e}")
    
    # Print comparison
    if results:
        print_comparison_table(results)
        
        # Save comparison
        comparison_df = compare_results(results)
        reports_dir = Path(__file__).parent / 'reports'
        reports_dir.mkdir(exist_ok=True)
        comparison_df.to_csv(reports_dir / f"comparison_{symbol}_{timeframe}.csv", index=False)
        
        if show_plots:
            try:
                plot_comparison(results, show=True)
            except Exception as e:
                print(f"Could not show comparison plot: {e}")
    
    return results


def run_strategy_on_all_stocks(strategy_name: str, timeframe: str = 'daily',
                               symbols: Optional[List[str]] = None):
    """
    Run a single strategy on all NIFTY 50 stocks.
    
    Args:
        strategy_name: Name of the strategy
        timeframe: Data timeframe
        symbols: List of symbols (defaults to NIFTY 50)
    """
    symbols = symbols or NIFTY_50_STOCKS
    
    print(f"\n{'='*60}")
    print(f"Running {strategy_name} on {len(symbols)} stocks ({timeframe})")
    print('='*60)
    
    strategy_class = STRATEGIES.get(strategy_name)
    if not strategy_class:
        print(f"Error: Unknown strategy '{strategy_name}'")
        return []
    
    loader = DataLoader()
    results = []
    
    for symbol in tqdm(symbols, desc="Stocks"):
        try:
            df = loader.load_stock(symbol, timeframe)
            strategy = strategy_class()
            engine = BacktestEngine(
                initial_capital=trading_config.initial_capital,
                risk_per_trade=trading_config.risk_per_trade,
                allow_short=trading_config.allow_short
            )
            result = engine.run(strategy, df, symbol)
            results.append(result)
        except Exception as e:
            # Silently skip errors
            pass
    
    # Print summary
    if results:
        print(f"\n{'='*60}")
        print(f"SUMMARY: {strategy_name} across {len(results)} stocks")
        print('='*60)
        
        # Aggregate stats
        total_return = sum(r.total_return_pct for r in results) / len(results)
        avg_win_rate = sum(r.win_rate for r in results) / len(results)
        avg_sharpe = sum(r.sharpe_ratio for r in results) / len(results)
        
        print(f"Average Return: {total_return:.2f}%")
        print(f"Average Win Rate: {avg_win_rate:.2f}%")
        print(f"Average Sharpe: {avg_sharpe:.2f}")
        
        # Best and worst
        best = max(results, key=lambda r: r.total_return_pct)
        worst = min(results, key=lambda r: r.total_return_pct)
        
        print(f"\nBest: {best.symbol} ({best.total_return_pct:.2f}%)")
        print(f"Worst: {worst.symbol} ({worst.total_return_pct:.2f}%)")
    
    return results


def main():
    parser = argparse.ArgumentParser(description='Run trading strategy backtests')
    
    parser.add_argument('--strategy', type=str, 
                        help=f'Strategy name. Options: {list(STRATEGIES.keys())}')
    parser.add_argument('--symbol', type=str, default='RELIANCE',
                        help='Stock symbol (default: RELIANCE)')
    parser.add_argument('--timeframe', type=str, default='daily',
                        choices=['minute', 'hourly', 'daily'],
                        help='Data timeframe (default: daily)')
    parser.add_argument('--all-strategies', action='store_true',
                        help='Run all strategies on the symbol')
    parser.add_argument('--all-stocks', action='store_true',
                        help='Run strategy on all NIFTY 50 stocks')
    parser.add_argument('--no-plots', action='store_true',
                        help='Disable plot display')
    parser.add_argument('--list-strategies', action='store_true',
                        help='List available strategies')
    
    args = parser.parse_args()
    
    if args.list_strategies:
        print("\nAvailable Strategies:")
        print("-" * 40)
        for name in STRATEGIES.keys():
            print(f"  - {name}")
        return
    
    show_plots = not args.no_plots
    
    if args.all_strategies:
        run_all_strategies(args.symbol, args.timeframe, show_plots)
    elif args.all_stocks:
        if not args.strategy:
            print("Error: --strategy required with --all-stocks")
            return
        run_strategy_on_all_stocks(args.strategy, args.timeframe)
    elif args.strategy:
        run_single_backtest(args.strategy, args.symbol, args.timeframe, show_plots)
    else:
        # Default: run all strategies on default symbol
        print("No strategy specified. Running all strategies on RELIANCE...")
        run_all_strategies('RELIANCE', args.timeframe, show_plots)


if __name__ == '__main__':
    main()
