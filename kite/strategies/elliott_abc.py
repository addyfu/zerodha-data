"""
Elliott ABC Correction Entry Strategy
- After 5-wave impulse, expect ABC correction
- Enter at end of C wave for new impulse
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr


class ElliottABCStrategy(BaseStrategy):
    """Elliott ABC Correction Entry Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'lookback': 60,
            'c_wave_min_retracement': 0.618,  # C typically reaches 61.8% of impulse
            'c_wave_max_retracement': 1.0,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.5,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def _identify_impulse_and_correction(self, df: pd.DataFrame, end_idx: int, 
                                          lookback: int) -> tuple:
        """Identify potential impulse wave and ABC correction."""
        window = df.iloc[max(0, end_idx-lookback):end_idx+1]
        
        # Find the major swing points
        swing_high = window['high'].max()
        swing_low = window['low'].min()
        swing_high_idx = window['high'].idxmax()
        swing_low_idx = window['low'].idxmin()
        
        impulse_range = swing_high - swing_low
        
        # Determine if we had an upward or downward impulse
        if swing_low_idx < swing_high_idx:
            # Upward impulse, looking for ABC correction down
            return swing_low, swing_high, 'up', impulse_range
        else:
            # Downward impulse, looking for ABC correction up
            return swing_high, swing_low, 'down', impulse_range
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on ABC correction completion."""
        df = df.copy()
        self.validate_data(df)
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        lookback = self.params['lookback']
        min_ret = self.params['c_wave_min_retracement']
        max_ret = self.params['c_wave_max_retracement']
        
        for i in range(lookback, len(df)):
            idx = df.index[i]
            
            impulse_start, impulse_end, direction, impulse_range = \
                self._identify_impulse_and_correction(df, i-1, lookback)
            
            if impulse_range <= 0:
                continue
            
            current_close = df.loc[idx, 'close']
            current_low = df.loc[idx, 'low']
            current_high = df.loc[idx, 'high']
            
            if direction == 'up':
                # After upward impulse, ABC correction goes down
                # C wave ends near Wave 4 low (approximately 38.2-61.8% of impulse)
                correction_depth = (impulse_end - current_low) / impulse_range
                
                # Check if C wave is complete (deep enough correction)
                if min_ret <= correction_depth <= max_ret:
                    # Bullish reversal at C wave end
                    bullish_candle = current_close > df['open'].iloc[i]
                    close_in_upper_half = current_close > (current_low + (current_high - current_low) * 0.5)
                    
                    if bullish_candle and close_in_upper_half:
                        df.loc[idx, 'signal'] = Signal.BUY.value
                        df.loc[idx, 'impulse_start'] = impulse_start
                        df.loc[idx, 'impulse_end'] = impulse_end
            
            elif direction == 'down':
                # After downward impulse, ABC correction goes up
                correction_depth = (current_high - impulse_end) / impulse_range
                
                if min_ret <= correction_depth <= max_ret:
                    bearish_candle = current_close < df['open'].iloc[i]
                    close_in_lower_half = current_close < (current_low + (current_high - current_low) * 0.5)
                    
                    if bearish_candle and close_in_lower_half:
                        df.loc[idx, 'signal'] = Signal.SELL.value
                        df.loc[idx, 'impulse_start'] = impulse_start
                        df.loc[idx, 'impulse_end'] = impulse_end
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Stop loss beyond the C wave extreme."""
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
        """Target based on new impulse projection."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
