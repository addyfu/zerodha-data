"""
Strategy 6: Supply & Demand Zone Trading

This strategy identifies supply and demand zones based on impulse moves.
- Demand Zone: Area before sharp up-move (buying zone)
- Supply Zone: Area before sharp down-move (selling zone)
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

from kite.strategies.base_strategy import BaseStrategy, Signal
from kite.indicators.volatility import atr
from kite.indicators.support_resistance import supply_demand_zones
from kite.config import strategy_params


class SupplyDemandStrategy(BaseStrategy):
    """
    Supply & Demand Zone Trading Strategy.
    
    Trades when price returns to untouched supply/demand zones.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = strategy_params.supply_demand.copy()
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "Supply_Demand"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate buy/sell signals based on supply/demand zones.
        
        Signal Logic:
        - BUY: Price returns to fresh demand zone
        - SELL: Price returns to fresh supply zone
        """
        self.validate_data(df)
        df = df.copy()
        
        # Calculate ATR
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Calculate minimum impulse size
        min_impulse_pct = df['atr'] / df['close'] * self.params['min_impulse_atr']
        
        # Identify supply and demand zones
        df = self._identify_zones(df, min_impulse_pct)
        
        # Track zone status (fresh/touched)
        df = self._track_zone_status(df)
        
        # Generate signals
        df['signal'] = 0
        
        # BUY: Price enters fresh demand zone
        buy_condition = df['in_fresh_demand']
        df.loc[buy_condition, 'signal'] = Signal.BUY.value
        
        # SELL: Price enters fresh supply zone
        sell_condition = df['in_fresh_supply']
        df.loc[sell_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def _identify_zones(self, df: pd.DataFrame, min_impulse_pct: pd.Series) -> pd.DataFrame:
        """Identify supply and demand zones."""
        df['demand_zone_high'] = np.nan
        df['demand_zone_low'] = np.nan
        df['supply_zone_high'] = np.nan
        df['supply_zone_low'] = np.nan
        df['zone_age'] = 0
        
        for i in range(3, len(df)):
            current = df.iloc[i]
            prev = df.iloc[i - 1]
            
            # Calculate move percentage
            move_pct = (current['close'] - prev['close']) / prev['close']
            threshold = min_impulse_pct.iloc[i] if isinstance(min_impulse_pct, pd.Series) else min_impulse_pct
            
            # Bullish impulse (demand zone)
            if move_pct >= threshold:
                # Find the last bearish candle before impulse
                for j in range(i - 1, max(0, i - 5), -1):
                    candle = df.iloc[j]
                    if candle['close'] < candle['open']:  # Bearish
                        idx = df.index[i]
                        df.loc[idx, 'demand_zone_low'] = candle['low']
                        df.loc[idx, 'demand_zone_high'] = candle['open']
                        break
            
            # Bearish impulse (supply zone)
            elif move_pct <= -threshold:
                # Find the last bullish candle before impulse
                for j in range(i - 1, max(0, i - 5), -1):
                    candle = df.iloc[j]
                    if candle['close'] > candle['open']:  # Bullish
                        idx = df.index[i]
                        df.loc[idx, 'supply_zone_low'] = candle['open']
                        df.loc[idx, 'supply_zone_high'] = candle['high']
                        break
        
        return df
    
    def _track_zone_status(self, df: pd.DataFrame) -> pd.DataFrame:
        """Track which zones are fresh (untouched) and detect entries."""
        df['in_fresh_demand'] = False
        df['in_fresh_supply'] = False
        
        # Track active zones
        active_demand_zones = []  # List of (high, low, created_idx)
        active_supply_zones = []
        
        max_age = self.params['max_zone_age']
        
        for i in range(len(df)):
            idx = df.index[i]
            current_high = df.loc[idx, 'high']
            current_low = df.loc[idx, 'low']
            current_close = df.loc[idx, 'close']
            
            # Add new zones
            if pd.notna(df.loc[idx, 'demand_zone_high']):
                zone_high = df.loc[idx, 'demand_zone_high']
                zone_low = df.loc[idx, 'demand_zone_low']
                active_demand_zones.append((zone_high, zone_low, i))
            
            if pd.notna(df.loc[idx, 'supply_zone_high']):
                zone_high = df.loc[idx, 'supply_zone_high']
                zone_low = df.loc[idx, 'supply_zone_low']
                active_supply_zones.append((zone_high, zone_low, i))
            
            # Check if price enters any fresh demand zone
            zones_to_remove = []
            for j, (zone_high, zone_low, created_idx) in enumerate(active_demand_zones):
                zone_age = i - created_idx
                
                # Remove old zones
                if zone_age > max_age:
                    zones_to_remove.append(j)
                    continue
                
                # Check if price enters zone
                if current_low <= zone_high and current_high >= zone_low:
                    # Price is in the zone
                    if current_close > zone_high:  # Bounced up
                        df.loc[idx, 'in_fresh_demand'] = True
                    zones_to_remove.append(j)  # Zone is now touched
            
            for j in reversed(zones_to_remove):
                active_demand_zones.pop(j)
            
            # Check if price enters any fresh supply zone
            zones_to_remove = []
            for j, (zone_high, zone_low, created_idx) in enumerate(active_supply_zones):
                zone_age = i - created_idx
                
                # Remove old zones
                if zone_age > max_age:
                    zones_to_remove.append(j)
                    continue
                
                # Check if price enters zone
                if current_low <= zone_high and current_high >= zone_low:
                    # Price is in the zone
                    if current_close < zone_low:  # Bounced down
                        df.loc[idx, 'in_fresh_supply'] = True
                    zones_to_remove.append(j)  # Zone is now touched
            
            for j in reversed(zones_to_remove):
                active_supply_zones.pop(j)
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, 
                           direction: Signal) -> float:
        """
        Calculate stop loss beyond the zone.
        """
        atr_val = df.loc[idx, 'atr']
        buffer = atr_val * self.params['zone_atr_buffer']
        
        if direction == Signal.BUY:
            # Stop below demand zone
            zone_low = df.loc[idx, 'demand_zone_low']
            if pd.isna(zone_low):
                zone_low = df.loc[idx, 'low']
            stop = zone_low - buffer
        else:
            # Stop above supply zone
            zone_high = df.loc[idx, 'supply_zone_high']
            if pd.isna(zone_high):
                zone_high = df.loc[idx, 'high']
            stop = zone_high + buffer
        
        return stop
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int,
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """
        Calculate take profit based on risk-reward ratio.
        """
        risk = abs(entry_price - stop_loss)
        reward = risk * 2.5  # 2.5:1 R:R
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
