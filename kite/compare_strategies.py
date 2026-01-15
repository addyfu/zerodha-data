"""
Strategy Comparison Tool

Compare all strategies across multiple stocks and generate comprehensive reports.

Usage:
    python compare_strategies.py
    python compare_strategies.py --stocks RELIANCE TCS INFY
    python compare_strategies.py --output reports/full_comparison.csv
"""
import argparse
import sys
from pathlib import Path
from typing import List, Dict
import pandas as pd
from tqdm import tqdm
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from kite.utils.data_loader import DataLoader
from kite.backtesting.engine import BacktestEngine
from kite.backtesting.performance import (
    compare_results,
    print_comparison_table,
    generate_performance_report
)
from kite.utils.plotting import plot_comparison
from kite.config import NIFTY_50_STOCKS, trading_config

# Import all strategies - Original
from kite.strategies.ema_21_55 import EMA2155Strategy
from kite.strategies.rsi_divergence import RSIDivergenceStrategy
from kite.strategies.vwap_pullback import VWAPPullbackStrategy
from kite.strategies.bb_squeeze import BBSqueezeStrategy
from kite.strategies.ema_3_scalping import EMA3ScalpingStrategy
from kite.strategies.supply_demand import SupplyDemandStrategy
from kite.strategies.stochastic_confluence import StochasticConfluenceStrategy
from kite.strategies.fib_3wave import Fib3WaveStrategy
from kite.strategies.multi_timeframe import MultiTimeframeStrategy

# Import all strategies - New Underrated
from kite.strategies.cpr_strategy import CPRStrategy
from kite.strategies.chandelier_strategy import ChandelierExitStrategy
from kite.strategies.donchian_turtle import DonchianTurtleStrategy
from kite.strategies.vwma_sma_strategy import VWMASMAStrategy
from kite.strategies.hull_slope_strategy import HullSlopeStrategy
from kite.strategies.psar_ichimoku import PSARIchimokuStrategy
from kite.strategies.roc_ma_strategy import ROCMAStrategy
from kite.strategies.cmf_ichimoku import CMFIchimokuStrategy
from kite.strategies.alligator_strategy import AlligatorStrategy
from kite.strategies.fib_pivot_strategy import FibPivotStrategy


STRATEGIES = {
    # Original Strategies
    'EMA_21_55': EMA2155Strategy,
    'RSI_Divergence': RSIDivergenceStrategy,
    'VWAP_Pullback': VWAPPullbackStrategy,
    'BB_Squeeze': BBSqueezeStrategy,
    'EMA_3_Scalping': EMA3ScalpingStrategy,
    'Supply_Demand': SupplyDemandStrategy,
    'Stochastic_Confluence': StochasticConfluenceStrategy,
    'Fib_3Wave': Fib3WaveStrategy,
    'Multi_Timeframe': MultiTimeframeStrategy,
    # New Underrated Strategies
    'CPR': CPRStrategy,
    'Chandelier_Exit': ChandelierExitStrategy,
    'Donchian_Turtle': DonchianTurtleStrategy,
    'VWMA_SMA': VWMASMAStrategy,
    'Hull_Slope': HullSlopeStrategy,
    'PSAR_Ichimoku': PSARIchimokuStrategy,
    'ROC_MA': ROCMAStrategy,
    'CMF_Ichimoku': CMFIchimokuStrategy,
    'Alligator': AlligatorStrategy,
    'Fib_Pivot': FibPivotStrategy,
}


def run_comprehensive_comparison(symbols: List[str], 
                                 timeframe: str = 'daily') -> pd.DataFrame:
    """
    Run all strategies on all specified symbols.
    
    Args:
        symbols: List of stock symbols
        timeframe: Data timeframe
        
    Returns:
        DataFrame with all results
    """
    loader = DataLoader()
    all_results = []
    
    print(f"\n{'='*70}")
    print(f"COMPREHENSIVE STRATEGY COMPARISON")
    print(f"Stocks: {len(symbols)} | Strategies: {len(STRATEGIES)} | Timeframe: {timeframe}")
    print(f"{'='*70}\n")
    
    total_tests = len(symbols) * len(STRATEGIES)
    
    with tqdm(total=total_tests, desc="Running backtests") as pbar:
        for symbol in symbols:
            try:
                df = loader.load_stock(symbol, timeframe)
            except FileNotFoundError:
                pbar.update(len(STRATEGIES))
                continue
            
            for strategy_name, strategy_class in STRATEGIES.items():
                try:
                    strategy = strategy_class()
                    engine = BacktestEngine(
                        initial_capital=trading_config.initial_capital,
                        risk_per_trade=trading_config.risk_per_trade,
                        allow_short=trading_config.allow_short
                    )
                    result = engine.run(strategy, df, symbol)
                    
                    all_results.append({
                        'Symbol': symbol,
                        'Strategy': strategy_name,
                        'Return %': result.total_return_pct,
                        'Win Rate %': result.win_rate,
                        'Profit Factor': result.profit_factor,
                        'Sharpe': result.sharpe_ratio,
                        'Max DD %': result.max_drawdown_pct,
                        'Trades': result.total_trades,
                        'Avg Trade ₹': result.avg_trade,
                        'Total Charges ₹': result.total_charges,
                    })
                except Exception as e:
                    pass
                
                pbar.update(1)
    
    return pd.DataFrame(all_results)


