"""
CCI Zero-Line Cross Strategy
- CCI crosses above zero + price above MA = Long
- CCI crosses below zero + price below MA = Short
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import cci
from ..indicators.moving_averages import ema
from ..indicators.volatility import atr


class CCIZeroCrossStrategy(BaseStrategy):
    """CCI Zero-Line Cross Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'cci_period': 21,
            'ma_period': 50,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on CCI zero-line cross."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate indicators
        df['cci'] = cci(df, self.params['cci_period'])
        df['ma'] = ema(df['close'], self.params['ma_period'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        # CCI crosses above zero
        cci_cross_up = (df['cci'] > 0) & (df['cci'].shift(1) <= 0)
        
        # CCI crosses below zero
        cci_cross_down = (df['cci'] < 0) & (df['cci'].shift(1) >= 0)
        
        # Long: CCI crosses above zero + price above MA
        long_condition = cci_cross_up & (df['close'] > df['ma'])
        
        # Short: CCI crosses below zero + price below MA
        short_condition = cci_cross_down & (df['close'] < df['ma'])
        
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
