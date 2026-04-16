"""
TTM Squeeze + Trend Filter Strategy
- Only take long squeezes when price above 200 EMA
- Only take short squeezes when price below 200 EMA
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import bollinger_bands, keltner_channels, atr
from ..indicators.oscillators import momentum
from ..indicators.moving_averages import ema


class TTMSqueezeTrendStrategy(BaseStrategy):
    """TTM Squeeze with Trend Filter Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'bb_period': 20,
            'bb_std': 2.0,
            'kc_period': 20,
            'kc_atr_period': 10,
            'kc_mult': 1.5,
            'momentum_period': 12,
            'trend_ema': 200,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on TTM Squeeze with trend filter."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate Bollinger Bands
        bb_upper, bb_middle, bb_lower = bollinger_bands(
            df, self.params['bb_period'], self.params['bb_std']
        )
        
        # Calculate Keltner Channels
        kc_upper, kc_middle, kc_lower = keltner_channels(
            df, self.params['kc_period'], 
            self.params['kc_atr_period'],
            self.params['kc_mult']
        )
        
        # Trend filter
        df['ema_200'] = ema(df['close'], self.params['trend_ema'])
        df['uptrend'] = df['close'] > df['ema_200']
        df['downtrend'] = df['close'] < df['ema_200']
        
        # Squeeze detection
        df['squeeze_on'] = (bb_lower > kc_lower) & (bb_upper < kc_upper)
        df['squeeze_fire'] = ~df['squeeze_on'] & df['squeeze_on'].shift(1)
        
        # Momentum
        df['momentum'] = momentum(df['close'], self.params['momentum_period'])
        df['momentum_rising'] = df['momentum'] > df['momentum'].shift(1)
        df['momentum_falling'] = df['momentum'] < df['momentum'].shift(1)
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        # Long: Squeeze fires + uptrend + momentum positive
        long_condition = (
            df['squeeze_fire'] &
            df['uptrend'] &
            (df['momentum'] > 0) &
            df['momentum_rising']
        )
        
        # Short: Squeeze fires + downtrend + momentum negative
        short_condition = (
            df['squeeze_fire'] &
            df['downtrend'] &
            (df['momentum'] < 0) &
            df['momentum_falling']
        )
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
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
