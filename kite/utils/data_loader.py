"""
Data Loader - Load and preprocess stock data from CSV files.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Union
from datetime import datetime, time
import warnings

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from kite.config import DATA_DIR, DAILY_DATA_DIR, HOURLY_DATA_DIR, NIFTY_50_STOCKS


class DataLoader:
    """Load and preprocess stock data from CSV files."""
    
    def __init__(self, data_dir: Path = DATA_DIR):
        """
        Initialize DataLoader.
        
        Args:
            data_dir: Base directory containing data files
        """
        self.data_dir = Path(data_dir)
        self.daily_dir = self.data_dir / "daily"
        self.hourly_dir = self.data_dir / "hourly"
        
    def load_stock(self, symbol: str, timeframe: str = 'minute',
                   start_date: Optional[str] = None,
                   end_date: Optional[str] = None) -> pd.DataFrame:
        """
        Load stock data for a given symbol and timeframe.
        
        Args:
            symbol: Stock symbol (e.g., 'RELIANCE')
            timeframe: 'minute', 'hourly', or 'daily'
            start_date: Start date filter (YYYY-MM-DD)
            end_date: End date filter (YYYY-MM-DD)
            
        Returns:
            DataFrame with OHLCV data
        """
        # Determine file path based on timeframe
        if timeframe == 'daily':
            file_path = self.daily_dir / f"{symbol}_day_2000d.csv"
        elif timeframe == 'hourly':
            # Try different naming conventions
            file_path = self.hourly_dir / f"{symbol}_60minute_400d.csv"
            if not file_path.exists():
                file_path = self.hourly_dir / f"{symbol}_hour_60d.csv"
        else:  # minute
            file_path = self.data_dir / f"{symbol}_minute_60d.csv"
        
        if not file_path.exists():
            raise FileNotFoundError(f"Data file not found: {file_path}")
        
        # Load CSV
        df = pd.read_csv(file_path)
        
        # Parse datetime
        df['datetime'] = pd.to_datetime(df['datetime'])
        df.set_index('datetime', inplace=True)
        
        # Ensure column names are lowercase
        df.columns = df.columns.str.lower()
        
        # Filter by date range if provided
        if start_date:
            df = df[df.index >= start_date]
        if end_date:
            df = df[df.index <= end_date]
        
        # Sort by datetime
        df.sort_index(inplace=True)
        
        # Add symbol column
        df['symbol'] = symbol
        
        return df
    
    def load_multiple_stocks(self, symbols: List[str], 
                            timeframe: str = 'daily',
                            start_date: Optional[str] = None,
                            end_date: Optional[str] = None) -> Dict[str, pd.DataFrame]:
        """
        Load data for multiple stocks.
        
        Args:
            symbols: List of stock symbols
            timeframe: 'minute', 'hourly', or 'daily'
            start_date: Start date filter
            end_date: End date filter
            
        Returns:
            Dictionary mapping symbol to DataFrame
        """
        data = {}
        for symbol in symbols:
            try:
                data[symbol] = self.load_stock(symbol, timeframe, 
                                               start_date, end_date)
            except FileNotFoundError as e:
                warnings.warn(f"Could not load {symbol}: {e}")
        
        return data
    
    def load_all_nifty50(self, timeframe: str = 'daily',
                         start_date: Optional[str] = None,
                         end_date: Optional[str] = None) -> Dict[str, pd.DataFrame]:
        """
        Load data for all NIFTY 50 stocks.
        
        Args:
            timeframe: 'minute', 'hourly', or 'daily'
            start_date: Start date filter
            end_date: End date filter
            
        Returns:
            Dictionary mapping symbol to DataFrame
        """
        return self.load_multiple_stocks(NIFTY_50_STOCKS, timeframe,
                                         start_date, end_date)
    
    def get_available_symbols(self, timeframe: str = 'minute') -> List[str]:
        """
        Get list of available symbols for a timeframe.
        
        Args:
            timeframe: 'minute', 'hourly', or 'daily'
            
        Returns:
            List of available symbols
        """
        if timeframe == 'daily':
            directory = self.daily_dir
        elif timeframe == 'hourly':
            directory = self.hourly_dir
        else:
            directory = self.data_dir
        
        symbols = []
        for file in directory.glob('*.csv'):
            symbol = file.stem
            # Clean up symbol name - handle various naming conventions
            if '_minute_' in symbol:
                symbol = symbol.split('_minute_')[0]
            elif '_60minute_' in symbol:
                symbol = symbol.split('_60minute_')[0]
            elif '_hour_' in symbol:
                symbol = symbol.split('_hour_')[0]
            elif '_day_' in symbol:
                symbol = symbol.split('_day_')[0]
            symbols.append(symbol)
        
        return sorted(list(set(symbols)))


def resample_timeframe(df: pd.DataFrame, target_tf: str) -> pd.DataFrame:
    """
    Resample OHLCV data to a different timeframe.
    
    Args:
        df: DataFrame with OHLCV data (datetime index)
        target_tf: Target timeframe ('5T', '15T', '30T', '1H', '4H', 'D', 'W')
        
    Returns:
        Resampled DataFrame
    """
    # Mapping for common timeframe strings
    tf_map = {
        '5min': '5T', '5m': '5T', '5T': '5T',
        '15min': '15T', '15m': '15T', '15T': '15T',
        '30min': '30T', '30m': '30T', '30T': '30T',
        '1h': '1H', '1H': '1H', 'hourly': '1H',
        '4h': '4H', '4H': '4H',
        'd': 'D', 'D': 'D', 'daily': 'D',
        'w': 'W', 'W': 'W', 'weekly': 'W',
    }
    
    target_tf = tf_map.get(target_tf, target_tf)
    
    # Aggregation rules for OHLCV
    agg_dict = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }
    
    # Add oi if present
    if 'oi' in df.columns:
        agg_dict['oi'] = 'last'
    
    # Resample
    resampled = df.resample(target_tf).agg(agg_dict)
    
    # Drop rows with NaN (incomplete periods)
    resampled.dropna(inplace=True)
    
    # Preserve symbol if present
    if 'symbol' in df.columns:
        resampled['symbol'] = df['symbol'].iloc[0]
    
    return resampled


def filter_market_hours(df: pd.DataFrame, 
                        market_open: str = "09:15",
                        market_close: str = "15:30") -> pd.DataFrame:
    """
    Filter data to only include market hours.
    
    Args:
        df: DataFrame with datetime index
        market_open: Market open time (HH:MM)
        market_close: Market close time (HH:MM)
        
    Returns:
        Filtered DataFrame
    """
    open_time = datetime.strptime(market_open, "%H:%M").time()
    close_time = datetime.strptime(market_close, "%H:%M").time()
    
    mask = (df.index.time >= open_time) & (df.index.time <= close_time)
    return df[mask]


def add_session_info(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add trading session information to DataFrame.
    
    Args:
        df: DataFrame with datetime index
        
    Returns:
        DataFrame with session columns
    """
    df = df.copy()
    
    # Date column
    df['date'] = df.index.date
    
    # Time column
    df['time'] = df.index.time
    
    # Session (morning/afternoon)
    df['session'] = np.where(df.index.hour < 12, 'morning', 'afternoon')
    
    # Day of week
    df['day_of_week'] = df.index.dayofweek
    df['day_name'] = df.index.day_name()
    
    # Is first/last hour
    df['is_first_hour'] = (df.index.hour == 9) & (df.index.minute < 60)
    df['is_last_hour'] = (df.index.hour == 14) | ((df.index.hour == 15) & (df.index.minute <= 30))
    
    return df