def generate_summary_report(df: pd.DataFrame) -> str:
    """
    Generate a summary report from comparison results.
    
    Args:
        df: DataFrame with comparison results
        
    Returns:
        Formatted report string
    """
    report = []
    report.append("\n" + "=" * 80)
    report.append(f"{'STRATEGY COMPARISON SUMMARY':^80}")
    report.append("=" * 80 + "\n")
    
    # Overall best strategies (by average across stocks)
    strategy_avg = df.groupby('Strategy').agg({
        'Return %': 'mean',
        'Win Rate %': 'mean',
        'Sharpe': 'mean',
        'Max DD %': 'mean',
        'Trades': 'sum',
    }).round(2)
    
    strategy_avg = strategy_avg.sort_values('Sharpe', ascending=False)
    
    report.append("STRATEGY RANKINGS (by Average Sharpe Ratio)")
    report.append("-" * 80)
    report.append(f"{'Strategy':<25} {'Avg Return %':>12} {'Avg Win %':>10} {'Avg Sharpe':>12} {'Avg DD %':>10}")
    report.append("-" * 80)
    
    for idx, (strategy, row) in enumerate(strategy_avg.iterrows(), 1):
        medal = "#1" if idx == 1 else "#2" if idx == 2 else "#3" if idx == 3 else "  "
        report.append(f"{medal} {strategy:<22} {row['Return %']:>12.2f} {row['Win Rate %']:>10.1f} {row['Sharpe']:>12.2f} {row['Max DD %']:>10.2f}")
    
    report.append("")
    
    # Best strategy per stock
    report.append("\nBEST STRATEGY PER STOCK")
    report.append("-" * 80)
    
    for symbol in df['Symbol'].unique():
        symbol_data = df[df['Symbol'] == symbol]
        best = symbol_data.loc[symbol_data['Sharpe'].idxmax()]
        report.append(f"{symbol:<15} -> {best['Strategy']:<25} (Sharpe: {best['Sharpe']:.2f}, Return: {best['Return %']:.2f}%)")
    
    report.append("")
    
    # Overall statistics
    report.append("\nOVERALL STATISTICS")
    report.append("-" * 80)
    
    total_tests = len(df)
    profitable = len(df[df['Return %'] > 0])
    
    report.append(f"Total backtests run: {total_tests}")
    report.append(f"Profitable combinations: {profitable} ({profitable/total_tests*100:.1f}%)")
    report.append(f"Average return: {df['Return %'].mean():.2f}%")
    report.append(f"Best single result: {df.loc[df['Return %'].idxmax(), 'Symbol']} + {df.loc[df['Return %'].idxmax(), 'Strategy']} ({df['Return %'].max():.2f}%)")
    report.append(f"Worst single result: {df.loc[df['Return %'].idxmin(), 'Symbol']} + {df.loc[df['Return %'].idxmin(), 'Strategy']} ({df['Return %'].min():.2f}%)")
    
    report.append("\n" + "=" * 80)
    
    return "\n".join(report)


def main():
    parser = argparse.ArgumentParser(description='Compare all trading strategies')
    
    parser.add_argument('--stocks', nargs='+', 
                        help='Stock symbols to test (default: top 10 NIFTY 50)')
    parser.add_argument('--all-stocks', action='store_true',
                        help='Test on all NIFTY 50 stocks')
    parser.add_argument('--timeframe', type=str, default='daily',
                        choices=['minute', 'hourly', 'daily'],
                        help='Data timeframe (default: daily)')
    parser.add_argument('--output', type=str,
                        help='Output CSV file path')
    parser.add_argument('--no-plots', action='store_true',
                        help='Disable plot display')
    
    args = parser.parse_args()
    
    # Determine stocks to test
    if args.all_stocks:
        symbols = NIFTY_50_STOCKS
    elif args.stocks:
        symbols = args.stocks
    else:
        # Default: top 10 by market cap
        symbols = ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
                   'HINDUNILVR', 'SBIN', 'BHARTIARTL', 'KOTAKBANK', 'ITC']
    
    # Run comparison
    results_df = run_comprehensive_comparison(symbols, args.timeframe)
    
    if results_df.empty:
        print("No results generated. Check if data files exist.")
        return
    
    # Generate and print summary
    summary = generate_summary_report(results_df)
    print(summary)
    
    # Save results
    reports_dir = Path(__file__).parent / 'reports'
    reports_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = reports_dir / f"comparison_{args.timeframe}_{timestamp}.csv"
    
    results_df.to_csv(output_path, index=False)
    print(f"\nResults saved to: {output_path}")
    
    # Save summary
    summary_path = output_path.with_suffix('.txt')
    with open(summary_path, 'w') as f:
        f.write(summary)
    print(f"Summary saved to: {summary_path}")


if __name__ == '__main__':
    main()
