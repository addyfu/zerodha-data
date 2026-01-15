"""
Base Strategy Class - Abstract base for all trading strategies.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any
from enum import Enum
import pandas as pd
import numpy as np


class Signal(Enum):
    """Trading signal types."""
    BUY = 1
    SELL = -1
    HOLD = 0


@dataclass
class TradeSignal:
    """Represents a trading signal with all necessary information."""
    timestamp: pd.Timestamp
    signal: Signal
    entry_price: float
    stop_loss: float
    take_profit: float
    quantity: int = 0
    reason: str = ""
    confidence: float = 1.0  # 0.0 to 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': self.timestamp,
            'signal': self.signal.value,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'quantity': self.quantity,
            'reason': self.reason,
            'confidence': self.confidence,
        }


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    
    All strategies must implement:
    - generate_signals(): Generate buy/sell signals
    - calculate_stop_loss(): Calculate stop loss for a trade
    - calculate_take_profit(): Calculate take profit for a trade
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        """
        Initialize strategy with parameters.
        
        Args:
            params: Strategy-specific parameters
        """
        self.params = params or {}
        self.name = self.__class__.__name__
        
    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate trading signals for the given data.
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            DataFrame with additional 'signal' column:
                1 = BUY, -1 = SELL, 0 = HOLD
        """
        pass
    
    @abstractmethod
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, 
                           direction: Signal) -> float:
        """
        Calculate stop loss price for a trade.
        
        Args:
            df: DataFrame with OHLCV data
            idx: Index of the entry candle
            direction: Trade direction (BUY or SELL)
            
        Returns:
            Stop loss price
        """
        pass
    
    @abstractmethod
    def calculate_take_profit(self, df: pd.DataFrame, idx: int,
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """
        Calculate take profit price for a trade.
        
        Args:
            df: DataFrame with OHLCV data
            idx: Index of the entry candle
            direction: Trade direction (BUY or SELL)
            entry_price: Entry price of the trade
            stop_loss: Stop loss price
            
        Returns:
            Take profit price
        """
        pass
    
    def get_trade_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Get complete trade signals with entry, SL, and TP.
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            DataFrame with signals and trade parameters
        """
        # Generate raw signals
        df = self.generate_signals(df.copy())
        
        # Initialize trade parameter columns
        df['entry_price'] = np.nan
        df['stop_loss'] = np.nan
        df['take_profit'] = np.nan
        
        # Calculate trade parameters for each signal
        for idx in df.index:
            if df.loc[idx, 'signal'] == Signal.BUY.value:
                df.loc[idx, 'entry_price'] = df.loc[idx, 'close']
                df.loc[idx, 'stop_loss'] = self.calculate_stop_loss(
                    df, idx, Signal.BUY)
                df.loc[idx, 'take_profit'] = self.calculate_take_profit(
                    df, idx, Signal.BUY, 
                    df.loc[idx, 'entry_price'],
                    df.loc[idx, 'stop_loss'])
                    
            elif df.loc[idx, 'signal'] == Signal.SELL.value:
                df.loc[idx, 'entry_price'] = df.loc[idx, 'close']
                df.loc[idx, 'stop_loss'] = self.calculate_stop_loss(
                    df, idx, Signal.SELL)
                df.loc[idx, 'take_profit'] = self.calculate_take_profit(
                    df, idx, Signal.SELL,
                    df.loc[idx, 'entry_price'],
                    df.loc[idx, 'stop_loss'])
        
        return df
    
    def validate_data(self, df: pd.DataFrame) -> bool:
        """
        Validate that DataFrame has required columns.
        
        Args:
            df: DataFrame to validate
            
        Returns:
            True if valid, raises ValueError otherwise
        """
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        missing = [col for col in required_columns if col not in df.columns]
        
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        
        if df.empty:
            raise ValueError("DataFrame is empty")
            
        return True
    
    def get_params(self) -> Dict[str, Any]:
        """Get strategy parameters."""
        return self.params.copy()
    
    def set_params(self, params: Dict[str, Any]) -> None:
        """Set strategy parameters."""
        self.params.update(params)
    
    def __repr__(self) -> str:
        return f"{self.name}(params={self.params})"
