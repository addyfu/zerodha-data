"""
ADX Filter Strategy
- Only trade when ADX > 25 (trending market)
- Avoid trades when ADX < 20 (ranging market)
- Use DI crossovers for direction
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import adx
from ..indicators.volatility import atr


class ADXFilterStrategy(BaseStrategy):
    """ADX Filter Strategy - Trade only in trending markets."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'adx_period': 14,
            'adx_threshold': 25,
            'adx_strong': 40,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on ADX trend strength."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate ADX and DI
        adx_val, plus_di, minus_di = adx(df, self.params['adx_period'])
        
        df['adx'] = adx_val
        df['plus_di'] = plus_di
        df['minus_di'] = minus_di
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        threshold = self.params['adx_threshold']
        
        # Strong trend filter
        trending = df['adx'] > threshold
        adx_rising = df['adx'] > df['adx'].shift(1)
        
        # Long: ADX > threshold + +DI crosses above -DI + ADX rising
        long_condition = (
            trending &
            adx_rising &
            (df['plus_di'] > df['minus_di']) &
            (df['plus_di'].shift(1) <= df['minus_di'].shift(1))
        )
        
        # Short: ADX > threshold + -DI crosses above +DI + ADX rising
        short_condition = (
            trending &
            adx_rising &
            (df['minus_di'] > df['plus_di']) &
            (df['minus_di'].shift(1) <= df['plus_di'].shift(1))
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
