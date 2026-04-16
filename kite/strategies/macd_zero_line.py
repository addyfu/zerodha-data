"""
MACD Zero-Line Crossover Strategy
- MACD histogram crosses above zero = Long
- MACD histogram crosses below zero = Short
- Confirm with price above/below recent swing
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import macd
from ..indicators.volatility import atr


class MACDZeroLineStrategy(BaseStrategy):
    """MACD Zero-Line Crossover Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'fast_period': 12,
            'slow_period': 26,
            'signal_period': 9,
            'swing_lookback': 10,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on MACD zero-line crossover."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate MACD
        macd_line, signal_line, histogram = macd(
            df['close'], 
            self.params['fast_period'],
            self.params['slow_period'],
            self.params['signal_period']
        )
        
        df['macd'] = macd_line
        df['macd_signal'] = signal_line
        df['macd_hist'] = histogram
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Calculate swing highs/lows for confirmation
        lookback = self.params['swing_lookback']
        df['swing_high'] = df['high'].rolling(window=lookback).max()
        df['swing_low'] = df['low'].rolling(window=lookback).min()
        
        # Initialize signal column
        df['signal'] = 0
        
        # Long: Histogram crosses above zero + price above recent swing high
        long_condition = (
            (histogram > 0) &
            (histogram.shift(1) <= 0) &
            (macd_line > signal_line) &
            (df['close'] > df['swing_high'].shift(1))
        )
        
        # Short: Histogram crosses below zero + price below recent swing low
        short_condition = (
            (histogram < 0) &
            (histogram.shift(1) >= 0) &
            (macd_line < signal_line) &
            (df['close'] < df['swing_low'].shift(1))
        )
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using ATR."""
        atr_val = df.loc[idx, 'atr'] if 'atr' in df.columns else df['atr'].iloc[-1]
        entry_price = df.loc[idx, 'close']
        multiplier = self.params['atr_multiplier']
        
        if direction == Signal.BUY:
            return entry_price - (atr_val * multiplier)
        else:
            return entry_price + (atr_val * multiplier)
    
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
