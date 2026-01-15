"""
Strategy 5: 3-EMA Scalping Strategy

This strategy uses three EMAs (50, 100, 150) for scalping.
- All EMAs must be trending in same direction
- Entry on pullback to 50 or 100 EMA
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

from kite.strategies.base_strategy import BaseStrategy, Signal
from kite.indicators.moving_averages import ema, ma_slope
from kite.indicators.volatility import atr
from kite.config import strategy_params


class EMA3ScalpingStrategy(BaseStrategy):
    """
    3-EMA Scalping Strategy.
    
    Uses 50, 100, 150 EMAs for trend identification and pullback entries.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = strategy_params.ema_3_scalping.copy()
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "EMA_3_Scalping"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate buy/sell signals based on 3-EMA pullback.
        
        Signal Logic:
        - BUY: All EMAs aligned bullish + price pulls back to 50/100 EMA + closes above 50 EMA
        - SELL: All EMAs aligned bearish + price pulls back to 50/100 EMA + closes below 50 EMA
        """
        self.validate_data(df)
        df = df.copy()
        
        # Calculate EMAs
        df['ema_fast'] = ema(df['close'], self.params['ema_fast'])
        df['ema_medium'] = ema(df['close'], self.params['ema_medium'])
        df['ema_slow'] = ema(df['close'], self.params['ema_slow'])
        
        # Calculate ATR
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Calculate slopes
        df['ema_fast_slope'] = ma_slope(df['ema_fast'], 3)
        df['ema_medium_slope'] = ma_slope(df['ema_medium'], 3)
        df['ema_slow_slope'] = ma_slope(df['ema_slow'], 3)
        
        # EMAs aligned bullish (fast > medium > slow, all sloping up)
        min_slope = self.params['min_slope']
        df['emas_bullish'] = (
            (df['ema_fast'] > df['ema_medium']) &
            (df['ema_medium'] > df['ema_slow']) &
            (df['ema_fast_slope'] > min_slope) &
            (df['ema_medium_slope'] > min_slope) &
            (df['ema_slow_slope'] > min_slope)
        )
        
        # EMAs aligned bearish (fast < medium < slow, all sloping down)
        df['emas_bearish'] = (
            (df['ema_fast'] < df['ema_medium']) &
            (df['ema_medium'] < df['ema_slow']) &
            (df['ema_fast_slope'] < -min_slope) &
            (df['ema_medium_slope'] < -min_slope) &
            (df['ema_slow_slope'] < -min_slope)
        )
        
        # Pullback to 50 or 100 EMA
        ema_tolerance = df['atr'] * 0.3
        
        df['touched_fast_ema'] = (
            (df['low'] <= df['ema_fast'] + ema_tolerance) &
            (df['high'] >= df['ema_fast'] - ema_tolerance)
        )
        
        df['touched_medium_ema'] = (
            (df['low'] <= df['ema_medium'] + ema_tolerance) &
            (df['high'] >= df['ema_medium'] - ema_tolerance)
        )
        
        # Price closes back above/below 50 EMA after pullback
        df['close_above_fast'] = df['close'] > df['ema_fast']
        df['close_below_fast'] = df['close'] < df['ema_fast']
        
        # Was below/above 50 EMA in previous candle (pullback confirmation)
        df['was_below_fast'] = df['close'].shift(1) < df['ema_fast'].shift(1)
        df['was_above_fast'] = df['close'].shift(1) > df['ema_fast'].shift(1)
        
        # Generate signals
        df['signal'] = 0
        
        # BUY: EMAs bullish + touched EMA + closed above 50 EMA
        buy_condition = (
            df['emas_bullish'] &
            (df['touched_fast_ema'] | df['touched_medium_ema']) &
            df['close_above_fast'] &
            (df['low'] < df['ema_fast'])  # Actually dipped below
        )
        df.loc[buy_condition, 'signal'] = Signal.BUY.value
        
        # SELL: EMAs bearish + touched EMA + closed below 50 EMA
        sell_condition = (
            df['emas_bearish'] &
            (df['touched_fast_ema'] | df['touched_medium_ema']) &
            df['close_below_fast'] &
            (df['high'] > df['ema_fast'])  # Actually spiked above
        )
        df.loc[sell_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, 
                           direction: Signal) -> float:
        """
        Calculate stop loss below the pullback low/high.
        """
        atr_val = df.loc[idx, 'atr']
        
        if direction == Signal.BUY:
            # Stop below the candle low
            stop = df.loc[idx, 'low'] - (atr_val * 0.5)
        else:
            # Stop above the candle high
            stop = df.loc[idx, 'high'] + (atr_val * 0.5)
        
        return stop
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int,
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """
        Calculate take profit - conservative for scalping.
        """
        risk = abs(entry_price - stop_loss)
        reward = risk * 1.5  # 1.5:1 R:R for scalping
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
