"""
VWMA vs SMA Divergence Strategy

Uses the separation between Volume Weighted MA and Simple MA to confirm trends.

Rules:
- Long: VWMA above SMA + Price above both = Strong uptrend confirmation
- Short: VWMA below SMA + Price below both = Strong downtrend confirmation
- Entry: When VWMA separates from SMA in trend direction
- Exit: When VWMA and SMA converge (no separation)
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.moving_averages import sma, vwma
from ..indicators.volatility import atr


class VWMASMAStrategy(BaseStrategy):
    """
    VWMA vs SMA Divergence Strategy.
    
    Uses volume-weighted MA divergence from simple MA for trend confirmation.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'ma_period': 50,
            'separation_threshold': 0.002,  # Minimum separation as % of price
            'atr_period': 14,
            'atr_sl_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "VWMA_SMA"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate trading signals based on VWMA vs SMA divergence."""
        df = df.copy()
        self.validate_data(df)
        
        # Add VWMA and SMA
        df['vwma'] = vwma(df, self.params['ma_period'])
        df['sma'] = sma(df['close'], self.params['ma_period'])
        
        # Add ATR
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Calculate separation
        df['ma_separation'] = (df['vwma'] - df['sma']) / df['close']
        df['ma_separation_abs'] = abs(df['ma_separation'])
        
        # Determine trend conditions
        df['vwma_above_sma'] = df['vwma'] > df['sma']
        df['price_above_both'] = (df['close'] > df['vwma']) & (df['close'] > df['sma'])
        df['price_below_both'] = (df['close'] < df['vwma']) & (df['close'] < df['sma'])
        
        # Detect separation changes
        threshold = self.params['separation_threshold']
        df['significant_separation'] = df['ma_separation_abs'] > threshold
        
        # Initialize signal column
        df['signal'] = 0
        
        # Skip if not enough data
        if len(df) < self.params['ma_period'] + 2:
            return df
        
        for i in range(self.params['ma_period'] + 1, len(df)):
            idx = df.index[i]
            prev_idx = df.index[i - 1]
            
            # Skip if data not available
            if pd.isna(df.loc[idx, 'vwma']) or pd.isna(df.loc[idx, 'atr']):
                continue
            
            # Check for new separation (wasn't separated, now is)
            was_separated = df.loc[prev_idx, 'significant_separation']
            is_separated = df.loc[idx, 'significant_separation']
            
            # LONG SIGNAL: VWMA separates above SMA + Price above both
            if is_separated and df.loc[idx, 'vwma_above_sma'] and df.loc[idx, 'price_above_both']:
                # Additional confirmation: VWMA was not above before or just crossed
                if not was_separated or not df.loc[prev_idx, 'vwma_above_sma']:
                    df.loc[idx, 'signal'] = Signal.BUY.value
            
            # SHORT SIGNAL: VWMA separates below SMA + Price below both
            elif is_separated and not df.loc[idx, 'vwma_above_sma'] and df.loc[idx, 'price_below_both']:
                # Additional confirmation
                if not was_separated or df.loc[prev_idx, 'vwma_above_sma']:
                    df.loc[idx, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using ATR and MA levels."""
        entry_price = df.loc[idx, 'close']
        current_atr = df.loc[idx, 'atr']
        current_sma = df.loc[idx, 'sma']
        
        if direction == Signal.BUY:
            # Stop below SMA or ATR-based
            sma_stop = current_sma * 0.995
            atr_stop = entry_price - (current_atr * self.params['atr_sl_multiplier'])
            return max(sma_stop, atr_stop)
        else:
            # Stop above SMA or ATR-based
            sma_stop = current_sma * 1.005
            atr_stop = entry_price + (current_atr * self.params['atr_sl_multiplier'])
            return min(sma_stop, atr_stop)
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, direction: Signal,
                             entry_price: float, stop_loss: float) -> float:
        """Calculate take profit based on risk-reward ratio."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
