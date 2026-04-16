"""
Chaikin Money Flow (CMF) Strategy
- CMF > 0 = Buying pressure (bullish)
- CMF < 0 = Selling pressure (bearish)
- CMF divergence = Potential reversal
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volume import chaikin_money_flow
from ..indicators.moving_averages import ema
from ..indicators.volatility import atr


class CMFStrategy(BaseStrategy):
    """Chaikin Money Flow Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'cmf_period': 20,
            'ema_period': 50,
            'cmf_threshold': 0.05,  # Minimum CMF for signal
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on CMF."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate CMF
        df['cmf'] = chaikin_money_flow(df, self.params['cmf_period'])
        df['ema'] = ema(df['close'], self.params['ema_period'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # CMF crosses
        threshold = self.params['cmf_threshold']
        
        # Initialize signal column
        df['signal'] = 0
        
        # Long: CMF crosses above threshold + price above EMA
        long_condition = (
            (df['cmf'] > threshold) &
            (df['cmf'].shift(1) <= threshold) &
            (df['close'] > df['ema'])
        )
        
        # Short: CMF crosses below -threshold + price below EMA
        short_condition = (
            (df['cmf'] < -threshold) &
            (df['cmf'].shift(1) >= -threshold) &
            (df['close'] < df['ema'])
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
