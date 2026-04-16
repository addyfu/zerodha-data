"""
ATR Breakout Strategy
- Price breaks above previous day high + 0.5 ATR = Long
- Price breaks below previous day low - 0.5 ATR = Short
- Volume confirmation
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr
from ..indicators.moving_averages import sma


class ATRBreakoutStrategy(BaseStrategy):
    """ATR Breakout Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'atr_period': 14,
            'atr_breakout_mult': 0.5,
            'volume_period': 20,
            'volume_mult': 1.2,
            'atr_stop_mult': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on ATR breakout."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate ATR
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Previous day high/low (use shift for daily data)
        df['prev_high'] = df['high'].shift(1)
        df['prev_low'] = df['low'].shift(1)
        
        # Breakout levels
        breakout_mult = self.params['atr_breakout_mult']
        df['long_breakout'] = df['prev_high'] + (df['atr'] * breakout_mult)
        df['short_breakout'] = df['prev_low'] - (df['atr'] * breakout_mult)
        
        # Volume confirmation
        df['volume_sma'] = sma(df['volume'], self.params['volume_period'])
        df['volume_high'] = df['volume'] > (df['volume_sma'] * self.params['volume_mult'])
        
        # Initialize signal column
        df['signal'] = 0
        
        # Long: Price breaks above long_breakout + volume
        long_condition = (
            (df['close'] > df['long_breakout']) &
            (df['close'].shift(1) <= df['long_breakout'].shift(1)) &
            df['volume_high']
        )
        
        # Short: Price breaks below short_breakout + volume
        short_condition = (
            (df['close'] < df['short_breakout']) &
            (df['close'].shift(1) >= df['short_breakout'].shift(1)) &
            df['volume_high']
        )
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using ATR."""
        atr_val = df.loc[idx, 'atr']
        entry_price = df.loc[idx, 'close']
        mult = self.params['atr_stop_mult']
        
        if direction == Signal.BUY:
            return entry_price - (atr_val * mult)
        else:
            return entry_price + (atr_val * mult)
    
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
