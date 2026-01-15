"""
Volume Indicators - VWAP, OBV, MFI, Volume Profile
"""
import pandas as pd
import numpy as np
from typing import Tuple, Optional


def vwap(df: pd.DataFrame, reset_daily: bool = True) -> pd.Series:
    """
    Volume Weighted Average Price.
    
    Args:
        df: DataFrame with high, low, close, volume columns
        reset_daily: Whether to reset VWAP each day
        
    Returns:
        VWAP series
    """
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    
    if reset_daily:
        # Group by date and calculate cumulative VWAP
        df_temp = df.copy()
        df_temp['typical_price'] = typical_price
        df_temp['tp_volume'] = typical_price * df['volume']
        df_temp['date'] = df_temp.index.date
        
        # Cumulative sums within each day
        df_temp['cum_tp_vol'] = df_temp.groupby('date')['tp_volume'].cumsum()
        df_temp['cum_vol'] = df_temp.groupby('date')['volume'].cumsum()
        
        vwap_values = df_temp['cum_tp_vol'] / df_temp['cum_vol']
    else:
        # Rolling VWAP without daily reset
        cum_tp_vol = (typical_price * df['volume']).cumsum()
        cum_vol = df['volume'].cumsum()
        vwap_values = cum_tp_vol / cum_vol
    
    return vwap_values


def vwap_bands(df: pd.DataFrame, std_multiplier: float = 2.0,
               reset_daily: bool = True) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    VWAP with standard deviation bands.
    
    Args:
        df: DataFrame with OHLCV data
        std_multiplier: Standard deviation multiplier
        reset_daily: Whether to reset each day
        
    Returns:
        Tuple of (upper_band, vwap, lower_band)
    """
    vwap_line = vwap(df, reset_daily)
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    
    if reset_daily:
        df_temp = df.copy()
        df_temp['typical_price'] = typical_price
        df_temp['vwap'] = vwap_line
        df_temp['date'] = df_temp.index.date
        
        # Calculate rolling variance within each day
        def cumulative_std(group):
            tp = group['typical_price']
            vwap_val = group['vwap']
            sq_diff = (tp - vwap_val) ** 2
            cum_var = sq_diff.expanding().mean()
            return np.sqrt(cum_var)
        
        std = df_temp.groupby('date').apply(cumulative_std).reset_index(level=0, drop=True)
    else:
        # Simple rolling std
        std = (typical_price - vwap_line).rolling(window=20).std()
    
    upper = vwap_line + (std_multiplier * std)
    lower = vwap_line - (std_multiplier * std)
    
    return upper, vwap_line, lower


def obv(df: pd.DataFrame) -> pd.Series:
    """
    On-Balance Volume.
    
    Args:
        df: DataFrame with close, volume columns
        
    Returns:
        OBV series
    """
    direction = np.sign(df['close'].diff())
    direction.iloc[0] = 0
    
    obv_values = (direction * df['volume']).cumsum()
    return obv_values


def obv_ema(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    OBV with EMA smoothing.
    
    Args:
        df: DataFrame with close, volume columns
        period: EMA period
        
    Returns:
        Smoothed OBV series
    """
    obv_raw = obv(df)
    return obv_raw.ewm(span=period, adjust=False).mean()


def volume_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Volume Simple Moving Average.
    
    Args:
        df: DataFrame with volume column
        period: SMA period
        
    Returns:
        Volume SMA series
    """
    return df['volume'].rolling(window=period).mean()


def relative_volume(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Relative Volume (current volume vs average).
    
    Args:
        df: DataFrame with volume column
        period: Lookback period for average
        
    Returns:
        Relative volume ratio
    """
    avg_volume = volume_sma(df, period)
    return df['volume'] / avg_volume


def volume_price_trend(df: pd.DataFrame) -> pd.Series:
    """
    Volume Price Trend (VPT).
    
    Args:
        df: DataFrame with close, volume columns
        
    Returns:
        VPT series
    """
    price_change_pct = df['close'].pct_change()
    vpt = (price_change_pct * df['volume']).cumsum()
    return vpt


