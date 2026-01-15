"""
Strategy 1: 21/55 EMA Contraction-Expansion Strategy

This strategy trades pullbacks to the dynamic zone between 21 and 55 EMAs.
- Entry: When price retraces to the 21-55 EMA zone and bounces with breakout confirmation
- Stop Loss: Below/above the 55 EMA
- Target: 1.5:1 risk-reward ratio
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


class EMA2155Strategy(BaseStrategy):
    """
    21/55 EMA Contraction-Expansion Strategy.
    
    Trades pullbacks to the dynamic zone between fast (21) and slow (55) EMAs.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = strategy_params.ema_21_55.copy()
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "EMA_21_55"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate buy/sell signals based on EMA contraction-expansion.
        
        Signal Logic:
        - BUY: Price pulls back to 21-55 zone in uptrend, then breaks out above
        - SELL: Price pulls back to 21-55 zone in downtrend, then breaks out below
        """
        self.validate_data(df)
        df = df.copy()
        
        # Calculate EMAs
        fast_period = self.params['fast_period']
        slow_period = self.params['slow_period']
        
        df['ema_fast'] = ema(df['close'], fast_period)
        df['ema_slow'] = ema(df['close'], slow_period)
        
        # Calculate ATR for stops
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Calculate EMA slopes
        df['ema_fast_slope'] = ma_slope(df['ema_fast'], 3)
        df['ema_slow_slope'] = ma_slope(df['ema_slow'], 3)
        
        # Determine trend
        df['uptrend'] = (df['ema_fast'] > df['ema_slow']) & (df['ema_slow_slope'] > 0)
        df['downtrend'] = (df['ema_fast'] < df['ema_slow']) & (df['ema_slow_slope'] < 0)
        
        # Dynamic zone (between EMAs)
        df['zone_upper'] = df[['ema_fast', 'ema_slow']].max(axis=1)
        df['zone_lower'] = df[['ema_fast', 'ema_slow']].min(axis=1)
        
        # Check if price is in the zone
        df['in_zone'] = (df['low'] <= df['zone_upper']) & (df['high'] >= df['zone_lower'])
        
        # Check if price was in zone recently (within last 3 candles)
        df['was_in_zone'] = df['in_zone'].rolling(window=3).max().shift(1) > 0
        
        # Price breaks out of zone
        df['breakout_up'] = (df['close'] > df['zone_upper']) & df['was_in_zone']
        df['breakout_down'] = (df['close'] < df['zone_lower']) & df['was_in_zone']
        
        # Generate signals
        df['signal'] = 0
        
        # BUY: Uptrend + was in zone + breakout up
        buy_condition = (
            df['uptrend'] & 
            df['breakout_up'] & 
            (df['ema_fast_slope'] > 0) &
            (~df['ema_fast'].isna())
        )
        df.loc[buy_condition, 'signal'] = Signal.BUY.value
        
        # SELL: Downtrend + was in zone + breakout down
        sell_condition = (
            df['downtrend'] & 
            df['breakout_down'] & 
            (df['ema_fast_slope'] < 0) &
            (~df['ema_fast'].isna())
        )
        df.loc[sell_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, 
                           direction: Signal) -> float:
        """
        Calculate stop loss using ATR below/above the slow EMA.
        """
        atr_val = df.loc[idx, 'atr']
        ema_slow = df.loc[idx, 'ema_slow']
        multiplier = self.params['atr_multiplier']
        
        if direction == Signal.BUY:
            # Stop below the slow EMA
            stop = ema_slow - (atr_val * multiplier)
        else:
            # Stop above the slow EMA
            stop = ema_slow + (atr_val * multiplier)
        
        return stop
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int,
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """
        Calculate take profit based on risk-reward ratio.
        """
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
