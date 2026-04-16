"""
Swing Pivot Trading Strategy
- Swing highs = Resistance levels
- Swing lows = Support levels
- Trade bounces from these levels
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr


class SwingPivotStrategy(BaseStrategy):
    """Swing Pivot Trading Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'swing_lookback': 5,  # Bars to look for swing points
            'sr_lookback': 50,  # Lookback for S/R levels
            'touch_tolerance': 0.005,  # 0.5% tolerance
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def _find_swing_points(self, df: pd.DataFrame, lookback: int) -> tuple:
        """Find swing highs and swing lows."""
        swing_highs = []
        swing_lows = []
        
        for i in range(lookback, len(df) - lookback):
            # Swing high: Higher than surrounding bars
            if df['high'].iloc[i] == df['high'].iloc[i-lookback:i+lookback+1].max():
                swing_highs.append((df.index[i], df['high'].iloc[i]))
            
            # Swing low: Lower than surrounding bars
            if df['low'].iloc[i] == df['low'].iloc[i-lookback:i+lookback+1].min():
                swing_lows.append((df.index[i], df['low'].iloc[i]))
        
        return swing_highs, swing_lows
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on swing pivot bounces."""
        df = df.copy()
        self.validate_data(df)
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        swing_lookback = self.params['swing_lookback']
        sr_lookback = self.params['sr_lookback']
        tolerance = self.params['touch_tolerance']
        
        for i in range(sr_lookback, len(df)):
            idx = df.index[i]
            
            # Find swing points in lookback window
            window = df.iloc[max(0, i-sr_lookback):i]
            swing_highs, swing_lows = self._find_swing_points(window, swing_lookback)
            
            current_close = df.loc[idx, 'close']
            current_low = df.loc[idx, 'low']
            current_high = df.loc[idx, 'high']
            
            # Check for support bounce
            for _, support_level in swing_lows[-5:]:  # Last 5 swing lows
                level_tolerance = support_level * tolerance
                
                if (current_low <= support_level + level_tolerance and
                    current_low >= support_level - level_tolerance and
                    current_close > support_level and
                    current_close > df['open'].iloc[i]):
                    df.loc[idx, 'signal'] = Signal.BUY.value
                    break
            
            # Check for resistance rejection
            for _, resistance_level in swing_highs[-5:]:  # Last 5 swing highs
                level_tolerance = resistance_level * tolerance
                
                if (current_high >= resistance_level - level_tolerance and
                    current_high <= resistance_level + level_tolerance and
                    current_close < resistance_level and
                    current_close < df['open'].iloc[i]):
                    df.loc[idx, 'signal'] = Signal.SELL.value
                    break
        
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
