"""
Order Book System
=================
JSON-based order book that persists between GitHub Actions runs.
Tracks all positions, trades, and P&L.
"""
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Represents an open position."""
    id: int
    symbol: str
    direction: str  # 'BUY' or 'SELL'
    entry_price: float
    entry_time: str
    quantity: int
    stop_loss: float
    take_profit: float
    strategy: str
    trailing_stop: Optional[float] = None
    highest_price: Optional[float] = None
    lowest_price: Optional[float] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Position':
        return cls(**data)


@dataclass
class ClosedTrade:
    """Represents a closed trade."""
    id: int
    symbol: str
    direction: str
    entry_price: float
    entry_time: str
    exit_price: float
    exit_time: str
    exit_reason: str  # 'stop_loss', 'take_profit', 'trailing_stop', 'manual', 'end_of_day'
    quantity: int
    pnl: float
    pnl_pct: float
    strategy: str
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ClosedTrade':
        return cls(**data)


class OrderBook:
    """
    JSON-based order book for paper trading.
    Designed to persist between GitHub Actions runs.
    """
    
    DEFAULT_STATE = {
        "account": {
            "initial_capital": 100000,
            "current_capital": 100000,
            "total_pnl": 0,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "max_drawdown": 0,
            "peak_capital": 100000
        },
        "open_positions": [],
        "closed_trades": [],
        "daily_summary": {},
        "last_scan": None,
        "trade_counter": 0,
        "settings": {
            "max_positions": 5,
            "risk_per_trade": 0.02,
            "use_trailing_stop": True,
            "trailing_stop_pct": 0.02
        }
    }
    
    def __init__(self, state_file: str = "order_book.json"):
        """
        Initialize order book.
        
        Args:
            state_file: Path to JSON state file
        """
        self.state_file = state_file
        self.state = self._load_state()
    
    def _load_state(self) -> Dict:
        """Load state from JSON file."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                logger.info(f"Loaded order book from {self.state_file}")
                return state
            except Exception as e:
                logger.error(f"Error loading state: {e}")
        
        logger.info("Creating new order book")
        return self.DEFAULT_STATE.copy()
    
    def save_state(self):
        """Save state to JSON file."""
        try:
            # Update last scan time
            self.state["last_scan"] = datetime.now().isoformat()
            
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
            logger.info(f"Saved order book to {self.state_file}")
        except Exception as e:
            logger.error(f"Error saving state: {e}")
    
    @property
    def account(self) -> Dict:
        return self.state["account"]
    
    @property
    def open_positions(self) -> List[Dict]:
        return self.state["open_positions"]
    
    @property
    def closed_trades(self) -> List[Dict]:
        return self.state["closed_trades"]
    
    @property
    def settings(self) -> Dict:
        return self.state["settings"]
    
    def can_open_position(self, symbol: str) -> bool:
        """Check if we can open a new position."""
        # Check max positions
        if len(self.open_positions) >= self.settings["max_positions"]:
            return False
        
        # Check if already have position in symbol
        for pos in self.open_positions:
            if pos["symbol"] == symbol:
                return False
        
        return True
    
    def open_position(self, signal: Dict) -> Optional[Dict]:
        """
        Open a new position.
        
        Args:
            signal: Trade signal dictionary
            
        Returns:
            Position dict if opened, None if rejected
        """
        symbol = signal.get("symbol")
        
        if not self.can_open_position(symbol):
            logger.warning(f"Cannot open position in {symbol}")
            return None
        
        # Check capital
        position_value = signal.get("quantity", 0) * signal.get("entry_price", 0)
        if position_value > self.account["current_capital"] * 0.5:
            logger.warning(f"Position too large for {symbol}")
            return None
        
        # Create position
        self.state["trade_counter"] += 1
        
        position = {
            "id": self.state["trade_counter"],
            "symbol": symbol,
            "direction": signal.get("direction", "BUY"),
            "entry_price": signal.get("entry_price"),
            "entry_time": datetime.now().isoformat(),
            "quantity": signal.get("quantity"),
            "stop_loss": signal.get("stop_loss"),
            "take_profit": signal.get("take_profit"),
            "strategy": signal.get("strategy", "fib_3wave"),
            "trailing_stop": signal.get("stop_loss") if self.settings["use_trailing_stop"] else None,
            "highest_price": signal.get("entry_price") if signal.get("direction") == "BUY" else None,
            "lowest_price": signal.get("entry_price") if signal.get("direction") == "SELL" else None
        }
        
        self.open_positions.append(position)
        self.save_state()
        
        logger.info(f"Opened {position['direction']} position in {symbol} @ {position['entry_price']:.2f}")
        return position
    
    def close_position(self, symbol: str, exit_price: float, exit_reason: str) -> Optional[Dict]:
        """
        Close an open position.
        
        Args:
            symbol: Stock symbol
            exit_price: Exit price
            exit_reason: Reason for exit
            
        Returns:
            Closed trade dict
        """
        # Find position
        position = None
        position_idx = None
        for i, pos in enumerate(self.open_positions):
            if pos["symbol"] == symbol:
                position = pos
                position_idx = i
                break
        
        if position is None:
            logger.warning(f"No open position in {symbol}")
            return None
        
        # Calculate P&L
        if position["direction"] == "BUY":
            pnl = (exit_price - position["entry_price"]) * position["quantity"]
        else:
            pnl = (position["entry_price"] - exit_price) * position["quantity"]
        
        pnl_pct = pnl / (position["entry_price"] * position["quantity"]) * 100
        
        # Create closed trade
        closed_trade = {
            "id": position["id"],
            "symbol": symbol,
            "direction": position["direction"],
            "entry_price": position["entry_price"],
            "entry_time": position["entry_time"],
            "exit_price": exit_price,
            "exit_time": datetime.now().isoformat(),
            "exit_reason": exit_reason,
            "quantity": position["quantity"],
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "strategy": position["strategy"]
        }
        
        # Update account
        self.account["current_capital"] += pnl
        self.account["total_pnl"] += pnl
        self.account["total_trades"] += 1
        
        if pnl > 0:
            self.account["wins"] += 1
        else:
            self.account["losses"] += 1
        
        # Update win rate
        if self.account["total_trades"] > 0:
            self.account["win_rate"] = round(
                self.account["wins"] / self.account["total_trades"] * 100, 1
            )
        
        # Update peak and drawdown
        if self.account["current_capital"] > self.account["peak_capital"]:
            self.account["peak_capital"] = self.account["current_capital"]
        
        drawdown = (self.account["peak_capital"] - self.account["current_capital"]) / self.account["peak_capital"] * 100
        if drawdown > self.account["max_drawdown"]:
            self.account["max_drawdown"] = round(drawdown, 2)
        
        # Move to closed trades
        self.closed_trades.append(closed_trade)
        self.open_positions.pop(position_idx)
        
        # Update daily summary
        self._update_daily_summary(closed_trade)
        
        self.save_state()
        
        logger.info(f"Closed {symbol}: P&L = Rs {pnl:+,.2f} ({pnl_pct:+.2f}%)")
        return closed_trade
    
    def check_exits(self, current_prices: Dict[str, float]) -> List[Dict]:
        """
        Check all open positions for SL/TP hits.
        
        Args:
            current_prices: Dictionary of symbol -> current price
            
        Returns:
            List of closed trades
        """
        closed = []
        
        # Iterate over copy to allow modification
        for position in list(self.open_positions):
            symbol = position["symbol"]
            
            if symbol not in current_prices:
                continue
            
            price = current_prices[symbol]
            
            # Update trailing stop
            if self.settings["use_trailing_stop"]:
                self._update_trailing_stop(position, price)
            
            exit_reason = None
            
            if position["direction"] == "BUY":
                effective_sl = position.get("trailing_stop") or position["stop_loss"]
                
                if price <= effective_sl:
                    exit_reason = "trailing_stop" if position.get("trailing_stop") else "stop_loss"
                elif price >= position["take_profit"]:
                    exit_reason = "take_profit"
            
            else:  # SELL/SHORT
                effective_sl = position.get("trailing_stop") or position["stop_loss"]
                
                if price >= effective_sl:
                    exit_reason = "trailing_stop" if position.get("trailing_stop") else "stop_loss"
                elif price <= position["take_profit"]:
                    exit_reason = "take_profit"
            
            if exit_reason:
                closed_trade = self.close_position(symbol, price, exit_reason)
                if closed_trade:
                    closed.append(closed_trade)
        
        return closed
    
    def _update_trailing_stop(self, position: Dict, current_price: float):
        """Update trailing stop based on current price."""
        trailing_pct = self.settings["trailing_stop_pct"]
        
        if position["direction"] == "BUY":
            if position.get("highest_price") is None or current_price > position["highest_price"]:
                position["highest_price"] = current_price
                new_trailing = current_price * (1 - trailing_pct)
                if position.get("trailing_stop") is None or new_trailing > position["trailing_stop"]:
                    position["trailing_stop"] = round(new_trailing, 2)
        
        else:  # SELL/SHORT
            if position.get("lowest_price") is None or current_price < position["lowest_price"]:
                position["lowest_price"] = current_price
                new_trailing = current_price * (1 + trailing_pct)
                if position.get("trailing_stop") is None or new_trailing < position["trailing_stop"]:
                    position["trailing_stop"] = round(new_trailing, 2)
    
    def _update_daily_summary(self, trade: Dict):
        """Update daily summary."""
        today = datetime.now().strftime("%Y-%m-%d")
        
        if today not in self.state["daily_summary"]:
            self.state["daily_summary"][today] = {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "pnl": 0
            }
        
        summary = self.state["daily_summary"][today]
        summary["trades"] += 1
        summary["pnl"] += trade["pnl"]
        
        if trade["pnl"] > 0:
            summary["wins"] += 1
        else:
            summary["losses"] += 1
    
    def get_position(self, symbol: str) -> Optional[Dict]:
        """Get open position for symbol."""
        for pos in self.open_positions:
            if pos["symbol"] == symbol:
                return pos
        return None
    
    def get_unrealized_pnl(self, current_prices: Dict[str, float]) -> float:
        """Calculate unrealized P&L for all open positions."""
        total = 0
        for pos in self.open_positions:
            symbol = pos["symbol"]
            if symbol in current_prices:
                price = current_prices[symbol]
                if pos["direction"] == "BUY":
                    pnl = (price - pos["entry_price"]) * pos["quantity"]
                else:
                    pnl = (pos["entry_price"] - price) * pos["quantity"]
                total += pnl
        return total
    
    def get_daily_summary(self, date: str = None) -> Dict:
        """Get daily summary."""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        return self.state["daily_summary"].get(date, {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "pnl": 0
        })
    
    def get_performance_summary(self) -> Dict:
        """Get overall performance summary."""
        return {
            "total_trades": self.account["total_trades"],
            "wins": self.account["wins"],
            "losses": self.account["losses"],
            "win_rate": self.account["win_rate"],
            "total_pnl": round(self.account["total_pnl"], 2),
            "return_pct": round(
                (self.account["current_capital"] - self.account["initial_capital"]) 
                / self.account["initial_capital"] * 100, 2
            ),
            "current_capital": round(self.account["current_capital"], 2),
            "max_drawdown": self.account["max_drawdown"],
            "open_positions": len(self.open_positions),
            "profit_factor": self._calculate_profit_factor()
        }
    
    def _calculate_profit_factor(self) -> float:
        """Calculate profit factor (gross profit / gross loss)."""
        gross_profit = sum(t["pnl"] for t in self.closed_trades if t["pnl"] > 0)
        gross_loss = abs(sum(t["pnl"] for t in self.closed_trades if t["pnl"] < 0))
        
        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0
        
        return round(gross_profit / gross_loss, 2)
    
    def format_open_positions(self, current_prices: Dict[str, float] = None) -> str:
        """Format open positions for display."""
        if not self.open_positions:
            return "No open positions"
        
        lines = []
        for pos in self.open_positions:
            symbol = pos["symbol"]
            direction = pos["direction"]
            entry = pos["entry_price"]
            qty = pos["quantity"]
            sl = pos.get("trailing_stop") or pos["stop_loss"]
            tp = pos["take_profit"]
            
            line = f"{symbol}: {direction} {qty}x @ Rs {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f}"
            
            if current_prices and symbol in current_prices:
                price = current_prices[symbol]
                if direction == "BUY":
                    pnl = (price - entry) * qty
                else:
                    pnl = (entry - price) * qty
                line += f" | P&L: Rs {pnl:+,.2f}"
            
            lines.append(line)
        
        return "\n".join(lines)
    
    def reset(self, initial_capital: float = 100000):
        """Reset order book to initial state."""
        self.state = self.DEFAULT_STATE.copy()
        self.state["account"]["initial_capital"] = initial_capital
        self.state["account"]["current_capital"] = initial_capital
        self.state["account"]["peak_capital"] = initial_capital
        self.save_state()
        logger.info(f"Order book reset with capital Rs {initial_capital:,.2f}")


if __name__ == "__main__":
    # Test order book
    print("Testing Order Book...")
    
    book = OrderBook("test_order_book.json")
    
    # Test opening position
    signal = {
        "symbol": "RELIANCE",
        "direction": "BUY",
        "entry_price": 2500.0,
        "stop_loss": 2450.0,
        "take_profit": 2600.0,
        "quantity": 40,
        "strategy": "fib_3wave"
    }
    
    pos = book.open_position(signal)
    print(f"\nOpened position: {pos}")
    
    # Test checking exits
    print("\nChecking exits with price at 2600...")
    closed = book.check_exits({"RELIANCE": 2600.0})
    if closed:
        print(f"Closed: {closed[0]}")
    
    # Get summary
    summary = book.get_performance_summary()
    print(f"\nPerformance: {summary}")
    
    # Cleanup
    os.remove("test_order_book.json")
    print("\nTest complete!")
