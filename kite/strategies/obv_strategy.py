"""
On-Balance Volume (OBV) Strategy
- OBV rising + Price rising = Confirmed uptrend (Long)
- OBV falling + Price falling = Confirmed downtrend (Short)
- OBV divergence from price = Warning signal
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volume import obv
from ..indicators.moving_averages import ema
from ..indicators.volatility import atr


class OBVStrategy(BaseStrategy):
    """On-Balance Volume Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'obv_ema_period': 20,
            'price_ema_period': 20,
            'confirmation_bars': 3,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on OBV confirmation."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate OBV and its EMA
        df['obv'] = obv(df)
        df['obv_ema'] = ema(df['obv'], self.params['obv_ema_period'])
        df['price_ema'] = ema(df['close'], self.params['price_ema_period'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # OBV trend
        df['obv_rising'] = df['obv'] > df['obv'].shift(1)
        df['obv_falling'] = df['obv'] < df['obv'].shift(1)
        
        # Price trend
        df['price_rising'] = df['close'] > df['close'].shift(1)
        df['price_falling'] = df['close'] < df['close'].shift(1)
        
        # OBV above/below its EMA
        df['obv_bullish'] = df['obv'] > df['obv_ema']
        df['obv_bearish'] = df['obv'] < df['obv_ema']
        
        # Initialize signal column
        df['signal'] = 0
        
        conf_bars = self.params['confirmation_bars']
        
        # Confirmed uptrend: OBV rising + Price rising for N bars
        obv_confirmed_rising = df['obv_rising'].copy()
        price_confirmed_rising = df['price_rising'].copy()
        
        for i in range(1, conf_bars):
            obv_confirmed_rising &= df['obv_rising'].shift(i)
            price_confirmed_rising &= df['price_rising'].shift(i)
        
        # Long: OBV and price both rising, OBV above EMA
        long_condition = (
            obv_confirmed_rising &
            price_confirmed_rising &
            df['obv_bullish'] &
            (df['close'] > df['price_ema'])
        )
        
        # Confirmed downtrend
        obv_confirmed_falling = df['obv_falling'].copy()
        price_confirmed_falling = df['price_falling'].copy()
        
        for i in range(1, conf_bars):
            obv_confirmed_falling &= df['obv_falling'].shift(i)
            price_confirmed_falling &= df['price_falling'].shift(i)
        
        # Short: OBV and price both falling, OBV below EMA
        short_condition = (
            obv_confirmed_falling &
            price_confirmed_falling &
            df['obv_bearish'] &
            (df['close'] < df['price_ema'])
        )
        
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
