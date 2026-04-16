"""
Bollinger Band Mean Reversion Strategy
- Long: Price touches lower band + RSI oversold + bullish candle
- Short: Price touches upper band + RSI overbought + bearish candle
- Target: Middle band (20 SMA)
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import rsi
from ..indicators.volatility import bollinger_bands, atr


class BBMeanReversionStrategy(BaseStrategy):
    """Bollinger Band Mean Reversion Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'bb_period': 20,
            'bb_std': 2.0,
            'rsi_period': 14,
            'rsi_oversold': 30,
            'rsi_overbought': 70,
            'atr_period': 14,
            'atr_multiplier': 1.5,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on BB mean reversion."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate indicators
        upper, middle, lower = bollinger_bands(
            df, 
            self.params['bb_period'],
            self.params['bb_std']
        )
        
        df['bb_upper'] = upper
        df['bb_middle'] = middle
        df['bb_lower'] = lower
        df['rsi'] = rsi(df['close'], self.params['rsi_period'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Bullish candle: close > open
        df['bullish_candle'] = df['close'] > df['open']
        # Bearish candle: close < open
        df['bearish_candle'] = df['close'] < df['open']
        
        # Initialize signal column
        df['signal'] = 0
        
        # Long: Price at/below lower band + RSI oversold + bullish candle
        long_condition = (
            (df['low'] <= df['bb_lower']) &
            (df['rsi'] < self.params['rsi_oversold']) &
            df['bullish_candle']
        )
        
        # Short: Price at/above upper band + RSI overbought + bearish candle
        short_condition = (
            (df['high'] >= df['bb_upper']) &
            (df['rsi'] > self.params['rsi_overbought']) &
            df['bearish_candle']
        )
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using ATR beyond the band."""
        atr_val = df.loc[idx, 'atr'] if 'atr' in df.columns else df['atr'].iloc[-1]
        multiplier = self.params['atr_multiplier']
        
        if direction == Signal.BUY:
            # Stop below lower band
            lower_band = df.loc[idx, 'bb_lower']
            return lower_band - (atr_val * multiplier)
        else:
            # Stop above upper band
            upper_band = df.loc[idx, 'bb_upper']
            return upper_band + (atr_val * multiplier)
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, 
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """Target is the middle band."""
        return df.loc[idx, 'bb_middle']
