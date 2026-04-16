"""
Market Swing Analysis Strategy
- Up bar: Higher high, higher low
- Down bar: Lower high, lower low
- Trade based on swing direction changes
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr


class MarketSwingStrategy(BaseStrategy):
    """Market Swing Analysis Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'swing_confirmation': 2,  # Bars to confirm swing
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on market swing analysis."""
        df = df.copy()
        self.validate_data(df)
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Bar classification
        df['up_bar'] = (df['high'] > df['high'].shift(1)) & (df['low'] > df['low'].shift(1))
        df['down_bar'] = (df['high'] < df['high'].shift(1)) & (df['low'] < df['low'].shift(1))
        df['inside_bar'] = (df['high'] < df['high'].shift(1)) & (df['low'] > df['low'].shift(1))
        df['outside_bar'] = (df['high'] > df['high'].shift(1)) & (df['low'] < df['low'].shift(1))
        
        # Initialize signal column
        df['signal'] = 0
        
        conf = self.params['swing_confirmation']
        
        for i in range(conf + 1, len(df)):
            idx = df.index[i]
            
            # Check for swing direction change
            # Upswing starts: After down bars, up bar appears
            was_down = all(df['down_bar'].iloc[i-conf:i])
            now_up = df['up_bar'].iloc[i]
            
            if was_down and now_up:
                df.loc[idx, 'signal'] = Signal.BUY.value
            
            # Downswing starts: After up bars, down bar appears
            was_up = all(df['up_bar'].iloc[i-conf:i])
            now_down = df['down_bar'].iloc[i]
            
            if was_up and now_down:
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
