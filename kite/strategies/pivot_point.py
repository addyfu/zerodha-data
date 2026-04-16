"""
Standard Pivot Point Trading Strategy
- Long: Price bounces from S1/S2 with bullish candle
- Short: Price rejects from R1/R2 with bearish candle
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr


def calculate_pivot_points(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate daily pivot points."""
    df = df.copy()
    
    # Get daily OHLC
    df['date'] = df.index.date
    
    # Previous day's high, low, close
    daily_hlc = df.groupby('date').agg({
        'high': 'max',
        'low': 'min',
        'close': 'last'
    }).shift(1)
    
    # Map back to original index
    df['prev_high'] = df['date'].map(daily_hlc['high'])
    df['prev_low'] = df['date'].map(daily_hlc['low'])
    df['prev_close'] = df['date'].map(daily_hlc['close'])
    
    # Calculate pivot point
    df['pivot'] = (df['prev_high'] + df['prev_low'] + df['prev_close']) / 3
    
    # Calculate support and resistance levels
    df['r1'] = 2 * df['pivot'] - df['prev_low']
    df['r2'] = df['pivot'] + (df['prev_high'] - df['prev_low'])
    df['r3'] = df['prev_high'] + 2 * (df['pivot'] - df['prev_low'])
    
    df['s1'] = 2 * df['pivot'] - df['prev_high']
    df['s2'] = df['pivot'] - (df['prev_high'] - df['prev_low'])
    df['s3'] = df['prev_low'] - 2 * (df['prev_high'] - df['pivot'])
    
    return df


class PivotPointStrategy(BaseStrategy):
    """Standard Pivot Point Trading Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'touch_tolerance': 0.002,  # 0.2% tolerance for level touch
            'atr_period': 14,
            'atr_multiplier': 1.5,
            'risk_reward': 1.5,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on pivot point bounces."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate pivot points
        df = calculate_pivot_points(df)
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Candle patterns
        df['bullish_candle'] = df['close'] > df['open']
        df['bearish_candle'] = df['close'] < df['open']
        
        tolerance = self.params['touch_tolerance']
        
        # Initialize signal column
        df['signal'] = 0
        
        # Long: Price bounces from S1 or S2
        touches_s1 = (df['low'] <= df['s1'] * (1 + tolerance)) & (df['low'] >= df['s1'] * (1 - tolerance))
        touches_s2 = (df['low'] <= df['s2'] * (1 + tolerance)) & (df['low'] >= df['s2'] * (1 - tolerance))
        
        long_condition = (
            (touches_s1 | touches_s2) &
            df['bullish_candle'] &
            (df['close'] > df['low'] + (df['high'] - df['low']) * 0.5)  # Close in upper half
        )
        
        # Short: Price rejects from R1 or R2
        touches_r1 = (df['high'] >= df['r1'] * (1 - tolerance)) & (df['high'] <= df['r1'] * (1 + tolerance))
        touches_r2 = (df['high'] >= df['r2'] * (1 - tolerance)) & (df['high'] <= df['r2'] * (1 + tolerance))
        
        short_condition = (
            (touches_r1 | touches_r2) &
            df['bearish_candle'] &
            (df['close'] < df['low'] + (df['high'] - df['low']) * 0.5)  # Close in lower half
        )
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
        # Clean up
        df.drop(['date', 'prev_high', 'prev_low', 'prev_close'], axis=1, inplace=True, errors='ignore')
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss below/above support/resistance."""
        atr_val = df.loc[idx, 'atr'] if 'atr' in df.columns else df['atr'].iloc[-1]
        
        if direction == Signal.BUY:
            # Stop below support level
            s2 = df.loc[idx, 's2']
            return s2 - atr_val
        else:
            # Stop above resistance level
            r2 = df.loc[idx, 'r2']
            return r2 + atr_val
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, 
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """Target is pivot point or next level."""
        if direction == Signal.BUY:
            return df.loc[idx, 'pivot']
        else:
            return df.loc[idx, 'pivot']
