"""
1-Minute EMA Scalping Strategy
- All EMAs aligned (9 > 21 > 55 for bullish)
- Price pulls back to EMA 9 or 21
- Enter with tight stop below EMA 55
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.moving_averages import ema
from ..indicators.volatility import atr


class EMAScalping1MinStrategy(BaseStrategy):
    """1-Minute EMA Scalping Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'ema_fast': 9,
            'ema_medium': 21,
            'ema_slow': 55,
            'pullback_tolerance': 0.001,  # 0.1% tolerance for pullback
            'atr_period': 14,
            'atr_multiplier': 1.5,
            'risk_reward': 1.5,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on EMA alignment and pullback."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate EMAs
        df['ema_fast'] = ema(df['close'], self.params['ema_fast'])
        df['ema_medium'] = ema(df['close'], self.params['ema_medium'])
        df['ema_slow'] = ema(df['close'], self.params['ema_slow'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # EMA alignment
        df['bullish_alignment'] = (
            (df['ema_fast'] > df['ema_medium']) &
            (df['ema_medium'] > df['ema_slow'])
        )
        
        df['bearish_alignment'] = (
            (df['ema_fast'] < df['ema_medium']) &
            (df['ema_medium'] < df['ema_slow'])
        )
        
        tolerance = self.params['pullback_tolerance']
        
        # Pullback to EMA 9 or 21
        df['pullback_to_fast'] = (
            (df['low'] <= df['ema_fast'] * (1 + tolerance)) &
            (df['low'] >= df['ema_fast'] * (1 - tolerance))
        )
        
        df['pullback_to_medium'] = (
            (df['low'] <= df['ema_medium'] * (1 + tolerance)) &
            (df['low'] >= df['ema_medium'] * (1 - tolerance))
        )
        
        df['rally_to_fast'] = (
            (df['high'] >= df['ema_fast'] * (1 - tolerance)) &
            (df['high'] <= df['ema_fast'] * (1 + tolerance))
        )
        
        df['rally_to_medium'] = (
            (df['high'] >= df['ema_medium'] * (1 - tolerance)) &
            (df['high'] <= df['ema_medium'] * (1 + tolerance))
        )
        
        # Candle patterns
        df['bullish_candle'] = df['close'] > df['open']
        df['bearish_candle'] = df['close'] < df['open']
        
        # Initialize signal column
        df['signal'] = 0
        
        # Long: Bullish alignment + pullback to EMA + bullish candle
        long_condition = (
            df['bullish_alignment'] &
            (df['pullback_to_fast'] | df['pullback_to_medium']) &
            df['bullish_candle']
        )
        
        # Short: Bearish alignment + rally to EMA + bearish candle
        short_condition = (
            df['bearish_alignment'] &
            (df['rally_to_fast'] | df['rally_to_medium']) &
            df['bearish_candle']
        )
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Stop loss below/above EMA 55."""
        ema_slow = df.loc[idx, 'ema_slow']
        atr_val = df.loc[idx, 'atr']
        
        if direction == Signal.BUY:
            return ema_slow - atr_val
        else:
            return ema_slow + atr_val
    
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
