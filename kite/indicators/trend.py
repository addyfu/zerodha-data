"""
Trend Indicators - Parabolic SAR, Alligator, Ichimoku Cloud
"""
import pandas as pd
import numpy as np
from typing import Tuple, Dict


def parabolic_sar(df: pd.DataFrame, af_start: float = 0.02, 
                  af_step: float = 0.02, af_max: float = 0.2) -> Tuple[pd.Series, pd.Series]:
    """
    Parabolic SAR (Stop and Reverse).
    
    Args:
        df: DataFrame with high, low, close columns
        af_start: Initial acceleration factor
        af_step: Acceleration factor increment
        af_max: Maximum acceleration factor
        
    Returns:
        Tuple of (psar_values, psar_direction) where direction is 1 (bullish) or -1 (bearish)
    """
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    length = len(df)
    
    psar = np.zeros(length)
    psar_direction = np.zeros(length)
    af = np.zeros(length)
    ep = np.zeros(length)
    
    # Initialize
    psar[0] = close[0]
    psar_direction[0] = 1  # Start bullish
    af[0] = af_start
    ep[0] = high[0]
    
    for i in range(1, length):
        # Previous values
        prev_psar = psar[i - 1]
        prev_af = af[i - 1]
        prev_ep = ep[i - 1]
        prev_direction = psar_direction[i - 1]
        
        if prev_direction == 1:  # Bullish
            # Calculate new PSAR
            psar[i] = prev_psar + prev_af * (prev_ep - prev_psar)
            
            # Make sure PSAR is not above prior two lows
            psar[i] = min(psar[i], low[i - 1])
            if i >= 2:
                psar[i] = min(psar[i], low[i - 2])
            
            # Check for reversal
            if low[i] < psar[i]:
                # Reverse to bearish
                psar_direction[i] = -1
                psar[i] = prev_ep  # EP becomes new PSAR
                af[i] = af_start
                ep[i] = low[i]
            else:
                # Continue bullish
                psar_direction[i] = 1
                
                # Update EP and AF
                if high[i] > prev_ep:
                    ep[i] = high[i]
                    af[i] = min(prev_af + af_step, af_max)
                else:
                    ep[i] = prev_ep
                    af[i] = prev_af
        
        else:  # Bearish
            # Calculate new PSAR
            psar[i] = prev_psar + prev_af * (prev_ep - prev_psar)
            
            # Make sure PSAR is not below prior two highs
            psar[i] = max(psar[i], high[i - 1])
            if i >= 2:
                psar[i] = max(psar[i], high[i - 2])
            
            # Check for reversal
            if high[i] > psar[i]:
                # Reverse to bullish
                psar_direction[i] = 1
                psar[i] = prev_ep  # EP becomes new PSAR
                af[i] = af_start
                ep[i] = high[i]
            else:
                # Continue bearish
                psar_direction[i] = -1
                
                # Update EP and AF
                if low[i] < prev_ep:
                    ep[i] = low[i]
                    af[i] = min(prev_af + af_step, af_max)
                else:
                    ep[i] = prev_ep
                    af[i] = prev_af
    
    return pd.Series(psar, index=df.index), pd.Series(psar_direction, index=df.index)


def add_parabolic_sar(df: pd.DataFrame, af_start: float = 0.02,
                      af_step: float = 0.02, af_max: float = 0.2) -> pd.DataFrame:
    """
    Add Parabolic SAR to DataFrame.
    
    Args:
        df: DataFrame with OHLC data
        af_start: Initial acceleration factor
        af_step: Acceleration factor increment
        af_max: Maximum acceleration factor
        
    Returns:
        DataFrame with PSAR columns
    """
    df = df.copy()
    df['psar'], df['psar_direction'] = parabolic_sar(df, af_start, af_step, af_max)
    return df


def smma(series: pd.Series, period: int) -> pd.Series:
    """
    Smoothed Moving Average (used by Alligator).
    
    Args:
        series: Price series
        period: Lookback period
        
    Returns:
        SMMA series
    """
    smma_values = series.ewm(alpha=1/period, min_periods=period).mean()
    return smma_values


