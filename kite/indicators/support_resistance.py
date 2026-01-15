"""
Support and Resistance Detection
"""
import pandas as pd
import numpy as np
from typing import List, Tuple, Optional
from collections import defaultdict


def find_support_resistance_levels(df: pd.DataFrame, 
                                   window: int = 20,
                                   num_levels: int = 5,
                                   tolerance: float = 0.02) -> Tuple[List[float], List[float]]:
    """
    Find key support and resistance levels.
    
    Args:
        df: DataFrame with OHLC data
        window: Window for finding local extrema
        num_levels: Number of levels to return
        tolerance: Tolerance for clustering nearby levels
        
    Returns:
        Tuple of (support_levels, resistance_levels)
    """
    # Find local minima (support) and maxima (resistance)
    local_min = df['low'].rolling(window=window, center=True).min()
    local_max = df['high'].rolling(window=window, center=True).max()
    
    # Get points where price equals local min/max
    support_points = df[df['low'] == local_min]['low'].tolist()
    resistance_points = df[df['high'] == local_max]['high'].tolist()
    
    # Cluster nearby levels
    support_levels = _cluster_levels(support_points, tolerance)
    resistance_levels = _cluster_levels(resistance_points, tolerance)
    
    # Sort and return top levels
    support_levels = sorted(support_levels, reverse=True)[:num_levels]
    resistance_levels = sorted(resistance_levels)[:num_levels]
    
    return support_levels, resistance_levels


def _cluster_levels(levels: List[float], tolerance: float) -> List[float]:
    """
    Cluster nearby price levels.
    
    Args:
        levels: List of price levels
        tolerance: Tolerance for clustering
        
    Returns:
        List of clustered levels
    """
    if not levels:
        return []
    
    levels = sorted(levels)
    clusters = []
    current_cluster = [levels[0]]
    
    for level in levels[1:]:
        if level <= current_cluster[-1] * (1 + tolerance):
            current_cluster.append(level)
        else:
            # Average the cluster
            clusters.append(np.mean(current_cluster))
            current_cluster = [level]
    
    # Don't forget the last cluster
    clusters.append(np.mean(current_cluster))
    
    return clusters


def add_support_resistance(df: pd.DataFrame, 
                          lookback: int = 50,
                          num_levels: int = 3) -> pd.DataFrame:
    """
    Add dynamic support and resistance levels to DataFrame.
    
    Args:
        df: DataFrame with OHLC data
        lookback: Lookback period for level calculation
        num_levels: Number of levels to track
        
    Returns:
        DataFrame with S/R columns
    """
    df = df.copy()
    
    # Initialize columns
    for i in range(1, num_levels + 1):
        df[f'support_{i}'] = np.nan
        df[f'resistance_{i}'] = np.nan
    
    for i in range(lookback, len(df)):
        window_df = df.iloc[i-lookback:i]
        
        support, resistance = find_support_resistance_levels(
            window_df, window=5, num_levels=num_levels
        )
        
        idx = df.index[i]
        for j, level in enumerate(support[:num_levels], 1):
            df.loc[idx, f'support_{j}'] = level
        for j, level in enumerate(resistance[:num_levels], 1):
            df.loc[idx, f'resistance_{j}'] = level
    
    return df


def detect_sr_touch(df: pd.DataFrame, 
                    tolerance: float = 0.005) -> pd.DataFrame:
    """
    Detect when price touches support/resistance levels.
    
    Args:
        df: DataFrame with S/R columns
        tolerance: Tolerance for touch detection
        
    Returns:
        DataFrame with touch detection columns
    """
    df = df.copy()
    
    df['support_touch'] = False
    df['resistance_touch'] = False
    df['touched_level'] = np.nan
    
    sr_cols = [col for col in df.columns if col.startswith(('support_', 'resistance_'))]
    
    for idx in df.index:
        low = df.loc[idx, 'low']
        high = df.loc[idx, 'high']
        
        for col in sr_cols:
            level = df.loc[idx, col]
            if pd.isna(level):
                continue
            
            # Check if price touched the level
            lower_bound = level * (1 - tolerance)
            upper_bound = level * (1 + tolerance)
            
            if low <= upper_bound and high >= lower_bound:
                if 'support' in col:
                    df.loc[idx, 'support_touch'] = True
                else:
                    df.loc[idx, 'resistance_touch'] = True
                df.loc[idx, 'touched_level'] = level
    
    return df


