"""
TRIX Zero-Line Strategy
- TRIX crosses above zero + price breaks resistance = Long
- TRIX crosses below zero + price breaks support = Short
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.moving_averages import ema
from ..indicators.volatility import atr


def trix(series: pd.Series, period: int = 15) -> pd.Series:
    """Calculate TRIX indicator (Triple Exponential Moving Average ROC)."""
    ema1 = ema(series, period)
    ema2 = ema(ema1, period)
    ema3 = ema(ema2, period)
    
    trix_val = ((ema3 - ema3.shift(1)) / ema3.shift(1)) * 100
    return trix_val


class TRIXZeroLineStrategy(BaseStrategy):
    """TRIX Zero-Line Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'trix_period': 15,
            'sr_lookback': 20,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on TRIX zero-line cross."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate TRIX
        df['trix'] = trix(df['close'], self.params['trix_period'])
        
        # S/R levels
        lookback = self.params['sr_lookback']
        df['resistance'] = df['high'].rolling(window=lookback).max()
        df['support'] = df['low'].rolling(window=lookback).min()
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # TRIX crosses
        trix_cross_up = (df['trix'] > 0) & (df['trix'].shift(1) <= 0)
        trix_cross_down = (df['trix'] < 0) & (df['trix'].shift(1) >= 0)
        
        # Price breakouts
        price_break_up = df['close'] > df['resistance'].shift(1)
        price_break_down = df['close'] < df['support'].shift(1)
        
        # Initialize signal column
        df['signal'] = 0
        
        # Long: TRIX crosses above zero + price breaks resistance
        long_condition = trix_cross_up & price_break_up
        
        # Short: TRIX crosses below zero + price breaks support
        short_condition = trix_cross_down & price_break_down
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using ATR."""
        atr_val = df.loc[idx, 'atr']
        entry_price = df.loc[idx, 'close']
        mult = self.params['atr_multiplier']
        
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
