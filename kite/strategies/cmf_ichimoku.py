"""
Chaikin Money Flow (CMF) + Ichimoku Cloud Strategy

Uses CMF for volume confirmation with Kumo Cloud for trend filter.

Rules:
- Long: Price above Kumo + CMF crosses above +0.05
- Short: Price below Kumo + CMF crosses below -0.05
- Avoid: CMF between -0.05 and +0.05 (decision zone)
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volume import chaikin_money_flow
from ..indicators.trend import add_ichimoku
from ..indicators.volatility import atr


class CMFIchimokuStrategy(BaseStrategy):
    """
    Chaikin Money Flow + Ichimoku Cloud Strategy.
    
    Uses CMF for volume confirmation with Kumo cloud trend filter.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'cmf_period': 21,
            'cmf_threshold': 0.05,  # Threshold for bullish/bearish
            'tenkan_period': 9,
            'kijun_period': 26,
            'senkou_b_period': 52,
            'displacement': 26,
            'atr_period': 14,
            'atr_sl_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "CMF_Ichimoku"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate trading signals based on CMF and Ichimoku."""
        df = df.copy()
        self.validate_data(df)
        
        # Add CMF
        df['cmf'] = chaikin_money_flow(df, self.params['cmf_period'])
        
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
        
        threshold = self.params['cmf_threshold']
        
        # Detect CMF threshold crosses
        df['cmf_cross_bull'] = (df['cmf'] > threshold) & (df['cmf'].shift(1) <= threshold)
        df['cmf_cross_bear'] = (df['cmf'] < -threshold) & (df['cmf'].shift(1) >= -threshold)
        
        # CMF in decision zone (neutral)
        df['cmf_neutral'] = (df['cmf'] > -threshold) & (df['cmf'] < threshold)
        
        # Initialize signal column
        df['signal'] = 0
        
        # Skip if not enough data
        min_period = max(self.params['cmf_period'], self.params['senkou_b_period'] + self.params['displacement'])
        if len(df) < min_period + 2:
            return df
        
        for i in range(min_period + 1, len(df)):
            idx = df.index[i]
            
            # Skip if data not available or inside cloud or CMF neutral
            if pd.isna(df.loc[idx, 'cmf']) or pd.isna(df.loc[idx, 'kumo_top']):
                continue
            if df.loc[idx, 'inside_kumo']:
                continue
            
            # LONG SIGNAL: Price above cloud + CMF crosses above threshold
            if df.loc[idx, 'above_kumo'] and df.loc[idx, 'cmf_cross_bull']:
                df.loc[idx, 'signal'] = Signal.BUY.value
            
            # SHORT SIGNAL: Price below cloud + CMF crosses below -threshold
            elif df.loc[idx, 'below_kumo'] and df.loc[idx, 'cmf_cross_bear']:
                df.loc[idx, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using Kumo and ATR."""
        entry_price = df.loc[idx, 'close']
        current_atr = df.loc[idx, 'atr']
        
        if direction == Signal.BUY:
            # Stop below Kumo top or ATR-based
            kumo_stop = df.loc[idx, 'kumo_top'] * 0.995
            atr_stop = entry_price - (current_atr * self.params['atr_sl_multiplier'])
            return max(kumo_stop, atr_stop)
        else:
            # Stop above Kumo bottom or ATR-based
            kumo_stop = df.loc[idx, 'kumo_bottom'] * 1.005
            atr_stop = entry_price + (current_atr * self.params['atr_sl_multiplier'])
            return min(kumo_stop, atr_stop)
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, direction: Signal,
                             entry_price: float, stop_loss: float) -> float:
        """Calculate take profit based on risk-reward ratio."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
