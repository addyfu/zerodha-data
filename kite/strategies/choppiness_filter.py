"""
Choppiness Index Filter Strategy
- CI > 61.8 = Choppy/Ranging market (avoid)
- CI < 38.2 = Trending market (trade)
- Use as filter for other strategies
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr
from ..indicators.moving_averages import ema


def choppiness_index(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Choppiness Index."""
    atr_val = atr(df, 1)  # True Range
    atr_sum = atr_val.rolling(window=period).sum()
    
    high_max = df['high'].rolling(window=period).max()
    low_min = df['low'].rolling(window=period).min()
    
    ci = 100 * np.log10(atr_sum / (high_max - low_min)) / np.log10(period)
    return ci


class ChoppinessFilterStrategy(BaseStrategy):
    """Choppiness Index Filter Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'ci_period': 14,
            'ci_choppy': 61.8,
            'ci_trending': 38.2,
            'ema_fast': 10,
            'ema_slow': 20,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals only in trending markets."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate Choppiness Index
        df['ci'] = choppiness_index(df, self.params['ci_period'])
        
        # EMAs for direction
        df['ema_fast'] = ema(df['close'], self.params['ema_fast'])
        df['ema_slow'] = ema(df['close'], self.params['ema_slow'])
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Market condition
        df['trending'] = df['ci'] < self.params['ci_trending']
        df['choppy'] = df['ci'] > self.params['ci_choppy']
        
        # EMA crossovers
        ema_bullish_cross = (
            (df['ema_fast'] > df['ema_slow']) &
            (df['ema_fast'].shift(1) <= df['ema_slow'].shift(1))
        )
        
        ema_bearish_cross = (
            (df['ema_fast'] < df['ema_slow']) &
            (df['ema_fast'].shift(1) >= df['ema_slow'].shift(1))
        )
        
        # Initialize signal column
        df['signal'] = 0
        
        # Long: Trending market + bullish EMA cross
        long_condition = df['trending'] & ema_bullish_cross
        
        # Short: Trending market + bearish EMA cross
        short_condition = df['trending'] & ema_bearish_cross
        
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
