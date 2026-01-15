"""
Fibonacci Pivot Points Strategy

Combines Fibonacci ratios with pivot point calculations for precise S/R levels.

Rules:
- Calculate central pivot point = (H + L + C) / 3
- R1 = Pivot + (0.382 × Range), R2 = Pivot + (0.618 × Range)
- S1 = Pivot - (0.382 × Range), S2 = Pivot - (0.618 × Range)
- Long: In uptrend, buy at S1 or central pivot with target at R1/R2
- Short: In downtrend, sell at R1 or central pivot with target at S1/S2
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.fibonacci import pivot_points_fibonacci
from ..indicators.moving_averages import ema
from ..indicators.volatility import atr


class FibPivotStrategy(BaseStrategy):
    """
    Fibonacci Pivot Points Strategy.
    
    Uses Fibonacci pivot levels for support/resistance trading.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'trend_ema_period': 50,
            'touch_tolerance': 0.003,  # How close price needs to get to pivot
            'atr_period': 14,
            'atr_sl_multiplier': 1.5,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "Fib_Pivot"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate trading signals based on Fibonacci Pivot Points."""
        df = df.copy()
        self.validate_data(df)
        
        # Add Fibonacci Pivot Points
        df = pivot_points_fibonacci(df)
        
        # Add trend EMA
        df['trend_ema'] = ema(df['close'], self.params['trend_ema_period'])
        
        # Add ATR
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Determine trend
        df['uptrend'] = df['close'] > df['trend_ema']
        df['downtrend'] = df['close'] < df['trend_ema']
        
        # Compare current pivot with previous (higher pivots = bullish)
        df['pivot_rising'] = df['pivot'] > df['pivot'].shift(1)
        df['pivot_falling'] = df['pivot'] < df['pivot'].shift(1)
        
        tolerance = self.params['touch_tolerance']
        
        # Initialize signal column
        df['signal'] = 0
        
        # Skip if not enough data
        min_period = self.params['trend_ema_period'] + 2
        if len(df) < min_period + 2:
            return df
        
        for i in range(min_period + 1, len(df)):
            idx = df.index[i]
            
            # Skip if data not available
            if pd.isna(df.loc[idx, 'pivot']) or pd.isna(df.loc[idx, 'trend_ema']):
                continue
            
            current_low = df.loc[idx, 'low']
            current_high = df.loc[idx, 'high']
            current_close = df.loc[idx, 'close']
            
            pivot = df.loc[idx, 'pivot']
            s1 = df.loc[idx, 's1']
            r1 = df.loc[idx, 'r1']
            
            # LONG SIGNAL: Uptrend + Rising pivots + Price bounces off S1 or Pivot
            if df.loc[idx, 'uptrend'] and df.loc[idx, 'pivot_rising']:
                # Touch S1 and bounce
                touched_s1 = current_low <= s1 * (1 + tolerance) and current_low >= s1 * (1 - tolerance)
                # Or touch Pivot and bounce
                touched_pivot = current_low <= pivot * (1 + tolerance) and current_low >= pivot * (1 - tolerance)
                
                # Closed above the touched level
                if touched_s1 and current_close > s1:
                    df.loc[idx, 'signal'] = Signal.BUY.value
                elif touched_pivot and current_close > pivot:
                    df.loc[idx, 'signal'] = Signal.BUY.value
            
            # SHORT SIGNAL: Downtrend + Falling pivots + Price rejects R1 or Pivot
            elif df.loc[idx, 'downtrend'] and df.loc[idx, 'pivot_falling']:
                # Touch R1 and reject
                touched_r1 = current_high >= r1 * (1 - tolerance) and current_high <= r1 * (1 + tolerance)
                # Or touch Pivot and reject
                touched_pivot = current_high >= pivot * (1 - tolerance) and current_high <= pivot * (1 + tolerance)
                
                # Closed below the touched level
                if touched_r1 and current_close < r1:
                    df.loc[idx, 'signal'] = Signal.SELL.value
                elif touched_pivot and current_close < pivot:
                    df.loc[idx, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using pivot levels and ATR."""
        entry_price = df.loc[idx, 'close']
        current_atr = df.loc[idx, 'atr']
        
        if direction == Signal.BUY:
            # Stop below S2 or ATR-based
            s2 = df.loc[idx, 's2']
            pivot_stop = s2 * 0.998 if not pd.isna(s2) else entry_price * 0.97
            atr_stop = entry_price - (current_atr * self.params['atr_sl_multiplier'])
            return max(pivot_stop, atr_stop)
        else:
            # Stop above R2 or ATR-based
            r2 = df.loc[idx, 'r2']
            pivot_stop = r2 * 1.002 if not pd.isna(r2) else entry_price * 1.03
            atr_stop = entry_price + (current_atr * self.params['atr_sl_multiplier'])
            return min(pivot_stop, atr_stop)
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, direction: Signal,
                             entry_price: float, stop_loss: float) -> float:
        """Calculate take profit using pivot levels and risk-reward."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            # Target at R1 or R2
            r1 = df.loc[idx, 'r1']
            rr_target = entry_price + reward
            return max(rr_target, r1) if not pd.isna(r1) else rr_target
        else:
            # Target at S1 or S2
            s1 = df.loc[idx, 's1']
            rr_target = entry_price - reward
            return min(rr_target, s1) if not pd.isna(s1) else rr_target
