"""
Volatility Indicators - ATR, Bollinger Bands, Keltner Channels, Donchian
"""
import pandas as pd
import numpy as np
from typing import Tuple


def true_range(df: pd.DataFrame) -> pd.Series:
    """
    Calculate True Range.
    
    Args:
        df: DataFrame with high, low, close columns
        
    Returns:
        True Range series
    """
    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift(1))
    low_close = abs(df['low'] - df['close'].shift(1))
    
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range.
    
    Args:
        df: DataFrame with high, low, close columns
        period: Lookback period
        
    Returns:
        ATR series
    """
    tr = true_range(df)
    return tr.ewm(alpha=1/period, min_periods=period).mean()


def bollinger_bands(df: pd.DataFrame, period: int = 20, 
                    std_dev: float = 2.0,
                    price_col: str = 'close') -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Bollinger Bands.
    
    Args:
        df: DataFrame with price data
        period: Moving average period
        std_dev: Standard deviation multiplier
        price_col: Column to use
        
    Returns:
        Tuple of (upper_band, middle_band, lower_band)
    """
    middle = df[price_col].rolling(window=period).mean()
    std = df[price_col].rolling(window=period).std()
    
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    
    return upper, middle, lower


def bollinger_bandwidth(upper: pd.Series, lower: pd.Series, 
                        middle: pd.Series) -> pd.Series:
    """
    Bollinger Bandwidth (measures squeeze).
    
    Args:
        upper: Upper band
        lower: Lower band
        middle: Middle band
        
    Returns:
        Bandwidth series
    """
    return (upper - lower) / middle


def bollinger_percent_b(price: pd.Series, upper: pd.Series, 
                        lower: pd.Series) -> pd.Series:
    """
    Bollinger %B (price position within bands).
    
    Args:
        price: Price series
        upper: Upper band
        lower: Lower band
        
    Returns:
        %B series (0 = lower band, 1 = upper band)
    """
    return (price - lower) / (upper - lower)


def keltner_channels(df: pd.DataFrame, ema_period: int = 20,
                     atr_period: int = 10, 
                     multiplier: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Keltner Channels.
    
    Args:
        df: DataFrame with OHLC data
        ema_period: EMA period for middle line
        atr_period: ATR period
        multiplier: ATR multiplier
        
    Returns:
        Tuple of (upper, middle, lower)
    """
    middle = df['close'].ewm(span=ema_period, adjust=False).mean()
    atr_val = atr(df, atr_period)
    
    upper = middle + (multiplier * atr_val)
    lower = middle - (multiplier * atr_val)
    
    return upper, middle, lower


def donchian_channels(df: pd.DataFrame, 
                      period: int = 20) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Donchian Channels.
    
    Args:
        df: DataFrame with high, low columns
        period: Lookback period
        
    Returns:
        Tuple of (upper, middle, lower)
    """
    upper = df['high'].rolling(window=period).max()
    lower = df['low'].rolling(window=period).min()
    middle = (upper + lower) / 2
    
    return upper, middle, lower


def chandelier_exit(df: pd.DataFrame, period: int = 22,
                    multiplier: float = 3.0) -> Tuple[pd.Series, pd.Series]:
    """
    Chandelier Exit (trailing stop based on ATR).
    
    Args:
        df: DataFrame with OHLC data
        period: ATR and highest high/lowest low period
        multiplier: ATR multiplier
        
    Returns:
        Tuple of (long_exit, short_exit)
    """
    atr_val = atr(df, period)
    highest_high = df['high'].rolling(window=period).max()
    lowest_low = df['low'].rolling(window=period).min()
    
    long_exit = highest_high - (multiplier * atr_val)
    short_exit = lowest_low + (multiplier * atr_val)
    
    return long_exit, short_exit


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Add ATR to DataFrame.
    
    Args:
        df: DataFrame with OHLC data
        period: ATR period
        
    Returns:
        DataFrame with ATR column
    """
    df = df.copy()
    df[f'atr_{period}'] = atr(df, period)
    return df


def add_bollinger_bands(df: pd.DataFrame, period: int = 20,
                        std_dev: float = 2.0) -> pd.DataFrame:
    """
    Add Bollinger Bands to DataFrame.
    
    Args:
        df: DataFrame with OHLC data
        period: BB period
        std_dev: Standard deviation multiplier
        
    Returns:
        DataFrame with BB columns
    """
    df = df.copy()
    upper, middle, lower = bollinger_bands(df, period, std_dev)
    
    df['bb_upper'] = upper
    df['bb_middle'] = middle
    df['bb_lower'] = lower
    df['bb_bandwidth'] = bollinger_bandwidth(upper, lower, middle)
    df['bb_percent_b'] = bollinger_percent_b(df['close'], upper, lower)
    
    return df


def detect_bb_squeeze(df: pd.DataFrame, 
                      squeeze_percentile: float = 0.1) -> pd.DataFrame:
    """
    Detect Bollinger Band squeeze conditions.
    
    Args:
        df: DataFrame with bb_bandwidth column
        squeeze_percentile: Percentile threshold for squeeze
        
    Returns:
        DataFrame with squeeze column
    """
    df = df.copy()
    
    if 'bb_bandwidth' not in df.columns:
        df = add_bollinger_bands(df)
    
    # Calculate rolling percentile of bandwidth
    rolling_low = df['bb_bandwidth'].rolling(window=100).quantile(squeeze_percentile)
    
    df['bb_squeeze'] = df['bb_bandwidth'] <= rolling_low
    
    # Detect squeeze release (expansion after squeeze)
    df['squeeze_release'] = (
        ~df['bb_squeeze'] & df['bb_squeeze'].shift(1)
    )
    
    return df


def volatility_regime(df: pd.DataFrame, atr_period: int = 14,
                      lookback: int = 100) -> pd.DataFrame:
    """
    Classify volatility regime (low, normal, high).
    
    Args:
        df: DataFrame with OHLC data
        atr_period: ATR period
        lookback: Period for percentile calculation
        
    Returns:
        DataFrame with volatility regime column
    """
    df = df.copy()
    
    if f'atr_{atr_period}' not in df.columns:
        df = add_atr(df, atr_period)
    
    atr_col = f'atr_{atr_period}'
    
    # Calculate percentile rank of current ATR
    df['atr_percentile'] = df[atr_col].rolling(window=lookback).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
    )
    
    # Classify regime
    df['volatility_regime'] = 'normal'
    df.loc[df['atr_percentile'] < 0.25, 'volatility_regime'] = 'low'
    df.loc[df['atr_percentile'] > 0.75, 'volatility_regime'] = 'high'
    
    return df
