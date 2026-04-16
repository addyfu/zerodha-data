"""
Fibonacci Retracement Trading Strategy
- Draw Fib from swing low to swing high
- Enter on pullback to 38.2%, 50%, or 61.8%
- Stop below 78.6%, target at previous swing or extension
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr


class FibRetracementStrategy(BaseStrategy):
    """Fibonacci Retracement Trading Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'swing_lookback': 20,
            'fib_levels': [0.382, 0.5, 0.618],
            'fib_tolerance': 0.01,  # 1% tolerance
            'stop_level': 0.786,
            'atr_period': 14,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def _find_swing_points(self, df: pd.DataFrame, lookback: int) -> tuple:
        """Find recent swing high and swing low."""
        swing_high_idx = df['high'].rolling(window=lookback).apply(
            lambda x: x.argmax(), raw=True
        ).astype(int)
        swing_low_idx = df['low'].rolling(window=lookback).apply(
            lambda x: x.argmin(), raw=True
        ).astype(int)
        
        return swing_high_idx, swing_low_idx
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on Fibonacci retracement."""
        df = df.copy()
        self.validate_data(df)
        
        lookback = self.params['swing_lookback']
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Find swing points
        df['swing_high'] = df['high'].rolling(window=lookback).max()
        df['swing_low'] = df['low'].rolling(window=lookback).min()
        
        # Initialize signal column
        df['signal'] = 0
        
        fib_levels = self.params['fib_levels']
        tolerance = self.params['fib_tolerance']
        
        for i in range(lookback * 2, len(df)):
            idx = df.index[i]
            
            swing_high = df.loc[idx, 'swing_high']
            swing_low = df.loc[idx, 'swing_low']
            swing_range = swing_high - swing_low
            
            if swing_range <= 0:
                continue
            
            current_close = df.loc[idx, 'close']
            current_low = df.loc[idx, 'low']
            current_high = df.loc[idx, 'high']
            
            # Determine trend direction
            # Uptrend: Recent swing low came before swing high
            window = df.iloc[i-lookback:i+1]
            swing_high_pos = window['high'].idxmax()
            swing_low_pos = window['low'].idxmin()
            
            is_uptrend = swing_low_pos < swing_high_pos
            is_downtrend = swing_high_pos < swing_low_pos
            
            # Calculate Fib levels
            for fib in fib_levels:
                if is_uptrend:
                    # Uptrend: Fib from low to high, looking for pullback
                    fib_price = swing_high - (swing_range * fib)
                    
                    # Check if price touches Fib level
                    touches_fib = (
                        (current_low <= fib_price * (1 + tolerance)) &
                        (current_low >= fib_price * (1 - tolerance))
                    )
                    
                    # Bullish candle at Fib level
                    bullish_candle = current_close > df['open'].iloc[i]
                    
                    if touches_fib and bullish_candle:
                        df.loc[idx, 'signal'] = Signal.BUY.value
                        df.loc[idx, 'fib_level'] = fib_price
                        break
                
                elif is_downtrend:
                    # Downtrend: Fib from high to low, looking for rally
                    fib_price = swing_low + (swing_range * fib)
                    
                    touches_fib = (
                        (current_high >= fib_price * (1 - tolerance)) &
                        (current_high <= fib_price * (1 + tolerance))
                    )
                    
                    bearish_candle = current_close < df['open'].iloc[i]
                    
                    if touches_fib and bearish_candle:
                        df.loc[idx, 'signal'] = Signal.SELL.value
                        df.loc[idx, 'fib_level'] = fib_price
                        break
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Stop loss at 78.6% Fib level."""
        swing_high = df.loc[idx, 'swing_high']
        swing_low = df.loc[idx, 'swing_low']
        swing_range = swing_high - swing_low
        stop_level = self.params['stop_level']
        
        if direction == Signal.BUY:
            return swing_high - (swing_range * stop_level)
        else:
            return swing_low + (swing_range * stop_level)
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, 
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """Target at previous swing or extension."""
        if direction == Signal.BUY:
            return df.loc[idx, 'swing_high']
        else:
            return df.loc[idx, 'swing_low']
