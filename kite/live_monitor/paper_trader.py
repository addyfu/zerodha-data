"""
Paper Trading Engine
====================
Simulates trading with virtual money, tracks positions and P&L.
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class PositionStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"


class ExitReason(Enum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    MANUAL = "manual"
    END_OF_DAY = "end_of_day"
    TRAILING_STOP = "trailing_stop"


@dataclass
class Position:
    """Represents an open or closed position."""
    id: int
    symbol: str
    direction: str  # 'BUY' or 'SELL'
    entry_price: float
    entry_time: datetime
    quantity: int
    stop_loss: float
    take_profit: float
    strategy: str
    
    # Exit info (filled when closed)
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_reason: Optional[str] = None
    
    # P&L
    pnl: float = 0.0
    pnl_pct: float = 0.0
    
    # Status
    status: str = "open"
    
    # Trailing stop
    trailing_stop: Optional[float] = None
    highest_price: Optional[float] = None  # For long
    lowest_price: Optional[float] = None   # For short
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'symbol': self.symbol,
            'direction': self.direction,
            'entry_price': self.entry_price,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'quantity': self.quantity,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'strategy': self.strategy,
            'exit_price': self.exit_price,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'exit_reason': self.exit_reason,
            'pnl': self.pnl,
            'pnl_pct': self.pnl_pct,
            'status': self.status,
            'trailing_stop': self.trailing_stop,
            'highest_price': self.highest_price,
            'lowest_price': self.lowest_price
        }


class PaperTrader:
    """
    Paper trading engine that simulates real trading.
    """
    
    def __init__(self, 
                 initial_capital: float = 100000,
                 max_positions: int = 5,
                 db_path: str = None,
                 use_trailing_stop: bool = True,
                 trailing_stop_pct: float = 0.02):
        """
        Initialize paper trader.
        
        Args:
            initial_capital: Starting capital
            max_positions: Maximum concurrent positions
            db_path: Path to SQLite database for persistence
            use_trailing_stop: Enable trailing stops
            trailing_stop_pct: Trailing stop percentage (0.02 = 2%)
        """
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.max_positions = max_positions
        self.use_trailing_stop = use_trailing_stop
        self.trailing_stop_pct = trailing_stop_pct
        
        self.positions: Dict[str, Position] = {}  # symbol -> Position
        self.closed_trades: List[Position] = []
        self.trade_counter = 0
        
        # Database
        self.db_path = db_path or str(Path(__file__).parent.parent.parent / "data" / "paper_trades.db")
        self._init_database()
        self._load_state()
    
    def _init_database(self):
        """Initialize SQLite database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                entry_time TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                strategy TEXT,
                exit_price REAL,
                exit_time TEXT,
                exit_reason TEXT,
                pnl REAL DEFAULT 0,
                pnl_pct REAL DEFAULT 0,
                status TEXT DEFAULT 'open',
                trailing_stop REAL,
                highest_price REAL,
                lowest_price REAL
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS account (
                id INTEGER PRIMARY KEY,
                capital REAL NOT NULL,
                initial_capital REAL NOT NULL,
                trade_counter INTEGER DEFAULT 0,
                last_updated TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_summary (
                date TEXT PRIMARY KEY,
                trades INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                pnl REAL DEFAULT 0,
                capital REAL
            )
        """)
        
        conn.commit()
        conn.close()
    
    def _load_state(self):
        """Load state from database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Load account
        cursor.execute("SELECT capital, trade_counter FROM account ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            self.capital = row[0]
            self.trade_counter = row[1]
        
        # Load open positions
        cursor.execute("SELECT * FROM positions WHERE status = 'open'")
        for row in cursor.fetchall():
            pos = Position(
                id=row[0],
                symbol=row[1],
                direction=row[2],
                entry_price=row[3],
                entry_time=datetime.fromisoformat(row[4]),
                quantity=row[5],
                stop_loss=row[6],
                take_profit=row[7],
                strategy=row[8],
                status='open',
                trailing_stop=row[15],
                highest_price=row[16],
                lowest_price=row[17]
            )
            self.positions[pos.symbol] = pos
        
        conn.close()
        logger.info(f"Loaded state: Capital={self.capital:.2f}, Open positions={len(self.positions)}")
    
    def _save_state(self):
        """Save state to database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO account (id, capital, initial_capital, trade_counter, last_updated)
            VALUES (1, ?, ?, ?, ?)
        """, (self.capital, self.initial_capital, self.trade_counter, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
    
    def _save_position(self, position: Position):
        """Save position to database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO positions 
            (id, symbol, direction, entry_price, entry_time, quantity, stop_loss, take_profit,
             strategy, exit_price, exit_time, exit_reason, pnl, pnl_pct, status,
             trailing_stop, highest_price, lowest_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            position.id, position.symbol, position.direction, position.entry_price,
            position.entry_time.isoformat(), position.quantity, position.stop_loss,
            position.take_profit, position.strategy, position.exit_price,
            position.exit_time.isoformat() if position.exit_time else None,
            position.exit_reason, position.pnl, position.pnl_pct, position.status,
            position.trailing_stop, position.highest_price, position.lowest_price
        ))
        
        conn.commit()
        conn.close()
    
    def open_position(self, signal) -> Optional[Position]:
        """
        Open a new position based on signal.
        
        Args:
            signal: TradeSignal object
            
        Returns:
            Position if opened, None if rejected
        """
        # Check if we can open more positions
        if len(self.positions) >= self.max_positions:
            logger.warning(f"Max positions ({self.max_positions}) reached. Cannot open {signal.symbol}")
            return None
        
        # Check if already have position in this symbol
        if signal.symbol in self.positions:
            logger.warning(f"Already have position in {signal.symbol}")
            return None
        
        # Check if we have enough capital
        required_capital = signal.quantity * signal.entry_price
        if required_capital > self.capital * 0.5:  # Don't use more than 50% on one trade
            logger.warning(f"Insufficient capital for {signal.symbol}")
            return None
        
        # Create position
        self.trade_counter += 1
        position = Position(
            id=self.trade_counter,
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.entry_price,
            entry_time=datetime.now(),
            quantity=signal.quantity,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            strategy=signal.strategy,
            highest_price=signal.entry_price if signal.direction == 'BUY' else None,
            lowest_price=signal.entry_price if signal.direction == 'SELL' else None
        )
        
        # Set initial trailing stop
        if self.use_trailing_stop:
            position.trailing_stop = signal.stop_loss
        
        # Add to positions
        self.positions[signal.symbol] = position
        
        # Save to database
        self._save_position(position)
        self._save_state()
        
        logger.info(f"Opened {position.direction} position in {position.symbol} @ {position.entry_price:.2f}")
        
        return position
    
    def close_position(self, symbol: str, exit_price: float, 
                      exit_reason: ExitReason) -> Optional[Position]:
        """
        Close an open position.
        
        Args:
            symbol: Stock symbol
            exit_price: Exit price
            exit_reason: Reason for exit
            
        Returns:
            Closed position
        """
        if symbol not in self.positions:
            logger.warning(f"No open position in {symbol}")
            return None
        
        position = self.positions[symbol]
        
        # Calculate P&L
        if position.direction == 'BUY':
            position.pnl = (exit_price - position.entry_price) * position.quantity
        else:  # SELL/SHORT
            position.pnl = (position.entry_price - exit_price) * position.quantity
        
        position.pnl_pct = position.pnl / (position.entry_price * position.quantity) * 100
        
        # Update position
        position.exit_price = exit_price
        position.exit_time = datetime.now()
        position.exit_reason = exit_reason.value
        position.status = 'closed'
        
        # Update capital
        self.capital += position.pnl
        
        # Move to closed trades
        self.closed_trades.append(position)
        del self.positions[symbol]
        
        # Save to database
        self._save_position(position)
        self._save_state()
        self._update_daily_summary(position)
        
        logger.info(f"Closed {position.symbol}: P&L = Rs {position.pnl:+,.2f} ({position.pnl_pct:+.2f}%)")
        
        return position
    
    def check_exits(self, current_prices: Dict[str, float]) -> List[Position]:
        """
        Check all open positions for SL/TP hits.
        
        Args:
            current_prices: Dictionary of symbol -> current price
            
        Returns:
            List of closed positions
        """
        closed = []
        
        for symbol, position in list(self.positions.items()):
            if symbol not in current_prices:
                continue
            
            price = current_prices[symbol]
            
            # Update trailing stop
            if self.use_trailing_stop:
                self._update_trailing_stop(position, price)
            
            # Check stop loss
            if position.direction == 'BUY':
                effective_sl = position.trailing_stop or position.stop_loss
                if price <= effective_sl:
                    reason = ExitReason.TRAILING_STOP if position.trailing_stop else ExitReason.STOP_LOSS
                    closed_pos = self.close_position(symbol, price, reason)
                    if closed_pos:
                        closed.append(closed_pos)
                    continue
                
                # Check take profit
                if price >= position.take_profit:
                    closed_pos = self.close_position(symbol, price, ExitReason.TAKE_PROFIT)
                    if closed_pos:
                        closed.append(closed_pos)
                    continue
            
            else:  # SELL/SHORT
                effective_sl = position.trailing_stop or position.stop_loss
                if price >= effective_sl:
                    reason = ExitReason.TRAILING_STOP if position.trailing_stop else ExitReason.STOP_LOSS
                    closed_pos = self.close_position(symbol, price, reason)
                    if closed_pos:
                        closed.append(closed_pos)
                    continue
                
                # Check take profit
                if price <= position.take_profit:
                    closed_pos = self.close_position(symbol, price, ExitReason.TAKE_PROFIT)
                    if closed_pos:
                        closed.append(closed_pos)
                    continue
        
        return closed
    
    def _update_trailing_stop(self, position: Position, current_price: float):
        """Update trailing stop based on current price."""
        if position.direction == 'BUY':
            # Update highest price
            if position.highest_price is None or current_price > position.highest_price:
                position.highest_price = current_price
                # Calculate new trailing stop
                new_trailing = current_price * (1 - self.trailing_stop_pct)
                if position.trailing_stop is None or new_trailing > position.trailing_stop:
                    position.trailing_stop = new_trailing
                    self._save_position(position)
        
        else:  # SELL/SHORT
            # Update lowest price
            if position.lowest_price is None or current_price < position.lowest_price:
                position.lowest_price = current_price
                # Calculate new trailing stop
                new_trailing = current_price * (1 + self.trailing_stop_pct)
                if position.trailing_stop is None or new_trailing < position.trailing_stop:
                    position.trailing_stop = new_trailing
                    self._save_position(position)
    
    def _update_daily_summary(self, position: Position):
        """Update daily summary in database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        today = datetime.now().strftime('%Y-%m-%d')
        
        cursor.execute("SELECT * FROM daily_summary WHERE date = ?", (today,))
        row = cursor.fetchone()
        
        if row:
            trades = row[1] + 1
            wins = row[2] + (1 if position.pnl > 0 else 0)
            losses = row[3] + (1 if position.pnl < 0 else 0)
            pnl = row[4] + position.pnl
        else:
            trades = 1
            wins = 1 if position.pnl > 0 else 0
            losses = 1 if position.pnl < 0 else 0
            pnl = position.pnl
        
        cursor.execute("""
            INSERT OR REPLACE INTO daily_summary (date, trades, wins, losses, pnl, capital)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (today, trades, wins, losses, pnl, self.capital))
        
        conn.commit()
        conn.close()
    
    def get_performance_summary(self) -> Dict:
        """Get overall performance summary."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get all closed trades
        cursor.execute("SELECT * FROM positions WHERE status = 'closed'")
        trades = cursor.fetchall()
        
        if not trades:
            return {
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'total_pnl_pct': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'profit_factor': 0,
                'capital': self.capital,
                'return_pct': 0
            }
        
        wins = [t for t in trades if t[12] > 0]  # pnl column
        losses = [t for t in trades if t[12] < 0]
        
        total_pnl = sum(t[12] for t in trades)
        gross_profit = sum(t[12] for t in wins) if wins else 0
        gross_loss = abs(sum(t[12] for t in losses)) if losses else 0
        
        conn.close()
        
        return {
            'total_trades': len(trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': len(wins) / len(trades) * 100 if trades else 0,
            'total_pnl': total_pnl,
            'total_pnl_pct': total_pnl / self.initial_capital * 100,
            'avg_win': gross_profit / len(wins) if wins else 0,
            'avg_loss': gross_loss / len(losses) if losses else 0,
            'profit_factor': gross_profit / gross_loss if gross_loss > 0 else float('inf'),
            'capital': self.capital,
            'return_pct': (self.capital - self.initial_capital) / self.initial_capital * 100,
            'open_positions': len(self.positions)
        }
    
    def get_open_positions(self) -> List[Dict]:
        """Get list of open positions."""
        return [pos.to_dict() for pos in self.positions.values()]
    
    def get_daily_summary(self, date: str = None) -> Dict:
        """Get daily summary."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        cursor.execute("SELECT * FROM daily_summary WHERE date = ?", (date,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'date': row[0],
                'trades_today': row[1],
                'wins': row[2],
                'losses': row[3],
                'day_pnl': row[4],
                'capital': row[5]
            }
        
        return {
            'date': date,
            'trades_today': 0,
            'wins': 0,
            'losses': 0,
            'day_pnl': 0,
            'capital': self.capital
        }


if __name__ == '__main__':
    # Test paper trader
    print("Testing Paper Trader...")
    
    trader = PaperTrader(initial_capital=100000)
    
    # Simulate a signal
    from signal_detector import TradeSignal
    
    signal = TradeSignal(
        symbol='RELIANCE',
        direction='BUY',
        strategy='fib_3wave',
        entry_price=2500.0,
        stop_loss=2450.0,
        take_profit=2600.0,
        risk_pct=2.0,
        reward_pct=4.0,
        rr_ratio=2.0,
        quantity=40,
        position_value=100000,
        timestamp=datetime.now()
    )
    
    # Open position
    position = trader.open_position(signal)
    print(f"\nOpened: {position}")
    
    # Check exits with price movement
    print("\nChecking exits...")
    
    # Simulate price hitting TP
    closed = trader.check_exits({'RELIANCE': 2600.0})
    if closed:
        print(f"Closed: {closed[0].to_dict()}")
    
    # Get summary
    summary = trader.get_performance_summary()
    print(f"\nPerformance: {summary}")
