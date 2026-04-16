"""
Choppiness + Volume Strategy
- High CI + Low volume = Consolidation
- CI drops + Volume increases = Breakout confirmation
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr
from ..indicators.moving_averages import sma


def choppiness_index(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Choppiness Index."""
    atr_val = atr(df, 1)
    atr_sum = atr_val.rolling(window=period).sum()
    
    high_max = df['high'].rolling(window=period).max()
    low_min = df['low'].rolling(window=period).min()
    
    ci = 100 * np.log10(atr_sum / (high_max - low_min)) / np.log10(period)
    return ci


class ChoppinessVolumeStrategy(BaseStrategy):
    """Choppiness + Volume Breakout Confirmation Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'ci_period': 14,
            'ci_choppy': 61.8,
            'volume_period': 20,
            'volume_low_mult': 0.8,
            'volume_high_mult': 1.5,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on CI + Volume."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate Choppiness Index
        df['ci'] = choppiness_index(df, self.params['ci_period'])
        
        # Volume analysis
        df['volume_sma'] = sma(df['volume'], self.params['volume_period'])
        df['volume_low'] = df['volume'] < (df['volume_sma'] * self.params['volume_low_mult'])
        df['volume_high'] = df['volume'] > (df['volume_sma'] * self.params['volume_high_mult'])
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Market states
        ci_choppy = self.params['ci_choppy']
        df['consolidation'] = (df['ci'] > ci_choppy) & df['volume_low']
        df['breakout_signal'] = (df['ci'] < ci_choppy) & df['volume_high']
        
        # Price direction
        df['price_up'] = df['close'] > df['close'].shift(1)
        df['price_down'] = df['close'] < df['close'].shift(1)
        
        # Initialize signal column
        df['signal'] = 0
        
        # Was consolidating, now breaking out
        was_consolidating = df['consolidation'].shift(1)
        
        # Long: Was consolidating + breakout signal + price up
        long_condition = (
            was_consolidating &
            df['breakout_signal'] &
            df['price_up']
        )
        
        # Short: Was consolidating + breakout signal + price down
        short_condition = (
            was_consolidating &
            df['breakout_signal'] &
            df['price_down']
        )
        
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
