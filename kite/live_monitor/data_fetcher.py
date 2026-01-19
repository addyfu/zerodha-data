"""
Real-Time Market Data Fetcher
=============================
Fetches live market data from Zerodha using enctoken.
Supports both polling (for OHLC) and WebSocket (for ticks).
"""
import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
import requests
import json
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ZerodhaDataFetcher:
    """Fetch real-time data from Zerodha."""
    
    BASE_URL = "https://kite.zerodha.com/orca"
    INSTRUMENTS_URL = "https://api.kite.trade/instruments"
    QUOTE_URL = "https://kite.zerodha.com/orca/quote"
    
    def __init__(self, enctoken: str = None):
        """
        Initialize data fetcher.
        
        Args:
            enctoken: Zerodha enctoken from web login
        """
        self.enctoken = enctoken or os.environ.get('ZERODHA_ENCTOKEN', '')
        self.instruments: Dict[str, int] = {}
        self.token_to_symbol: Dict[int, str] = {}
        self._load_instruments()
    
    def _get_headers(self) -> Dict:
        """Get request headers with auth."""
        return {
            "Authorization": f"enctoken {self.enctoken}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
    
    def _load_instruments(self):
        """Load NSE instrument list."""
        try:
            response = requests.get(self.INSTRUMENTS_URL, timeout=30)
            if response.status_code == 200:
                lines = response.text.strip().split('\n')
                for line in lines[1:]:
                    parts = line.split(',')
                    if len(parts) >= 3 and parts[2] == 'NSE':
                        symbol = parts[1]
                        token = int(parts[0])
                        self.instruments[symbol] = token
                        self.token_to_symbol[token] = symbol
                logger.info(f"Loaded {len(self.instruments)} NSE instruments")
        except Exception as e:
            logger.error(f"Failed to load instruments from API: {e}")
        
        # Fallback to tokens from cloud_collector if API failed
        if len(self.instruments) == 0:
            try:
                from cloud_collector import CloudCollector
                # Try to load ALL NSE stocks first
                logger.info("Loading ALL NSE stocks from cloud_collector...")
                self.instruments = CloudCollector.load_all_nse_stocks()
                self.token_to_symbol = {v: k for k, v in self.instruments.items()}
                logger.info(f"Loaded {len(self.instruments)} instruments")
            except Exception as e:
                logger.error(f"Could not load instruments: {e}")
    
    def get_quote(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        Get current quotes for symbols.
        
        Args:
            symbols: List of stock symbols
            
        Returns:
            Dictionary of symbol -> quote data
        """
        if not self.enctoken:
            logger.warning("No enctoken set. Cannot fetch live quotes.")
            return {}
        
        try:
            # Build instrument string
            instruments = []
            for symbol in symbols:
                if symbol in self.instruments:
                    instruments.append(f"NSE:{symbol}")
            
            if not instruments:
                return {}
            
            url = f"{self.QUOTE_URL}?i={'&i='.join(instruments)}"
            response = requests.get(url, headers=self._get_headers(), timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    quotes = {}
                    for key, value in data.get('data', {}).items():
                        symbol = key.replace('NSE:', '')
                        quotes[symbol] = {
                            'last_price': value.get('last_price', 0),
                            'open': value.get('ohlc', {}).get('open', 0),
                            'high': value.get('ohlc', {}).get('high', 0),
                            'low': value.get('ohlc', {}).get('low', 0),
                            'close': value.get('ohlc', {}).get('close', 0),
                            'volume': value.get('volume', 0),
                            'change': value.get('change', 0),
                            'change_pct': value.get('change', 0) / value.get('ohlc', {}).get('close', 1) * 100 if value.get('ohlc', {}).get('close') else 0,
                            'timestamp': datetime.now()
                        }
                    return quotes
            else:
                logger.warning(f"Quote fetch failed: HTTP {response.status_code}")
                
        except Exception as e:
            logger.error(f"Quote fetch error: {e}")
        
        return {}
    
    def get_historical_data(self, symbol: str, interval: str = "day", 
                           days: int = 60) -> Optional[pd.DataFrame]:
        """
        Get historical OHLCV data.
        
        Args:
            symbol: Stock symbol
            interval: "minute", "5minute", "15minute", "30minute", "60minute", "day"
            days: Number of days of history
            
        Returns:
            DataFrame with OHLCV data
        """
        if not self.enctoken:
            logger.warning("No enctoken set. Cannot fetch historical data.")
            return None
        
        if symbol not in self.instruments:
            logger.warning(f"Symbol {symbol} not found in instruments")
            return None
        
        try:
            token = self.instruments[symbol]
            to_date = datetime.now()
            from_date = to_date - timedelta(days=days)
            
            url = f"{self.BASE_URL}/instruments/historical/{token}/{interval}"
            params = {
                "from": from_date.strftime("%Y-%m-%d"),
                "to": to_date.strftime("%Y-%m-%d"),
                "oi": 1
            }
            
            response = requests.get(url, headers=self._get_headers(), 
                                   params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success' and data.get('data', {}).get('candles'):
                    candles = data['data']['candles']
                    df = pd.DataFrame(candles, 
                                     columns=['datetime', 'open', 'high', 'low', 'close', 'volume', 'oi'])
                    df['datetime'] = pd.to_datetime(df['datetime'])
                    df.set_index('datetime', inplace=True)
                    df['symbol'] = symbol
                    return df
            else:
                logger.warning(f"Historical data fetch failed for {symbol}: HTTP {response.status_code}")
                
        except Exception as e:
            logger.error(f"Historical data error for {symbol}: {e}")
        
        return None
    
    def get_intraday_data(self, symbol: str, interval: str = "5minute") -> Optional[pd.DataFrame]:
        """
        Get today's intraday data.
        
        Args:
            symbol: Stock symbol
            interval: "minute", "5minute", "15minute", "30minute", "60minute"
            
        Returns:
            DataFrame with intraday OHLCV data
        """
        return self.get_historical_data(symbol, interval, days=1)


class LiveDataMonitor:
    """
    Monitor live market data with callbacks.
    Polls quotes at regular intervals.
    """
    
    def __init__(self, fetcher: ZerodhaDataFetcher, 
                 symbols: List[str],
                 poll_interval: int = 5):
        """
        Initialize live monitor.
        
        Args:
            fetcher: ZerodhaDataFetcher instance
            symbols: List of symbols to monitor
            poll_interval: Seconds between polls
        """
        self.fetcher = fetcher
        self.symbols = symbols
        self.poll_interval = poll_interval
        self.running = False
        self.callbacks: List[Callable] = []
        self.last_quotes: Dict[str, Dict] = {}
        self._thread = None
    
    def add_callback(self, callback: Callable):
        """Add a callback function to be called on each quote update."""
        self.callbacks.append(callback)
    
    def _poll_loop(self):
        """Main polling loop."""
        while self.running:
            try:
                quotes = self.fetcher.get_quote(self.symbols)
                
                if quotes:
                    # Check for changes and call callbacks
                    for symbol, quote in quotes.items():
                        old_quote = self.last_quotes.get(symbol, {})
                        
                        # Detect price change
                        if quote.get('last_price') != old_quote.get('last_price'):
                            for callback in self.callbacks:
                                try:
                                    callback(symbol, quote, old_quote)
                                except Exception as e:
                                    logger.error(f"Callback error: {e}")
                    
                    self.last_quotes = quotes
                
                time.sleep(self.poll_interval)
                
            except Exception as e:
                logger.error(f"Poll loop error: {e}")
                time.sleep(self.poll_interval)
    
    def start(self):
        """Start monitoring."""
        if self.running:
            return
        
        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info(f"Live monitor started for {len(self.symbols)} symbols")
    
    def stop(self):
        """Stop monitoring."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Live monitor stopped")
    
    def get_current_prices(self) -> Dict[str, float]:
        """Get current prices for all monitored symbols."""
        return {s: q.get('last_price', 0) for s, q in self.last_quotes.items()}


class OfflineDataFetcher:
    """
    Fallback data fetcher using local CSV files.
    Used when live data is not available.
    """
    
    def __init__(self):
        from kite.utils.data_loader import DataLoader
        self.loader = DataLoader()
    
    def get_historical_data(self, symbol: str, interval: str = "day", 
                           days: int = 60) -> Optional[pd.DataFrame]:
        """Get historical data from local files."""
        try:
            timeframe = 'daily' if interval == 'day' else 'hourly' if '60' in interval else 'minute'
            df = self.loader.load_stock(symbol, timeframe)
            if df is not None and len(df) > days:
                return df.tail(days)
            return df
        except:
            return None
    
    def get_quote(self, symbols: List[str]) -> Dict[str, Dict]:
        """Get latest quote from local data."""
        quotes = {}
        for symbol in symbols:
            try:
                df = self.loader.load_stock(symbol, 'daily')
                if df is not None and len(df) > 0:
                    latest = df.iloc[-1]
                    prev = df.iloc[-2] if len(df) > 1 else latest
                    quotes[symbol] = {
                        'last_price': latest['close'],
                        'open': latest['open'],
                        'high': latest['high'],
                        'low': latest['low'],
                        'close': latest['close'],
                        'volume': latest.get('volume', 0),
                        'change': latest['close'] - prev['close'],
                        'change_pct': (latest['close'] - prev['close']) / prev['close'] * 100,
                        'timestamp': df.index[-1]
                    }
            except:
                pass
        return quotes


def get_data_fetcher(enctoken: str = None) -> ZerodhaDataFetcher:
    """
    Get appropriate data fetcher.
    Falls back to offline if enctoken not available.
    """
    if enctoken or os.environ.get('ZERODHA_ENCTOKEN'):
        fetcher = ZerodhaDataFetcher(enctoken)
        # Test connection
        test_quote = fetcher.get_quote(['RELIANCE'])
        if test_quote:
            logger.info("Using live Zerodha data")
            return fetcher
    
    logger.info("Using offline data (no live connection)")
    return OfflineDataFetcher()


if __name__ == '__main__':
    # Test the data fetcher
    print("Testing Data Fetcher...")
    
    enctoken = os.environ.get('ZERODHA_ENCTOKEN', '')
    if enctoken:
        fetcher = ZerodhaDataFetcher(enctoken)
        
        # Test quote
        quotes = fetcher.get_quote(['RELIANCE', 'TCS', 'INFY'])
        print("\nQuotes:")
        for symbol, quote in quotes.items():
            print(f"  {symbol}: ₹{quote['last_price']:.2f} ({quote['change_pct']:+.2f}%)")
        
        # Test historical
        df = fetcher.get_historical_data('RELIANCE', 'day', 10)
        if df is not None:
            print(f"\nHistorical data for RELIANCE: {len(df)} rows")
            print(df.tail())
    else:
        print("No ZERODHA_ENCTOKEN set. Using offline data.")
        fetcher = OfflineDataFetcher()
        quotes = fetcher.get_quote(['RELIANCE', 'TCS'])
        print("\nOffline Quotes:")
        for symbol, quote in quotes.items():
            print(f"  {symbol}: ₹{quote['last_price']:.2f}")