def horizontal_sr_zones(df: pd.DataFrame, 
                        min_touches: int = 2,
                        zone_width_pct: float = 0.01) -> List[Tuple[float, float, int]]:
    """
    Find horizontal support/resistance zones with multiple touches.
    
    Args:
        df: DataFrame with OHLC data
        min_touches: Minimum touches to qualify as zone
        zone_width_pct: Zone width as percentage
        
    Returns:
        List of (zone_low, zone_high, touch_count) tuples
    """
    # Collect all price levels (highs and lows)
    price_levels = pd.concat([df['high'], df['low']]).tolist()
    
    # Create zones and count touches
    zones = defaultdict(int)
    
    for price in price_levels:
        zone_center = round(price, -1)  # Round to nearest 10
        zones[zone_center] += 1
    
    # Filter zones with minimum touches
    valid_zones = []
    for center, count in zones.items():
        if count >= min_touches:
            zone_low = center * (1 - zone_width_pct)
            zone_high = center * (1 + zone_width_pct)
            valid_zones.append((zone_low, zone_high, count))
    
    # Sort by touch count
    valid_zones.sort(key=lambda x: x[2], reverse=True)
    
    return valid_zones


def supply_demand_zones(df: pd.DataFrame, 
                        min_impulse_pct: float = 0.02,
                        lookback: int = 3) -> pd.DataFrame:
    """
    Identify supply and demand zones based on impulse moves.
    
    Args:
        df: DataFrame with OHLC data
        min_impulse_pct: Minimum impulse move percentage
        lookback: Candles to look back for zone base
        
    Returns:
        DataFrame with supply/demand zone columns
    """
    df = df.copy()
    
    df['demand_zone_high'] = np.nan
    df['demand_zone_low'] = np.nan
    df['supply_zone_high'] = np.nan
    df['supply_zone_low'] = np.nan
    df['zone_type'] = None
    
    for i in range(lookback + 1, len(df)):
        current = df.iloc[i]
        prev = df.iloc[i - 1]
        
        # Calculate move percentage
        move_pct = (current['close'] - prev['close']) / prev['close']
        
        # Bullish impulse (demand zone)
        if move_pct >= min_impulse_pct:
            # Find the base (consolidation before impulse)
            base_start = max(0, i - lookback - 1)
            base_df = df.iloc[base_start:i]
            
            # Zone is from the last bearish candle before impulse
            bearish_candles = base_df[base_df['close'] < base_df['open']]
            if len(bearish_candles) > 0:
                last_bearish = bearish_candles.iloc[-1]
                zone_low = last_bearish['low']
                zone_high = last_bearish['open']
                
                idx = df.index[i]
                df.loc[idx, 'demand_zone_low'] = zone_low
                df.loc[idx, 'demand_zone_high'] = zone_high
                df.loc[idx, 'zone_type'] = 'demand'
        
        # Bearish impulse (supply zone)
        elif move_pct <= -min_impulse_pct:
            # Find the base
            base_start = max(0, i - lookback - 1)
            base_df = df.iloc[base_start:i]
            
            # Zone is from the last bullish candle before impulse
            bullish_candles = base_df[base_df['close'] > base_df['open']]
            if len(bullish_candles) > 0:
                last_bullish = bullish_candles.iloc[-1]
                zone_low = last_bullish['open']
                zone_high = last_bullish['high']
                
                idx = df.index[i]
                df.loc[idx, 'supply_zone_low'] = zone_low
                df.loc[idx, 'supply_zone_high'] = zone_high
                df.loc[idx, 'zone_type'] = 'supply'
    
    return df


def detect_breakout(df: pd.DataFrame, 
                    lookback: int = 20,
                    volume_confirm: bool = True) -> pd.DataFrame:
    """
    Detect breakouts from support/resistance levels.
    
    Args:
        df: DataFrame with OHLC and volume data
        lookback: Period for resistance/support calculation
        volume_confirm: Require volume confirmation
        
    Returns:
        DataFrame with breakout columns
    """
    df = df.copy()
    
    # Calculate recent high/low
    recent_high = df['high'].rolling(window=lookback).max().shift(1)
    recent_low = df['low'].rolling(window=lookback).min().shift(1)
    
    # Average volume for confirmation
    avg_volume = df['volume'].rolling(window=lookback).mean()
    
    # Resistance breakout
    df['resistance_breakout'] = df['close'] > recent_high
    
    # Support breakdown
    df['support_breakdown'] = df['close'] < recent_low
    
    # Volume confirmation
    if volume_confirm:
        high_volume = df['volume'] > avg_volume * 1.5
        df['resistance_breakout'] = df['resistance_breakout'] & high_volume
        df['support_breakdown'] = df['support_breakdown'] & high_volume
    
    # Breakout direction
    df['breakout'] = 0
    df.loc[df['resistance_breakout'], 'breakout'] = 1
    df.loc[df['support_breakdown'], 'breakout'] = -1
    
    return df