def accumulation_distribution(df: pd.DataFrame) -> pd.Series:
    """
    Accumulation/Distribution Line.
    
    Args:
        df: DataFrame with OHLCV columns
        
    Returns:
        A/D Line series
    """
    clv = ((df['close'] - df['low']) - (df['high'] - df['close'])) / (df['high'] - df['low'])
    clv = clv.fillna(0)  # Handle zero range candles
    
    ad = (clv * df['volume']).cumsum()
    return ad


def chaikin_money_flow(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Chaikin Money Flow.
    
    Args:
        df: DataFrame with OHLCV columns
        period: Lookback period
        
    Returns:
        CMF series (-1 to 1)
    """
    clv = ((df['close'] - df['low']) - (df['high'] - df['close'])) / (df['high'] - df['low'])
    clv = clv.fillna(0)
    
    money_flow_volume = clv * df['volume']
    
    cmf = money_flow_volume.rolling(window=period).sum() / df['volume'].rolling(window=period).sum()
    return cmf


def add_vwap(df: pd.DataFrame, reset_daily: bool = True) -> pd.DataFrame:
    """
    Add VWAP to DataFrame.
    
    Args:
        df: DataFrame with OHLCV data
        reset_daily: Whether to reset VWAP each day
        
    Returns:
        DataFrame with VWAP column
    """
    df = df.copy()
    df['vwap'] = vwap(df, reset_daily)
    return df


def add_volume_indicators(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """
    Add multiple volume indicators to DataFrame.
    
    Args:
        df: DataFrame with OHLCV data
        period: Period for indicators
        
    Returns:
        DataFrame with volume indicator columns
    """
    df = df.copy()
    
    df['vwap'] = vwap(df)
    df['obv'] = obv(df)
    df['volume_sma'] = volume_sma(df, period)
    df['relative_volume'] = relative_volume(df, period)
    df['cmf'] = chaikin_money_flow(df, period)
    
    return df


def volume_breakout(df: pd.DataFrame, volume_threshold: float = 2.0,
                    period: int = 20) -> pd.DataFrame:
    """
    Detect volume breakouts (unusually high volume).
    
    Args:
        df: DataFrame with volume column
        volume_threshold: Multiple of average volume for breakout
        period: Period for average volume calculation
        
    Returns:
        DataFrame with volume breakout column
    """
    df = df.copy()
    
    avg_vol = volume_sma(df, period)
    df['volume_breakout'] = df['volume'] > (avg_vol * volume_threshold)
    df['volume_ratio'] = df['volume'] / avg_vol
    
    return df


def price_volume_divergence(df: pd.DataFrame, 
                            lookback: int = 20) -> pd.DataFrame:
    """
    Detect price-volume divergences.
    
    Args:
        df: DataFrame with close, volume columns
        lookback: Lookback period
        
    Returns:
        DataFrame with divergence columns
    """
    df = df.copy()
    
    # Calculate OBV
    df['obv'] = obv(df)
    
    df['pv_bullish_div'] = False
    df['pv_bearish_div'] = False
    
    for i in range(lookback, len(df)):
        window = df.iloc[i-lookback:i+1]
        current_idx = df.index[i]
        
        # Find price and OBV extremes
        price_min_idx = window['close'].idxmin()
        price_max_idx = window['close'].idxmax()
        
        current_price = df.loc[current_idx, 'close']
        current_obv = df.loc[current_idx, 'obv']
        
        # Bullish: Price lower low, OBV higher low
        if current_idx != price_min_idx:
            prev_price = df.loc[price_min_idx, 'close']
            prev_obv = df.loc[price_min_idx, 'obv']
            
            if current_price < prev_price and current_obv > prev_obv:
                df.loc[current_idx, 'pv_bullish_div'] = True
        
        # Bearish: Price higher high, OBV lower high
        if current_idx != price_max_idx:
            prev_price = df.loc[price_max_idx, 'close']
            prev_obv = df.loc[price_max_idx, 'obv']
            
            if current_price > prev_price and current_obv < prev_obv:
                df.loc[current_idx, 'pv_bearish_div'] = True
    
    return df
