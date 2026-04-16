"""
Elliott Wave 3 Entry Strategy
- Identify Wave 1 (initial impulse)
- Wait for Wave 2 correction (50-61.8% retracement)
- Enter at end of Wave 2 for Wave 3 ride
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr


class ElliottWave3Strategy(BaseStrategy):
    """Elliott Wave 3 Entry Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'wave1_min_bars': 5,
            'wave2_min_retracement': 0.382,
            'wave2_max_retracement': 0.786,
            'wave2_ideal_low': 0.5,
            'wave2_ideal_high': 0.618,
            'lookback': 50,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 3.0,  # Wave 3 is typically longest
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def _find_wave1(self, df: pd.DataFrame, end_idx: int, lookback: int) -> tuple:
        """Find potential Wave 1 impulse."""
        window = df.iloc[max(0, end_idx-lookback):end_idx+1]
        
        # Find swing low and swing high
        swing_low_idx = window['low'].idxmin()
        swing_high_idx = window['high'].idxmax()
        
        swing_low = window.loc[swing_low_idx, 'low']
        swing_high = window.loc[swing_high_idx, 'high']
        
        # Wave 1 should be an impulse move
        # Uptrend Wave 1: Low comes before High
        if swing_low_idx < swing_high_idx:
            return swing_low, swing_high, swing_low_idx, swing_high_idx, 'up'
        else:
            return swing_high, swing_low, swing_high_idx, swing_low_idx, 'down'
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on Elliott Wave 3 entry."""
        df = df.copy()
        self.validate_data(df)
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        lookback = self.params['lookback']
        min_ret = self.params['wave2_min_retracement']
        max_ret = self.params['wave2_max_retracement']
        ideal_low = self.params['wave2_ideal_low']
        ideal_high = self.params['wave2_ideal_high']
        
        for i in range(lookback, len(df)):
            idx = df.index[i]
            
            # Find Wave 1
            wave1_start, wave1_end, start_idx, end_idx, direction = self._find_wave1(df, i-1, lookback)
            
            wave1_range = abs(wave1_end - wave1_start)
            if wave1_range <= 0:
                continue
            
            current_close = df.loc[idx, 'close']
            current_low = df.loc[idx, 'low']
            current_high = df.loc[idx, 'high']
            
            if direction == 'up':
                # Wave 2 retracement from Wave 1 high
                retracement = (wave1_end - current_low) / wave1_range
                
                # Check if in valid Wave 2 zone
                if min_ret <= retracement <= max_ret:
                    # Ideal zone (50-61.8%)
                    in_ideal_zone = ideal_low <= retracement <= ideal_high
                    
                    # Bullish reversal candle
                    bullish_candle = current_close > df['open'].iloc[i]
                    
                    # Wave 2 cannot retrace more than 100% of Wave 1
                    valid_wave2 = current_low > wave1_start
                    
                    if valid_wave2 and bullish_candle:
                        df.loc[idx, 'signal'] = Signal.BUY.value
                        df.loc[idx, 'wave1_start'] = wave1_start
                        df.loc[idx, 'wave1_end'] = wave1_end
            
            elif direction == 'down':
                # Wave 2 retracement from Wave 1 low
                retracement = (current_high - wave1_end) / wave1_range
                
                if min_ret <= retracement <= max_ret:
                    in_ideal_zone = ideal_low <= retracement <= ideal_high
                    
                    bearish_candle = current_close < df['open'].iloc[i]
                    valid_wave2 = current_high < wave1_start
                    
                    if valid_wave2 and bearish_candle:
                        df.loc[idx, 'signal'] = Signal.SELL.value
                        df.loc[idx, 'wave1_start'] = wave1_start
                        df.loc[idx, 'wave1_end'] = wave1_end
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Stop loss below Wave 1 start (Wave 2 cannot exceed 100%)."""
        if 'wave1_start' in df.columns and not pd.isna(df.loc[idx, 'wave1_start']):
            wave1_start = df.loc[idx, 'wave1_start']
            atr_val = df.loc[idx, 'atr']
            
            if direction == Signal.BUY:
                return wave1_start - atr_val
            else:
                return wave1_start + atr_val
        else:
            # Fallback to ATR-based stop
            atr_val = df.loc[idx, 'atr']
            entry_price = df.loc[idx, 'close']
            
            if direction == Signal.BUY:
                return entry_price - (atr_val * self.params['atr_multiplier'])
            else:
                return entry_price + (atr_val * self.params['atr_multiplier'])
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, 
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """Target based on Wave 3 projection (typically 1.618x Wave 1)."""
        if 'wave1_start' in df.columns and 'wave1_end' in df.columns:
            wave1_start = df.loc[idx, 'wave1_start']
            wave1_end = df.loc[idx, 'wave1_end']
            
            if not pd.isna(wave1_start) and not pd.isna(wave1_end):
                wave1_range = abs(wave1_end - wave1_start)
                wave3_target = wave1_range * 1.618
                
                if direction == Signal.BUY:
                    return entry_price + wave3_target
                else:
                    return entry_price - wave3_target
        
        # Fallback
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
