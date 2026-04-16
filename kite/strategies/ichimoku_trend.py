"""
Ichimoku Trend Trading Strategy
- Price above cloud + Tenkan crosses Kijun + Chikou above price = Long
- Price below cloud + Tenkan crosses below Kijun + Chikou below price = Short
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr


def calculate_ichimoku(df: pd.DataFrame, tenkan: int = 9, kijun: int = 26, 
                       senkou_b: int = 52) -> dict:
    """Calculate Ichimoku Cloud components."""
    # Tenkan-sen (Conversion Line)
    tenkan_high = df['high'].rolling(window=tenkan).max()
    tenkan_low = df['low'].rolling(window=tenkan).min()
    tenkan_sen = (tenkan_high + tenkan_low) / 2
    
    # Kijun-sen (Base Line)
    kijun_high = df['high'].rolling(window=kijun).max()
    kijun_low = df['low'].rolling(window=kijun).min()
    kijun_sen = (kijun_high + kijun_low) / 2
    
    # Senkou Span A (Leading Span A)
    senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(kijun)
    
    # Senkou Span B (Leading Span B)
    senkou_b_high = df['high'].rolling(window=senkou_b).max()
    senkou_b_low = df['low'].rolling(window=senkou_b).min()
    senkou_span_b = ((senkou_b_high + senkou_b_low) / 2).shift(kijun)
    
    # Chikou Span (Lagging Span)
    chikou_span = df['close'].shift(-kijun)
    
    return {
        'tenkan': tenkan_sen,
        'kijun': kijun_sen,
        'senkou_a': senkou_span_a,
        'senkou_b': senkou_span_b,
        'chikou': chikou_span
    }


class IchimokuTrendStrategy(BaseStrategy):
    """Ichimoku Cloud Trend Trading Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'tenkan_period': 9,
            'kijun_period': 26,
            'senkou_b_period': 52,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on Ichimoku Cloud."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate Ichimoku
        ichimoku = calculate_ichimoku(
            df,
            self.params['tenkan_period'],
            self.params['kijun_period'],
            self.params['senkou_b_period']
        )
        
        df['tenkan'] = ichimoku['tenkan']
        df['kijun'] = ichimoku['kijun']
        df['senkou_a'] = ichimoku['senkou_a']
        df['senkou_b'] = ichimoku['senkou_b']
        df['chikou'] = ichimoku['chikou']
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Cloud top and bottom
        df['cloud_top'] = df[['senkou_a', 'senkou_b']].max(axis=1)
        df['cloud_bottom'] = df[['senkou_a', 'senkou_b']].min(axis=1)
        
        # Cloud color (bullish = green, bearish = red)
        df['cloud_bullish'] = df['senkou_a'] > df['senkou_b']
        
        # Initialize signal column
        df['signal'] = 0
        
        # Tenkan/Kijun crossover
        tk_bullish_cross = (
            (df['tenkan'] > df['kijun']) &
            (df['tenkan'].shift(1) <= df['kijun'].shift(1))
        )
        
        tk_bearish_cross = (
            (df['tenkan'] < df['kijun']) &
            (df['tenkan'].shift(1) >= df['kijun'].shift(1))
        )
        
        # Long conditions
        long_condition = (
            (df['close'] > df['cloud_top']) &  # Price above cloud
            tk_bullish_cross &  # TK cross
            df['cloud_bullish']  # Cloud is green
            # Note: Chikou confirmation is complex due to shift, simplified here
        )
        
        # Short conditions
        short_condition = (
            (df['close'] < df['cloud_bottom']) &  # Price below cloud
            tk_bearish_cross &  # TK cross
            ~df['cloud_bullish']  # Cloud is red
        )
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss at cloud edge."""
        if direction == Signal.BUY:
            # Stop at cloud bottom
            return df.loc[idx, 'cloud_bottom']
        else:
            # Stop at cloud top
            return df.loc[idx, 'cloud_top']
    
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
