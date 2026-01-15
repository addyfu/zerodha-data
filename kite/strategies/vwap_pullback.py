"""
Strategy 3: VWAP Pullback Strategy

This strategy trades pullbacks to VWAP in trending markets.
- In uptrends, buy pullbacks to VWAP
- In downtrends, sell rallies to VWAP
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

from kite.strategies.base_strategy import BaseStrategy, Signal
from kite.indicators.volume import vwap, add_vwap
from kite.indicators.moving_averages import ema
from kite.indicators.volatility import atr
from kite.config import strategy_params


class VWAPPullbackStrategy(BaseStrategy):
    """
    VWAP Pullback Strategy.
    
    Trades pullbacks to VWAP as dynamic support/resistance.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = strategy_params.vwap_pullback.copy()
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "VWAP_Pullback"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate buy/sell signals based on VWAP pullbacks.
        
        Signal Logic:
        - BUY: Price in uptrend, pulls back to VWAP, then closes above VWAP
        - SELL: Price in downtrend, rallies to VWAP, then closes below VWAP
        """
        self.validate_data(df)
        df = df.copy()
        
        # Calculate VWAP
        df = add_vwap(df, reset_daily=True)
        
        # Calculate trend using EMA
        df['ema_20'] = ema(df['close'], 20)
        df['ema_50'] = ema(df['close'], 50)
        
        # Calculate ATR
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Determine trend
        df['uptrend'] = (df['close'] > df['ema_20']) & (df['ema_20'] > df['ema_50'])
        df['downtrend'] = (df['close'] < df['ema_20']) & (df['ema_20'] < df['ema_50'])
        
        # VWAP touch detection
        vwap_tolerance = df['atr'] * 0.5  # Half ATR tolerance
        df['touched_vwap'] = (
            (df['low'] <= df['vwap'] + vwap_tolerance) & 
            (df['high'] >= df['vwap'] - vwap_tolerance)
        )
        
        # Price was below VWAP and now above (bullish)
        df['vwap_cross_up'] = (df['close'] > df['vwap']) & (df['close'].shift(1) <= df['vwap'].shift(1))
        
        # Price was above VWAP and now below (bearish)
        df['vwap_cross_down'] = (df['close'] < df['vwap']) & (df['close'].shift(1) >= df['vwap'].shift(1))
        
        # Check for pullback (price came from above/below VWAP)
        df['came_from_above'] = df['close'].shift(1) > df['vwap'].shift(1)
        df['came_from_below'] = df['close'].shift(1) < df['vwap'].shift(1)
        
        # Generate signals
        df['signal'] = 0
        
        # BUY: Uptrend + touched VWAP from above + closed back above
        buy_condition = (
            df['uptrend'] &
            df['touched_vwap'] &
            (df['close'] > df['vwap']) &
            (df['low'] <= df['vwap'] * 1.002)  # Actually touched VWAP
        )
        df.loc[buy_condition, 'signal'] = Signal.BUY.value
        
        # SELL: Downtrend + touched VWAP from below + closed back below
        sell_condition = (
            df['downtrend'] &
            df['touched_vwap'] &
            (df['close'] < df['vwap']) &
            (df['high'] >= df['vwap'] * 0.998)  # Actually touched VWAP
        )
        df.loc[sell_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, 
                           direction: Signal) -> float:
        """
        Calculate stop loss below recent swing low/high.
        """
        atr_val = df.loc[idx, 'atr']
        multiplier = self.params['atr_multiplier']
        
        # Look back for recent swing
        lookback = 5
        start_idx = max(0, df.index.get_loc(idx) - lookback)
        recent_data = df.iloc[start_idx:df.index.get_loc(idx) + 1]
        
        if direction == Signal.BUY:
            # Stop below recent low
            recent_low = recent_data['low'].min()
            stop = recent_low - (atr_val * 0.5)
        else:
            # Stop above recent high
            recent_high = recent_data['high'].max()
            stop = recent_high + (atr_val * 0.5)
        
        return stop
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int,
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """
        Calculate take profit based on risk-reward ratio.
        """
        risk = abs(entry_price - stop_loss)
        reward = risk * 2.0  # 2:1 R:R
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