def alligator(df: pd.DataFrame, jaw_period: int = 13, jaw_shift: int = 8,
              teeth_period: int = 8, teeth_shift: int = 5,
              lips_period: int = 5, lips_shift: int = 3,
              price_col: str = 'close') -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Bill Williams' Alligator Indicator.
    
    Args:
        df: DataFrame with price data
        jaw_period: Jaw (Blue) SMMA period
        jaw_shift: Jaw forward shift
        teeth_period: Teeth (Red) SMMA period
        teeth_shift: Teeth forward shift
        lips_period: Lips (Green) SMMA period
        lips_shift: Lips forward shift
        price_col: Column to use (typically median price)
        
    Returns:
        Tuple of (jaw, teeth, lips) series
    """
    # Use median price if available, otherwise use specified column
    if 'high' in df.columns and 'low' in df.columns:
        price = (df['high'] + df['low']) / 2
    else:
        price = df[price_col]
    
    # Calculate SMAs
    jaw = smma(price, jaw_period).shift(jaw_shift)
    teeth = smma(price, teeth_period).shift(teeth_shift)
    lips = smma(price, lips_period).shift(lips_shift)
    
    return jaw, teeth, lips


def add_alligator(df: pd.DataFrame, jaw_period: int = 13, jaw_shift: int = 8,
                  teeth_period: int = 8, teeth_shift: int = 5,
                  lips_period: int = 5, lips_shift: int = 3) -> pd.DataFrame:
    """
    Add Alligator indicator to DataFrame.
    
    Args:
        df: DataFrame with OHLC data
        jaw_period: Jaw period
        jaw_shift: Jaw shift
        teeth_period: Teeth period
        teeth_shift: Teeth shift
        lips_period: Lips period
        lips_shift: Lips shift
        
    Returns:
        DataFrame with Alligator columns
    """
    df = df.copy()
    df['alligator_jaw'], df['alligator_teeth'], df['alligator_lips'] = alligator(
        df, jaw_period, jaw_shift, teeth_period, teeth_shift, lips_period, lips_shift
    )
    
    # Add perfect order detection
    df['alligator_bullish'] = (
        (df['alligator_lips'] > df['alligator_teeth']) & 
        (df['alligator_teeth'] > df['alligator_jaw'])
    )
    df['alligator_bearish'] = (
        (df['alligator_lips'] < df['alligator_teeth']) & 
        (df['alligator_teeth'] < df['alligator_jaw'])
    )
    
    # Add sleeping (no trend) detection
    df['alligator_sleeping'] = ~(df['alligator_bullish'] | df['alligator_bearish'])
    
    return df


def alligator_mouth_width(jaw: pd.Series, teeth: pd.Series, lips: pd.Series) -> pd.Series:
    """
    Calculate Alligator mouth width (distance between jaw and lips).
    
    Args:
        jaw: Jaw series
        teeth: Teeth series
        lips: Lips series
        
    Returns:
        Width series (larger = stronger trend)
    """
    return abs(lips - jaw)


def ichimoku_cloud(df: pd.DataFrame, tenkan_period: int = 9, kijun_period: int = 26,
                   senkou_b_period: int = 52, displacement: int = 26) -> Dict[str, pd.Series]:
    """
    Ichimoku Cloud (Ichimoku Kinko Hyo).
    
    Args:
        df: DataFrame with high, low, close columns
        tenkan_period: Tenkan-sen (Conversion Line) period
        kijun_period: Kijun-sen (Base Line) period
        senkou_b_period: Senkou Span B period
        displacement: Cloud displacement (typically 26)
        
    Returns:
        Dictionary with all Ichimoku components
    """
    high = df['high']
    low = df['low']
    close = df['close']
    
    # Tenkan-sen (Conversion Line): (highest high + lowest low) / 2 for past 9 periods
    tenkan_high = high.rolling(window=tenkan_period).max()
    tenkan_low = low.rolling(window=tenkan_period).min()
    tenkan_sen = (tenkan_high + tenkan_low) / 2
    
    # Kijun-sen (Base Line): (highest high + lowest low) / 2 for past 26 periods
    kijun_high = high.rolling(window=kijun_period).max()
    kijun_low = low.rolling(window=kijun_period).min()
    kijun_sen = (kijun_high + kijun_low) / 2
    
    # Senkou Span A (Leading Span A): (Tenkan-sen + Kijun-sen) / 2, displaced forward
    senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(displacement)
    
    # Senkou Span B (Leading Span B): (highest high + lowest low) / 2 for past 52 periods, displaced
    senkou_b_high = high.rolling(window=senkou_b_period).max()
    senkou_b_low = low.rolling(window=senkou_b_period).min()
    senkou_span_b = ((senkou_b_high + senkou_b_low) / 2).shift(displacement)
    
    # Chikou Span (Lagging Span): Close displaced backwards
    chikou_span = close.shift(-displacement)
    
    return {
        'tenkan_sen': tenkan_sen,
        'kijun_sen': kijun_sen,
        'senkou_span_a': senkou_span_a,
        'senkou_span_b': senkou_span_b,
        'chikou_span': chikou_span,
    }


def add_ichimoku(df: pd.DataFrame, tenkan_period: int = 9, kijun_period: int = 26,
                 senkou_b_period: int = 52, displacement: int = 26) -> pd.DataFrame:
    """
    Add Ichimoku Cloud to DataFrame.
    
    Args:
        df: DataFrame with OHLC data
        tenkan_period: Tenkan-sen period
        kijun_period: Kijun-sen period
        senkou_b_period: Senkou Span B period
        displacement: Cloud displacement
        
    Returns:
        DataFrame with Ichimoku columns
    """
    df = df.copy()
    ichimoku = ichimoku_cloud(df, tenkan_period, kijun_period, senkou_b_period, displacement)
    
    df['tenkan_sen'] = ichimoku['tenkan_sen']
    df['kijun_sen'] = ichimoku['kijun_sen']
    df['senkou_span_a'] = ichimoku['senkou_span_a']
    df['senkou_span_b'] = ichimoku['senkou_span_b']
    df['chikou_span'] = ichimoku['chikou_span']
    
    # Add cloud analysis
    df['kumo_top'] = df[['senkou_span_a', 'senkou_span_b']].max(axis=1)
    df['kumo_bottom'] = df[['senkou_span_a', 'senkou_span_b']].min(axis=1)
    
    # Price relative to cloud
    df['above_kumo'] = df['close'] > df['kumo_top']
    df['below_kumo'] = df['close'] < df['kumo_bottom']
    df['inside_kumo'] = ~(df['above_kumo'] | df['below_kumo'])
    
    # Cloud color (bullish = Span A > Span B)
    df['kumo_bullish'] = df['senkou_span_a'] > df['senkou_span_b']
    
    return df


def kumo_breakout(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect Kumo (cloud) breakouts.
    
    Args:
        df: DataFrame with Ichimoku columns
        
    Returns:
        DataFrame with breakout signals
    """
    df = df.copy()
    
    if 'kumo_top' not in df.columns:
        df = add_ichimoku(df)
    
    # Bullish breakout: price crosses above cloud
    df['kumo_bullish_breakout'] = (
        (df['close'] > df['kumo_top']) & 
        (df['close'].shift(1) <= df['kumo_top'].shift(1))
    )
    
    # Bearish breakout: price crosses below cloud
    df['kumo_bearish_breakout'] = (
        (df['close'] < df['kumo_bottom']) & 
        (df['close'].shift(1) >= df['kumo_bottom'].shift(1))
    )
    
    return df


