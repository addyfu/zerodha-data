"""
Kumo Breakout Strategy
- Price breaks above cloud + cloud ahead is green = Long
- Price breaks below cloud + cloud ahead is red = Short
- Volume confirmation
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.moving_averages import sma
from ..indicators.volatility import atr


def calculate_ichimoku(df: pd.DataFrame, tenkan: int = 9, kijun: int = 26, 
                       senkou_b: int = 52) -> dict:
    """Calculate Ichimoku Cloud components."""
    tenkan_high = df['high'].rolling(window=tenkan).max()
    tenkan_low = df['low'].rolling(window=tenkan).min()
    tenkan_sen = (tenkan_high + tenkan_low) / 2
    
    kijun_high = df['high'].rolling(window=kijun).max()
    kijun_low = df['low'].rolling(window=kijun).min()
    kijun_sen = (kijun_high + kijun_low) / 2
    
    senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(kijun)
    
    senkou_b_high = df['high'].rolling(window=senkou_b).max()
    senkou_b_low = df['low'].rolling(window=senkou_b).min()
    senkou_span_b = ((senkou_b_high + senkou_b_low) / 2).shift(kijun)
    
    return {
        'tenkan': tenkan_sen,
        'kijun': kijun_sen,
        'senkou_a': senkou_span_a,
        'senkou_b': senkou_span_b
    }


class KumoBreakoutStrategy(BaseStrategy):
    """Kumo (Cloud) Breakout Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'tenkan_period': 9,
            'kijun_period': 26,
            'senkou_b_period': 52,
            'volume_period': 20,
            'volume_multiplier': 1.2,
            'atr_period': 14,
            'cloud_thickness_multiplier': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on Kumo breakout."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate Ichimoku
        ichimoku = calculate_ichimoku(
            df,
            self.params['tenkan_period'],
            self.params['kijun_period'],
            self.params['senkou_b_period']
        )
        
        df['senkou_a'] = ichimoku['senkou_a']
        df['senkou_b'] = ichimoku['senkou_b']
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Cloud boundaries
        df['cloud_top'] = df[['senkou_a', 'senkou_b']].max(axis=1)
        df['cloud_bottom'] = df[['senkou_a', 'senkou_b']].min(axis=1)
        df['cloud_thickness'] = df['cloud_top'] - df['cloud_bottom']
        
        # Future cloud color (for confirmation)
        df['future_cloud_bullish'] = df['senkou_a'] > df['senkou_b']
        
        # Volume confirmation
        df['volume_sma'] = sma(df['volume'], self.params['volume_period'])
        df['volume_high'] = df['volume'] > (df['volume_sma'] * self.params['volume_multiplier'])
        
        # Initialize signal column
        df['signal'] = 0
        
        # Was inside or below cloud
        was_in_or_below_cloud = (
            (df['close'].shift(1) <= df['cloud_top'].shift(1))
        )
        
        # Was inside or above cloud
        was_in_or_above_cloud = (
            (df['close'].shift(1) >= df['cloud_bottom'].shift(1))
        )
        
        # Long: Price breaks above cloud + future cloud bullish + volume
        long_condition = (
            (df['close'] > df['cloud_top']) &
            was_in_or_below_cloud &
            df['future_cloud_bullish'] &
            df['volume_high']
        )
        
        # Short: Price breaks below cloud + future cloud bearish + volume
        short_condition = (
            (df['close'] < df['cloud_bottom']) &
            was_in_or_above_cloud &
            ~df['future_cloud_bullish'] &
            df['volume_high']
        )
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Stop loss inside the cloud."""
        if direction == Signal.BUY:
            # Stop inside cloud (at cloud bottom)
            return df.loc[idx, 'cloud_bottom']
        else:
            # Stop inside cloud (at cloud top)
            return df.loc[idx, 'cloud_top']
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, 
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """Target is 2x cloud thickness."""
        cloud_thickness = df.loc[idx, 'cloud_thickness']
        multiplier = self.params['cloud_thickness_multiplier']
        
        if direction == Signal.BUY:
            return entry_price + (cloud_thickness * multiplier)
        else:
            return entry_price - (cloud_thickness * multiplier)
