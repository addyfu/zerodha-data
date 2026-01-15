"""
Moving Average Indicators - EMA, SMA, WMA, HMA, VWMA
"""
import pandas as pd
import numpy as np
from typing import Optional


def sma(series: pd.Series, period: int) -> pd.Series:
    """
    Simple Moving Average.
    
    Args:
        series: Price series
        period: Lookback period
        
    Returns:
        SMA series
    """
    return series.rolling(window=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """
    Exponential Moving Average.
    
    Args:
        series: Price series
        period: Lookback period
        
    Returns:
        EMA series
    """
    return series.ewm(span=period, adjust=False).mean()


def wma(series: pd.Series, period: int) -> pd.Series:
    """
    Weighted Moving Average.
    
    Args:
        series: Price series
        period: Lookback period
        
    Returns:
        WMA series
    """
    weights = np.arange(1, period + 1)
    return series.rolling(window=period).apply(
        lambda x: np.dot(x, weights) / weights.sum(), raw=True
    )


def hma(series: pd.Series, period: int) -> pd.Series:
    """
    Hull Moving Average - Faster and smoother.
    
    Args:
        series: Price series
        period: Lookback period
        
    Returns:
        HMA series
    """
    half_period = int(period / 2)
    sqrt_period = int(np.sqrt(period))
    
    wma_half = wma(series, half_period)
    wma_full = wma(series, period)
    
    raw_hma = 2 * wma_half - wma_full
    return wma(raw_hma, sqrt_period)


def vwma(df: pd.DataFrame, period: int, price_col: str = 'close') -> pd.Series:
    """
    Volume Weighted Moving Average.
    
    Args:
        df: DataFrame with price and volume columns
        period: Lookback period
        price_col: Column to use for price
        
    Returns:
        VWMA series
    """
    pv = df[price_col] * df['volume']
    return pv.rolling(window=period).sum() / df['volume'].rolling(window=period).sum()


def tema(series: pd.Series, period: int) -> pd.Series:
    """
    Triple Exponential Moving Average - Very responsive.
    
    Args:
        series: Price series
        period: Lookback period
        
    Returns:
        TEMA series
    """
    ema1 = ema(series, period)
    ema2 = ema(ema1, period)
    ema3 = ema(ema2, period)
    return 3 * ema1 - 3 * ema2 + ema3


def dema(series: pd.Series, period: int) -> pd.Series:
    """
    Double Exponential Moving Average.
    
    Args:
        series: Price series
        period: Lookback period
        
    Returns:
        DEMA series
    """
    ema1 = ema(series, period)
    ema2 = ema(ema1, period)
    return 2 * ema1 - ema2


def add_moving_averages(df: pd.DataFrame, 
                        periods: list = [20, 50, 200],
                        ma_type: str = 'ema',
                        price_col: str = 'close') -> pd.DataFrame:
    """
    Add multiple moving averages to DataFrame.
    
    Args:
        df: DataFrame with OHLCV data
        periods: List of periods to calculate
        ma_type: Type of MA ('sma', 'ema', 'wma', 'hma')
        price_col: Column to use for calculation
        
    Returns:
        DataFrame with MA columns added
    """
    df = df.copy()
    
    ma_functions = {
        'sma': sma,
        'ema': ema,
        'wma': wma,
        'hma': hma,
        'tema': tema,
        'dema': dema,
    }
    
    ma_func = ma_functions.get(ma_type.lower(), ema)
    
    for period in periods:
        col_name = f'{ma_type.lower()}_{period}'
        df[col_name] = ma_func(df[price_col], period)
    
    return df


def ma_crossover(fast_ma: pd.Series, slow_ma: pd.Series) -> pd.Series:
    """
    Detect moving average crossovers.
    
    Args:
        fast_ma: Fast moving average series
        slow_ma: Slow moving average series
        
    Returns:
        Series with 1 (bullish cross), -1 (bearish cross), 0 (no cross)
    """
    cross = pd.Series(0, index=fast_ma.index)
    
    # Bullish crossover: fast crosses above slow
    bullish = (fast_ma > slow_ma) & (fast_ma.shift(1) <= slow_ma.shift(1))
    cross[bullish] = 1
    
    # Bearish crossover: fast crosses below slow
    bearish = (fast_ma < slow_ma) & (fast_ma.shift(1) >= slow_ma.shift(1))
    cross[bearish] = -1
    
    return cross


def ma_slope(ma_series: pd.Series, period: int = 1) -> pd.Series:
    """
    Calculate slope of moving average.
    
    Args:
        ma_series: Moving average series
        period: Period for slope calculation
        
    Returns:
        Slope series (positive = upward, negative = downward)
    """
    return (ma_series - ma_series.shift(period)) / period


def ma_distance(price: pd.Series, ma_series: pd.Series) -> pd.Series:
    """
    Calculate distance from price to moving average (percentage).
    
    Args:
        price: Price series
        ma_series: Moving average series
        
    Returns:
        Distance as percentage
    """
    return (price - ma_series) / ma_series * 100


def ema_ribbon(df: pd.DataFrame, 
               periods: list = [8, 13, 21, 34, 55, 89],
               price_col: str = 'close') -> pd.DataFrame:
    """
    Create EMA ribbon (multiple EMAs for trend visualization).
    
    Args:
        df: DataFrame with OHLCV data
        periods: List of EMA periods
        price_col: Column to use
        
    Returns:
        DataFrame with EMA ribbon columns
    """
    df = df.copy()
    
    for period in periods:
        df[f'ema_ribbon_{period}'] = ema(df[price_col], period)
    
    # Add ribbon direction (all EMAs aligned)
    ribbon_cols = [f'ema_ribbon_{p}' for p in periods]
    
    # Bullish: all EMAs in ascending order (fastest on top)
    df['ribbon_bullish'] = True
    for i in range(len(ribbon_cols) - 1):
        df['ribbon_bullish'] &= df[ribbon_cols[i]] > df[ribbon_cols[i + 1]]
    
    # Bearish: all EMAs in descending order
    df['ribbon_bearish'] = True
    for i in range(len(ribbon_cols) - 1):
        df['ribbon_bearish'] &= df[ribbon_cols[i]] < df[ribbon_cols[i + 1]]
    
    return df
