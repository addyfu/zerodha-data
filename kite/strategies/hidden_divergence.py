"""
Hidden Divergence Trading Strategy (Trend Continuation)
- Bullish Hidden: Price higher low + Indicator lower low (in uptrend)
- Bearish Hidden: Price lower high + Indicator higher high (in downtrend)
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import rsi, macd
from ..indicators.moving_averages import ema
from ..indicators.volatility import atr


class HiddenDivergenceStrategy(BaseStrategy):
    """Hidden Divergence Strategy for trend continuation."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'rsi_period': 14,
            'ema_period': 50,
            'divergence_lookback': 20,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on hidden divergence."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate indicators
        df['rsi'] = rsi(df['close'], self.params['rsi_period'])
        df['ema'] = ema(df['close'], self.params['ema_period'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Trend direction
        df['uptrend'] = df['close'] > df['ema']
        df['downtrend'] = df['close'] < df['ema']
        
        # Initialize signal column
        df['signal'] = 0
        
        lookback = self.params['divergence_lookback']
        
        for i in range(lookback * 2, len(df)):
            idx = df.index[i]
            
            window_price_low = df['low'].iloc[i-lookback:i+1]
            window_price_high = df['high'].iloc[i-lookback:i+1]
            window_rsi = df['rsi'].iloc[i-lookback:i+1]
            
            current_price_low = df.loc[idx, 'low']
            current_price_high = df.loc[idx, 'high']
            current_rsi = df.loc[idx, 'rsi']
            
            # Hidden Bullish: In uptrend, price higher low, RSI lower low
            if df.loc[idx, 'uptrend']:
                price_min_idx = window_price_low.idxmin()
                if price_min_idx != idx:
                    prev_price_low = df.loc[price_min_idx, 'low']
                    prev_rsi = df.loc[price_min_idx, 'rsi']
                    
                    if current_price_low > prev_price_low and current_rsi < prev_rsi:
                        # Confirm with RSI turning up
                        if df['rsi'].iloc[i] > df['rsi'].iloc[i-1]:
                            df.loc[idx, 'signal'] = Signal.BUY.value
            
            # Hidden Bearish: In downtrend, price lower high, RSI higher high
            if df.loc[idx, 'downtrend']:
                price_max_idx = window_price_high.idxmax()
                if price_max_idx != idx:
                    prev_price_high = df.loc[price_max_idx, 'high']
                    prev_rsi = df.loc[price_max_idx, 'rsi']
                    
                    if current_price_high < prev_price_high and current_rsi > prev_rsi:
                        # Confirm with RSI turning down
                        if df['rsi'].iloc[i] < df['rsi'].iloc[i-1]:
                            df.loc[idx, 'signal'] = Signal.SELL.value
        
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
