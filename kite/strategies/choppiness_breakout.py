"""
Choppiness Breakout Strategy
- CI above 61.8 for extended period = Consolidation
- CI drops below 61.8 + price breaks S/R = Breakout
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr
from ..indicators.moving_averages import sma


def choppiness_index(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Choppiness Index."""
    atr_val = atr(df, 1)
    atr_sum = atr_val.rolling(window=period).sum()
    
    high_max = df['high'].rolling(window=period).max()
    low_min = df['low'].rolling(window=period).min()
    
    ci = 100 * np.log10(atr_sum / (high_max - low_min)) / np.log10(period)
    return ci


class ChoppinessBreakoutStrategy(BaseStrategy):
    """Choppiness Breakout Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'ci_period': 14,
            'ci_choppy': 61.8,
            'consolidation_bars': 5,
            'breakout_period': 20,
            'volume_period': 20,
            'volume_mult': 1.2,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on choppiness breakout."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate Choppiness Index
        df['ci'] = choppiness_index(df, self.params['ci_period'])
        
        # S/R levels
        period = self.params['breakout_period']
        df['resistance'] = df['high'].rolling(window=period).max()
        df['support'] = df['low'].rolling(window=period).min()
        
        # Volume
        df['volume_sma'] = sma(df['volume'], self.params['volume_period'])
        df['volume_high'] = df['volume'] > (df['volume_sma'] * self.params['volume_mult'])
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        ci_choppy = self.params['ci_choppy']
        cons_bars = self.params['consolidation_bars']
        
        for i in range(cons_bars + 1, len(df)):
            idx = df.index[i]
            
            # Check for extended consolidation (CI > choppy for N bars)
            was_consolidating = all(df['ci'].iloc[i-cons_bars:i] > ci_choppy)
            
            # CI now dropping (trend starting)
            ci_dropping = df['ci'].iloc[i] < ci_choppy
            
            if was_consolidating and ci_dropping:
                # Breakout above resistance
                if (df['close'].iloc[i] > df['resistance'].iloc[i-1] and
                    df['volume_high'].iloc[i]):
                    df.loc[idx, 'signal'] = Signal.BUY.value
                
                # Breakdown below support
                elif (df['close'].iloc[i] < df['support'].iloc[i-1] and
                      df['volume_high'].iloc[i]):
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
