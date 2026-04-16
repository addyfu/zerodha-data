"""
RSI 50-Level Centerline Strategy
- RSI above 50 = Bullish bias (only longs)
- RSI below 50 = Bearish bias (only shorts)
- Uses RSI 50 crossover as entry signal
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import rsi
from ..indicators.volatility import atr


class RSICenterlineStrategy(BaseStrategy):
    """RSI 50-Level Centerline Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'rsi_period': 14,
            'rsi_mid': 50,
            'confirmation_bars': 2,  # Bars RSI must stay above/below 50
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 1.5,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on RSI centerline crossover."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate indicators
        df['rsi'] = rsi(df['close'], self.params['rsi_period'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        # RSI above/below 50 for confirmation bars
        conf_bars = self.params['confirmation_bars']
        
        # Long: RSI crosses above 50 and stays above
        rsi_above = df['rsi'] > self.params['rsi_mid']
        rsi_was_below = df['rsi'].shift(conf_bars) <= self.params['rsi_mid']
        
        # Check RSI stayed above 50 for confirmation period
        rsi_confirmed_above = rsi_above.copy()
        for i in range(1, conf_bars):
            rsi_confirmed_above &= df['rsi'].shift(i) > self.params['rsi_mid']
        
        long_condition = rsi_confirmed_above & rsi_was_below
        
        # Short: RSI crosses below 50 and stays below
        rsi_below = df['rsi'] < self.params['rsi_mid']
        rsi_was_above = df['rsi'].shift(conf_bars) >= self.params['rsi_mid']
        
        rsi_confirmed_below = rsi_below.copy()
        for i in range(1, conf_bars):
            rsi_confirmed_below &= df['rsi'].shift(i) < self.params['rsi_mid']
        
        short_condition = rsi_confirmed_below & rsi_was_above
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using ATR."""
        atr_val = df.loc[idx, 'atr'] if 'atr' in df.columns else df['atr'].iloc[-1]
        entry_price = df.loc[idx, 'close']
        multiplier = self.params['atr_multiplier']
        
        if direction == Signal.BUY:
            return entry_price - (atr_val * multiplier)
        else:
            return entry_price + (atr_val * multiplier)
    
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
