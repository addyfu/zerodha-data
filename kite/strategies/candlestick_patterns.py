"""
Candlestick Pattern Strategy
- Hammer at support = Bullish
- Shooting star at resistance = Bearish
- Engulfing patterns = Strong reversal
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr


class CandlestickPatternStrategy(BaseStrategy):
    """Candlestick Pattern Strategy at S/R levels."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'sr_lookback': 20,
            'body_ratio': 0.3,  # Max body size relative to range for hammer/star
            'wick_ratio': 2.0,  # Min wick size relative to body
            'engulf_ratio': 1.1,  # Min engulfing body ratio
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def _is_hammer(self, row: pd.Series, body_ratio: float, wick_ratio: float) -> bool:
        """Check if candle is a hammer (bullish reversal)."""
        body = abs(row['close'] - row['open'])
        total_range = row['high'] - row['low']
        
        if total_range == 0:
            return False
        
        lower_wick = min(row['open'], row['close']) - row['low']
        upper_wick = row['high'] - max(row['open'], row['close'])
        
        # Hammer: Small body, long lower wick, small upper wick
        small_body = body / total_range <= body_ratio
        long_lower_wick = lower_wick >= body * wick_ratio if body > 0 else lower_wick > total_range * 0.5
        small_upper_wick = upper_wick <= body * 0.5 if body > 0 else upper_wick < total_range * 0.2
        
        return small_body and long_lower_wick and small_upper_wick
    
    def _is_shooting_star(self, row: pd.Series, body_ratio: float, wick_ratio: float) -> bool:
        """Check if candle is a shooting star (bearish reversal)."""
        body = abs(row['close'] - row['open'])
        total_range = row['high'] - row['low']
        
        if total_range == 0:
            return False
        
        lower_wick = min(row['open'], row['close']) - row['low']
        upper_wick = row['high'] - max(row['open'], row['close'])
        
        # Shooting star: Small body, long upper wick, small lower wick
        small_body = body / total_range <= body_ratio
        long_upper_wick = upper_wick >= body * wick_ratio if body > 0 else upper_wick > total_range * 0.5
        small_lower_wick = lower_wick <= body * 0.5 if body > 0 else lower_wick < total_range * 0.2
        
        return small_body and long_upper_wick and small_lower_wick
    
    def _is_bullish_engulfing(self, curr: pd.Series, prev: pd.Series, ratio: float) -> bool:
        """Check for bullish engulfing pattern."""
        prev_bearish = prev['close'] < prev['open']
        curr_bullish = curr['close'] > curr['open']
        
        if not (prev_bearish and curr_bullish):
            return False
        
        curr_body = curr['close'] - curr['open']
        prev_body = prev['open'] - prev['close']
        
        # Current body engulfs previous body
        engulfs = (curr['open'] <= prev['close'] and 
                   curr['close'] >= prev['open'] and
                   curr_body >= prev_body * ratio)
        
        return engulfs
    
    def _is_bearish_engulfing(self, curr: pd.Series, prev: pd.Series, ratio: float) -> bool:
        """Check for bearish engulfing pattern."""
        prev_bullish = prev['close'] > prev['open']
        curr_bearish = curr['close'] < curr['open']
        
        if not (prev_bullish and curr_bearish):
            return False
        
        curr_body = curr['open'] - curr['close']
        prev_body = prev['close'] - prev['open']
        
        engulfs = (curr['open'] >= prev['close'] and 
                   curr['close'] <= prev['open'] and
                   curr_body >= prev_body * ratio)
        
        return engulfs
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on candlestick patterns."""
        df = df.copy()
        self.validate_data(df)
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # S/R levels
        lookback = self.params['sr_lookback']
        df['support'] = df['low'].rolling(window=lookback).min()
        df['resistance'] = df['high'].rolling(window=lookback).max()
        
        # Initialize signal column
        df['signal'] = 0
        
        body_ratio = self.params['body_ratio']
        wick_ratio = self.params['wick_ratio']
        engulf_ratio = self.params['engulf_ratio']
        
        for i in range(lookback + 1, len(df)):
            idx = df.index[i]
            curr = df.iloc[i]
            prev = df.iloc[i-1]
            
            support = df['support'].iloc[i-1]
            resistance = df['resistance'].iloc[i-1]
            
            # Near support
            near_support = curr['low'] <= support * 1.01
            
            # Near resistance
            near_resistance = curr['high'] >= resistance * 0.99
            
            # Bullish patterns at support
            if near_support:
                if self._is_hammer(curr, body_ratio, wick_ratio):
                    df.loc[idx, 'signal'] = Signal.BUY.value
                elif self._is_bullish_engulfing(curr, prev, engulf_ratio):
                    df.loc[idx, 'signal'] = Signal.BUY.value
            
            # Bearish patterns at resistance
            if near_resistance:
                if self._is_shooting_star(curr, body_ratio, wick_ratio):
                    df.loc[idx, 'signal'] = Signal.SELL.value
                elif self._is_bearish_engulfing(curr, prev, engulf_ratio):
                    df.loc[idx, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Stop loss at pattern high/low."""
        atr_val = df.loc[idx, 'atr']
        
        if direction == Signal.BUY:
            return df.loc[idx, 'low'] - atr_val
        else:
            return df.loc[idx, 'high'] + atr_val
    
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
