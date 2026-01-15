"""
Donchian Channel Turtle Trading Strategy

Based on the famous Turtle Traders system - breakout strategy using Donchian Channels.

Rules:
- Long Entry: Price breaks above 20-period Donchian upper band
- Short Entry: Price breaks below 20-period Donchian lower band
- Stop Loss: 2 × ATR from entry
- Exit: Touch of midpoint line OR break of opposite channel
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import donchian_channels, atr


class DonchianTurtleStrategy(BaseStrategy):
    """
    Donchian Channel Turtle Trading Strategy.
    
    Classic breakout system based on Turtle Traders methodology.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'entry_period': 20,      # Entry breakout period
            'exit_period': 10,       # Exit period (shorter for faster exits)
            'atr_period': 20,
            'atr_sl_multiplier': 2.0,
            'use_midline_exit': False,  # Exit at midline touch
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "Donchian_Turtle"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate trading signals based on Donchian Channel breakouts."""
        df = df.copy()
        self.validate_data(df)
        
        # Add Donchian Channels for entry
        df['dc_upper'], df['dc_middle'], df['dc_lower'] = donchian_channels(
            df, self.params['entry_period']
        )
        
        # Add shorter Donchian for exits
        df['dc_exit_upper'], df['dc_exit_middle'], df['dc_exit_lower'] = donchian_channels(
            df, self.params['exit_period']
        )
        
        # Add ATR
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        # Skip if not enough data
        if len(df) < self.params['entry_period'] + 2:
            return df
        
        for i in range(self.params['entry_period'] + 1, len(df)):
            idx = df.index[i]
            prev_idx = df.index[i - 1]
            
            # Skip if data not available
            if pd.isna(df.loc[idx, 'dc_upper']) or pd.isna(df.loc[idx, 'atr']):
                continue
            
            current_close = df.loc[idx, 'close']
            current_high = df.loc[idx, 'high']
            current_low = df.loc[idx, 'low']
            
            prev_close = df.loc[prev_idx, 'close']
            prev_high = df.loc[prev_idx, 'high']
            
            # Use previous bar's channel levels (to avoid look-ahead bias)
            dc_upper = df.loc[prev_idx, 'dc_upper']
            dc_lower = df.loc[prev_idx, 'dc_lower']
            
            # LONG SIGNAL: Price breaks above upper Donchian channel
            if current_close > dc_upper and prev_close <= dc_upper:
                df.loc[idx, 'signal'] = Signal.BUY.value
            
            # SHORT SIGNAL: Price breaks below lower Donchian channel
            elif current_close < dc_lower and prev_close >= dc_lower:
                df.loc[idx, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using ATR."""
        entry_price = df.loc[idx, 'close']
        current_atr = df.loc[idx, 'atr']
        
        if direction == Signal.BUY:
            # Stop below entry by 2 ATR, but not below lower channel
            atr_stop = entry_price - (current_atr * self.params['atr_sl_multiplier'])
            channel_stop = df.loc[idx, 'dc_lower']
            return max(atr_stop, channel_stop)
        else:
            # Stop above entry by 2 ATR, but not above upper channel
            atr_stop = entry_price + (current_atr * self.params['atr_sl_multiplier'])
            channel_stop = df.loc[idx, 'dc_upper']
            return min(atr_stop, channel_stop)
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, direction: Signal,
                             entry_price: float, stop_loss: float) -> float:
        """Calculate take profit based on risk-reward ratio."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
