"""
Compare Batch 2 Underrated Strategies

Tests all 10 new strategies against NIFTY 50 data.
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

# Import all Batch 2 strategies
from kite.strategies.adx_dmi_obv import ADXDMIOBVStrategy
from kite.strategies.cci_divergence import CCIDivergenceStrategy
from kite.strategies.stochrsi_macd import StochRSIMACDStrategy
from kite.strategies.tdi_strategy import TDIStrategy
from kite.strategies.ma_envelopes import MAEnvelopesStrategy
from kite.strategies.gmma_strategy import GMMAStrategy
from kite.strategies.mfi_divergence import MFIDivergenceStrategy
from kite.strategies.momentum_zero import MomentumZeroStrategy
from kite.strategies.ascending_triangle import AscendingTriangleStrategy
from kite.strategies.london_breakout import LondonBreakoutStrategy


# Strategy definitions
BATCH2_STRATEGIES = {
    'ADX_DMI_OBV': ADXDMIOBVStrategy,
    'CCI_Divergence': CCIDivergenceStrategy,
    'StochRSI_MACD': StochRSIMACDStrategy,
    'TDI': TDIStrategy,
    'MA_Envelopes': MAEnvelopesStrategy,
    'GMMA': GMMAStrategy,
    'MFI_Divergence': MFIDivergenceStrategy,
    'Momentum_Zero': MomentumZeroStrategy,
    'Ascending_Triangle': AscendingTriangleStrategy,
    'London_Breakout': LondonBreakoutStrategy,
}


def run_comparison(timeframe: str = 'daily', num_stocks: int = 10):
    """Run comparison of all Batch 2 strategies."""
    
    print("\n" + "=" * 70)
    print("BATCH 2 UNDERRATED STRATEGIES COMPARISON")
    print(f"Timeframe: {timeframe}")
    print("=" * 70)
    
    # Load data
    loader = DataLoader()
    stocks = loader.get_available_symbols(timeframe)[:num_stocks]
    
    print(f"\nTesting on {len(stocks)} stocks: {', '.join(stocks)}")
    print(f"Testing {len(BATCH2_STRATEGIES)} strategies")
    
    # Results storage
    all_results = []
    
    # Create backtest engine
    engine = BacktestEngine(
        initial_capital=trading_config.initial_capital,
        risk_per_trade=trading_config.risk_per_trade,
        allow_short=True
    )
    
    # Run backtests
    total_tests = len(stocks) * len(BATCH2_STRATEGIES)
    
    with tqdm(total=total_tests, desc="Running backtests") as pbar:
        for stock in stocks:
            try:
                df = loader.load_stock(stock, timeframe)
                if df is None or len(df) < 100:
                    pbar.update(len(BATCH2_STRATEGIES))
                    continue
                
                for strategy_name, strategy_class in BATCH2_STRATEGIES.items():
                    try:
                        strategy = strategy_class()
                        result = engine.run(strategy, df.copy(), stock)
                        
                        if result is not None and result.total_trades > 0:
                            all_results.append({
                                'Stock': stock,
                                'Strategy': strategy_name,
                                'Total_Trades': result.total_trades,
                                'Win_Rate': result.win_rate,
                                'Total_Return': result.total_return_pct,
                                'Sharpe_Ratio': result.sharpe_ratio,
                                'Sortino_Ratio': result.sortino_ratio,
                                'Max_Drawdown': result.max_drawdown_pct,
                                'Profit_Factor': result.profit_factor,
                            })
                    except Exception as e:
                        # Silently skip errors
                        pass
                    
                    pbar.update(1)
                    
            except Exception as e:
                pbar.update(len(BATCH2_STRATEGIES))
    
    # Convert to DataFrame
    results_df = pd.DataFrame(all_results)
    
    if len(results_df) == 0:
        print("\nNo results generated!")
        return
    
    # Calculate averages by strategy
    strategy_summary = results_df.groupby('Strategy').agg({
        'Total_Trades': 'mean',
        'Win_Rate': 'mean',
        'Total_Return': 'mean',
        'Sharpe_Ratio': 'mean',
        'Max_Drawdown': 'mean',
        'Profit_Factor': 'mean',
    }).round(2)
    
    strategy_summary = strategy_summary.sort_values('Sharpe_Ratio', ascending=False)
    
    # Print results
    print("\n" + "=" * 90)
    print("                      BATCH 2 STRATEGY COMPARISON RESULTS")
    print("=" * 90)
    
    print("\n" + "-" * 90)
    print(f"{'Strategy':<25} {'Trades':>8} {'Return%':>10} {'Win%':>8} {'Sharpe':>8} {'MaxDD%':>10} {'PF':>8}")
    print("-" * 90)
    
    for strategy, row in strategy_summary.iterrows():
        print(f"{strategy:<25} {row['Total_Trades']:>8.0f} {row['Total_Return']:>10.2f} {row['Win_Rate']:>8.1f} {row['Sharpe_Ratio']:>8.2f} {row['Max_Drawdown']:>10.2f} {row['Profit_Factor']:>8.2f}")
    
    # Top performers
    print("\n" + "=" * 90)
    print("                      TOP 3 PERFORMERS BY SHARPE RATIO")
    print("=" * 90)
    
    top3 = strategy_summary.head(3)
    for i, (strategy, row) in enumerate(top3.iterrows(), 1):
        marker = ["#1", "#2", "#3"][i-1]
        print(f"\n{marker} {strategy}")
        print(f"   Return: {row['Total_Return']:.2f}% | Win Rate: {row['Win_Rate']:.1f}% | Sharpe: {row['Sharpe_Ratio']:.2f} | Max DD: {row['Max_Drawdown']:.2f}%")
    
    # Best strategy per stock
    print("\n" + "=" * 90)
    print("                      BEST STRATEGY PER STOCK")
    print("=" * 90)
    
    best_per_stock = results_df.loc[results_df.groupby('Stock')['Sharpe_Ratio'].idxmax()]
    
    print("\n" + "-" * 70)
    strategy_wins = {}
    for _, row in best_per_stock.iterrows():
        print(f"{row['Stock']:<15} -> {row['Strategy']:<25} (Sharpe: {row['Sharpe_Ratio']:.2f})")
        strategy_wins[row['Strategy']] = strategy_wins.get(row['Strategy'], 0) + 1
    
    print("\n" + "-" * 70)
    print("\nStrategy Win Count:")
    for strategy, wins in sorted(strategy_wins.items(), key=lambda x: -x[1]):
        print(f"  {strategy}: {wins} stocks")
    
    # Save results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_dir = Path(__file__).parent / 'reports'
    report_dir.mkdir(exist_ok=True)
    
    csv_path = report_dir / f'batch2_comparison_{timeframe}_{timestamp}.csv'
    results_df.to_csv(csv_path, index=False)
    
    summary_path = report_dir / f'batch2_summary_{timeframe}_{timestamp}.csv'
    strategy_summary.to_csv(summary_path)
    
    print(f"\nDetailed results saved to: {csv_path}")
    print(f"Summary saved to: {summary_path}")
    
    return results_df, strategy_summary


def main():
    parser = argparse.ArgumentParser(description='Compare Batch 2 Strategies')
    parser.add_argument('--timeframe', type=str, default='daily',
                       choices=['minute', 'hourly', 'daily'],
                       help='Timeframe to test')
    parser.add_argument('--stocks', type=int, default=10,
                       help='Number of stocks to test')
    
    args = parser.parse_args()
    
    run_comparison(args.timeframe, args.stocks)


if __name__ == '__main__':
    main()
