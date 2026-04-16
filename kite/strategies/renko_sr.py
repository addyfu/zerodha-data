"""
Renko Support/Resistance Strategy
- Uses ATR-based price levels as S/R
- Trade bounces from clear S/R levels
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr


class RenkoSRStrategy(BaseStrategy):
    """Renko-style Support/Resistance Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'brick_atr_mult': 1.0,
            'sr_lookback': 50,
            'touch_count': 2,  # Minimum touches for valid S/R
            'tolerance': 0.005,  # 0.5% tolerance
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def _find_sr_levels(self, df: pd.DataFrame, lookback: int, 
                        brick_size: float, tolerance: float) -> tuple:
        """Find support and resistance levels based on price clustering."""
        # Round prices to brick size
        rounded_highs = (df['high'] / brick_size).round() * brick_size
        rounded_lows = (df['low'] / brick_size).round() * brick_size
        
        # Count touches at each level
        all_levels = pd.concat([rounded_highs, rounded_lows])
        level_counts = all_levels.value_counts()
        
        # Filter for significant levels
        min_touches = self.params['touch_count']
        significant_levels = level_counts[level_counts >= min_touches].index.tolist()
        
        return significant_levels
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on S/R bounces."""
        df = df.copy()
        self.validate_data(df)
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        lookback = self.params['sr_lookback']
        tolerance = self.params['tolerance']
        
        for i in range(lookback, len(df)):
            idx = df.index[i]
            
            # Get brick size
            brick_size = df['atr'].iloc[i] * self.params['brick_atr_mult']
            if pd.isna(brick_size) or brick_size <= 0:
                continue
            
            # Find S/R levels from recent data
            window = df.iloc[i-lookback:i]
            sr_levels = self._find_sr_levels(window, lookback, brick_size, tolerance)
            
            if not sr_levels:
                continue
            
            current_close = df.loc[idx, 'close']
            current_low = df.loc[idx, 'low']
            current_high = df.loc[idx, 'high']
            
            # Check for bounces from S/R levels
            for level in sr_levels:
                level_tolerance = level * tolerance
                
                # Support bounce (price touches level from above and bounces)
                if (current_low <= level + level_tolerance and 
                    current_low >= level - level_tolerance and
                    current_close > level and
                    current_close > df['open'].iloc[i]):
                    df.loc[idx, 'signal'] = Signal.BUY.value
                    df.loc[idx, 'sr_level'] = level
                    break
                
                # Resistance rejection (price touches level from below and rejects)
                if (current_high >= level - level_tolerance and 
                    current_high <= level + level_tolerance and
                    current_close < level and
                    current_close < df['open'].iloc[i]):
                    df.loc[idx, 'signal'] = Signal.SELL.value
                    df.loc[idx, 'sr_level'] = level
                    break
        
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
