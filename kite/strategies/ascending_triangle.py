"""
Ascending Triangle Breakout Strategy

Identify ascending triangle pattern (flat resistance + rising support).
Trade breakout above flat resistance with volume confirmation.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr


class AscendingTriangleStrategy(BaseStrategy):
    """Ascending Triangle breakout strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'lookback': 20,
            'resistance_tolerance': 0.005,  # 0.5% tolerance for flat resistance
            'min_touches': 2,  # Min touches on resistance
            'volume_multiplier': 1.5,  # Volume must be 1.5x average
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "Ascending_Triangle"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        self.validate_data(df)
        
        df['atr'] = atr(df, self.params['atr_period'])
        df['avg_volume'] = df['volume'].rolling(20).mean()
        
        # Initialize signal
        df['signal'] = 0
        
        lookback = self.params['lookback']
        tolerance = self.params['resistance_tolerance']
        
        for i in range(lookback + 5, len(df)):
            window = df.iloc[i-lookback:i]
            current_idx = df.index[i]
            current_close = df.loc[current_idx, 'close']
            current_high = df.loc[current_idx, 'high']
            current_volume = df.loc[current_idx, 'volume']
            avg_volume = df.loc[current_idx, 'avg_volume']
            
            # Find resistance level (highest highs that are relatively flat)
            highs = window['high']
            resistance = highs.max()
            
            # Count touches near resistance
            near_resistance = highs[highs >= resistance * (1 - tolerance)]
            touches = len(near_resistance)
            
            if touches < self.params['min_touches']:
                continue
            
            # Check for rising lows (ascending support)
            lows = window['low']
            first_half_low = lows.iloc[:len(lows)//2].min()
            second_half_low = lows.iloc[len(lows)//2:].min()
            
            rising_support = second_half_low > first_half_low
            
            if not rising_support:
                continue
            
            # Check for breakout
            prev_high = df.iloc[i-1]['high']
            breakout = current_close > resistance and prev_high <= resistance
            
            # Volume confirmation
            high_volume = current_volume > avg_volume * self.params['volume_multiplier']
            
            if breakout and high_volume:
                df.loc[current_idx, 'signal'] = Signal.BUY.value
            
            # Descending triangle (bearish) - flat support, falling highs
            support = lows.min()
            near_support = lows[lows <= support * (1 + tolerance)]
            support_touches = len(near_support)
            
            if support_touches >= self.params['min_touches']:
                first_half_high = highs.iloc[:len(highs)//2].max()
                second_half_high = highs.iloc[len(highs)//2:].max()
                
                falling_resistance = second_half_high < first_half_high
                
                if falling_resistance:
                    prev_low = df.iloc[i-1]['low']
                    breakdown = current_close < support and prev_low >= support
                    
                    if breakdown and high_volume:
                        df.loc[current_idx, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        entry_price = df.loc[idx, 'close']
        current_atr = df.loc[idx, 'atr']
        
        if direction == Signal.BUY:
            return entry_price - (current_atr * self.params['atr_multiplier'])
        else:
            return entry_price + (current_atr * self.params['atr_multiplier'])
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, direction: Signal,
                             entry_price: float, stop_loss: float) -> float:
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
