"""
Rate of Change (ROC) + Moving Average Strategy

Uses ROC zero-line crossovers filtered by moving average trend.

Rules:
- Long: Price above 50 SMA + ROC crosses above zero
- Short: Price below 50 SMA + ROC crosses below zero
- Exit: When ROC slope reverses
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import roc
from ..indicators.moving_averages import sma
from ..indicators.volatility import atr


class ROCMAStrategy(BaseStrategy):
    """
    Rate of Change + Moving Average Strategy.
    
    Uses ROC zero-line crossovers with MA trend filter.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'roc_period': 14,
            'ma_period': 50,
            'atr_period': 14,
            'atr_sl_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "ROC_MA"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate trading signals based on ROC and MA."""
        df = df.copy()
        self.validate_data(df)
        
        # Add ROC
        df['roc'] = roc(df['close'], self.params['roc_period'])
        
        # Add trend MA
        df['trend_ma'] = sma(df['close'], self.params['ma_period'])
        
        # Add ATR
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Detect ROC zero-line crosses
        df['roc_cross_up'] = (df['roc'] > 0) & (df['roc'].shift(1) <= 0)
        df['roc_cross_down'] = (df['roc'] < 0) & (df['roc'].shift(1) >= 0)
        
        # Price relative to MA
        df['above_ma'] = df['close'] > df['trend_ma']
        df['below_ma'] = df['close'] < df['trend_ma']
        
        # Initialize signal column
        df['signal'] = 0
        
        # Skip if not enough data
        min_period = max(self.params['roc_period'], self.params['ma_period'])
        if len(df) < min_period + 2:
            return df
        
        for i in range(min_period + 1, len(df)):
            idx = df.index[i]
            
            # Skip if data not available
            if pd.isna(df.loc[idx, 'roc']) or pd.isna(df.loc[idx, 'trend_ma']):
                continue
            
            # LONG SIGNAL: Price above MA + ROC crosses above zero
            if df.loc[idx, 'above_ma'] and df.loc[idx, 'roc_cross_up']:
                df.loc[idx, 'signal'] = Signal.BUY.value
            
            # SHORT SIGNAL: Price below MA + ROC crosses below zero
            elif df.loc[idx, 'below_ma'] and df.loc[idx, 'roc_cross_down']:
                df.loc[idx, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using ATR and MA."""
        entry_price = df.loc[idx, 'close']
        current_atr = df.loc[idx, 'atr']
        trend_ma = df.loc[idx, 'trend_ma']
        
        if direction == Signal.BUY:
            # Stop below MA or ATR-based
            ma_stop = trend_ma * 0.995
            atr_stop = entry_price - (current_atr * self.params['atr_sl_multiplier'])
            return max(ma_stop, atr_stop)
        else:
            # Stop above MA or ATR-based
            ma_stop = trend_ma * 1.005
            atr_stop = entry_price + (current_atr * self.params['atr_sl_multiplier'])
            return min(ma_stop, atr_stop)
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, direction: Signal,
                             entry_price: float, stop_loss: float) -> float:
        """Calculate take profit based on risk-reward ratio."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
