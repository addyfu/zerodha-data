"""
TRIX Divergence Strategy
- Bullish divergence: Price lower low, TRIX higher low
- Bearish divergence: Price higher high, TRIX lower high
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.moving_averages import ema
from ..indicators.volatility import atr


def trix(series: pd.Series, period: int = 15) -> pd.Series:
    """Calculate TRIX indicator."""
    ema1 = ema(series, period)
    ema2 = ema(ema1, period)
    ema3 = ema(ema2, period)
    
    trix_val = ((ema3 - ema3.shift(1)) / ema3.shift(1)) * 100
    return trix_val


class TRIXDivergenceStrategy(BaseStrategy):
    """TRIX Divergence Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'trix_period': 15,
            'divergence_lookback': 20,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on TRIX divergence."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate TRIX
        df['trix'] = trix(df['close'], self.params['trix_period'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        lookback = self.params['divergence_lookback']
        
        for i in range(lookback * 2, len(df)):
            idx = df.index[i]
            
            window_price_low = df['low'].iloc[i-lookback:i+1]
            window_price_high = df['high'].iloc[i-lookback:i+1]
            window_trix = df['trix'].iloc[i-lookback:i+1]
            
            current_price_low = df.loc[idx, 'low']
            current_price_high = df.loc[idx, 'high']
            current_trix = df.loc[idx, 'trix']
            
            # Bullish divergence: Price lower low, TRIX higher low
            price_min_idx = window_price_low.idxmin()
            if price_min_idx != idx:
                prev_price_low = df.loc[price_min_idx, 'low']
                prev_trix = df.loc[price_min_idx, 'trix']
                
                if current_price_low < prev_price_low and current_trix > prev_trix:
                    # Confirm with TRIX crossing above zero
                    if df['trix'].iloc[i] > 0 and df['trix'].iloc[i-1] <= 0:
                        df.loc[idx, 'signal'] = Signal.BUY.value
            
            # Bearish divergence: Price higher high, TRIX lower high
            price_max_idx = window_price_high.idxmax()
            if price_max_idx != idx:
                prev_price_high = df.loc[price_max_idx, 'high']
                prev_trix = df.loc[price_max_idx, 'trix']
                
                if current_price_high > prev_price_high and current_trix < prev_trix:
                    # Confirm with TRIX crossing below zero
                    if df['trix'].iloc[i] < 0 and df['trix'].iloc[i-1] >= 0:
                        df.loc[idx, 'signal'] = Signal.SELL.value
        
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
