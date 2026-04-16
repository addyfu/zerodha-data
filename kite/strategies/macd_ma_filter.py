"""
MACD + Moving Average Filter Strategy
- Only take MACD buy signals when price > 200 SMA
- Only take MACD sell signals when price < 200 SMA
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import macd
from ..indicators.moving_averages import sma
from ..indicators.volatility import atr


class MACDMAFilterStrategy(BaseStrategy):
    """MACD with Moving Average Filter Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'fast_period': 12,
            'slow_period': 26,
            'signal_period': 9,
            'ma_period': 200,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on MACD with MA filter."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate indicators
        macd_line, signal_line, histogram = macd(
            df['close'], 
            self.params['fast_period'],
            self.params['slow_period'],
            self.params['signal_period']
        )
        
        df['macd'] = macd_line
        df['macd_signal'] = signal_line
        df['macd_hist'] = histogram
        df['ma_200'] = sma(df['close'], self.params['ma_period'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        # MACD bullish crossover
        macd_bullish_cross = (
            (macd_line > signal_line) &
            (macd_line.shift(1) <= signal_line.shift(1))
        )
        
        # MACD bearish crossover
        macd_bearish_cross = (
            (macd_line < signal_line) &
            (macd_line.shift(1) >= signal_line.shift(1))
        )
        
        # Long: MACD bullish cross + price above 200 SMA
        long_condition = macd_bullish_cross & (df['close'] > df['ma_200'])
        
        # Short: MACD bearish cross + price below 200 SMA
        short_condition = macd_bearish_cross & (df['close'] < df['ma_200'])
        
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
