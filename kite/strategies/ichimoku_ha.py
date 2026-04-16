"""
Ichimoku + Heikin Ashi Strategy
- Price above Kumo + cloud green + HA changes red to green = Long
- Price below Kumo + cloud red + HA changes green to red = Short
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
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


def calculate_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate Heikin Ashi candles."""
    ha_df = df.copy()
    
    ha_df['ha_close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha_df['ha_open'] = (df['open'].shift(1) + df['close'].shift(1)) / 2
    ha_df['ha_open'].iloc[0] = df['open'].iloc[0]
    
    for i in range(1, len(ha_df)):
        ha_df['ha_open'].iloc[i] = (ha_df['ha_open'].iloc[i-1] + ha_df['ha_close'].iloc[i-1]) / 2
    
    ha_df['ha_high'] = ha_df[['high', 'ha_open', 'ha_close']].max(axis=1)
    ha_df['ha_low'] = ha_df[['low', 'ha_open', 'ha_close']].min(axis=1)
    
    return ha_df


class IchimokuHAStrategy(BaseStrategy):
    """Ichimoku Cloud + Heikin Ashi Strategy."""
    
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
        """Generate signals based on Ichimoku + Heikin Ashi."""
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
        
        # Cloud boundaries
        df['cloud_top'] = df[['senkou_a', 'senkou_b']].max(axis=1)
        df['cloud_bottom'] = df[['senkou_a', 'senkou_b']].min(axis=1)
        df['cloud_bullish'] = df['senkou_a'] > df['senkou_b']
        
        # Calculate Heikin Ashi
        ha_df = calculate_heikin_ashi(df)
        df['ha_close'] = ha_df['ha_close']
        df['ha_open'] = ha_df['ha_open']
        
        # HA color
        df['ha_green'] = df['ha_close'] > df['ha_open']
        df['ha_red'] = df['ha_close'] < df['ha_open']
        
        # HA color change
        df['ha_turn_green'] = df['ha_green'] & df['ha_red'].shift(1)
        df['ha_turn_red'] = df['ha_red'] & df['ha_green'].shift(1)
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        # Long: Price above cloud + cloud green + HA turns green
        long_condition = (
            (df['close'] > df['cloud_top']) &
            df['cloud_bullish'] &
            df['ha_turn_green']
        )
        
        # Short: Price below cloud + cloud red + HA turns red
        short_condition = (
            (df['close'] < df['cloud_bottom']) &
            ~df['cloud_bullish'] &
            df['ha_turn_red']
        )
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss at cloud edge."""
        if direction == Signal.BUY:
            return df.loc[idx, 'cloud_bottom']
        else:
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
