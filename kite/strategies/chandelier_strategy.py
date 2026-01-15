"""
Chandelier Exit Strategy

A volatility-based trailing stop strategy using ATR to stay in trends until reversal.
Uses 200 EMA for trend confirmation.

Rules:
- Long Entry: Price above 200 EMA + Chandelier Exit flips bullish
- Short Entry: Price below 200 EMA + Chandelier Exit flips bearish
- Exit: When price closes beyond Chandelier Exit level
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import chandelier_exit, atr
from ..indicators.moving_averages import ema


class ChandelierExitStrategy(BaseStrategy):
    """
    Chandelier Exit Trend Following Strategy.
    
    Uses Chandelier Exit for trailing stops with EMA trend filter.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'chandelier_period': 22,
            'chandelier_multiplier': 3.0,
            'trend_ema_period': 200,
            'atr_period': 14,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "Chandelier_Exit"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate trading signals based on Chandelier Exit."""
        df = df.copy()
        self.validate_data(df)
        
        # Add Chandelier Exit
        df['chandelier_long'], df['chandelier_short'] = chandelier_exit(
            df, 
            self.params['chandelier_period'],
            self.params['chandelier_multiplier']
        )
        
        # Add trend EMA
        df['trend_ema'] = ema(df['close'], self.params['trend_ema_period'])
        
        # Add ATR for position sizing
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Determine Chandelier direction
        df['chandelier_bullish'] = df['close'] > df['chandelier_long']
        df['chandelier_bearish'] = df['close'] < df['chandelier_short']
        
        # Detect direction changes (flips)
        df['chandelier_flip_bull'] = (
            df['chandelier_bullish'] & ~df['chandelier_bullish'].shift(1).fillna(False)
        )
        df['chandelier_flip_bear'] = (
            df['chandelier_bearish'] & ~df['chandelier_bearish'].shift(1).fillna(False)
        )
        
        # Initialize signal column
        df['signal'] = 0
        
        # Skip if not enough data
        min_period = max(self.params['chandelier_period'], self.params['trend_ema_period'])
        if len(df) < min_period + 2:
            return df
        
        for i in range(min_period + 1, len(df)):
            idx = df.index[i]
            
            # Skip if data not available
            if pd.isna(df.loc[idx, 'trend_ema']) or pd.isna(df.loc[idx, 'chandelier_long']):
                continue
            
            current_close = df.loc[idx, 'close']
            trend_ema = df.loc[idx, 'trend_ema']
            
            # LONG SIGNAL: Price above 200 EMA + Chandelier flips bullish
            if df.loc[idx, 'chandelier_flip_bull'] and current_close > trend_ema:
                df.loc[idx, 'signal'] = Signal.BUY.value
            
            # SHORT SIGNAL: Price below 200 EMA + Chandelier flips bearish
            elif df.loc[idx, 'chandelier_flip_bear'] and current_close < trend_ema:
                df.loc[idx, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using Chandelier Exit level."""
        if direction == Signal.BUY:
            return df.loc[idx, 'chandelier_long']
        else:
            return df.loc[idx, 'chandelier_short']
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, direction: Signal,
                             entry_price: float, stop_loss: float) -> float:
        """Calculate take profit based on risk-reward ratio."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
