"""
Wyckoff Distribution Trading Strategy
- Identifies distribution phases: PSY, BC, AR, ST, UTAD, SOW, LPSY
- Short on UTAD (aggressive) or LPSY rally (conservative)
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volume import obv
from ..indicators.volatility import atr


class WyckoffDistributionStrategy(BaseStrategy):
    """Wyckoff Distribution Pattern Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'lookback': 50,
            'volume_spike_mult': 2.0,
            'utad_tolerance': 0.02,  # 2% above resistance
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
        """Generate signals based on Wyckoff distribution pattern."""
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
        
        # Initialize signal column
        df['signal'] = 0
        
        utad_tol = self.params['utad_tolerance']
        
        for i in range(lookback * 2, len(df)):
            idx = df.index[i]
            
            support = df.loc[idx, 'support']
            resistance = df.loc[idx, 'resistance']
            current_high = df.loc[idx, 'high']
            current_close = df.loc[idx, 'close']
            current_low = df.loc[idx, 'low']
            
            # UTAD (Upthrust After Distribution): Price briefly breaks above resistance then closes below
            utad_level = resistance * (1 + utad_tol)
            
            is_utad = (
                (current_high > resistance) &
                (current_close < resistance) &
                (current_close < df['open'].iloc[i])  # Bearish close
            )
            
            # Sign of Weakness (SOW): Break below support with volume
            is_sow = (
                (current_close < support) &
                df.loc[idx, 'volume_spike'] &
                (df['obv'].iloc[i] < df['obv'].iloc[i-5])  # OBV falling
            )
            
            # Last Point of Supply (LPSY): Rally after SOW
            recent_sow = False
            for j in range(max(0, i-10), i):
                if df['low'].iloc[j] < df['support'].iloc[j]:
                    recent_sow = True
                    break
            
            is_lpsy = (
                recent_sow &
                (current_high >= resistance * 0.98) &  # Near resistance
                (current_close < current_low + (current_high - current_low) * 0.5) &  # Close in lower half
                (df['close'].iloc[i] < df['open'].iloc[i])  # Bearish candle
            )
            
            # Generate signals
            if is_utad:
                df.loc[idx, 'signal'] = Signal.SELL.value
            elif is_lpsy:
                df.loc[idx, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Stop loss above the UTAD high or resistance."""
        resistance = df.loc[idx, 'resistance']
        atr_val = df.loc[idx, 'atr']
        
        return resistance + atr_val
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, 
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """Target is support or based on risk-reward."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        return entry_price - reward
