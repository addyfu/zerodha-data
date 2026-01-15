"""
Parabolic SAR + Ichimoku Cloud Strategy

Combines PSAR for entries/exits with Kumo Cloud for trend filter.

Rules:
- Long: Price above Kumo Cloud + PSAR dot appears below price
- Short: Price below Kumo Cloud + PSAR dot appears above price
- Never trade inside the cloud
- Stop Loss: At the PSAR dot level
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.trend import add_parabolic_sar, add_ichimoku
from ..indicators.volatility import atr


class PSARIchimokuStrategy(BaseStrategy):
    """
    Parabolic SAR + Ichimoku Cloud Strategy.
    
    Uses Kumo cloud for trend filter and PSAR for entry timing.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'psar_af_start': 0.02,
            'psar_af_step': 0.02,
            'psar_af_max': 0.2,
            'tenkan_period': 9,
            'kijun_period': 26,
            'senkou_b_period': 52,
            'displacement': 26,
            'atr_period': 14,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "PSAR_Ichimoku"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate trading signals based on PSAR and Ichimoku."""
        df = df.copy()
        self.validate_data(df)
        
        # Add Parabolic SAR
        df = add_parabolic_sar(
            df, 
            self.params['psar_af_start'],
            self.params['psar_af_step'],
            self.params['psar_af_max']
        )
        
        # Add Ichimoku Cloud
        df = add_ichimoku(
            df,
            self.params['tenkan_period'],
            self.params['kijun_period'],
            self.params['senkou_b_period'],
            self.params['displacement']
        )
        
        # Add ATR
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Detect PSAR flips
        df['psar_flip_bull'] = (
            (df['psar_direction'] == 1) & 
            (df['psar_direction'].shift(1) == -1)
        )
        df['psar_flip_bear'] = (
            (df['psar_direction'] == -1) & 
            (df['psar_direction'].shift(1) == 1)
        )
        
        # Initialize signal column
        df['signal'] = 0
        
        # Skip if not enough data
        min_period = max(self.params['senkou_b_period'], self.params['displacement']) + 5
        if len(df) < min_period + 2:
            return df
        
        for i in range(min_period + 1, len(df)):
            idx = df.index[i]
            
            # Skip if data not available or inside cloud
            if pd.isna(df.loc[idx, 'kumo_top']) or df.loc[idx, 'inside_kumo']:
                continue
            
            # LONG SIGNAL: Price above cloud + PSAR flips bullish
            if df.loc[idx, 'above_kumo'] and df.loc[idx, 'psar_flip_bull']:
                df.loc[idx, 'signal'] = Signal.BUY.value
            
            # SHORT SIGNAL: Price below cloud + PSAR flips bearish
            elif df.loc[idx, 'below_kumo'] and df.loc[idx, 'psar_flip_bear']:
                df.loc[idx, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using PSAR level."""
        psar = df.loc[idx, 'psar']
        entry_price = df.loc[idx, 'close']
        
        if direction == Signal.BUY:
            # PSAR is below price for long, use it as stop
            return psar * 0.998  # Small buffer
        else:
            # PSAR is above price for short, use it as stop
            return psar * 1.002  # Small buffer
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, direction: Signal,
                             entry_price: float, stop_loss: float) -> float:
        """Calculate take profit based on risk-reward ratio."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
