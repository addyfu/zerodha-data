"""
Oscillator Indicators - RSI, Stochastic, CCI, MFI, Williams %R
"""
import pandas as pd
import numpy as np
from typing import Tuple, Optional


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index.
    
    Args:
        series: Price series (typically close)
        period: Lookback period
        
    Returns:
        RSI series (0-100)
    """
    delta = series.diff()
    
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    
    rs = avg_gain / avg_loss
    rsi_values = 100 - (100 / (1 + rs))
    
    return rsi_values


def stochastic(df: pd.DataFrame, k_period: int = 14, 
               d_period: int = 3, smooth_k: int = 3) -> Tuple[pd.Series, pd.Series]:
    """
    Stochastic Oscillator (%K and %D).
    
    Args:
        df: DataFrame with high, low, close columns
        k_period: Lookback period for %K
        d_period: Smoothing period for %D
        smooth_k: Smoothing period for %K
        
    Returns:
        Tuple of (%K, %D) series
    """
    lowest_low = df['low'].rolling(window=k_period).min()
    highest_high = df['high'].rolling(window=k_period).max()
    
    # Fast %K
    fast_k = 100 * (df['close'] - lowest_low) / (highest_high - lowest_low)
    
    # Slow %K (smoothed)
    slow_k = fast_k.rolling(window=smooth_k).mean()
    
    # %D (signal line)
    slow_d = slow_k.rolling(window=d_period).mean()
    
    return slow_k, slow_d


def cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Commodity Channel Index.
    
    Args:
        df: DataFrame with high, low, close columns
        period: Lookback period
        
    Returns:
        CCI series
    """
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    sma_tp = typical_price.rolling(window=period).mean()
    mean_deviation = typical_price.rolling(window=period).apply(
        lambda x: np.mean(np.abs(x - x.mean())), raw=True
    )
    
    cci_values = (typical_price - sma_tp) / (0.015 * mean_deviation)
    return cci_values


def mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Money Flow Index (Volume-weighted RSI).
    
    Args:
        df: DataFrame with high, low, close, volume columns
        period: Lookback period
        
    Returns:
        MFI series (0-100)
    """
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    raw_money_flow = typical_price * df['volume']
    
    # Positive and negative money flow
    positive_flow = raw_money_flow.where(typical_price > typical_price.shift(1), 0)
    negative_flow = raw_money_flow.where(typical_price < typical_price.shift(1), 0)
    
    positive_mf = positive_flow.rolling(window=period).sum()
    negative_mf = negative_flow.rolling(window=period).sum()
    
    money_ratio = positive_mf / negative_mf
    mfi_values = 100 - (100 / (1 + money_ratio))
    
    return mfi_values


def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Williams %R.
    
    Args:
        df: DataFrame with high, low, close columns
        period: Lookback period
        
    Returns:
        Williams %R series (-100 to 0)
    """
    highest_high = df['high'].rolling(window=period).max()
    lowest_low = df['low'].rolling(window=period).min()
    
    wr = -100 * (highest_high - df['close']) / (highest_high - lowest_low)
    return wr


def roc(series: pd.Series, period: int = 12) -> pd.Series:
    """
    Rate of Change.
    
    Args:
        series: Price series
        period: Lookback period
        
    Returns:
        ROC series (percentage)
    """
    return ((series - series.shift(period)) / series.shift(period)) * 100


def momentum(series: pd.Series, period: int = 10) -> pd.Series:
    """
    Momentum indicator.
    
    Args:
        series: Price series
        period: Lookback period
        
    Returns:
        Momentum series
    """
    return series - series.shift(period)


def add_rsi(df: pd.DataFrame, period: int = 14, 
            price_col: str = 'close') -> pd.DataFrame:
    """
    Add RSI to DataFrame.
    
    Args:
        df: DataFrame with price data
        period: RSI period
        price_col: Column to use
        
    Returns:
        DataFrame with RSI column
    """
    df = df.copy()
    df[f'rsi_{period}'] = rsi(df[price_col], period)
    return df


