"""
McGinley Dynamic Strategy
- Adaptive moving average that adjusts to market speed
- Price above MD = Bullish, Price below MD = Bearish
- Less whipsaws than traditional MAs
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.moving_averages import mcginley_dynamic
from ..indicators.volatility import atr


class McGinleyDynamicStrategy(BaseStrategy):
    """McGinley Dynamic Indicator Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'md_period': 14,
            'confirmation_bars': 2,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on McGinley Dynamic."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate McGinley Dynamic
        df['md'] = mcginley_dynamic(df['close'], self.params['md_period'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Calculate MD slope
        df['md_slope'] = df['md'] - df['md'].shift(1)
        
        # Initialize signal column
        df['signal'] = 0
        
        conf_bars = self.params['confirmation_bars']
        
        # Price crosses above MD with positive slope
        price_above = df['close'] > df['md']
        price_was_below = df['close'].shift(conf_bars) <= df['md'].shift(conf_bars)
        md_rising = df['md_slope'] > 0
        
        # Confirm price stayed above for confirmation period
        price_confirmed_above = price_above.copy()
        for i in range(1, conf_bars):
            price_confirmed_above &= df['close'].shift(i) > df['md'].shift(i)
        
        long_condition = price_confirmed_above & price_was_below & md_rising
        
        # Price crosses below MD with negative slope
        price_below = df['close'] < df['md']
        price_was_above = df['close'].shift(conf_bars) >= df['md'].shift(conf_bars)
        md_falling = df['md_slope'] < 0
        
        price_confirmed_below = price_below.copy()
        for i in range(1, conf_bars):
            price_confirmed_below &= df['close'].shift(i) < df['md'].shift(i)
        
        short_condition = price_confirmed_below & price_was_above & md_falling
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using ATR from MD."""
        atr_val = df.loc[idx, 'atr'] if 'atr' in df.columns else df['atr'].iloc[-1]
        md_val = df.loc[idx, 'md']
        multiplier = self.params['atr_multiplier']
        
        if direction == Signal.BUY:
            return md_val - (atr_val * multiplier)
        else:
            return md_val + (atr_val * multiplier)
    
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
