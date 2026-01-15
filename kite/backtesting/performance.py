"""
Performance Analytics - Metrics, reports, and visualizations.
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime
import json

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

from kite.backtesting.engine import BacktestResult, Trade


def generate_performance_report(result: BacktestResult) -> str:
    """
    Generate a text-based performance report.
    
    Args:
        result: BacktestResult object
        
    Returns:
        Formatted report string
    """
    report = []
    report.append("=" * 70)
    report.append(f"{'BACKTEST PERFORMANCE REPORT':^70}")
    report.append("=" * 70)
    report.append("")
    
    # Strategy Info
    report.append(f"Strategy: {result.strategy_name}")
    report.append(f"Symbol: {result.symbol}")
    report.append(f"Period: {result.start_date.strftime('%Y-%m-%d')} to {result.end_date.strftime('%Y-%m-%d')}")
    report.append("")
    
    # Capital
    report.append("-" * 70)
    report.append("CAPITAL")
    report.append("-" * 70)
    report.append(f"Initial Capital:     Rs{result.initial_capital:>15,.2f}")
    report.append(f"Final Capital:       Rs{result.final_capital:>15,.2f}")
    report.append(f"Total Return:        Rs{result.total_return:>15,.2f} ({result.total_return_pct:+.2f}%)")
    report.append(f"Total Charges:       Rs{result.total_charges:>15,.2f}")
    report.append("")
    
    # Trade Statistics
    report.append("-" * 70)
    report.append("TRADE STATISTICS")
    report.append("-" * 70)
    report.append(f"Total Trades:        {result.total_trades:>15}")
    report.append(f"Winning Trades:      {result.winning_trades:>15}")
    report.append(f"Losing Trades:       {result.losing_trades:>15}")
    report.append(f"Win Rate:            {result.win_rate:>14.2f}%")
    report.append("")
    
    # Profit/Loss
    report.append("-" * 70)
    report.append("PROFIT/LOSS")
    report.append("-" * 70)
    report.append(f"Gross Profit:        Rs{result.gross_profit:>15,.2f}")
    report.append(f"Gross Loss:          Rs{result.gross_loss:>15,.2f}")
    report.append(f"Profit Factor:       {result.profit_factor:>15.2f}")
    report.append(f"Average Win:         Rs{result.avg_win:>15,.2f}")
    report.append(f"Average Loss:        Rs{result.avg_loss:>15,.2f}")
    report.append(f"Average Trade:       Rs{result.avg_trade:>15,.2f}")
    report.append("")
    
    # Risk Metrics
    report.append("-" * 70)
    report.append("RISK METRICS")
    report.append("-" * 70)
    report.append(f"Max Drawdown:        Rs{result.max_drawdown:>15,.2f} ({result.max_drawdown_pct:.2f}%)")
    report.append(f"Sharpe Ratio:        {result.sharpe_ratio:>15.2f}")
    report.append(f"Sortino Ratio:       {result.sortino_ratio:>15.2f}")
    report.append(f"Calmar Ratio:        {result.calmar_ratio:>15.2f}")
    report.append("")
    
    report.append("=" * 70)
    
    return "\n".join(report)


def generate_trade_log(result: BacktestResult) -> pd.DataFrame:
    """
    Generate a DataFrame of all trades.
    
    Args:
        result: BacktestResult object
        
    Returns:
        DataFrame with trade details
    """
    trades_data = [t.to_dict() for t in result.trades]
    if not trades_data:
        return pd.DataFrame()
    
    df = pd.DataFrame(trades_data)
    
    # Format columns
    if 'entry_time' in df.columns:
        df['entry_time'] = pd.to_datetime(df['entry_time'])
    if 'exit_time' in df.columns:
        df['exit_time'] = pd.to_datetime(df['exit_time'])
    
    return df


def calculate_monthly_returns(result: BacktestResult) -> pd.DataFrame:
    """
    Calculate monthly returns from equity curve.
    
    Args:
        result: BacktestResult object
        
    Returns:
        DataFrame with monthly returns
    """
    if len(result.equity_curve) == 0:
        return pd.DataFrame()
    
    equity = result.equity_curve.copy()
    equity.index = pd.to_datetime(equity.index)
    
    # Resample to monthly
    monthly = equity.resample('M').last()
    monthly_returns = monthly.pct_change() * 100
    
    # Create pivot table by year and month
    monthly_returns = monthly_returns.dropna()
    
    if len(monthly_returns) == 0:
        return pd.DataFrame()
    
    df = pd.DataFrame({
        'year': monthly_returns.index.year,
        'month': monthly_returns.index.month,
        'return': monthly_returns.values
    })
    
    pivot = df.pivot(index='year', columns='month', values='return')
    pivot.columns = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][:len(pivot.columns)]
    
    return pivot


def calculate_drawdown_series(result: BacktestResult) -> pd.Series:
    """
    Calculate drawdown series from equity curve.
    
    Args:
        result: BacktestResult object
        
    Returns:
        Series with drawdown values
    """
    if len(result.equity_curve) == 0:
        return pd.Series()
    
    equity = result.equity_curve
    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max * 100
    
    return drawdown


def analyze_trades_by_exit(result: BacktestResult) -> Dict[str, Dict]:
    """
    Analyze trades grouped by exit reason.
    
    Args:
        result: BacktestResult object
        
    Returns:
        Dictionary with stats per exit reason
    """
    trades = result.trades
    
    stats = {}
    exit_reasons = set(t.exit_reason for t in trades)
    
    for reason in exit_reasons:
        reason_trades = [t for t in trades if t.exit_reason == reason]
        
        if not reason_trades:
            continue
        
        total_pnl = sum(t.net_pnl for t in reason_trades)
        wins = len([t for t in reason_trades if t.net_pnl > 0])
        
        stats[reason] = {
            'count': len(reason_trades),
            'total_pnl': total_pnl,
            'avg_pnl': total_pnl / len(reason_trades),
            'win_rate': wins / len(reason_trades) * 100 if reason_trades else 0
        }
    
    return stats


def compare_results(results: List[BacktestResult]) -> pd.DataFrame:
    """
    Compare multiple backtest results.
    
    Args:
        results: List of BacktestResult objects
        
    Returns:
        DataFrame comparing all results
    """
    comparison_data = []
    
    for result in results:
        comparison_data.append({
            'Strategy': result.strategy_name,
            'Symbol': result.symbol,
            'Total Return %': result.total_return_pct,
            'Win Rate %': result.win_rate,
            'Profit Factor': result.profit_factor,
            'Sharpe Ratio': result.sharpe_ratio,
            'Max Drawdown %': result.max_drawdown_pct,
            'Total Trades': result.total_trades,
            'Avg Trade Rs': result.avg_trade,
        })
    
    df = pd.DataFrame(comparison_data)
    
    # Sort by Sharpe Ratio
    df = df.sort_values('Sharpe Ratio', ascending=False)
    
    return df


def export_results_json(result: BacktestResult, filepath: str):
    """
    Export backtest results to JSON.
    
    Args:
        result: BacktestResult object
        filepath: Output file path
    """
    data = result.to_dict()
    
    # Convert datetime objects
    for key, value in data.items():
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    
    # Add trades
    data['trades'] = []
    for trade in result.trades:
        trade_dict = trade.to_dict()
        for k, v in trade_dict.items():
            if isinstance(v, datetime):
                trade_dict[k] = v.isoformat() if v else None
        data['trades'].append(trade_dict)
    
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2, default=str)


def print_comparison_table(results: List[BacktestResult]):
    """
    Print a formatted comparison table.
    
    Args:
        results: List of BacktestResult objects
    """
    df = compare_results(results)
    
    print("\n" + "=" * 120)
    print(f"{'STRATEGY COMPARISON':^120}")
    print("=" * 120)
    
    # Header
    print(f"{'Strategy':<25} {'Return %':>10} {'Win Rate':>10} {'PF':>8} {'Sharpe':>8} {'Max DD %':>10} {'Trades':>8} {'Avg Rs':>12}")
    print("-" * 120)
    
    # Data rows
    for _, row in df.iterrows():
        print(f"{row['Strategy']:<25} {row['Total Return %']:>10.2f} {row['Win Rate %']:>9.1f}% {row['Profit Factor']:>8.2f} {row['Sharpe Ratio']:>8.2f} {row['Max Drawdown %']:>10.2f} {row['Total Trades']:>8} {row['Avg Trade Rs']:>12,.0f}")
    
    print("=" * 120)


def get_best_strategy(results: List[BacktestResult], 
                      metric: str = 'sharpe_ratio') -> BacktestResult:
    """
    Get the best performing strategy based on a metric.
    
    Args:
        results: List of BacktestResult objects
        metric: Metric to compare ('sharpe_ratio', 'total_return_pct', 'win_rate', etc.)
        
    Returns:
        Best performing BacktestResult
    """
    if not results:
        raise ValueError("No results to compare")
    
    return max(results, key=lambda r: getattr(r, metric, 0))
