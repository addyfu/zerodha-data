"""
Fibonacci Confluence Strategy
- Draw Fibs from multiple swing points
- Trade at confluence zones (2+ Fibs align)
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, List

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr


class FibConfluenceStrategy(BaseStrategy):
    """Fibonacci Confluence Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'swing_lookbacks': [10, 20, 40],  # Multiple timeframes
            'fib_levels': [0.382, 0.5, 0.618],
            'confluence_tolerance': 0.005,  # 0.5% for confluence
            'min_confluence': 2,  # Minimum Fibs aligning
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def _get_fib_levels(self, swing_high: float, swing_low: float, 
                        is_uptrend: bool) -> List[float]:
        """Calculate Fib levels for a swing."""
        swing_range = swing_high - swing_low
        levels = []
        
        for fib in self.params['fib_levels']:
            if is_uptrend:
                level = swing_high - (swing_range * fib)
            else:
                level = swing_low + (swing_range * fib)
            levels.append(level)
        
        return levels
    
    def _find_confluence(self, all_levels: List[float], tolerance: float) -> List[float]:
        """Find confluence zones where multiple Fibs align."""
        if not all_levels:
            return []
        
        all_levels = sorted(all_levels)
        confluence_zones = []
        
        i = 0
        while i < len(all_levels):
            cluster = [all_levels[i]]
            j = i + 1
            
            while j < len(all_levels):
                if abs(all_levels[j] - all_levels[i]) / all_levels[i] <= tolerance:
                    cluster.append(all_levels[j])
                    j += 1
                else:
                    break
            
            if len(cluster) >= self.params['min_confluence']:
                confluence_zones.append(np.mean(cluster))
            
            i = j
        
        return confluence_zones
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on Fibonacci confluence."""
        df = df.copy()
        self.validate_data(df)
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        max_lookback = max(self.params['swing_lookbacks'])
        tolerance = self.params['confluence_tolerance']
        
        for i in range(max_lookback * 2, len(df)):
            idx = df.index[i]
            
            all_fib_levels = []
            trend_votes = []
            
            # Get Fib levels from multiple swing lookbacks
            for lookback in self.params['swing_lookbacks']:
                window = df.iloc[max(0, i-lookback):i+1]
                
                swing_high = window['high'].max()
                swing_low = window['low'].min()
                
                if swing_high <= swing_low:
                    continue
                
                swing_high_pos = window['high'].idxmax()
                swing_low_pos = window['low'].idxmin()
                
                is_uptrend = swing_low_pos < swing_high_pos
                trend_votes.append(1 if is_uptrend else -1)
                
                levels = self._get_fib_levels(swing_high, swing_low, is_uptrend)
                all_fib_levels.extend(levels)
            
            if not all_fib_levels or not trend_votes:
                continue
            
            # Find confluence zones
            confluence_zones = self._find_confluence(all_fib_levels, tolerance)
            
            if not confluence_zones:
                continue
            
            current_close = df.loc[idx, 'close']
            current_low = df.loc[idx, 'low']
            current_high = df.loc[idx, 'high']
            
            # Determine overall trend
            overall_trend = sum(trend_votes)
            
            # Check if price is at a confluence zone
            for zone in confluence_zones:
                zone_tolerance = zone * tolerance
                
                if overall_trend > 0:  # Uptrend
                    if (current_low <= zone + zone_tolerance and 
                        current_low >= zone - zone_tolerance and
                        current_close > df['open'].iloc[i]):
                        df.loc[idx, 'signal'] = Signal.BUY.value
                        df.loc[idx, 'confluence_zone'] = zone
                        break
                
                elif overall_trend < 0:  # Downtrend
                    if (current_high >= zone - zone_tolerance and 
                        current_high <= zone + zone_tolerance and
                        current_close < df['open'].iloc[i]):
                        df.loc[idx, 'signal'] = Signal.SELL.value
                        df.loc[idx, 'confluence_zone'] = zone
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
