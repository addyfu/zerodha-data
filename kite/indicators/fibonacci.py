"""
Fibonacci Indicators - Retracements, Extensions, Pivot Points
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


# Standard Fibonacci levels
FIB_RETRACEMENT_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
FIB_EXTENSION_LEVELS = [1.0, 1.272, 1.414, 1.618, 2.0, 2.618]


@dataclass
class FibonacciLevels:
    """Container for Fibonacci levels."""
    swing_high: float
    swing_low: float
    direction: str  # 'up' or 'down'
    retracements: Dict[float, float]
    extensions: Dict[float, float]


def calculate_fib_retracements(swing_high: float, swing_low: float,
                               direction: str = 'up') -> Dict[float, float]:
    """
    Calculate Fibonacci retracement levels.
    
    Args:
        swing_high: Swing high price
        swing_low: Swing low price
        direction: 'up' for uptrend, 'down' for downtrend
        
    Returns:
        Dictionary mapping fib level to price
    """
    diff = swing_high - swing_low
    levels = {}
    
    if direction == 'up':
        # Retracements from high going down
        for level in FIB_RETRACEMENT_LEVELS:
            levels[level] = swing_high - (diff * level)
    else:
        # Retracements from low going up
        for level in FIB_RETRACEMENT_LEVELS:
            levels[level] = swing_low + (diff * level)
    
    return levels


def calculate_fib_extensions(point_a: float, point_b: float, 
                            point_c: float) -> Dict[float, float]:
    """
    Calculate Fibonacci extension levels.
    
    For 3-wave pattern: A->B is impulse, B->C is retracement,
    extensions project from C in direction of A->B.
    
    Args:
        point_a: Start of first wave
        point_b: End of first wave / start of retracement
        point_c: End of retracement / start of extension
        
    Returns:
        Dictionary mapping fib level to price
    """
    ab_move = point_b - point_a
    levels = {}
    
    for level in FIB_EXTENSION_LEVELS:
        levels[level] = point_c + (ab_move * level)
    
    return levels


def find_swing_points(df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """
    Identify swing highs and swing lows.
    
    Args:
        df: DataFrame with high, low columns
        lookback: Number of bars on each side to confirm swing
        
    Returns:
        DataFrame with swing_high and swing_low columns
    """
    df = df.copy()
    
    df['swing_high'] = False
    df['swing_low'] = False
    
    for i in range(lookback, len(df) - lookback):
        # Check for swing high
        is_swing_high = True
        for j in range(1, lookback + 1):
            if df['high'].iloc[i] <= df['high'].iloc[i - j] or \
               df['high'].iloc[i] <= df['high'].iloc[i + j]:
                is_swing_high = False
                break
        df.iloc[i, df.columns.get_loc('swing_high')] = is_swing_high
        
        # Check for swing low
        is_swing_low = True
        for j in range(1, lookback + 1):
            if df['low'].iloc[i] >= df['low'].iloc[i - j] or \
               df['low'].iloc[i] >= df['low'].iloc[i + j]:
                is_swing_low = False
                break
        df.iloc[i, df.columns.get_loc('swing_low')] = is_swing_low
    
    return df


def get_recent_swings(df: pd.DataFrame, n_swings: int = 2,
                      lookback: int = 5) -> Tuple[List[Tuple], List[Tuple]]:
    """
    Get the most recent swing highs and lows.
    
    Args:
        df: DataFrame with OHLC data
        n_swings: Number of recent swings to return
        lookback: Lookback for swing detection
        
    Returns:
        Tuple of (swing_highs, swing_lows) as lists of (index, price)
    """
    df_swings = find_swing_points(df, lookback)
    
    swing_highs = []
    swing_lows = []
    
    # Get swing highs
    high_indices = df_swings[df_swings['swing_high']].index[-n_swings:]
    for idx in high_indices:
        swing_highs.append((idx, df_swings.loc[idx, 'high']))
    
    # Get swing lows
    low_indices = df_swings[df_swings['swing_low']].index[-n_swings:]
    for idx in low_indices:
        swing_lows.append((idx, df_swings.loc[idx, 'low']))
    
    return swing_highs, swing_lows


def add_fib_levels(df: pd.DataFrame, lookback: int = 50) -> pd.DataFrame:
    """
    Add Fibonacci retracement levels based on recent swing.
    
    Args:
        df: DataFrame with OHLC data
        lookback: Period to find swing high/low
        
    Returns:
        DataFrame with Fibonacci level columns
    """
    df = df.copy()
    
    # Find swing high and low in lookback period
    rolling_high = df['high'].rolling(window=lookback).max()
    rolling_low = df['low'].rolling(window=lookback).min()
    
    diff = rolling_high - rolling_low
    
    # Add retracement levels
    for level in FIB_RETRACEMENT_LEVELS:
        df[f'fib_{int(level*100)}'] = rolling_high - (diff * level)
    
    return df


def detect_fib_bounce(df: pd.DataFrame, tolerance: float = 0.002) -> pd.DataFrame:
    """
    Detect price bounces off Fibonacci levels.
    
    Args:
        df: DataFrame with Fibonacci levels
        tolerance: Percentage tolerance for level touch
        
    Returns:
        DataFrame with fib_bounce column
    """
    df = df.copy()
    
    fib_cols = [col for col in df.columns if col.startswith('fib_')]
    
    df['fib_bounce'] = None
    df['fib_level_touched'] = None
    
    for idx in df.index:
        low = df.loc[idx, 'low']
        high = df.loc[idx, 'high']
        close = df.loc[idx, 'close']
        
        for fib_col in fib_cols:
            fib_level = df.loc[idx, fib_col]
            
            # Check if price touched the level
            if low <= fib_level * (1 + tolerance) and high >= fib_level * (1 - tolerance):
                # Bullish bounce (touched from above, closed higher)
                if close > fib_level:
                    df.loc[idx, 'fib_bounce'] = 'bullish'
                    df.loc[idx, 'fib_level_touched'] = fib_col
                    break
                # Bearish bounce (touched from below, closed lower)
                elif close < fib_level:
                    df.loc[idx, 'fib_bounce'] = 'bearish'
                    df.loc[idx, 'fib_level_touched'] = fib_col
                    break
    
    return df


def calculate_3wave_setup(df: pd.DataFrame, 
                          min_wave_size: float = 0.02,
                          swing_lookback: int = 5) -> pd.DataFrame:
    """
    Identify 3-wave patterns for Fibonacci extension trading.
    
    Args:
        df: DataFrame with OHLC data
        min_wave_size: Minimum wave size as percentage
        swing_lookback: Lookback for swing detection
        
    Returns:
        DataFrame with 3-wave pattern information
    """
    df = df.copy()
    df = find_swing_points(df, swing_lookback)
    
    df['wave_pattern'] = None
    df['point_a'] = np.nan
    df['point_b'] = np.nan
    df['point_c'] = np.nan
    df['fib_target_161'] = np.nan
    df['fib_entry_50'] = np.nan
    df['fib_stop_23'] = np.nan
    
    # Get all swing points
    swing_high_idx = df[df['swing_high']].index.tolist()
    swing_low_idx = df[df['swing_low']].index.tolist()
    
    # Combine and sort
    all_swings = []
    for idx in swing_high_idx:
        all_swings.append((idx, 'high', df.loc[idx, 'high']))
    for idx in swing_low_idx:
        all_swings.append((idx, 'low', df.loc[idx, 'low']))
    
    all_swings.sort(key=lambda x: x[0])
    
    # Look for ABC patterns
    for i in range(len(all_swings) - 2):
        a_idx, a_type, a_price = all_swings[i]
        b_idx, b_type, b_price = all_swings[i + 1]
        c_idx, c_type, c_price = all_swings[i + 2]
        
        # Bullish pattern: Low -> High -> Higher Low
        if a_type == 'low' and b_type == 'high' and c_type == 'low':
            ab_move = b_price - a_price
            bc_retrace = b_price - c_price
            
            # Check minimum wave size
            if ab_move / a_price < min_wave_size:
                continue
            
            # Check C is higher than A (valid higher low)
            if c_price <= a_price:
                continue
            
            # Check retracement is between 38.2% and 61.8%
            retrace_pct = bc_retrace / ab_move
            if 0.382 <= retrace_pct <= 0.618:
                # Valid bullish 3-wave pattern
                df.loc[c_idx, 'wave_pattern'] = 'bullish_3wave'
                df.loc[c_idx, 'point_a'] = a_price
                df.loc[c_idx, 'point_b'] = b_price
                df.loc[c_idx, 'point_c'] = c_price
                
                # Calculate Fibonacci levels
                df.loc[c_idx, 'fib_entry_50'] = b_price - (ab_move * 0.5)
                df.loc[c_idx, 'fib_stop_23'] = b_price - (ab_move * 0.236)
                df.loc[c_idx, 'fib_target_161'] = c_price + (ab_move * 1.618)
        
        # Bearish pattern: High -> Low -> Lower High
        elif a_type == 'high' and b_type == 'low' and c_type == 'high':
            ab_move = a_price - b_price
            bc_retrace = c_price - b_price
            
            # Check minimum wave size
            if ab_move / a_price < min_wave_size:
                continue
            
            # Check C is lower than A (valid lower high)
            if c_price >= a_price:
                continue
            
            # Check retracement is between 38.2% and 61.8%
            retrace_pct = bc_retrace / ab_move
            if 0.382 <= retrace_pct <= 0.618:
                # Valid bearish 3-wave pattern
                df.loc[c_idx, 'wave_pattern'] = 'bearish_3wave'
                df.loc[c_idx, 'point_a'] = a_price
                df.loc[c_idx, 'point_b'] = b_price
                df.loc[c_idx, 'point_c'] = c_price
                
                # Calculate Fibonacci levels
                df.loc[c_idx, 'fib_entry_50'] = b_price + (ab_move * 0.5)
                df.loc[c_idx, 'fib_stop_23'] = b_price + (ab_move * 0.236)
                df.loc[c_idx, 'fib_target_161'] = c_price - (ab_move * 1.618)
    
    return df


def pivot_points_fibonacci(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate Fibonacci Pivot Points (daily).
    
    Args:
        df: DataFrame with OHLC data
        
    Returns:
        DataFrame with pivot point columns
    """
    df = df.copy()
    
    # Use previous day's data
    prev_high = df['high'].shift(1)
    prev_low = df['low'].shift(1)
    prev_close = df['close'].shift(1)
    
    # Pivot point
    pp = (prev_high + prev_low + prev_close) / 3
    diff = prev_high - prev_low
    
    df['pivot'] = pp
    df['r1'] = pp + (diff * 0.382)
    df['r2'] = pp + (diff * 0.618)
    df['r3'] = pp + diff
    df['s1'] = pp - (diff * 0.382)
    df['s2'] = pp - (diff * 0.618)
    df['s3'] = pp - diff
    
    return df