def add_stochastic(df: pd.DataFrame, k_period: int = 14,
                   d_period: int = 3, smooth_k: int = 3) -> pd.DataFrame:
    """
    Add Stochastic to DataFrame.
    
    Args:
        df: DataFrame with OHLC data
        k_period: %K period
        d_period: %D period
        smooth_k: %K smoothing
        
    Returns:
        DataFrame with Stochastic columns
    """
    df = df.copy()
    df['stoch_k'], df['stoch_d'] = stochastic(df, k_period, d_period, smooth_k)
    return df


def rsi_divergence(df: pd.DataFrame, rsi_col: str = 'rsi_14',
                   price_col: str = 'close', lookback: int = 20) -> pd.DataFrame:
    """
    Detect RSI divergences.
    
    Args:
        df: DataFrame with RSI and price columns
        rsi_col: RSI column name
        price_col: Price column name
        lookback: Lookback period for divergence detection
        
    Returns:
        DataFrame with divergence columns
    """
    df = df.copy()
    
    # Initialize divergence columns
    df['bullish_divergence'] = False
    df['bearish_divergence'] = False
    df['hidden_bullish_div'] = False
    df['hidden_bearish_div'] = False
    
    for i in range(lookback, len(df)):
        window = df.iloc[i-lookback:i+1]
        
        # Find local price lows/highs
        price_min_idx = window[price_col].idxmin()
        price_max_idx = window[price_col].idxmax()
        
        current_idx = df.index[i]
        current_price = df.loc[current_idx, price_col]
        current_rsi = df.loc[current_idx, rsi_col]
        
        # Regular Bullish Divergence: Price lower low, RSI higher low
        if current_idx != price_min_idx:
            prev_price_low = df.loc[price_min_idx, price_col]
            prev_rsi_low = df.loc[price_min_idx, rsi_col]
            
            if current_price < prev_price_low and current_rsi > prev_rsi_low:
                df.loc[current_idx, 'bullish_divergence'] = True
        
        # Regular Bearish Divergence: Price higher high, RSI lower high
        if current_idx != price_max_idx:
            prev_price_high = df.loc[price_max_idx, price_col]
            prev_rsi_high = df.loc[price_max_idx, rsi_col]
            
            if current_price > prev_price_high and current_rsi < prev_rsi_high:
                df.loc[current_idx, 'bearish_divergence'] = True
        
        # Hidden Bullish Divergence: Price higher low, RSI lower low
        if current_idx != price_min_idx:
            prev_price_low = df.loc[price_min_idx, price_col]
            prev_rsi_low = df.loc[price_min_idx, rsi_col]
            
            if current_price > prev_price_low and current_rsi < prev_rsi_low:
                df.loc[current_idx, 'hidden_bullish_div'] = True
        
        # Hidden Bearish Divergence: Price lower high, RSI higher high
        if current_idx != price_max_idx:
            prev_price_high = df.loc[price_max_idx, price_col]
            prev_rsi_high = df.loc[price_max_idx, rsi_col]
            
            if current_price < prev_price_high and current_rsi > prev_rsi_high:
                df.loc[current_idx, 'hidden_bearish_div'] = True
    
    return df


def stochastic_crossover(stoch_k: pd.Series, stoch_d: pd.Series) -> pd.Series:
    """
    Detect Stochastic crossovers.
    
    Args:
        stoch_k: %K series
        stoch_d: %D series
        
    Returns:
        Series with 1 (bullish), -1 (bearish), 0 (none)
    """
    cross = pd.Series(0, index=stoch_k.index)
    
    # Bullish: %K crosses above %D
    bullish = (stoch_k > stoch_d) & (stoch_k.shift(1) <= stoch_d.shift(1))
    cross[bullish] = 1
    
    # Bearish: %K crosses below %D
    bearish = (stoch_k < stoch_d) & (stoch_k.shift(1) >= stoch_d.shift(1))
    cross[bearish] = -1
    
    return cross
