"""
Moving Average Crossover Swing Trading Strategy
- EMA 10 crosses above EMA 20 + price above both = Long
- EMA 10 crosses below EMA 20 + price below both = Short
- Volume confirmation
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.moving_averages import ema, sma
from ..indicators.volatility import atr


class MACrossoverSwingStrategy(BaseStrategy):
    """Moving Average Crossover for Swing Trading."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'fast_period': 10,
            'slow_period': 20,
            'volume_period': 20,
            'volume_multiplier': 1.2,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on MA crossover."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate EMAs
        df['ema_fast'] = ema(df['close'], self.params['fast_period'])
        df['ema_slow'] = ema(df['close'], self.params['slow_period'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Volume confirmation
        df['volume_sma'] = sma(df['volume'], self.params['volume_period'])
        df['volume_high'] = df['volume'] > (df['volume_sma'] * self.params['volume_multiplier'])
        
        # Initialize signal column
        df['signal'] = 0
        
        # Bullish crossover
        bullish_cross = (
            (df['ema_fast'] > df['ema_slow']) &
            (df['ema_fast'].shift(1) <= df['ema_slow'].shift(1))
        )
        
        # Bearish crossover
        bearish_cross = (
            (df['ema_fast'] < df['ema_slow']) &
            (df['ema_fast'].shift(1) >= df['ema_slow'].shift(1))
        )
        
        # Long: Bullish cross + price above both EMAs + volume
        long_condition = (
            bullish_cross &
            (df['close'] > df['ema_fast']) &
            (df['close'] > df['ema_slow']) &
            df['volume_high']
        )
        
        # Short: Bearish cross + price below both EMAs
        short_condition = (
            bearish_cross &
            (df['close'] < df['ema_fast']) &
            (df['close'] < df['ema_slow'])
        )
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss below/above slow EMA."""
        atr_val = df.loc[idx, 'atr'] if 'atr' in df.columns else df['atr'].iloc[-1]
        ema_slow = df.loc[idx, 'ema_slow']
        
        if direction == Signal.BUY:
            return ema_slow - atr_val
        else:
            return ema_slow + atr_val
    
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
