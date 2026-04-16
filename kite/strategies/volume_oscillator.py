"""
Volume Oscillator Strategy
- Fast Volume MA - Slow Volume MA
- Oscillator > 0 = Volume expanding (confirms trend)
- Oscillator < 0 = Volume contracting (trend weakening)
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.moving_averages import ema, sma
from ..indicators.volatility import atr


class VolumeOscillatorStrategy(BaseStrategy):
    """Volume Oscillator Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'fast_period': 14,
            'slow_period': 28,
            'price_ema': 20,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on Volume Oscillator."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate Volume Oscillator
        fast_vol = ema(df['volume'], self.params['fast_period'])
        slow_vol = ema(df['volume'], self.params['slow_period'])
        df['vol_osc'] = ((fast_vol - slow_vol) / slow_vol) * 100
        
        df['price_ema'] = ema(df['close'], self.params['price_ema'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Price trend
        df['price_uptrend'] = df['close'] > df['price_ema']
        df['price_downtrend'] = df['close'] < df['price_ema']
        
        # Initialize signal column
        df['signal'] = 0
        
        # Long: Volume expanding (osc > 0) + price uptrend + osc crossing above 0
        long_condition = (
            (df['vol_osc'] > 0) &
            (df['vol_osc'].shift(1) <= 0) &
            df['price_uptrend'] &
            (df['close'] > df['close'].shift(1))  # Price rising
        )
        
        # Short: Volume expanding + price downtrend + osc crossing above 0
        short_condition = (
            (df['vol_osc'] > 0) &
            (df['vol_osc'].shift(1) <= 0) &
            df['price_downtrend'] &
            (df['close'] < df['close'].shift(1))  # Price falling
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
