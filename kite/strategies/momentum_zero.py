"""
Momentum Zero-Line Strategy

Pure momentum measurement - trade when momentum crosses zero line.
Uses trend filter to avoid choppy markets.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import momentum
from ..indicators.moving_averages import ema
from ..indicators.volatility import atr


class MomentumZeroStrategy(BaseStrategy):
    """Momentum zero-line crossover strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'momentum_period': 14,
            'trend_ma_period': 50,
            'momentum_ma_period': 5,  # Smooth momentum
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "Momentum_Zero"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        self.validate_data(df)
        
        # Calculate momentum
        df['momentum'] = momentum(df['close'], self.params['momentum_period'])
        df['momentum_smooth'] = ema(df['momentum'], self.params['momentum_ma_period'])
        
        # Trend filter
        df['trend_ma'] = ema(df['close'], self.params['trend_ma_period'])
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal
        df['signal'] = 0
        
        # Momentum crosses zero
        mom_cross_up = (df['momentum_smooth'] > 0) & \
                       (df['momentum_smooth'].shift(1) <= 0)
        mom_cross_down = (df['momentum_smooth'] < 0) & \
                        (df['momentum_smooth'].shift(1) >= 0)
        
        # Trend filter
        uptrend = df['close'] > df['trend_ma']
        downtrend = df['close'] < df['trend_ma']
        
        # Momentum increasing/decreasing
        mom_increasing = df['momentum_smooth'] > df['momentum_smooth'].shift(1)
        mom_decreasing = df['momentum_smooth'] < df['momentum_smooth'].shift(1)
        
        # Generate signals
        # Buy: Momentum crosses above zero in uptrend, momentum increasing
        buy_signal = mom_cross_up & uptrend & mom_increasing
        
        # Sell: Momentum crosses below zero in downtrend, momentum decreasing
        sell_signal = mom_cross_down & downtrend & mom_decreasing
        
        df.loc[buy_signal, 'signal'] = Signal.BUY.value
        df.loc[sell_signal, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        entry_price = df.loc[idx, 'close']
        current_atr = df.loc[idx, 'atr']
        
        if direction == Signal.BUY:
            return entry_price - (current_atr * self.params['atr_multiplier'])
        else:
            return entry_price + (current_atr * self.params['atr_multiplier'])
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, direction: Signal,
                             entry_price: float, stop_loss: float) -> float:
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
