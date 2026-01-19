"""
StochRSI + MACD Momentum Strategy

Uses smoothed StochRSI with 50-level as trend filter, confirmed by MACD.
Looks for momentum continuation, NOT overbought/oversold reversals.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import stoch_rsi, macd
from ..indicators.volatility import atr


class StochRSIMACDStrategy(BaseStrategy):
    """StochRSI + MACD momentum continuation strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'rsi_period': 100,
            'stoch_period': 100,
            'k_smooth': 3,
            'd_smooth': 3,
            'macd_fast': 10,
            'macd_slow': 100,
            'macd_signal': 1,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "StochRSI_MACD"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        self.validate_data(df)
        
        # Calculate StochRSI
        df['stoch_rsi_k'], df['stoch_rsi_d'] = stoch_rsi(
            df['close'], 
            self.params['rsi_period'],
            self.params['stoch_period'],
            self.params['k_smooth'],
            self.params['d_smooth']
        )
        
        # Calculate MACD
        df['macd'], df['macd_signal'], df['macd_hist'] = macd(
            df['close'],
            self.params['macd_fast'],
            self.params['macd_slow'],
            self.params['macd_signal']
        )
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal
        df['signal'] = 0
        
        # StochRSI above 50 = bullish momentum
        stoch_bullish = df['stoch_rsi_d'] > 50
        stoch_bearish = df['stoch_rsi_d'] < 50
        
        # StochRSI crosses 50 level
        stoch_cross_up = stoch_bullish & ~stoch_bullish.shift(1).fillna(False)
        stoch_cross_down = stoch_bearish & ~stoch_bearish.shift(1).fillna(False)
        
        # MACD confirmation
        macd_bullish = df['macd'] > 0
        macd_bearish = df['macd'] < 0
        
        # Generate signals
        # Buy: StochRSI crosses above 50 AND MACD > 0
        buy_signal = stoch_cross_up & macd_bullish
        
        # Sell: StochRSI crosses below 50 AND MACD < 0
        sell_signal = stoch_cross_down & macd_bearish
        
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
