"""
VWAP Standard Deviation Bands Strategy
- Price at +2SD = Overbought (short opportunity)
- Price at -2SD = Oversold (long opportunity)
- VWAP acts as mean reversion target
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volume import vwap_bands
from ..indicators.volatility import atr


class VWAPSDBandsStrategy(BaseStrategy):
    """VWAP with Standard Deviation Bands Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'sd_multiplier': 2.0,
            'reset_daily': True,
            'atr_period': 14,
            'atr_multiplier': 1.5,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on VWAP SD bands."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate VWAP bands
        upper, vwap_line, lower = vwap_bands(
            df, 
            self.params['sd_multiplier'],
            self.params['reset_daily']
        )
        
        df['vwap'] = vwap_line
        df['vwap_upper'] = upper
        df['vwap_lower'] = lower
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Bullish candle confirmation
        df['bullish_candle'] = df['close'] > df['open']
        df['bearish_candle'] = df['close'] < df['open']
        
        # Initialize signal column
        df['signal'] = 0
        
        # Long: Price at/below -2SD + bullish candle
        long_condition = (
            (df['low'] <= df['vwap_lower']) &
            df['bullish_candle']
        )
        
        # Short: Price at/above +2SD + bearish candle
        short_condition = (
            (df['high'] >= df['vwap_upper']) &
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
            lower_band = df.loc[idx, 'vwap_lower']
            return lower_band - (atr_val * multiplier)
        else:
            upper_band = df.loc[idx, 'vwap_upper']
            return upper_band + (atr_val * multiplier)
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, 
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """Target is VWAP (mean reversion)."""
        return df.loc[idx, 'vwap']