def tk_cross(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect Tenkan-sen / Kijun-sen crosses.
    
    Args:
        df: DataFrame with Ichimoku columns
        
    Returns:
        DataFrame with TK cross signals
    """
    df = df.copy()
    
    if 'tenkan_sen' not in df.columns:
        df = add_ichimoku(df)
    
    # Bullish TK cross: Tenkan crosses above Kijun
    df['tk_bullish_cross'] = (
        (df['tenkan_sen'] > df['kijun_sen']) & 
        (df['tenkan_sen'].shift(1) <= df['kijun_sen'].shift(1))
    )
    
    # Bearish TK cross: Tenkan crosses below Kijun
    df['tk_bearish_cross'] = (
        (df['tenkan_sen'] < df['kijun_sen']) & 
        (df['tenkan_sen'].shift(1) >= df['kijun_sen'].shift(1))
    )
    
    return df


def central_pivot_range(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate Central Pivot Range (CPR).
    
    Args:
        df: DataFrame with OHLC data
        
    Returns:
        DataFrame with CPR columns
    """
    df = df.copy()
    
    # Use previous day's data
    prev_high = df['high'].shift(1)
    prev_low = df['low'].shift(1)
    prev_close = df['close'].shift(1)
    
    # Pivot Point
    pivot = (prev_high + prev_low + prev_close) / 3
    
    # Bottom Central Pivot (BC)
    bc = (prev_high + prev_low) / 2
    
    # Top Central Pivot (TC)
    tc = (pivot - bc) + pivot
    
    # CPR Width
    cpr_width = abs(tc - bc)
    
    df['cpr_pivot'] = pivot
    df['cpr_tc'] = tc  # Top Central
    df['cpr_bc'] = bc  # Bottom Central
    df['cpr_width'] = cpr_width
    
    # Determine bias
    df['cpr_bullish'] = prev_close > tc  # Previous close above CPR
    df['cpr_bearish'] = prev_close < bc  # Previous close below CPR
    df['cpr_neutral'] = ~(df['cpr_bullish'] | df['cpr_bearish'])
    
    # Standard pivot levels
    diff = prev_high - prev_low
    df['cpr_r1'] = (2 * pivot) - prev_low
    df['cpr_r2'] = pivot + diff
    df['cpr_s1'] = (2 * pivot) - prev_high
    df['cpr_s2'] = pivot - diff
    
    return df
