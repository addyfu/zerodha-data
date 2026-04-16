"""
Wyckoff Accumulation Trading Strategy
- Identifies accumulation phases: PS, SC, AR, ST, Spring, SOS, LPS
- Entry on Spring (aggressive) or LPS pullback (conservative)
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volume import obv
from ..indicators.volatility import atr


class WyckoffAccumulationStrategy(BaseStrategy):
    """Wyckoff Accumulation Pattern Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'lookback': 50,
            'volume_spike_mult': 2.0,
            'spring_tolerance': 0.02,  # 2% below support
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 3.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def _find_support_resistance(self, df: pd.DataFrame, lookback: int) -> tuple:
        """Find support and resistance levels."""
        support = df['low'].rolling(window=lookback).min()
        resistance = df['high'].rolling(window=lookback).max()
        return support, resistance
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on Wyckoff accumulation pattern."""
        df = df.copy()
        self.validate_data(df)
        
        lookback = self.params['lookback']
        
        # Calculate indicators
        df['obv'] = obv(df)
        df['atr'] = atr(df, self.params['atr_period'])
        df['volume_sma'] = df['volume'].rolling(window=20).mean()
        df['volume_spike'] = df['volume'] > (df['volume_sma'] * self.params['volume_spike_mult'])
        
        # Support and resistance
        df['support'], df['resistance'] = self._find_support_resistance(df, lookback)
        df['range'] = df['resistance'] - df['support']
        
        # Initialize signal column
        df['signal'] = 0
        
        spring_tol = self.params['spring_tolerance']
        
        for i in range(lookback * 2, len(df)):
            idx = df.index[i]
            
            support = df.loc[idx, 'support']
            resistance = df.loc[idx, 'resistance']
            current_low = df.loc[idx, 'low']
            current_close = df.loc[idx, 'close']
            current_high = df.loc[idx, 'high']
            
            # Spring detection: Price briefly breaks below support then closes above
            spring_level = support * (1 - spring_tol)
            
            # Spring: Low goes below support but closes above
            is_spring = (
                (current_low < support) &
                (current_close > support) &
                (current_close > df['open'].iloc[i])  # Bullish close
            )
            
            # Sign of Strength (SOS): Break above resistance with volume
            is_sos = (
                (current_close > resistance) &
                df.loc[idx, 'volume_spike'] &
                (df['obv'].iloc[i] > df['obv'].iloc[i-5])  # OBV rising
            )
            
            # Last Point of Support (LPS): Pullback after SOS
            # Check if there was a recent SOS and now pulling back
            recent_sos = False
            for j in range(max(0, i-10), i):
                if df['high'].iloc[j] > df['resistance'].iloc[j]:
                    recent_sos = True
                    break
            
            is_lps = (
                recent_sos &
                (current_low <= support * 1.02) &  # Near support
                (current_close > current_low + (current_high - current_low) * 0.5) &  # Close in upper half
                (df['close'].iloc[i] > df['open'].iloc[i])  # Bullish candle
            )
            
            # Generate signals
            if is_spring:
                df.loc[idx, 'signal'] = Signal.BUY.value
            elif is_lps:
                df.loc[idx, 'signal'] = Signal.BUY.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Stop loss below the spring low or support."""
        support = df.loc[idx, 'support']
        atr_val = df.loc[idx, 'atr']
        
        return support - atr_val
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, 
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """Target is resistance or based on risk-reward."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        return entry_price + reward
