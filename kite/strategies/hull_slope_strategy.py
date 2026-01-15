"""
Hull Moving Average Slope Strategy

Uses the HMA slope (not crossovers) to identify trend changes with minimal lag.

Rules:
- Use 50-period HMA for trend direction
- Use 7-period HMA for entry timing
- Long: Both HMA slopes pointing UP
- Short: Both HMA slopes pointing DOWN
- Entry: When 7-period HMA turns in direction of 50-period HMA
- Exit: When 7-period HMA slope reverses
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.moving_averages import hma, ma_slope
from ..indicators.volatility import atr


class HullSlopeStrategy(BaseStrategy):
    """
    Hull Moving Average Slope Strategy.
    
    Uses HMA slope changes for low-lag trend following.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'fast_hma_period': 7,
            'slow_hma_period': 50,
            'slope_period': 2,  # Bars to calculate slope
            'atr_period': 14,
            'atr_sl_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "Hull_Slope"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate trading signals based on HMA slope."""
        df = df.copy()
        self.validate_data(df)
        
        # Add HMAs
        df['hma_fast'] = hma(df['close'], self.params['fast_hma_period'])
        df['hma_slow'] = hma(df['close'], self.params['slow_hma_period'])
        
        # Calculate slopes
        df['hma_fast_slope'] = ma_slope(df['hma_fast'], self.params['slope_period'])
        df['hma_slow_slope'] = ma_slope(df['hma_slow'], self.params['slope_period'])
        
        # Determine slope direction
        df['fast_slope_up'] = df['hma_fast_slope'] > 0
        df['slow_slope_up'] = df['hma_slow_slope'] > 0
        
        # Detect slope changes (hooks)
        df['fast_hook_up'] = df['fast_slope_up'] & ~df['fast_slope_up'].shift(1).fillna(False)
        df['fast_hook_down'] = ~df['fast_slope_up'] & df['fast_slope_up'].shift(1).fillna(True)
        
        # Add ATR
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        # Skip if not enough data
        min_period = self.params['slow_hma_period'] + self.params['slope_period']
        if len(df) < min_period + 2:
            return df
        
        for i in range(min_period + 1, len(df)):
            idx = df.index[i]
            
            # Skip if data not available
            if pd.isna(df.loc[idx, 'hma_slow']) or pd.isna(df.loc[idx, 'atr']):
                continue
            
            # LONG SIGNAL: Fast HMA hooks up while slow HMA slope is up
            if df.loc[idx, 'fast_hook_up'] and df.loc[idx, 'slow_slope_up']:
                df.loc[idx, 'signal'] = Signal.BUY.value
            
            # SHORT SIGNAL: Fast HMA hooks down while slow HMA slope is down
            elif df.loc[idx, 'fast_hook_down'] and not df.loc[idx, 'slow_slope_up']:
                df.loc[idx, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using ATR and HMA levels."""
        entry_price = df.loc[idx, 'close']
        current_atr = df.loc[idx, 'atr']
        hma_slow = df.loc[idx, 'hma_slow']
        
        if direction == Signal.BUY:
            # Stop below slow HMA or ATR-based
            hma_stop = hma_slow * 0.99
            atr_stop = entry_price - (current_atr * self.params['atr_sl_multiplier'])
            return max(hma_stop, atr_stop)
        else:
            # Stop above slow HMA or ATR-based
            hma_stop = hma_slow * 1.01
            atr_stop = entry_price + (current_atr * self.params['atr_sl_multiplier'])
            return min(hma_stop, atr_stop)
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, direction: Signal,
                             entry_price: float, stop_loss: float) -> float:
        """Calculate take profit based on risk-reward ratio."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
