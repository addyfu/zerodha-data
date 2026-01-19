"""
CCI Double Divergence Strategy

Wait for CCI to hit extreme levels (-200/+200) twice, form divergence, 
then enter on momentum shift.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import cci
from ..indicators.volatility import atr


class CCIDivergenceStrategy(BaseStrategy):
    """CCI Double Divergence reversal strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'cci_period': 21,
            'extreme_level': 200,
            'lookback': 30,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "CCI_Divergence"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        self.validate_data(df)
        
        # Calculate indicators
        df['cci'] = cci(df, self.params['cci_period'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal
        df['signal'] = 0
        
        extreme = self.params['extreme_level']
        lookback = self.params['lookback']
        
        for i in range(lookback * 2, len(df)):
            window = df.iloc[i-lookback:i+1]
            current_idx = df.index[i]
            
            # Check for oversold divergence (bullish)
            oversold_hits = window[window['cci'] <= -extreme]
            if len(oversold_hits) >= 2:
                # Check for bullish divergence: price lower low, CCI higher low
                first_hit_idx = oversold_hits.index[0]
                last_hit_idx = oversold_hits.index[-1]
                
                if first_hit_idx != last_hit_idx:
                    price_first = df.loc[first_hit_idx, 'close']
                    price_last = df.loc[last_hit_idx, 'close']
                    cci_first = df.loc[first_hit_idx, 'cci']
                    cci_last = df.loc[last_hit_idx, 'cci']
                    
                    # Bullish divergence: price makes lower low, CCI makes higher low
                    if price_last < price_first and cci_last > cci_first:
                        # Confirm with CCI crossing above -100
                        if df.loc[current_idx, 'cci'] > -100 and window['cci'].iloc[-2] <= -100:
                            df.loc[current_idx, 'signal'] = Signal.BUY.value
            
            # Check for overbought divergence (bearish)
            overbought_hits = window[window['cci'] >= extreme]
            if len(overbought_hits) >= 2:
                first_hit_idx = overbought_hits.index[0]
                last_hit_idx = overbought_hits.index[-1]
                
                if first_hit_idx != last_hit_idx:
                    price_first = df.loc[first_hit_idx, 'close']
                    price_last = df.loc[last_hit_idx, 'close']
                    cci_first = df.loc[first_hit_idx, 'cci']
                    cci_last = df.loc[last_hit_idx, 'cci']
                    
                    # Bearish divergence: price makes higher high, CCI makes lower high
                    if price_last > price_first and cci_last < cci_first:
                        # Confirm with CCI crossing below 100
                        if df.loc[current_idx, 'cci'] < 100 and window['cci'].iloc[-2] >= 100:
                            df.loc[current_idx, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        entry_price = df.loc[idx, 'close']
        current_atr = df.loc[idx, 'atr']
        
        if direction == Signal.BUY:
            return entry_price - (current_atr * self.params['atr_multiplier'])
        else:
            return entry_price + (current_atr * self.params['atr_multiplier'])
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, direction: Signal,
                             entry_price: float, stop_loss: float) -> float:
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
