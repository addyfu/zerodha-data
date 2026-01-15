"""
Compare Combined Multi-Strategy Performance

Tests various strategy combinations against individual strategies.
"""
import sys
import io
from pathlib import Path

# Fix encoding for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime
from tqdm import tqdm
import argparse

from kite.utils.data_loader import DataLoader
from kite.backtesting.engine import BacktestEngine
from kite.config import trading_config

# Import individual strategies for comparison
from kite.strategies.fib_3wave import Fib3WaveStrategy
from kite.strategies.ema_21_55 import EMA2155Strategy
from kite.strategies.multi_timeframe import MultiTimeframeStrategy

# Import combined strategy framework
from kite.strategies.combined_strategy import (
    CombinedStrategy, CombinationMethod, COMBO_STRATEGIES,
    create_trend_momentum_combo,
    create_volume_price_combo,
    create_breakout_combo,
    create_sr_bounce_combo,
    create_trend_following_combo,
    create_best_performers_combo,
    create_scalping_combo,
)


def run_comparison(timeframe: str = 'daily', num_stocks: int = 10):
    """Run comparison of combined vs individual strategies."""
    
    print("\n" + "=" * 70)
    print("COMBINED STRATEGY COMPARISON")
    print(f"Timeframe: {timeframe}")
    print("=" * 70)
    
    # Load data
    loader = DataLoader()
    stocks = loader.get_available_symbols(timeframe)[:num_stocks]
    
    print(f"\nTesting on {len(stocks)} stocks: {', '.join(stocks)}")
    
    # Create all strategies to test
    strategies = {}
    
    # Individual top performers
    strategies['Individual_Fib3Wave'] = Fib3WaveStrategy()
    strategies['Individual_EMA2155'] = EMA2155Strategy()
    strategies['Individual_MultiTF'] = MultiTimeframeStrategy()
    
    # Combined strategies
    strategies['Combo_TrendMomentum'] = create_trend_momentum_combo()
    strategies['Combo_VolumePrice'] = create_volume_price_combo()
    strategies['Combo_Breakout'] = create_breakout_combo()
    strategies['Combo_SRBounce'] = create_sr_bounce_combo()
    strategies['Combo_TrendFollow'] = create_trend_following_combo()
    strategies['Combo_BestPerformers'] = create_best_performers_combo()
    strategies['Combo_Scalping'] = create_scalping_combo()
    
    # Results storage
    all_results = []
    
    # Create backtest engine
    engine = BacktestEngine(
        initial_capital=trading_config.initial_capital,
        risk_per_trade=trading_config.risk_per_trade,
        allow_short=True
    )
    
    # Run backtests
    total_tests = len(stocks) * len(strategies)
    
    with tqdm(total=total_tests, desc="Running backtests") as pbar:
        for stock in stocks:
            try:
                df = loader.load_stock(stock, timeframe)
                if df is None or len(df) < 100:
                    pbar.update(len(strategies))
                    continue
                
                for strategy_name, strategy in strategies.items():
                    try:
                        # Re-create combined strategies for each stock (they may have state)
                        if 'Combo' in strategy_name:
                            if strategy_name == 'Combo_TrendMomentum':
                                strategy = create_trend_momentum_combo()
                            elif strategy_name == 'Combo_VolumePrice':
                                strategy = create_volume_price_combo()
                            elif strategy_name == 'Combo_Breakout':
                                strategy = create_breakout_combo()
                            elif strategy_name == 'Combo_SRBounce':
                                strategy = create_sr_bounce_combo()
                            elif strategy_name == 'Combo_TrendFollow':
                                strategy = create_trend_following_combo()
                            elif strategy_name == 'Combo_BestPerformers':
                                strategy = create_best_performers_combo()
                            elif strategy_name == 'Combo_Scalping':
                                strategy = create_scalping_combo()
                        
                        result = engine.run(strategy, df.copy(), stock)
                        
                        if result is not None and result.total_trades > 0:
                            all_results.append({
                                'Stock': stock,
                                'Strategy': strategy_name,
                                'Type': 'Combined' if 'Combo' in strategy_name else 'Individual',
                                'Total_Trades': result.total_trades,
                                'Win_Rate': result.win_rate,
                                'Total_Return': result.total_return_pct,
                                'Sharpe_Ratio': result.sharpe_ratio,
                                'Sortino_Ratio': result.sortino_ratio,
                                'Max_Drawdown': result.max_drawdown_pct,
                                'Profit_Factor': result.profit_factor,
                            })
                    except Exception as e:
                        print(f"Error with {strategy_name} on {stock}: {e}")
                    
                    pbar.update(1)
                    
            except Exception as e:
                print(f"Error loading {stock}: {e}")
                pbar.update(len(strategies))
    
    # Convert to DataFrame
    results_df = pd.DataFrame(all_results)
    
    if len(results_df) == 0:
        print("\nNo results generated!")
        return
    
    # Calculate averages by strategy
    strategy_summary = results_df.groupby(['Strategy', 'Type']).agg({
        'Total_Trades': 'mean',
        'Win_Rate': 'mean',
        'Total_Return': 'mean',
        'Sharpe_Ratio': 'mean',
        'Max_Drawdown': 'mean',
    }).round(2)
    
    strategy_summary = strategy_summary.sort_values('Sharpe_Ratio', ascending=False)
    
    # Print results
    print("\n" + "=" * 80)
    print("                      STRATEGY COMPARISON RESULTS")
    print("=" * 80)
    
    print("\n" + "-" * 80)
    print(f"{'Strategy':<30} {'Type':<12} {'Return%':>10} {'Win%':>8} {'Sharpe':>8} {'MaxDD%':>10}")
    print("-" * 80)
    
    for (strategy, stype), row in strategy_summary.iterrows():
        print(f"{strategy:<30} {stype:<12} {row['Total_Return']:>10.2f} {row['Win_Rate']:>8.1f} {row['Sharpe_Ratio']:>8.2f} {row['Max_Drawdown']:>10.2f}")
    
    # Compare Individual vs Combined
    print("\n" + "=" * 80)
    print("                      INDIVIDUAL vs COMBINED SUMMARY")
    print("=" * 80)
    
    type_summary = results_df.groupby('Type').agg({
        'Total_Return': ['mean', 'std', 'max', 'min'],
        'Sharpe_Ratio': ['mean', 'max'],
        'Win_Rate': 'mean',
        'Max_Drawdown': 'mean',
    }).round(2)
    
    print("\n" + "-" * 70)
    print(f"{'Metric':<25} {'Individual':>20} {'Combined':>20}")
    print("-" * 70)
    
    individual = type_summary.loc['Individual'] if 'Individual' in type_summary.index else None
    combined = type_summary.loc['Combined'] if 'Combined' in type_summary.index else None
    
    if individual is not None and combined is not None:
        print(f"{'Avg Return %':<25} {individual[('Total_Return', 'mean')]:>20.2f} {combined[('Total_Return', 'mean')]:>20.2f}")
        print(f"{'Return Std Dev':<25} {individual[('Total_Return', 'std')]:>20.2f} {combined[('Total_Return', 'std')]:>20.2f}")
        print(f"{'Best Return %':<25} {individual[('Total_Return', 'max')]:>20.2f} {combined[('Total_Return', 'max')]:>20.2f}")
        print(f"{'Worst Return %':<25} {individual[('Total_Return', 'min')]:>20.2f} {combined[('Total_Return', 'min')]:>20.2f}")
        print(f"{'Avg Sharpe':<25} {individual[('Sharpe_Ratio', 'mean')]:>20.2f} {combined[('Sharpe_Ratio', 'mean')]:>20.2f}")
        print(f"{'Best Sharpe':<25} {individual[('Sharpe_Ratio', 'max')]:>20.2f} {combined[('Sharpe_Ratio', 'max')]:>20.2f}")
        print(f"{'Avg Win Rate %':<25} {individual[('Win_Rate', 'mean')]:>20.1f} {combined[('Win_Rate', 'mean')]:>20.1f}")
        print(f"{'Avg Max Drawdown %':<25} {individual[('Max_Drawdown', 'mean')]:>20.2f} {combined[('Max_Drawdown', 'mean')]:>20.2f}")
    
    # Best strategy per stock
    print("\n" + "=" * 80)
    print("                      BEST STRATEGY PER STOCK")
    print("=" * 80)
    
    best_per_stock = results_df.loc[results_df.groupby('Stock')['Sharpe_Ratio'].idxmax()]
    
    print("\n" + "-" * 70)
    for _, row in best_per_stock.iterrows():
        marker = "[COMBO]" if row['Type'] == 'Combined' else "[INDIV]"
        print(f"{row['Stock']:<15} -> {row['Strategy']:<30} {marker} (Sharpe: {row['Sharpe_Ratio']:.2f})")
    
    # Count wins
    combo_wins = (best_per_stock['Type'] == 'Combined').sum()
    indiv_wins = (best_per_stock['Type'] == 'Individual').sum()
    
    print("\n" + "-" * 70)
    print(f"Combined strategies won on {combo_wins}/{len(best_per_stock)} stocks")
    print(f"Individual strategies won on {indiv_wins}/{len(best_per_stock)} stocks")
    
    # Save results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_dir = Path(__file__).parent / 'reports'
    report_dir.mkdir(exist_ok=True)
    
    csv_path = report_dir / f'combined_comparison_{timeframe}_{timestamp}.csv'
    results_df.to_csv(csv_path, index=False)
    print(f"\nDetailed results saved to: {csv_path}")
    
    return results_df


def main():
    parser = argparse.ArgumentParser(description='Compare Combined Strategies')
    parser.add_argument('--timeframe', type=str, default='daily',
                       choices=['minute', 'hourly', 'daily'],
                       help='Timeframe to test')
    parser.add_argument('--stocks', type=int, default=10,
                       help='Number of stocks to test')
    
    args = parser.parse_args()
    
    run_comparison(args.timeframe, args.stocks)


if __name__ == '__main__':
    main()
