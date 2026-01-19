"""
Moving Average Envelopes Strategy

MA with upper/lower bands at fixed percentage distance.
Mean reversion strategy - buy at lower envelope, sell at upper envelope.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.moving_averages import ma_envelopes, ema
from ..indicators.volatility import atr


class MAEnvelopesStrategy(BaseStrategy):
    """Moving Average Envelopes mean reversion strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'ma_period': 20,
            'envelope_pct': 2.5,
            'ma_type': 'ema',
            'trend_ma_period': 50,
            'atr_period': 14,
            'atr_multiplier': 1.5,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "MA_Envelopes"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        self.validate_data(df)
        
        # Calculate envelopes
        df['env_ma'], df['env_upper'], df['env_lower'] = ma_envelopes(
            df['close'],
            self.params['ma_period'],
            self.params['envelope_pct'],
            self.params['ma_type']
        )
        
        # Trend filter
        df['trend_ma'] = ema(df['close'], self.params['trend_ma_period'])
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal
        df['signal'] = 0
        
        # Price touches/crosses envelopes
        touch_lower = df['low'] <= df['env_lower']
        touch_upper = df['high'] >= df['env_upper']
        
        # Price returns inside envelope (confirmation)
        close_above_lower = df['close'] > df['env_lower']
        close_below_upper = df['close'] < df['env_upper']
        
        # Trend filter
        uptrend = df['close'] > df['trend_ma']
        downtrend = df['close'] < df['trend_ma']
        
        # Generate signals
        # Buy: Price touches lower envelope in uptrend, closes above it
        buy_signal = touch_lower & close_above_lower & uptrend
        
        # Sell: Price touches upper envelope in downtrend, closes below it
        sell_signal = touch_upper & close_below_upper & downtrend
        
        df.loc[buy_signal, 'signal'] = Signal.BUY.value
        df.loc[sell_signal, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        entry_price = df.loc[idx, 'close']
        current_atr = df.loc[idx, 'atr']
        
        if direction == Signal.BUY:
            # Stop below lower envelope
            return min(entry_price - (current_atr * self.params['atr_multiplier']),
                      df.loc[idx, 'env_lower'] * 0.99)
        else:
            # Stop above upper envelope
            return max(entry_price + (current_atr * self.params['atr_multiplier']),
                      df.loc[idx, 'env_upper'] * 1.01)
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, direction: Signal,
                             entry_price: float, stop_loss: float) -> float:
        if direction == Signal.BUY:
            # Target: MA or upper envelope
            return df.loc[idx, 'env_ma']
        else:
            # Target: MA or lower envelope
            return df.loc[idx, 'env_ma']
