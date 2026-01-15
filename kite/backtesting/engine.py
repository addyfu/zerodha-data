"""
Backtesting Engine - Core backtesting logic.
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
from datetime import datetime

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

from kite.strategies.base_strategy import BaseStrategy, Signal
from kite.config import trading_config, zerodha_charges


class TradeStatus(Enum):
    """Trade status."""
    OPEN = "open"
    CLOSED = "closed"


@dataclass
class Trade:
    """Represents a single trade."""
    id: int
    symbol: str
    direction: str  # 'LONG' or 'SHORT'
    entry_time: datetime
    entry_price: float
    quantity: int
    stop_loss: float
    take_profit: float
    
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    status: TradeStatus = TradeStatus.OPEN
    
    pnl: float = 0.0
    pnl_pct: float = 0.0
    charges: float = 0.0
    net_pnl: float = 0.0
    
    def close(self, exit_time: datetime, exit_price: float, 
              exit_reason: str, charges: float = 0.0):
        """Close the trade."""
        self.exit_time = exit_time
        self.exit_price = exit_price
        self.exit_reason = exit_reason
        self.status = TradeStatus.CLOSED
        self.charges = charges
        
        # Calculate P&L
        if self.direction == 'LONG':
            self.pnl = (exit_price - self.entry_price) * self.quantity
        else:
            self.pnl = (self.entry_price - exit_price) * self.quantity
        
        self.pnl_pct = self.pnl / (self.entry_price * self.quantity) * 100
        self.net_pnl = self.pnl - charges
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'symbol': self.symbol,
            'direction': self.direction,
            'entry_time': self.entry_time,
            'entry_price': self.entry_price,
            'quantity': self.quantity,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'exit_time': self.exit_time,
            'exit_price': self.exit_price,
            'exit_reason': self.exit_reason,
            'status': self.status.value,
            'pnl': self.pnl,
            'pnl_pct': self.pnl_pct,
            'charges': self.charges,
            'net_pnl': self.net_pnl,
        }


@dataclass
class BacktestResult:
    """Results from a backtest run."""
    strategy_name: str
    symbol: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    
    trades: List[Trade] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=pd.Series)
    
    # Performance metrics
    total_return: float = 0.0
    total_return_pct: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_trade: float = 0.0
    
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    
    total_charges: float = 0.0
    
    def calculate_metrics(self):
        """Calculate all performance metrics."""
        if not self.trades:
            return
        
        # Basic counts
        closed_trades = [t for t in self.trades if t.status == TradeStatus.CLOSED]
        self.total_trades = len(closed_trades)
        
        if self.total_trades == 0:
            return
        
        # Win/Loss
        self.winning_trades = len([t for t in closed_trades if t.net_pnl > 0])
        self.losing_trades = len([t for t in closed_trades if t.net_pnl <= 0])
        self.win_rate = self.winning_trades / self.total_trades * 100
        
        # Profit/Loss
        self.gross_profit = sum(t.net_pnl for t in closed_trades if t.net_pnl > 0)
        self.gross_loss = abs(sum(t.net_pnl for t in closed_trades if t.net_pnl < 0))
        
        self.profit_factor = self.gross_profit / self.gross_loss if self.gross_loss > 0 else float('inf')
        
        # Averages
        if self.winning_trades > 0:
            self.avg_win = self.gross_profit / self.winning_trades
        if self.losing_trades > 0:
            self.avg_loss = self.gross_loss / self.losing_trades
        self.avg_trade = sum(t.net_pnl for t in closed_trades) / self.total_trades
        
        # Total return
        self.total_return = self.final_capital - self.initial_capital
        self.total_return_pct = self.total_return / self.initial_capital * 100
        
        # Total charges
        self.total_charges = sum(t.charges for t in closed_trades)
        
        # Drawdown
        if len(self.equity_curve) > 0:
            rolling_max = self.equity_curve.cummax()
            drawdown = self.equity_curve - rolling_max
            self.max_drawdown = drawdown.min()
            self.max_drawdown_pct = (self.max_drawdown / rolling_max[drawdown.idxmin()]) * 100
        
        # Sharpe Ratio (assuming daily returns)
        if len(self.equity_curve) > 1:
            returns = self.equity_curve.pct_change().dropna()
            if len(returns) > 0 and returns.std() > 0:
                self.sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252)
                
                # Sortino (downside deviation)
                downside_returns = returns[returns < 0]
                if len(downside_returns) > 0 and downside_returns.std() > 0:
                    self.sortino_ratio = (returns.mean() / downside_returns.std()) * np.sqrt(252)
        
        # Calmar Ratio
        if self.max_drawdown_pct != 0:
            # Annualized return / Max drawdown
            days = (self.end_date - self.start_date).days
            if days > 0:
                annual_return = self.total_return_pct * (365 / days)
                self.calmar_ratio = annual_return / abs(self.max_drawdown_pct)
    
    def to_dict(self) -> Dict:
        return {
            'strategy_name': self.strategy_name,
            'symbol': self.symbol,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'initial_capital': self.initial_capital,
            'final_capital': self.final_capital,
            'total_return': self.total_return,
            'total_return_pct': self.total_return_pct,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': self.win_rate,
            'profit_factor': self.profit_factor,
            'avg_win': self.avg_win,
            'avg_loss': self.avg_loss,
            'avg_trade': self.avg_trade,
            'max_drawdown': self.max_drawdown,
            'max_drawdown_pct': self.max_drawdown_pct,
            'sharpe_ratio': self.sharpe_ratio,
            'sortino_ratio': self.sortino_ratio,
            'calmar_ratio': self.calmar_ratio,
            'total_charges': self.total_charges,
        }


class BacktestEngine:
    """
    Main backtesting engine.
    
    Runs strategies on historical data and tracks performance.
    """
    
    def __init__(self, 
                 initial_capital: float = None,
                 risk_per_trade: float = None,
                 max_positions: int = None,
                 allow_short: bool = True,
                 slippage: float = None):
        """
        Initialize backtesting engine.
        
        Args:
            initial_capital: Starting capital
            risk_per_trade: Risk per trade as decimal (0.02 = 2%)
            max_positions: Maximum concurrent positions
            allow_short: Allow short selling
            slippage: Slippage as decimal
        """
        self.initial_capital = initial_capital or trading_config.initial_capital
        self.risk_per_trade = risk_per_trade or trading_config.risk_per_trade
        self.max_positions = max_positions or trading_config.max_positions
        self.allow_short = allow_short
        self.slippage = slippage or trading_config.slippage
        
        # State
        self.capital = self.initial_capital
        self.open_positions: List[Trade] = []
        self.closed_trades: List[Trade] = []
        self.trade_counter = 0
        self.equity_history: List[tuple] = []
    
    def run(self, strategy: BaseStrategy, df: pd.DataFrame,
            symbol: str = "UNKNOWN") -> BacktestResult:
        """
        Run backtest for a strategy on given data.
        
        Args:
            strategy: Strategy instance
            df: DataFrame with OHLCV data
            symbol: Stock symbol
            
        Returns:
            BacktestResult with performance metrics
        """
        # Reset state
        self.capital = self.initial_capital
        self.open_positions = []
        self.closed_trades = []
        self.trade_counter = 0
        self.equity_history = []
        
        # Generate signals
        df_signals = strategy.get_trade_signals(df)
        
        # Run through each bar
        for idx in df_signals.index:
            row = df_signals.loc[idx]
            
            # Check exits first
            self._check_exits(idx, row)
            
            # Check for new signals
            signal = row.get('signal', 0)
            
            if signal == Signal.BUY.value and len(self.open_positions) < self.max_positions:
                self._open_trade(idx, row, 'LONG', symbol)
            elif signal == Signal.SELL.value and self.allow_short and len(self.open_positions) < self.max_positions:
                self._open_trade(idx, row, 'SHORT', symbol)
            
            # Track equity
            equity = self._calculate_equity(row['close'])
            self.equity_history.append((idx, equity))
        
        # Close any remaining positions at last price
        if self.open_positions:
            last_row = df_signals.iloc[-1]
            last_idx = df_signals.index[-1]
            for trade in self.open_positions[:]:
                self._close_trade(trade, last_idx, last_row['close'], "END_OF_DATA")
        
        # Create result
        result = BacktestResult(
            strategy_name=strategy.name,
            symbol=symbol,
            start_date=df_signals.index[0],
            end_date=df_signals.index[-1],
            initial_capital=self.initial_capital,
            final_capital=self.capital,
            trades=self.closed_trades,
            equity_curve=pd.Series(
                [e[1] for e in self.equity_history],
                index=[e[0] for e in self.equity_history]
            )
        )
        
        result.calculate_metrics()
        return result
    
    def _open_trade(self, idx, row, direction: str, symbol: str):
        """Open a new trade."""
        entry_price = row['close']
        
        # Apply slippage
        if direction == 'LONG':
            entry_price *= (1 + self.slippage)
        else:
            entry_price *= (1 - self.slippage)
        
        stop_loss = row.get('stop_loss', entry_price * 0.98)
        take_profit = row.get('take_profit', entry_price * 1.04)
        
        # Calculate position size based on risk
        risk_amount = self.capital * self.risk_per_trade
        risk_per_share = abs(entry_price - stop_loss)
        
        if risk_per_share > 0:
            quantity = int(risk_amount / risk_per_share)
        else:
            quantity = int(self.capital * 0.1 / entry_price)  # 10% of capital
        
        # Ensure we have enough capital
        required_capital = entry_price * quantity
        if required_capital > self.capital * 0.95:  # Leave 5% buffer
            quantity = int(self.capital * 0.95 / entry_price)
        
        if quantity <= 0:
            return
        
        self.trade_counter += 1
        trade = Trade(
            id=self.trade_counter,
            symbol=symbol,
            direction=direction,
            entry_time=idx,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit
        )
        
        self.open_positions.append(trade)
    
    def _check_exits(self, idx, row):
        """Check if any open positions should be closed."""
        high = row['high']
        low = row['low']
        close = row['close']
        
        for trade in self.open_positions[:]:
            exit_price = None
            exit_reason = ""
            
            if trade.direction == 'LONG':
                # Check stop loss
                if low <= trade.stop_loss:
                    exit_price = trade.stop_loss
                    exit_reason = "STOP_LOSS"
                # Check take profit
                elif high >= trade.take_profit:
                    exit_price = trade.take_profit
                    exit_reason = "TAKE_PROFIT"
            
            else:  # SHORT
                # Check stop loss
                if high >= trade.stop_loss:
                    exit_price = trade.stop_loss
                    exit_reason = "STOP_LOSS"
                # Check take profit
                elif low <= trade.take_profit:
                    exit_price = trade.take_profit
                    exit_reason = "TAKE_PROFIT"
            
            if exit_price:
                self._close_trade(trade, idx, exit_price, exit_reason)
    
    def _close_trade(self, trade: Trade, idx, exit_price: float, reason: str):
        """Close a trade."""
        # Apply slippage
        if trade.direction == 'LONG':
            exit_price *= (1 - self.slippage)
        else:
            exit_price *= (1 + self.slippage)
        
        # Calculate charges
        buy_value = trade.entry_price * trade.quantity
        sell_value = exit_price * trade.quantity
        charges = zerodha_charges.calculate_charges(buy_value, sell_value, is_intraday=True)
        
        trade.close(idx, exit_price, reason, charges['total'])
        
        # Update capital
        self.capital += trade.net_pnl
        
        # Move to closed trades
        self.open_positions.remove(trade)
        self.closed_trades.append(trade)
    
    def _calculate_equity(self, current_price: float) -> float:
        """Calculate current equity including open positions."""
        equity = self.capital
        
        for trade in self.open_positions:
            if trade.direction == 'LONG':
                unrealized = (current_price - trade.entry_price) * trade.quantity
            else:
                unrealized = (trade.entry_price - current_price) * trade.quantity
            equity += unrealized
        
        return equity


def run_backtest(strategy: BaseStrategy, df: pd.DataFrame, 
                symbol: str = "UNKNOWN", **kwargs) -> BacktestResult:
    """
    Convenience function to run a backtest.
    
    Args:
        strategy: Strategy instance
        df: DataFrame with OHLCV data
        symbol: Stock symbol
        **kwargs: Additional arguments for BacktestEngine
        
    Returns:
        BacktestResult
    """
    engine = BacktestEngine(**kwargs)
    return engine.run(strategy, df, symbol)
