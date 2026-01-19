"""
MFI (Money Flow Index) Divergence Strategy

Volume-weighted RSI that incorporates money flow.
Trade divergences at extreme levels (90/10).
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import mfi
from ..indicators.moving_averages import ema
from ..indicators.volatility import atr


class MFIDivergenceStrategy(BaseStrategy):
    """Money Flow Index divergence strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'mfi_period': 14,
            'overbought': 80,
            'oversold': 20,
            'lookback': 20,
            'trend_ma': 50,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "MFI_Divergence"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        self.validate_data(df)
        
        # Calculate MFI
        df['mfi'] = mfi(df, self.params['mfi_period'])
        df['trend_ma'] = ema(df['close'], self.params['trend_ma'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal
        df['signal'] = 0
        
        lookback = self.params['lookback']
        
        for i in range(lookback, len(df)):
            window = df.iloc[i-lookback:i+1]
            current_idx = df.index[i]
            current_mfi = df.loc[current_idx, 'mfi']
            current_price = df.loc[current_idx, 'close']
            
            # Find MFI extremes in window
            mfi_min_idx = window['mfi'].idxmin()
            mfi_max_idx = window['mfi'].idxmax()
            
            # Bullish divergence: Price lower low, MFI higher low (in oversold)
            if current_mfi < self.params['oversold']:
                price_min_idx = window['close'].idxmin()
                if price_min_idx != current_idx:
                    prev_price = df.loc[price_min_idx, 'close']
                    prev_mfi = df.loc[price_min_idx, 'mfi']
                    
                    if current_price < prev_price and current_mfi > prev_mfi:
                        # Confirm with MFI crossing above oversold
                        if current_mfi > self.params['oversold'] and \
                           window['mfi'].iloc[-2] <= self.params['oversold']:
                            df.loc[current_idx, 'signal'] = Signal.BUY.value
            
            # Bearish divergence: Price higher high, MFI lower high (in overbought)
            if current_mfi > self.params['overbought']:
                price_max_idx = window['close'].idxmax()
                if price_max_idx != current_idx:
                    prev_price = df.loc[price_max_idx, 'close']
                    prev_mfi = df.loc[price_max_idx, 'mfi']
                    
                    if current_price > prev_price and current_mfi < prev_mfi:
                        # Confirm with MFI crossing below overbought
                        if current_mfi < self.params['overbought'] and \
                           window['mfi'].iloc[-2] >= self.params['overbought']:
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
