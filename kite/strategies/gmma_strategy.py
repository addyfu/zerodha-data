"""
GMMA (Guppy Multiple Moving Average) Strategy

12 EMAs split into short-term (traders) and long-term (investors) groups.
Trade when short-term group crosses long-term group.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.moving_averages import gmma
from ..indicators.volatility import atr


class GMMAStrategy(BaseStrategy):
    """Guppy Multiple Moving Average trend following strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'separation_threshold': 0.5,  # Min separation for trend strength
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "GMMA"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        self.validate_data(df)
        
        # Calculate GMMA
        gmma_data = gmma(df)
        
        df['short_avg'] = gmma_data['short_avg']
        df['long_avg'] = gmma_data['long_avg']
        df['short_spread'] = gmma_data['short_spread']
        df['long_spread'] = gmma_data['long_spread']
        
        # Store individual EMAs for analysis
        for name, series in gmma_data['short_emas'].items():
            df[f'short_{name}'] = series
        for name, series in gmma_data['long_emas'].items():
            df[f'long_{name}'] = series
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal
        df['signal'] = 0
        
        # Short-term group above/below long-term group
        short_above_long = df['short_avg'] > df['long_avg']
        short_below_long = df['short_avg'] < df['long_avg']
        
        # Crossover detection
        cross_up = short_above_long & ~short_above_long.shift(1).fillna(False)
        cross_down = short_below_long & ~short_below_long.shift(1).fillna(False)
        
        # Trend strength: groups should be separated (not compressed)
        # Normalize spread by price
        short_spread_pct = df['short_spread'] / df['close'] * 100
        long_spread_pct = df['long_spread'] / df['close'] * 100
        
        # Groups expanding = strong trend
        short_expanding = short_spread_pct > short_spread_pct.shift(1)
        long_expanding = long_spread_pct > long_spread_pct.shift(1)
        
        # Generate signals
        # Buy: Short crosses above long, groups expanding
        buy_signal = cross_up & (short_expanding | long_expanding)
        
        # Sell: Short crosses below long, groups expanding
        sell_signal = cross_down & (short_expanding | long_expanding)
        
        df.loc[buy_signal, 'signal'] = Signal.BUY.value
        df.loc[sell_signal, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        entry_price = df.loc[idx, 'close']
        current_atr = df.loc[idx, 'atr']
        
        if direction == Signal.BUY:
            # Stop below long-term average
            return min(entry_price - (current_atr * self.params['atr_multiplier']),
                      df.loc[idx, 'long_avg'] * 0.99)
        else:
            return max(entry_price + (current_atr * self.params['atr_multiplier']),
                      df.loc[idx, 'long_avg'] * 1.01)
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, direction: Signal,
                             entry_price: float, stop_loss: float) -> float:
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
