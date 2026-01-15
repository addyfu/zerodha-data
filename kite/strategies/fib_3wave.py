"""
Strategy 9: 3-Wave Fibonacci Strategy

This strategy trades the 3rd wave after trendline breakout using Fibonacci.
- Find trendline breakout (AB wave)
- Wait for retracement to 50% Fib level
- Target 161.8% Fibonacci extension
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

from kite.strategies.base_strategy import BaseStrategy, Signal
from kite.indicators.fibonacci import calculate_3wave_setup, find_swing_points
from kite.indicators.volatility import atr
from kite.config import strategy_params


class Fib3WaveStrategy(BaseStrategy):
    """
    3-Wave Fibonacci Strategy.
    
    Trades the extension move after identifying ABC pattern.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = strategy_params.fib_3wave.copy()
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "Fib_3Wave"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate buy/sell signals based on 3-wave Fibonacci pattern.
        
        Signal Logic:
        - BUY: Bullish 3-wave pattern, price at 50% retracement
        - SELL: Bearish 3-wave pattern, price at 50% retracement
        """
        self.validate_data(df)
        df = df.copy()
        
        # Calculate ATR
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Calculate minimum wave size
        min_wave_pct = (df['atr'] / df['close']) * self.params['min_wave_atr']
        
        # Find 3-wave patterns
        df = calculate_3wave_setup(df, min_wave_size=0.02, swing_lookback=5)
        
        # Generate signals
        df['signal'] = 0
        
        # Look for entry opportunities at 50% retracement
        for i in range(len(df)):
            idx = df.index[i]
            
            if df.loc[idx, 'wave_pattern'] == 'bullish_3wave':
                # Check if price is at entry level
                entry_level = df.loc[idx, 'fib_entry_50']
                if pd.notna(entry_level):
                    current_low = df.loc[idx, 'low']
                    current_close = df.loc[idx, 'close']
                    tolerance = df.loc[idx, 'atr'] * 0.3
                    
                    # Price touched 50% level and bounced
                    if current_low <= entry_level + tolerance and current_close > entry_level:
                        df.loc[idx, 'signal'] = Signal.BUY.value
            
            elif df.loc[idx, 'wave_pattern'] == 'bearish_3wave':
                # Check if price is at entry level
                entry_level = df.loc[idx, 'fib_entry_50']
                if pd.notna(entry_level):
                    current_high = df.loc[idx, 'high']
                    current_close = df.loc[idx, 'close']
                    tolerance = df.loc[idx, 'atr'] * 0.3
                    
                    # Price touched 50% level and bounced
                    if current_high >= entry_level - tolerance and current_close < entry_level:
                        df.loc[idx, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, 
                           direction: Signal) -> float:
        """
        Calculate stop loss at 23.6% Fibonacci level.
        """
        fib_stop = df.loc[idx, 'fib_stop_23']
        
        if pd.notna(fib_stop):
            return fib_stop
        
        # Fallback to ATR-based stop
        atr_val = df.loc[idx, 'atr']
        if direction == Signal.BUY:
            return df.loc[idx, 'low'] - (atr_val * 2)
        else:
            return df.loc[idx, 'high'] + (atr_val * 2)
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int,
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """
        Calculate take profit at 161.8% Fibonacci extension.
        """
        fib_target = df.loc[idx, 'fib_target_161']
        
        if pd.notna(fib_target):
            return fib_target
        
        # Fallback to risk-reward based target
        risk = abs(entry_price - stop_loss)
        reward = risk * 3.0  # 3:1 R:R
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