def validate_data(df: pd.DataFrame) -> Dict[str, any]:
    """
    Validate data quality and return statistics.
    
    Args:
        df: DataFrame to validate
        
    Returns:
        Dictionary with validation results
    """
    results = {
        'total_rows': len(df),
        'date_range': (df.index.min(), df.index.max()),
        'missing_values': df.isnull().sum().to_dict(),
        'has_gaps': False,
        'gap_count': 0,
    }
    
    # Check for gaps in daily data
    if len(df) > 1:
        time_diff = df.index.to_series().diff()
        # For daily data, gaps > 3 days (accounting for weekends)
        if time_diff.median() > pd.Timedelta(hours=1):
            gaps = time_diff[time_diff > pd.Timedelta(days=4)]
        else:
            # For intraday, gaps > 2 hours during market hours
            gaps = time_diff[time_diff > pd.Timedelta(hours=2)]
        
        results['has_gaps'] = len(gaps) > 0
        results['gap_count'] = len(gaps)
    
    # Check for zero/negative prices
    results['zero_prices'] = (df[['open', 'high', 'low', 'close']] <= 0).any().any()
    
    # Check OHLC validity
    results['invalid_ohlc'] = (
        (df['high'] < df['low']) | 
        (df['high'] < df['open']) | 
        (df['high'] < df['close']) |
        (df['low'] > df['open']) |
        (df['low'] > df['close'])
    ).any()
    
    return results


# Convenience function
def load_stock_data(symbol: str, timeframe: str = 'daily') -> pd.DataFrame:
    """
    Quick function to load stock data.
    
    Args:
        symbol: Stock symbol
        timeframe: 'minute', 'hourly', or 'daily'
        
    Returns:
        DataFrame with OHLCV data
    """
    loader = DataLoader()
    return loader.load_stock(symbol, timeframe)
