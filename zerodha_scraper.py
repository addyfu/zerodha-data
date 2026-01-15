"""
Zerodha 1-Minute Historical Data Scraper
=========================================
This script fetches 1-minute OHLCV data from Zerodha using your existing session.
No paid API subscription required - uses the same endpoints as Kite web charts.

Usage:
1. Login to Kite web (kite.zerodha.com)
2. Get your enctoken from browser cookies
3. Run this script

Author: Your friendly neighborhood scraper
"""

import sys
import io

# Fix Windows console encoding for unicode
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import time
import json
import os
from tqdm import tqdm


class ZerodhaDataFetcher:
    """
    Fetches historical data from Zerodha using the internal chart API.
    Requires enctoken from browser session (no paid API needed).
    """
    
    BASE_URL = "https://kite.zerodha.com"
    CHART_URL = "https://kite.zerodha.com/oms/instruments/historical"
    
    # Common instrument tokens (NSE) - Add more as needed
    INSTRUMENT_TOKENS = {
        # NIFTY 50 Stocks
        "RELIANCE": 738561,
        "TCS": 2953217,
        "HDFCBANK": 341249,
        "INFY": 408065,
        "ICICIBANK": 1270529,
        "HINDUNILVR": 356865,
        "SBIN": 779521,
        "BHARTIARTL": 2714625,
        "KOTAKBANK": 492033,
        "ITC": 424961,
        "LT": 2939649,
        "AXISBANK": 1510401,
        "ASIANPAINT": 60417,
        "MARUTI": 2815745,
        "BAJFINANCE": 81153,
        "HCLTECH": 1850625,
        "TITAN": 897537,
        "SUNPHARMA": 857857,
        "WIPRO": 969473,
        "ULTRACEMCO": 2952193,
        "NESTLEIND": 4598529,
        "TECHM": 3465729,
        "POWERGRID": 3834113,
        "NTPC": 2977281,
        "M&M": 519937,
        "TATAMOTORS": 884737,
        "ONGC": 633601,
        "TATASTEEL": 895745,
        "JSWSTEEL": 3001089,
        "COALINDIA": 5215745,
        "BAJAJFINSV": 4268801,
        "ADANIPORTS": 3861249,
        "GRASIM": 315393,
        "DIVISLAB": 2800641,
        "DRREDDY": 225537,
        "CIPLA": 177665,
        "EICHERMOT": 232961,
        "BRITANNIA": 140033,
        "APOLLOHOSP": 40193,
        "HINDALCO": 348929,
        "INDUSINDBK": 1346049,
        "SBILIFE": 5765889,
        "HDFCLIFE": 119553,
        "BAJAJ-AUTO": 4267265,
        "BPCL": 134657,
        "TATACONSUM": 878593,
        "HEROMOTOCO": 345089,
        "UPL": 2889473,
        "SHREECEM": 794369,
        # Index
        "NIFTY 50": 256265,
        "NIFTY BANK": 260105,
        # Add more stocks as needed
    }
    
    def __init__(self, enctoken: str):
        """
        Initialize with enctoken from browser cookies.
        
        Args:
            enctoken: The enctoken value from Kite web cookies
        """
        self.enctoken = enctoken
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"enctoken {enctoken}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "X-Kite-Version": "3.0.0"
        })
    
    def get_instrument_token(self, symbol: str) -> Optional[int]:
        """Get instrument token for a symbol."""
        return self.INSTRUMENT_TOKENS.get(symbol.upper())
    
    def fetch_historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str = "minute"
    ) -> Optional[pd.DataFrame]:
        """
        Fetch historical OHLCV data.
        
        Args:
            instrument_token: Zerodha instrument token
            from_date: Start date
            to_date: End date  
            interval: candle interval (minute, 3minute, 5minute, 15minute, 30minute, 60minute, day)
        
        Returns:
            DataFrame with OHLCV data or None if failed
        """
        url = f"{self.CHART_URL}/{instrument_token}/{interval}"
        
        params = {
            "from": from_date.strftime("%Y-%m-%d %H:%M:%S"),
            "to": to_date.strftime("%Y-%m-%d %H:%M:%S"),
            "oi": 1  # Include open interest
        }
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            
            if response.status_code == 403:
                print("❌ Session expired! Please get a fresh enctoken from browser.")
                return None
            
            if response.status_code != 200:
                print(f"❌ Error: HTTP {response.status_code}")
                return None
            
            data = response.json()
            
            if data.get("status") != "success":
                print(f"❌ API Error: {data.get('message', 'Unknown error')}")
                return None
            
            candles = data.get("data", {}).get("candles", [])
            
            if not candles:
                return pd.DataFrame()
            
            df = pd.DataFrame(candles, columns=["datetime", "open", "high", "low", "close", "volume", "oi"])
            df["datetime"] = pd.to_datetime(df["datetime"])
            df.set_index("datetime", inplace=True)
            
            return df
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Network error: {e}")
            return None
        except json.JSONDecodeError:
            print("❌ Invalid response from server")
            return None
    
    def fetch_stock_data(
        self,
        symbol: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "minute"
    ) -> Optional[pd.DataFrame]:
        """
        Fetch data for a stock by symbol name.
        
        Args:
            symbol: Stock symbol (e.g., "RELIANCE", "TCS")
            from_date: Start date
            to_date: End date
            interval: Candle interval
        
        Returns:
            DataFrame with OHLCV data
        """
        token = self.get_instrument_token(symbol)
        if token is None:
            print(f"❌ Unknown symbol: {symbol}")
            print("   Add it to INSTRUMENT_TOKENS or use fetch_historical_data with token directly")
            return None
        
        return self.fetch_historical_data(token, from_date, to_date, interval)
    
    def fetch_multiple_days(
        self,
        symbol: str,
        days: int = 60,
        interval: str = "minute"
    ) -> Optional[pd.DataFrame]:
        """
        Fetch data for multiple days (handles API limits).
        Zerodha limits 1-minute data to ~60 days at a time.
        
        Args:
            symbol: Stock symbol
            days: Number of days to fetch
            interval: Candle interval
        
        Returns:
            Combined DataFrame
        """
        token = self.get_instrument_token(symbol)
        if token is None:
            print(f"❌ Unknown symbol: {symbol}")
            return None
        
        all_data = []
        to_date = datetime.now()
        
        # For minute data, fetch in 60-day chunks
        chunk_days = 60 if interval == "minute" else 365
        
        remaining_days = days
        
        with tqdm(total=days, desc=f"Fetching {symbol}", unit="days") as pbar:
            while remaining_days > 0:
                fetch_days = min(remaining_days, chunk_days)
                from_date = to_date - timedelta(days=fetch_days)
                
                df = self.fetch_historical_data(token, from_date, to_date, interval)
                
                if df is None:
                    return None
                
                if not df.empty:
                    all_data.append(df)
                
                to_date = from_date - timedelta(days=1)
                remaining_days -= fetch_days
                pbar.update(fetch_days)
                
                # Rate limiting
                time.sleep(0.5)
        
        if not all_data:
            return pd.DataFrame()
        
        combined = pd.concat(all_data)
        combined.sort_index(inplace=True)
        combined = combined[~combined.index.duplicated(keep='first')]
        
        return combined
    
    def download_all_nifty50(
        self,
        days: int = 60,
        interval: str = "minute",
        output_dir: str = "data"
    ) -> Dict[str, str]:
        """
        Download data for all NIFTY 50 stocks.
        
        Args:
            days: Number of days to fetch
            interval: Candle interval
            output_dir: Directory to save CSV files
        
        Returns:
            Dict mapping symbol to file path
        """
        os.makedirs(output_dir, exist_ok=True)
        
        nifty50_stocks = [
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
            "HINDUNILVR", "SBIN", "BHARTIARTL", "KOTAKBANK", "ITC",
            "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "BAJFINANCE",
            "HCLTECH", "TITAN", "SUNPHARMA", "WIPRO", "ULTRACEMCO",
            "NESTLEIND", "TECHM", "POWERGRID", "NTPC", "M&M",
            "TATAMOTORS", "ONGC", "TATASTEEL", "JSWSTEEL", "COALINDIA",
            "BAJAJFINSV", "ADANIPORTS", "GRASIM", "DIVISLAB", "DRREDDY",
            "CIPLA", "EICHERMOT", "BRITANNIA", "APOLLOHOSP", "HINDALCO",
            "INDUSINDBK", "SBILIFE", "HDFCLIFE", "BAJAJ-AUTO", "BPCL",
            "TATACONSUM", "HEROMOTOCO", "UPL", "SHREECEM"
        ]
        
        results = {}
        failed = []
        
        print(f"\n📊 Downloading {len(nifty50_stocks)} stocks ({days} days of {interval} data)\n")
        
        for symbol in tqdm(nifty50_stocks, desc="Overall Progress"):
            try:
                df = self.fetch_multiple_days(symbol, days, interval)
                
                if df is not None and not df.empty:
                    filename = f"{output_dir}/{symbol}_{interval}_{days}d.csv"
                    df.to_csv(filename)
                    results[symbol] = filename
                    print(f"✅ {symbol}: {len(df)} candles saved")
                else:
                    failed.append(symbol)
                    print(f"⚠️ {symbol}: No data")
                
                # Rate limiting between stocks
                time.sleep(1)
                
            except Exception as e:
                failed.append(symbol)
                print(f"❌ {symbol}: {e}")
        
        print(f"\n{'='*50}")
        print(f"✅ Successfully downloaded: {len(results)} stocks")
        if failed:
            print(f"❌ Failed: {', '.join(failed)}")
        
        return results
    
    def verify_session(self) -> bool:
        """Verify if the session is valid."""
        try:
            response = self.session.get(f"{self.BASE_URL}/oms/user/profile", timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    user = data.get("data", {})
                    print(f"✅ Session valid for: {user.get('user_name', 'Unknown')} ({user.get('user_id', '')})")
                    return True
            print("❌ Session invalid or expired")
            return False
        except Exception as e:
            print(f"❌ Could not verify session: {e}")
            return False


def get_enctoken_instructions():
    """Print instructions for getting enctoken."""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║           HOW TO GET YOUR ENCTOKEN FROM ZERODHA                  ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  1. Open Chrome/Edge and go to: https://kite.zerodha.com         ║
║                                                                  ║
║  2. Login with your Zerodha credentials                          ║
║                                                                  ║
║  3. Once logged in, press F12 to open Developer Tools            ║
║                                                                  ║
║  4. Go to: Application tab → Cookies → kite.zerodha.com          ║
║                                                                  ║
║  5. Find the cookie named 'enctoken'                             ║
║                                                                  ║
║  6. Copy its VALUE (it's a long string)                          ║
║                                                                  ║
║  7. Paste it in config.py or pass it to the script               ║
║                                                                  ║
║  ⚠️  The enctoken expires when you logout or after ~24 hours     ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
    """)


# Example usage
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Zerodha Historical Data Scraper")
    parser.add_argument("--enctoken", "-e", help="Your enctoken from browser cookies")
    parser.add_argument("--symbol", "-s", help="Stock symbol to fetch (e.g., RELIANCE)")
    parser.add_argument("--days", "-d", type=int, default=60, help="Number of days (default: 60)")
    parser.add_argument("--interval", "-i", default="minute", 
                       choices=["minute", "3minute", "5minute", "15minute", "30minute", "60minute", "day"],
                       help="Candle interval (default: minute)")
    parser.add_argument("--all-nifty50", action="store_true", help="Download all NIFTY 50 stocks")
    parser.add_argument("--output", "-o", default="data", help="Output directory (default: data)")
    parser.add_argument("--how", action="store_true", help="Show how to get enctoken")
    
    args = parser.parse_args()
    
    if args.how:
        get_enctoken_instructions()
        exit(0)
    
    # Try to load from config file if not provided
    enctoken = args.enctoken
    if not enctoken:
        try:
            from config import ENCTOKEN
            enctoken = ENCTOKEN
        except ImportError:
            get_enctoken_instructions()
            print("\n💡 Create a config.py file with: ENCTOKEN = 'your_token_here'")
            print("   Or pass it via --enctoken argument\n")
            exit(1)
    
    # Initialize fetcher
    fetcher = ZerodhaDataFetcher(enctoken)
    
    # Verify session
    if not fetcher.verify_session():
        print("\n⚠️  Your session has expired. Please get a fresh enctoken.")
        get_enctoken_instructions()
        exit(1)
    
    # Download data
    if args.all_nifty50:
        fetcher.download_all_nifty50(args.days, args.interval, args.output)
    elif args.symbol:
        df = fetcher.fetch_multiple_days(args.symbol, args.days, args.interval)
        if df is not None and not df.empty:
            os.makedirs(args.output, exist_ok=True)
            filename = f"{args.output}/{args.symbol}_{args.interval}_{args.days}d.csv"
            df.to_csv(filename)
            print(f"\n✅ Saved {len(df)} candles to {filename}")
            print(f"\n📊 Data Preview:\n{df.head(10)}")
        else:
            print("No data fetched")
    else:
        print("Please specify --symbol or --all-nifty50")
        print("Run with --help for more options")
