"""
ATR Trailing Stop Strategy
- Uses ATR-based trailing stop for trend following
- Entry on breakout, exit when trailing stop hit
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr
from ..indicators.moving_averages import ema


class ATRTrailingStopStrategy(BaseStrategy):
    """ATR Trailing Stop Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'atr_period': 14,
            'atr_multiplier': 3.0,
            'ema_period': 50,
            'breakout_period': 20,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on ATR trailing stop."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate indicators
        df['atr'] = atr(df, self.params['atr_period'])
        df['ema'] = ema(df['close'], self.params['ema_period'])
        
        # Breakout levels
        period = self.params['breakout_period']
        df['highest_high'] = df['high'].rolling(window=period).max()
        df['lowest_low'] = df['low'].rolling(window=period).min()
        
        # ATR trailing stop levels
        mult = self.params['atr_multiplier']
        df['long_stop'] = df['highest_high'] - (df['atr'] * mult)
        df['short_stop'] = df['lowest_low'] + (df['atr'] * mult)
        
        # Initialize signal column
        df['signal'] = 0
        
        # Long: Price breaks above highest high + above EMA
        long_condition = (
            (df['close'] > df['highest_high'].shift(1)) &
            (df['close'] > df['ema']) &
            (df['close'].shift(1) <= df['highest_high'].shift(2))
        )
        
        # Short: Price breaks below lowest low + below EMA
        short_condition = (
            (df['close'] < df['lowest_low'].shift(1)) &
            (df['close'] < df['ema']) &
            (df['close'].shift(1) >= df['lowest_low'].shift(2))
        )
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using ATR trailing stop."""
        if direction == Signal.BUY:
            return df.loc[idx, 'long_stop']
        else:
            return df.loc[idx, 'short_stop']
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, 
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """Calculate take profit based on risk-reward ratio."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
