"""
Golden Ratio (61.8%) Strategy
- Focus on the 50-61.8% retracement zone
- Enter on rejection from 61.8%
- Stop above 78.6%
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr


class GoldenRatioStrategy(BaseStrategy):
    """Golden Ratio (61.8%) Fibonacci Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'swing_lookback': 30,
            'golden_zone_low': 0.5,
            'golden_zone_high': 0.618,
            'stop_level': 0.786,
            'tolerance': 0.015,
            'atr_period': 14,
            'risk_reward': 2.5,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on Golden Ratio zone."""
        df = df.copy()
        self.validate_data(df)
        
        lookback = self.params['swing_lookback']
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Find swing points
        df['swing_high'] = df['high'].rolling(window=lookback).max()
        df['swing_low'] = df['low'].rolling(window=lookback).min()
        
        # Initialize signal column
        df['signal'] = 0
        
        zone_low = self.params['golden_zone_low']
        zone_high = self.params['golden_zone_high']
        tolerance = self.params['tolerance']
        
        for i in range(lookback * 2, len(df)):
            idx = df.index[i]
            
            swing_high = df.loc[idx, 'swing_high']
            swing_low = df.loc[idx, 'swing_low']
            swing_range = swing_high - swing_low
            
            if swing_range <= 0:
                continue
            
            current_close = df.loc[idx, 'close']
            current_low = df.loc[idx, 'low']
            current_high = df.loc[idx, 'high']
            
            # Determine trend
            window = df.iloc[i-lookback:i+1]
            swing_high_pos = window['high'].idxmax()
            swing_low_pos = window['low'].idxmin()
            
            is_uptrend = swing_low_pos < swing_high_pos
            is_downtrend = swing_high_pos < swing_low_pos
            
            # Golden zone levels
            if is_uptrend:
                zone_top = swing_high - (swing_range * zone_low)
                zone_bottom = swing_high - (swing_range * zone_high)
                
                # Price in golden zone
                in_zone = (current_low <= zone_top) & (current_low >= zone_bottom * (1 - tolerance))
                
                # Rejection candle (wick below but close above)
                rejection = (
                    (current_low < zone_bottom) &
                    (current_close > zone_bottom) &
                    (current_close > df['open'].iloc[i])
                )
                
                if in_zone and rejection:
                    df.loc[idx, 'signal'] = Signal.BUY.value
            
            elif is_downtrend:
                zone_bottom = swing_low + (swing_range * zone_low)
                zone_top = swing_low + (swing_range * zone_high)
                
                in_zone = (current_high >= zone_bottom) & (current_high <= zone_top * (1 + tolerance))
                
                rejection = (
                    (current_high > zone_top) &
                    (current_close < zone_top) &
                    (current_close < df['open'].iloc[i])
                )
                
                if in_zone and rejection:
                    df.loc[idx, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Stop loss at 78.6% level."""
        swing_high = df.loc[idx, 'swing_high']
        swing_low = df.loc[idx, 'swing_low']
        swing_range = swing_high - swing_low
        stop_level = self.params['stop_level']
        
        if direction == Signal.BUY:
            return swing_high - (swing_range * stop_level)
        else:
            return swing_low + (swing_range * stop_level)
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, 
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """Target at swing high/low or extension."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
