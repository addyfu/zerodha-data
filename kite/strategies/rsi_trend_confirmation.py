"""
RSI Trend Confirmation Strategy
- Price above 200 EMA (uptrend) + RSI crosses above 50 = Long
- Price below 200 EMA (downtrend) + RSI crosses below 50 = Short
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import rsi
from ..indicators.moving_averages import ema
from ..indicators.volatility import atr


class RSITrendConfirmationStrategy(BaseStrategy):
    """RSI Trend Confirmation with 200 EMA filter."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'rsi_period': 14,
            'ema_period': 200,
            'rsi_upper': 70,
            'rsi_lower': 30,
            'rsi_mid': 50,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on RSI + EMA trend confirmation."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate indicators
        df['rsi'] = rsi(df['close'], self.params['rsi_period'])
        df['ema_200'] = ema(df['close'], self.params['ema_period'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        # Long: Price > EMA200 and RSI crosses above 50
        long_condition = (
            (df['close'] > df['ema_200']) &
            (df['rsi'] > self.params['rsi_mid']) &
            (df['rsi'].shift(1) <= self.params['rsi_mid'])
        )
        
        # Short: Price < EMA200 and RSI crosses below 50
        short_condition = (
            (df['close'] < df['ema_200']) &
            (df['rsi'] < self.params['rsi_mid']) &
            (df['rsi'].shift(1) >= self.params['rsi_mid'])
        )
        
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
