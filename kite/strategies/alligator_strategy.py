"""
Alligator Indicator Pullback Strategy

Uses Bill Williams' Alligator (3 smoothed MAs) for dynamic S/R and trend following.

Rules:
- Lips (Green) = 5-period SMMA, shifted 3 bars
- Teeth (Red) = 8-period SMMA, shifted 5 bars  
- Jaws (Blue) = 13-period SMMA, shifted 8 bars
- Long: All lines pointing up (perfect order) + pullback to Lips/Teeth
- Short: All lines pointing down + pullback to Lips/Teeth
- Exit: When Lips crosses back through Teeth
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.trend import add_alligator
from ..indicators.volatility import atr


class AlligatorStrategy(BaseStrategy):
    """
    Bill Williams' Alligator Pullback Strategy.
    
    Uses Alligator indicator for trend following with pullback entries.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'jaw_period': 13,
            'jaw_shift': 8,
            'teeth_period': 8,
            'teeth_shift': 5,
            'lips_period': 5,
            'lips_shift': 3,
            'pullback_tolerance': 0.002,  # How close price needs to get to MA
            'atr_period': 14,
            'atr_sl_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "Alligator"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate trading signals based on Alligator indicator."""
        df = df.copy()
        self.validate_data(df)
        
        # Add Alligator indicator
        df = add_alligator(
            df,
            self.params['jaw_period'],
            self.params['jaw_shift'],
            self.params['teeth_period'],
            self.params['teeth_shift'],
            self.params['lips_period'],
            self.params['lips_shift']
        )
        
        # Add ATR
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Calculate mouth width (trend strength)
        df['alligator_width'] = abs(df['alligator_lips'] - df['alligator_jaw'])
        
        # Detect pullbacks to Lips or Teeth
        tolerance = self.params['pullback_tolerance']
        
        # Bullish pullback: Price pulls back to touch Lips or Teeth in uptrend
        df['pullback_to_lips'] = (
            (df['low'] <= df['alligator_lips'] * (1 + tolerance)) &
            (df['close'] > df['alligator_lips'])
        )
        df['pullback_to_teeth'] = (
            (df['low'] <= df['alligator_teeth'] * (1 + tolerance)) &
            (df['close'] > df['alligator_teeth'])
        )
        
        # Bearish pullback: Price pulls back to touch Lips or Teeth in downtrend
        df['rally_to_lips'] = (
            (df['high'] >= df['alligator_lips'] * (1 - tolerance)) &
            (df['close'] < df['alligator_lips'])
        )
        df['rally_to_teeth'] = (
            (df['high'] >= df['alligator_teeth'] * (1 - tolerance)) &
            (df['close'] < df['alligator_teeth'])
        )
        
        # Initialize signal column
        df['signal'] = 0
        
        # Skip if not enough data
        min_period = self.params['jaw_period'] + self.params['jaw_shift'] + 5
        if len(df) < min_period + 2:
            return df
        
        for i in range(min_period + 1, len(df)):
            idx = df.index[i]
            
            # Skip if data not available or Alligator is sleeping
            if pd.isna(df.loc[idx, 'alligator_jaw']) or df.loc[idx, 'alligator_sleeping']:
                continue
            
            # LONG SIGNAL: Bullish perfect order + pullback to Lips/Teeth
            if df.loc[idx, 'alligator_bullish']:
                if df.loc[idx, 'pullback_to_lips'] or df.loc[idx, 'pullback_to_teeth']:
                    df.loc[idx, 'signal'] = Signal.BUY.value
            
            # SHORT SIGNAL: Bearish perfect order + rally to Lips/Teeth
            elif df.loc[idx, 'alligator_bearish']:
                if df.loc[idx, 'rally_to_lips'] or df.loc[idx, 'rally_to_teeth']:
                    df.loc[idx, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using Alligator Jaw and ATR."""
        entry_price = df.loc[idx, 'close']
        current_atr = df.loc[idx, 'atr']
        jaw = df.loc[idx, 'alligator_jaw']
        
        if direction == Signal.BUY:
            # Stop below Jaw (strongest support) or ATR-based
            jaw_stop = jaw * 0.995
            atr_stop = entry_price - (current_atr * self.params['atr_sl_multiplier'])
            return max(jaw_stop, atr_stop)
        else:
            # Stop above Jaw (strongest resistance) or ATR-based
            jaw_stop = jaw * 1.005
            atr_stop = entry_price + (current_atr * self.params['atr_sl_multiplier'])
            return min(jaw_stop, atr_stop)
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, direction: Signal,
                             entry_price: float, stop_loss: float) -> float:
        """Calculate take profit based on risk-reward ratio."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
