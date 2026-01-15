"""
Plotting utilities for backtesting visualization.
"""
import pandas as pd
import numpy as np
from typing import Optional, List
from pathlib import Path

try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from kite.backtesting.engine import BacktestResult, Trade


def plot_equity_curve(result: BacktestResult, 
                      save_path: Optional[str] = None,
                      show: bool = True):
    """
    Plot equity curve from backtest result.
    
    Args:
        result: BacktestResult object
        save_path: Path to save the plot
        show: Whether to display the plot
    """
    if not MATPLOTLIB_AVAILABLE:
        print("Matplotlib not available. Install with: pip install matplotlib")
        return
    
    fig, ax = plt.subplots(figsize=(12, 6))
    
    equity = result.equity_curve
    ax.plot(equity.index, equity.values, 'b-', linewidth=1.5, label='Equity')
    
    # Add initial capital line
    ax.axhline(y=result.initial_capital, color='gray', linestyle='--', 
               alpha=0.5, label='Initial Capital')
    
    # Formatting
    ax.set_title(f'{result.strategy_name} - {result.symbol}\nEquity Curve', fontsize=14)
    ax.set_xlabel('Date')
    ax.set_ylabel('Equity (₹)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Format x-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.xticks(rotation=45)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    
    if show:
        plt.show()
    
    plt.close()


def plot_drawdown(result: BacktestResult,
                  save_path: Optional[str] = None,
                  show: bool = True):
    """
    Plot drawdown chart.
    
    Args:
        result: BacktestResult object
        save_path: Path to save the plot
        show: Whether to display the plot
    """
    if not MATPLOTLIB_AVAILABLE:
        print("Matplotlib not available. Install with: pip install matplotlib")
        return
    
    fig, ax = plt.subplots(figsize=(12, 4))
    
    equity = result.equity_curve
    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max * 100
    
    ax.fill_between(drawdown.index, drawdown.values, 0, 
                    color='red', alpha=0.3, label='Drawdown')
    ax.plot(drawdown.index, drawdown.values, 'r-', linewidth=1)
    
    # Formatting
    ax.set_title(f'{result.strategy_name} - Drawdown', fontsize=14)
    ax.set_xlabel('Date')
    ax.set_ylabel('Drawdown (%)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Format x-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.xticks(rotation=45)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    
    if show:
        plt.show()
    
    plt.close()


def plot_trade_distribution(result: BacktestResult,
                            save_path: Optional[str] = None,
                            show: bool = True):
    """
    Plot trade P&L distribution.
    
    Args:
        result: BacktestResult object
        save_path: Path to save the plot
        show: Whether to display the plot
    """
    if not MATPLOTLIB_AVAILABLE:
        print("Matplotlib not available. Install with: pip install matplotlib")
        return
    
    pnls = [t.net_pnl for t in result.trades]
    
    if not pnls:
        print("No trades to plot")
        return
    
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    
    # Histogram
    ax1 = axes[0]
    colors = ['green' if p > 0 else 'red' for p in pnls]
    ax1.hist(pnls, bins=30, color='steelblue', edgecolor='black', alpha=0.7)
    ax1.axvline(x=0, color='black', linestyle='-', linewidth=2)
    ax1.axvline(x=np.mean(pnls), color='orange', linestyle='--', 
                linewidth=2, label=f'Mean: ₹{np.mean(pnls):.0f}')
    ax1.set_title('Trade P&L Distribution', fontsize=12)
    ax1.set_xlabel('P&L (₹)')
    ax1.set_ylabel('Frequency')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Cumulative P&L
    ax2 = axes[1]
    cumulative_pnl = np.cumsum(pnls)
    ax2.plot(range(len(cumulative_pnl)), cumulative_pnl, 'b-', linewidth=1.5)
    ax2.fill_between(range(len(cumulative_pnl)), cumulative_pnl, 0,
                     where=np.array(cumulative_pnl) >= 0, color='green', alpha=0.3)
    ax2.fill_between(range(len(cumulative_pnl)), cumulative_pnl, 0,
                     where=np.array(cumulative_pnl) < 0, color='red', alpha=0.3)
    ax2.axhline(y=0, color='black', linestyle='-', linewidth=1)
    ax2.set_title('Cumulative P&L', fontsize=12)
    ax2.set_xlabel('Trade #')
    ax2.set_ylabel('Cumulative P&L (₹)')
    ax2.grid(True, alpha=0.3)
    
    plt.suptitle(f'{result.strategy_name} - {result.symbol}', fontsize=14)
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    
    if show:
        plt.show()
    
    plt.close()


def plot_monthly_returns_heatmap(result: BacktestResult,
                                 save_path: Optional[str] = None,
                                 show: bool = True):
    """
    Plot monthly returns heatmap.
    
    Args:
        result: BacktestResult object
        save_path: Path to save the plot
        show: Whether to display the plot
    """
    if not MATPLOTLIB_AVAILABLE:
        print("Matplotlib not available. Install with: pip install matplotlib")
        return
    
    from kite.backtesting.performance import calculate_monthly_returns
    
    monthly = calculate_monthly_returns(result)
    
    if monthly.empty:
        print("Not enough data for monthly returns")
        return
    
    fig, ax = plt.subplots(figsize=(14, 6))
    
    # Create heatmap
    im = ax.imshow(monthly.values, cmap='RdYlGn', aspect='auto',
                   vmin=-10, vmax=10)
    
    # Set ticks
    ax.set_xticks(range(len(monthly.columns)))
    ax.set_xticklabels(monthly.columns)
    ax.set_yticks(range(len(monthly.index)))
    ax.set_yticklabels(monthly.index)
    
    # Add text annotations
    for i in range(len(monthly.index)):
        for j in range(len(monthly.columns)):
            val = monthly.iloc[i, j]
            if not np.isnan(val):
                text_color = 'white' if abs(val) > 5 else 'black'
                ax.text(j, i, f'{val:.1f}%', ha='center', va='center',
                       color=text_color, fontsize=9)
    
    # Colorbar
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label('Return (%)')
    
    ax.set_title(f'{result.strategy_name} - Monthly Returns', fontsize=14)
    ax.set_xlabel('Month')
    ax.set_ylabel('Year')
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    
    if show:
        plt.show()
    
    plt.close()


def plot_comparison(results: List[BacktestResult],
                    save_path: Optional[str] = None,
                    show: bool = True):
    """
    Plot comparison of multiple strategies.
    
    Args:
        results: List of BacktestResult objects
        save_path: Path to save the plot
        show: Whether to display the plot
    """
    if not MATPLOTLIB_AVAILABLE:
        print("Matplotlib not available. Install with: pip install matplotlib")
        return
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    
    # Equity curves comparison
    ax1 = axes[0, 0]
    for result in results:
        # Normalize to percentage returns
        equity = result.equity_curve / result.initial_capital * 100 - 100
        ax1.plot(equity.index, equity.values, label=result.strategy_name, linewidth=1.5)
    ax1.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    ax1.set_title('Equity Curves (% Return)', fontsize=12)
    ax1.set_xlabel('Date')
    ax1.set_ylabel('Return (%)')
    ax1.legend(loc='upper left', fontsize=8)
    ax1.grid(True, alpha=0.3)
    
    # Return comparison bar chart
    ax2 = axes[0, 1]
    names = [r.strategy_name for r in results]
    returns = [r.total_return_pct for r in results]
    colors = ['green' if r > 0 else 'red' for r in returns]
    bars = ax2.bar(names, returns, color=colors, alpha=0.7)
    ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    ax2.set_title('Total Return (%)', fontsize=12)
    ax2.set_ylabel('Return (%)')
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha='right')
    ax2.grid(True, alpha=0.3, axis='y')
    
    # Sharpe ratio comparison
    ax3 = axes[1, 0]
    sharpes = [r.sharpe_ratio for r in results]
    ax3.bar(names, sharpes, color='steelblue', alpha=0.7)
    ax3.axhline(y=1, color='green', linestyle='--', linewidth=1, label='Good (>1)')
    ax3.axhline(y=2, color='darkgreen', linestyle='--', linewidth=1, label='Excellent (>2)')
    ax3.set_title('Sharpe Ratio', fontsize=12)
    ax3.set_ylabel('Sharpe Ratio')
    plt.setp(ax3.xaxis.get_majorticklabels(), rotation=45, ha='right')
    ax3.legend(fontsize=8)
    ax3.grid(True, alpha=0.3, axis='y')
    
    # Win rate comparison
    ax4 = axes[1, 1]
    win_rates = [r.win_rate for r in results]
    ax4.bar(names, win_rates, color='purple', alpha=0.7)
    ax4.axhline(y=50, color='orange', linestyle='--', linewidth=1, label='50%')
    ax4.set_title('Win Rate (%)', fontsize=12)
    ax4.set_ylabel('Win Rate (%)')
    plt.setp(ax4.xaxis.get_majorticklabels(), rotation=45, ha='right')
    ax4.legend(fontsize=8)
    ax4.grid(True, alpha=0.3, axis='y')
    
    plt.suptitle('Strategy Comparison', fontsize=14)
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    
    if show:
        plt.show()
    
    plt.close()


def create_full_report(result: BacktestResult, output_dir: str):
    """
    Create a full visual report with all charts.
    
    Args:
        result: BacktestResult object
        output_dir: Directory to save charts
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    prefix = f"{result.strategy_name}_{result.symbol}"
    
    # Generate all charts
    plot_equity_curve(result, 
                      save_path=str(output_path / f"{prefix}_equity.png"),
                      show=False)
    
    plot_drawdown(result,
                  save_path=str(output_path / f"{prefix}_drawdown.png"),
                  show=False)
    
    plot_trade_distribution(result,
                            save_path=str(output_path / f"{prefix}_trades.png"),
                            show=False)
    
    plot_monthly_returns_heatmap(result,
                                 save_path=str(output_path / f"{prefix}_monthly.png"),
                                 show=False)
    
    print(f"Charts saved to {output_path}")
