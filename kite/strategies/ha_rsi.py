"""
Heikin-Ashi + RSI Strategy
- HA candle changes from red to green + RSI > 50 = Long
- HA candle changes from green to red + RSI < 50 = Short
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import rsi
from ..indicators.volatility import atr


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


class HARSIStrategy(BaseStrategy):
    """Heikin-Ashi + RSI Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'rsi_period': 14,
            'rsi_mid': 50,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on HA + RSI."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate Heikin Ashi
        ha_df = calculate_heikin_ashi(df)
        df['ha_close'] = ha_df['ha_close']
        df['ha_open'] = ha_df['ha_open']
        
        # Calculate RSI
        df['rsi'] = rsi(df['close'], self.params['rsi_period'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # HA color
        df['ha_green'] = df['ha_close'] > df['ha_open']
        df['ha_red'] = df['ha_close'] < df['ha_open']
        
        # Color change
        df['ha_turn_green'] = df['ha_green'] & df['ha_red'].shift(1)
        df['ha_turn_red'] = df['ha_red'] & df['ha_green'].shift(1)
        
        # Initialize signal column
        df['signal'] = 0
        
        rsi_mid = self.params['rsi_mid']
        
        # Long: HA turns green + RSI > 50
        long_condition = df['ha_turn_green'] & (df['rsi'] > rsi_mid)
        
        # Short: HA turns red + RSI < 50
        short_condition = df['ha_turn_red'] & (df['rsi'] < rsi_mid)
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
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
