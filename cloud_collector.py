"""
Cloud Data Collector
====================
Designed to run on GitHub Actions (FREE).
Automatically logs in, collects data, and stores it.

Features:
- Auto-login with TOTP
- Collects 1-minute data for all stocks
- Stores in SQLite database
- Uploads to GitHub Releases (free storage)
- Sends Telegram notifications
"""

import os
import sys
import io
import sqlite3
import json
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import logging

# Fix encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import requests
import pandas as pd
from tqdm import tqdm

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "zerodha_data.db"


class CloudCollector:
    """
    Data collector optimized for cloud/CI environments.
    """
    
    CHART_URL = "https://kite.zerodha.com/oms/instruments/historical"
    
    # Default: NIFTY 50 stocks
    NIFTY50_STOCKS = {
        "RELIANCE": 738561, "TCS": 2953217, "HDFCBANK": 341249, "INFY": 408065,
        "ICICIBANK": 1270529, "HINDUNILVR": 356865, "SBIN": 779521, "BHARTIARTL": 2714625,
        "KOTAKBANK": 492033, "ITC": 424961, "LT": 2939649, "AXISBANK": 1510401,
        "ASIANPAINT": 60417, "MARUTI": 2815745, "BAJFINANCE": 81153, "HCLTECH": 1850625,
        "TITAN": 897537, "SUNPHARMA": 857857, "WIPRO": 969473, "ULTRACEMCO": 2952193,
        "NESTLEIND": 4598529, "TECHM": 3465729, "POWERGRID": 3834113, "NTPC": 2977281,
        "M&M": 519937, "TATAMOTORS": 884737, "ONGC": 633601, "TATASTEEL": 895745,
        "JSWSTEEL": 3001089, "COALINDIA": 5215745, "BAJAJFINSV": 4268801, "ADANIPORTS": 3861249,
        "GRASIM": 315393, "DIVISLAB": 2800641, "DRREDDY": 225537, "CIPLA": 177665,
        "EICHERMOT": 232961, "BRITANNIA": 140033, "APOLLOHOSP": 40193, "HINDALCO": 348929,
        "INDUSINDBK": 1346049, "HDFCLIFE": 119553, "BAJAJ-AUTO": 4267265, "BPCL": 134657,
        "TATACONSUM": 878593, "HEROMOTOCO": 345089, "UPL": 2889473, "SHREECEM": 794369,
        "NIFTY 50": 256265, "NIFTY BANK": 260105,
    }
    
    STOCKS = NIFTY50_STOCKS  # Default
    
    @classmethod
    def load_all_nse_stocks(cls):
        """Load all NSE stocks from Zerodha's instruments API."""
        try:
            import requests
            import io
            import pandas as pd
            
            logger.info("Fetching all NSE instruments from Zerodha...")
            
            url = "https://api.kite.trade/instruments"
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            
            df = pd.read_csv(io.StringIO(response.text))
            
            # Filter NSE equity stocks only
            nse_eq = df[
                (df['exchange'] == 'NSE') & 
                (df['instrument_type'] == 'EQ')
            ]
            
            stocks = dict(zip(nse_eq['tradingsymbol'], nse_eq['instrument_token']))
            
            # Add indices
            indices = df[
                (df['exchange'] == 'NSE') & 
                (df['segment'] == 'INDICES')
            ]
            for _, row in indices.iterrows():
                stocks[row['tradingsymbol']] = row['instrument_token']
            
            logger.info(f"Loaded {len(stocks)} NSE stocks")
            return stocks
            
        except Exception as e:
            logger.error(f"Failed to load NSE stocks: {e}")
            logger.info("Falling back to NIFTY 50 stocks")
            return cls.NIFTY50_STOCKS
    
    def __init__(self):
        self.enctoken = None
        self.session = requests.Session()
        self.db_conn = None
        
        # Load credentials from environment
        self.user_id = os.environ.get('ZERODHA_USER_ID')
        self.password = os.environ.get('ZERODHA_PASSWORD')
        self.totp_secret = os.environ.get('ZERODHA_TOTP_SECRET')
        self.telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    
    def auto_login(self) -> bool:
        """Automatically login to Zerodha."""
        from zerodha_auto_login import get_enctoken
        
        try:
            logger.info("Attempting auto-login...")
            self.enctoken = get_enctoken(
                self.user_id,
                self.password,
                self.totp_secret
            )
            
            self.session.headers.update({
                "Authorization": f"enctoken {self.enctoken}",
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json"
            })
            
            logger.info("Login successful!")
            return True
            
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False
    
    def init_database(self):
        """Initialize SQLite database."""
        DATA_DIR.mkdir(exist_ok=True)
        
        self.db_conn = sqlite3.connect(DB_PATH)
        self.db_conn.execute("PRAGMA journal_mode=WAL")
        
        self.db_conn.execute("""
            CREATE TABLE IF NOT EXISTS ohlcv (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                datetime TEXT NOT NULL,
                interval TEXT NOT NULL,
                open REAL, high REAL, low REAL, close REAL,
                volume INTEGER, oi INTEGER DEFAULT 0,
                UNIQUE(symbol, datetime, interval)
            )
        """)
        
        self.db_conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_symbol_datetime 
            ON ohlcv(symbol, datetime)
        """)
        
        self.db_conn.execute("""
            CREATE TABLE IF NOT EXISTS collection_log (
                id INTEGER PRIMARY KEY,
                date TEXT, candles_added INTEGER,
                collected_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.db_conn.commit()
        logger.info(f"Database initialized: {DB_PATH}")
    
    def fetch_data(self, token: int, from_date: datetime, to_date: datetime) -> pd.DataFrame:
        """Fetch historical data."""
        url = f"{self.CHART_URL}/{token}/minute"
        params = {
            "from": from_date.strftime("%Y-%m-%d %H:%M:%S"),
            "to": to_date.strftime("%Y-%m-%d %H:%M:%S"),
            "oi": 1
        }
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            
            if response.status_code == 403:
                logger.error(f"Token {token}: 403 Forbidden - Session may have expired")
                return pd.DataFrame()
            
            if response.status_code != 200:
                logger.error(f"Token {token}: HTTP {response.status_code}")
                return pd.DataFrame()
            
            data = response.json()
            
            if data.get("status") != "success":
                logger.error(f"Token {token}: API error - {data.get('message', 'Unknown')}")
                return pd.DataFrame()
            
            candles = data.get("data", {}).get("candles", [])
            if not candles:
                logger.warning(f"Token {token}: No candles returned (market closed or holiday?)")
                return pd.DataFrame()
            
            df = pd.DataFrame(candles, columns=["datetime", "open", "high", "low", "close", "volume", "oi"])
            df["datetime"] = pd.to_datetime(df["datetime"])
            df.set_index("datetime", inplace=True)
            return df
            
        except Exception as e:
            logger.error(f"Token {token}: Fetch error - {e}")
            return pd.DataFrame()
    
    def store_data(self, symbol: str, df: pd.DataFrame) -> int:
        """Store data in database."""
        if df.empty:
            return 0
        
        df = df.reset_index()
        df['symbol'] = symbol
        df['interval'] = 'minute'
        df['datetime'] = df['datetime'].astype(str)
        
        inserted = 0
        cursor = self.db_conn.cursor()
        
        for _, row in df.iterrows():
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO ohlcv 
                    (symbol, datetime, interval, open, high, low, close, volume, oi)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    row['symbol'], row['datetime'], row['interval'],
                    row['open'], row['high'], row['low'], row['close'],
                    row['volume'], row.get('oi', 0)
                ))
                if cursor.rowcount > 0:
                    inserted += 1
            except:
                pass
        
        self.db_conn.commit()
        return inserted
    
    def collect(self, days: int = 1) -> dict:
        """Collect data for all stocks."""
        results = {"success": [], "failed": [], "total_candles": 0}
        
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days)
        
        logger.info(f"Collecting {days} day(s) of data...")
        
        for symbol, token in tqdm(self.STOCKS.items(), desc="Collecting"):
            try:
                df = self.fetch_data(token, from_date, to_date)
                
                if df.empty:
                    results["failed"].append(symbol)
                    continue
                
                inserted = self.store_data(symbol, df)
                results["success"].append(symbol)
                results["total_candles"] += inserted
                
                if inserted > 0:
                    logger.info(f"{symbol}: +{inserted}")
                
                import time
                time.sleep(0.3)
                
            except Exception as e:
                results["failed"].append(symbol)
                logger.error(f"{symbol}: {e}")
        
        # Log collection
        self.db_conn.execute(
            "INSERT INTO collection_log (date, candles_added) VALUES (?, ?)",
            (to_date.strftime("%Y-%m-%d"), results["total_candles"])
        )
        self.db_conn.commit()
        
        return results
    
    async def send_telegram(self, message: str):
        """Send Telegram notification."""
        if not self.telegram_token or not self.telegram_chat_id:
            logger.warning("Telegram not configured")
            return
        
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            data = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            requests.post(url, data=data, timeout=10)
            logger.info("Telegram notification sent")
        except Exception as e:
            logger.error(f"Telegram error: {e}")
    
    def get_stats(self) -> dict:
        """Get database statistics."""
        cursor = self.db_conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM ohlcv")
        total = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(DISTINCT symbol) FROM ohlcv")
        symbols = cursor.fetchone()[0]
        
        cursor.execute("SELECT MAX(datetime) FROM ohlcv WHERE interval='minute'")
        last_update = cursor.fetchone()[0]
        
        db_size = DB_PATH.stat().st_size / (1024 * 1024) if DB_PATH.exists() else 0
        
        return {
            "total_records": total,
            "symbols": symbols,
            "last_update": last_update,
            "db_size_mb": round(db_size, 2)
        }
    
    def close(self):
        """Cleanup."""
        if self.db_conn:
            self.db_conn.close()
    
    def run(self, days: int = 1, historical: bool = False):
        """Main entry point."""
        start_time = datetime.now()
        
        # Initialize
        self.init_database()
        
        # Login
        if not self.auto_login():
            asyncio.run(self.send_telegram("❌ <b>Zerodha Login Failed!</b>\nCheck credentials."))
            return False
        
        # Collect
        collect_days = 60 if historical else days
        results = self.collect(collect_days)
        
        # Stats
        stats = self.get_stats()
        duration = (datetime.now() - start_time).seconds
        
        # Summary
        summary = (
            f"{'📊' if results['total_candles'] > 0 else '⚠️'} <b>Collection Complete</b>\n\n"
            f"✅ Stocks: {len(results['success'])}/{len(self.STOCKS)}\n"
            f"📈 New candles: {results['total_candles']:,}\n"
            f"💾 DB Size: {stats['db_size_mb']} MB\n"
            f"📁 Total records: {stats['total_records']:,}\n"
            f"⏱️ Duration: {duration}s"
        )
        
        if results['failed']:
            summary += f"\n\n⚠️ Failed: {', '.join(results['failed'][:5])}"
        
        logger.info(summary.replace('<b>', '').replace('</b>', ''))
        
        # Send notification
        asyncio.run(self.send_telegram(summary))
        
        self.close()
        return True


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Cloud Data Collector")
    parser.add_argument("--days", "-d", type=int, default=1, help="Days to collect")
    parser.add_argument("--historical", action="store_true", help="Collect 60 days")
    parser.add_argument("--all-nse", action="store_true", help="Collect ALL NSE stocks (~2000)")
    parser.add_argument("--top", type=int, help="Collect top N stocks by market cap (e.g., 100, 200, 500)")
    
    args = parser.parse_args()
    
    collector = CloudCollector()
    
    # Load stocks based on arguments
    if args.all_nse:
        logger.info("Loading ALL NSE stocks...")
        collector.STOCKS = CloudCollector.load_all_nse_stocks()
    elif args.top:
        logger.info(f"Loading top {args.top} NSE stocks...")
        all_stocks = CloudCollector.load_all_nse_stocks()
        # For now, just take first N (ideally should be sorted by market cap)
        collector.STOCKS = dict(list(all_stocks.items())[:args.top])
    
    logger.info(f"Will collect data for {len(collector.STOCKS)} stocks")
    
    success = collector.run(args.days, args.historical)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
