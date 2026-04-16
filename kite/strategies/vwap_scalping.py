"""
VWAP Scalping Strategy
- Trade bounces from VWAP
- Long bias when price above VWAP
- Short bias when price below VWAP
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volume import vwap
from ..indicators.volatility import atr


class VWAPScalpingStrategy(BaseStrategy):
    """VWAP Scalping Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'vwap_touch_tolerance': 0.002,  # 0.2% tolerance
            'atr_period': 14,
            'atr_multiplier': 1.5,
            'risk_reward': 1.5,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on VWAP bounces."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate VWAP
        df['vwap'] = vwap(df, reset_daily=True)
        df['atr'] = atr(df, self.params['atr_period'])
        
        tolerance = self.params['vwap_touch_tolerance']
        
        # VWAP touch detection
        df['touches_vwap'] = (
            (df['low'] <= df['vwap'] * (1 + tolerance)) &
            (df['high'] >= df['vwap'] * (1 - tolerance))
        )
        
        # Bias based on price position
        df['above_vwap'] = df['close'] > df['vwap']
        df['below_vwap'] = df['close'] < df['vwap']
        
        # Candle patterns
        df['bullish_candle'] = df['close'] > df['open']
        df['bearish_candle'] = df['close'] < df['open']
        
        # Initialize signal column
        df['signal'] = 0
        
        # Long: Price above VWAP + touches VWAP + bullish candle
        long_condition = (
            df['above_vwap'] &
            df['touches_vwap'] &
            df['bullish_candle'] &
            (df['low'] <= df['vwap'] * (1 + tolerance))  # Pullback to VWAP
        )
        
        # Short: Price below VWAP + touches VWAP + bearish candle
        short_condition = (
            df['below_vwap'] &
            df['touches_vwap'] &
            df['bearish_candle'] &
            (df['high'] >= df['vwap'] * (1 - tolerance))  # Rally to VWAP
        )
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using ATR."""
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
        """Calculate take profit based on risk-reward ratio."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
