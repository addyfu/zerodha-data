"""
Stochastic Divergence Strategy
- Bullish: Price lower low + Stochastic higher low in oversold zone
- Bearish: Price higher high + Stochastic lower high in overbought zone
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import stochastic
from ..indicators.volatility import atr


class StochasticDivergenceStrategy(BaseStrategy):
    """Stochastic Divergence Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'k_period': 14,
            'd_period': 3,
            'smooth_k': 3,
            'oversold': 20,
            'overbought': 80,
            'divergence_lookback': 20,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on Stochastic divergence."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate Stochastic
        stoch_k, stoch_d = stochastic(
            df,
            self.params['k_period'],
            self.params['d_period'],
            self.params['smooth_k']
        )
        
        df['stoch_k'] = stoch_k
        df['stoch_d'] = stoch_d
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        lookback = self.params['divergence_lookback']
        oversold = self.params['oversold']
        overbought = self.params['overbought']
        
        for i in range(lookback * 2, len(df)):
            window_price_low = df['low'].iloc[i-lookback:i+1]
            window_price_high = df['high'].iloc[i-lookback:i+1]
            window_stoch = df['stoch_k'].iloc[i-lookback:i+1]
            
            current_idx = df.index[i]
            current_stoch = df.loc[current_idx, 'stoch_k']
            
            # Bullish Divergence: Price lower low, Stochastic higher low in oversold
            if current_stoch < oversold:
                # Find two lowest price points
                price_low_idx = window_price_low.idxmin()
                current_price_low = df.loc[current_idx, 'low']
                prev_price_low = df.loc[price_low_idx, 'low']
                
                if current_idx != price_low_idx:
                    prev_stoch = df.loc[price_low_idx, 'stoch_k']
                    
                    # Price lower low, stoch higher low
                    if current_price_low < prev_price_low and current_stoch > prev_stoch:
                        # Confirm with K crossing above D
                        if (df.loc[current_idx, 'stoch_k'] > df.loc[current_idx, 'stoch_d'] and
                            df['stoch_k'].iloc[i-1] <= df['stoch_d'].iloc[i-1]):
                            df.loc[current_idx, 'signal'] = Signal.BUY.value
            
            # Bearish Divergence: Price higher high, Stochastic lower high in overbought
            if current_stoch > overbought:
                # Find two highest price points
                price_high_idx = window_price_high.idxmax()
                current_price_high = df.loc[current_idx, 'high']
                prev_price_high = df.loc[price_high_idx, 'high']
                
                if current_idx != price_high_idx:
                    prev_stoch = df.loc[price_high_idx, 'stoch_k']
                    
                    # Price higher high, stoch lower high
                    if current_price_high > prev_price_high and current_stoch < prev_stoch:
                        # Confirm with K crossing below D
                        if (df.loc[current_idx, 'stoch_k'] < df.loc[current_idx, 'stoch_d'] and
                            df['stoch_k'].iloc[i-1] >= df['stoch_d'].iloc[i-1]):
                            df.loc[current_idx, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using ATR."""
        atr_val = df.loc[idx, 'atr'] if 'atr' in df.columns else df['atr'].iloc[-1]
        entry_price = df.loc[idx, 'close']
        multiplier = self.params['atr_multiplier']
        
        if direction == Signal.BUY:
            return entry_price - (atr_val * multiplier)
        else:
            return entry_price + (atr_val * multiplier)
    
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
