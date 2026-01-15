"""
Zerodha Daily Data Collector
============================
Automatically fetches today's 1-minute data for all stocks and stores in SQLite database.
Designed to run daily via Windows Task Scheduler.

Features:
- Fetches 1-minute data for all NIFTY 50 stocks
- Stores in SQLite database (efficient & queryable)
- Handles duplicates automatically
- Logs all operations
- Sends desktop notification on completion
"""

import sys
import io
import os
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
import json

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import requests
import pandas as pd
from tqdm import tqdm

# Setup paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "zerodha_data.db"
LOG_DIR = BASE_DIR / "logs"
CONFIG_PATH = BASE_DIR / "config.py"

# Create directories
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / f"collector_{datetime.now().strftime('%Y%m%d')}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ZerodhaDatabase:
    """SQLite database for storing historical data."""
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn = None
        self._connect()
        self._create_tables()
    
    def _connect(self):
        """Connect to database."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")  # Better performance
        self.conn.execute("PRAGMA synchronous=NORMAL")
    
    def _create_tables(self):
        """Create necessary tables."""
        # Main OHLCV data table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS ohlcv (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                datetime TEXT NOT NULL,
                interval TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume INTEGER,
                oi INTEGER DEFAULT 0,
                UNIQUE(symbol, datetime, interval)
            )
        """)
        
        # Index for faster queries
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_symbol_datetime 
            ON ohlcv(symbol, datetime)
        """)
        
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_symbol_interval 
            ON ohlcv(symbol, interval, datetime)
        """)
        
        # Metadata table for tracking
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS collection_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                date TEXT NOT NULL,
                candles_added INTEGER,
                collected_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Instruments table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS instruments (
                instrument_token INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                name TEXT,
                exchange TEXT,
                segment TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.conn.commit()
        logger.info(f"Database initialized at {self.db_path}")
    
    def insert_ohlcv(self, symbol: str, df: pd.DataFrame, interval: str = "minute") -> int:
        """
        Insert OHLCV data, ignoring duplicates.
        Returns number of new rows inserted.
        """
        if df.empty:
            return 0
        
        # Prepare data
        df = df.reset_index()
        df['symbol'] = symbol
        df['interval'] = interval
        df['datetime'] = df['datetime'].astype(str)
        
        # Insert with conflict handling
        cursor = self.conn.cursor()
        inserted = 0
        
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
            except Exception as e:
                logger.error(f"Error inserting row: {e}")
        
        self.conn.commit()
        return inserted
    
    def log_collection(self, symbol: str, interval: str, date: str, candles: int):
        """Log a collection event."""
        self.conn.execute("""
            INSERT INTO collection_log (symbol, interval, date, candles_added)
            VALUES (?, ?, ?, ?)
        """, (symbol, interval, date, candles))
        self.conn.commit()
    
    def get_data(self, symbol: str, start_date: str = None, end_date: str = None, 
                 interval: str = "minute") -> pd.DataFrame:
        """Query data for a symbol."""
        query = "SELECT * FROM ohlcv WHERE symbol = ? AND interval = ?"
        params = [symbol, interval]
        
        if start_date:
            query += " AND datetime >= ?"
            params.append(start_date)
        if end_date:
            query += " AND datetime <= ?"
            params.append(end_date)
        
        query += " ORDER BY datetime"
        
        df = pd.read_sql_query(query, self.conn, params=params)
        if not df.empty:
            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)
        return df
    
    def get_stats(self) -> dict:
        """Get database statistics."""
        cursor = self.conn.cursor()
        
        # Total records
        cursor.execute("SELECT COUNT(*) FROM ohlcv")
        total_records = cursor.fetchone()[0]
        
        # Records by symbol
        cursor.execute("""
            SELECT symbol, COUNT(*) as count, MIN(datetime) as first, MAX(datetime) as last
            FROM ohlcv WHERE interval = 'minute'
            GROUP BY symbol ORDER BY symbol
        """)
        by_symbol = cursor.fetchall()
        
        # Database size
        db_size = os.path.getsize(self.db_path) / (1024 * 1024)  # MB
        
        return {
            'total_records': total_records,
            'by_symbol': by_symbol,
            'db_size_mb': round(db_size, 2)
        }
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()


class DailyCollector:
    """Collects daily data from Zerodha."""
    
    BASE_URL = "https://kite.zerodha.com"
    CHART_URL = "https://kite.zerodha.com/oms/instruments/historical"
    
    # NIFTY 50 + some popular stocks
    STOCKS = {
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
        # Indices
        "NIFTY 50": 256265, "NIFTY BANK": 260105,
    }
    
    def __init__(self, enctoken: str):
        self.enctoken = enctoken
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"enctoken {enctoken}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "X-Kite-Version": "3.0.0"
        })
        self.db = ZerodhaDatabase()
    
    def verify_session(self) -> bool:
        """Verify if session is valid."""
        try:
            response = self.session.get(f"{self.BASE_URL}/oms/user/profile", timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    user = data.get("data", {})
                    logger.info(f"Session valid for: {user.get('user_name')} ({user.get('user_id')})")
                    return True
            logger.error("Session invalid or expired")
            return False
        except Exception as e:
            logger.error(f"Session verification failed: {e}")
            return False
    
    def fetch_data(self, token: int, from_date: datetime, to_date: datetime, 
                   interval: str = "minute") -> pd.DataFrame:
        """Fetch historical data for a token."""
        url = f"{self.CHART_URL}/{token}/{interval}"
        params = {
            "from": from_date.strftime("%Y-%m-%d %H:%M:%S"),
            "to": to_date.strftime("%Y-%m-%d %H:%M:%S"),
            "oi": 1
        }
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            if response.status_code != 200:
                return pd.DataFrame()
            
            data = response.json()
            if data.get("status") != "success":
                return pd.DataFrame()
            
            candles = data.get("data", {}).get("candles", [])
            if not candles:
                return pd.DataFrame()
            
            df = pd.DataFrame(candles, columns=["datetime", "open", "high", "low", "close", "volume", "oi"])
            df["datetime"] = pd.to_datetime(df["datetime"])
            df.set_index("datetime", inplace=True)
            return df
            
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            return pd.DataFrame()
    
    def collect_today(self, days_back: int = 1) -> dict:
        """
        Collect data for today (or last N days).
        
        Args:
            days_back: Number of days to fetch (1 = today only)
        """
        results = {"success": [], "failed": [], "total_candles": 0}
        
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days_back)
        date_str = to_date.strftime("%Y-%m-%d")
        
        logger.info(f"Collecting data from {from_date.date()} to {to_date.date()}")
        
        for symbol, token in tqdm(self.STOCKS.items(), desc="Collecting"):
            try:
                df = self.fetch_data(token, from_date, to_date, "minute")
                
                if df.empty:
                    results["failed"].append(symbol)
                    logger.warning(f"{symbol}: No data")
                    continue
                
                # Store in database
                inserted = self.db.insert_ohlcv(symbol, df, "minute")
                self.db.log_collection(symbol, "minute", date_str, inserted)
                
                results["success"].append(symbol)
                results["total_candles"] += inserted
                
                if inserted > 0:
                    logger.info(f"{symbol}: +{inserted} new candles")
                
                # Rate limiting
                import time
                time.sleep(0.3)
                
            except Exception as e:
                results["failed"].append(symbol)
                logger.error(f"{symbol}: {e}")
        
        return results
    
    def collect_historical(self, days: int = 60) -> dict:
        """Collect historical data (for initial setup)."""
        results = {"success": [], "failed": [], "total_candles": 0}
        
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days)
        
        logger.info(f"Collecting {days} days of historical data")
        
        for symbol, token in tqdm(self.STOCKS.items(), desc="Historical"):
            try:
                df = self.fetch_data(token, from_date, to_date, "minute")
                
                if df.empty:
                    results["failed"].append(symbol)
                    continue
                
                inserted = self.db.insert_ohlcv(symbol, df, "minute")
                results["success"].append(symbol)
                results["total_candles"] += inserted
                
                logger.info(f"{symbol}: {inserted} candles")
                
                import time
                time.sleep(0.5)
                
            except Exception as e:
                results["failed"].append(symbol)
                logger.error(f"{symbol}: {e}")
        
        return results
    
    def close(self):
        """Cleanup."""
        self.db.close()


def send_notification(title: str, message: str):
    """Send Windows desktop notification."""
    try:
        from win10toast import ToastNotifier
        toaster = ToastNotifier()
        toaster.show_toast(title, message, duration=5, threaded=True)
    except ImportError:
        # Fallback to PowerShell notification
        import subprocess
        ps_script = f'''
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        $template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
        $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template)
        $xml.GetElementsByTagName("text")[0].AppendChild($xml.CreateTextNode("{title}")) | Out-Null
        $xml.GetElementsByTagName("text")[1].AppendChild($xml.CreateTextNode("{message}")) | Out-Null
        $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Zerodha Collector").Show($toast)
        '''
        try:
            subprocess.run(["powershell", "-Command", ps_script], capture_output=True)
        except:
            pass  # Notification is optional


def load_enctoken() -> str:
    """Load enctoken from config or environment."""
    # Try environment variable first
    token = os.environ.get("ZERODHA_ENCTOKEN")
    if token:
        return token
    
    # Try config file
    try:
        sys.path.insert(0, str(BASE_DIR))
        from config import ENCTOKEN
        return ENCTOKEN
    except ImportError:
        pass
    
    # Try token file
    token_file = BASE_DIR / "enctoken.txt"
    if token_file.exists():
        return token_file.read_text().strip()
    
    return None


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Zerodha Daily Data Collector")
    parser.add_argument("--enctoken", "-e", help="Enctoken (or set ZERODHA_ENCTOKEN env var)")
    parser.add_argument("--days", "-d", type=int, default=1, help="Days to fetch (default: 1)")
    parser.add_argument("--historical", action="store_true", help="Fetch 60 days historical data")
    parser.add_argument("--stats", action="store_true", help="Show database statistics")
    parser.add_argument("--query", "-q", help="Query data for a symbol")
    parser.add_argument("--notify", action="store_true", help="Send desktop notification")
    
    args = parser.parse_args()
    
    # Load enctoken
    enctoken = args.enctoken or load_enctoken()
    
    # Stats mode
    if args.stats:
        db = ZerodhaDatabase()
        stats = db.get_stats()
        print(f"\n{'='*60}")
        print(f"DATABASE STATISTICS")
        print(f"{'='*60}")
        print(f"Total Records: {stats['total_records']:,}")
        print(f"Database Size: {stats['db_size_mb']} MB")
        print(f"\nData by Symbol:")
        print(f"{'Symbol':<15} {'Records':>10} {'First Date':<25} {'Last Date':<25}")
        print("-" * 75)
        for symbol, count, first, last in stats['by_symbol'][:20]:
            print(f"{symbol:<15} {count:>10,} {first:<25} {last:<25}")
        if len(stats['by_symbol']) > 20:
            print(f"... and {len(stats['by_symbol']) - 20} more symbols")
        db.close()
        return
    
    # Query mode
    if args.query:
        db = ZerodhaDatabase()
        df = db.get_data(args.query.upper())
        if df.empty:
            print(f"No data found for {args.query}")
        else:
            print(f"\nData for {args.query.upper()}:")
            print(f"Records: {len(df)}")
            print(f"Date Range: {df.index.min()} to {df.index.max()}")
            print(f"\nLatest data:")
            print(df.tail(10))
        db.close()
        return
    
    # Collection mode - need enctoken
    if not enctoken:
        print("ERROR: No enctoken found!")
        print("\nProvide enctoken via:")
        print("  1. --enctoken argument")
        print("  2. ZERODHA_ENCTOKEN environment variable")
        print("  3. config.py file with ENCTOKEN = 'your_token'")
        print("  4. enctoken.txt file")
        return
    
    # Initialize collector
    collector = DailyCollector(enctoken)
    
    # Verify session
    if not collector.verify_session():
        logger.error("Session expired! Please update your enctoken.")
        if args.notify:
            send_notification("Zerodha Collector", "Session expired! Update enctoken.")
        return
    
    # Collect data
    try:
        if args.historical:
            results = collector.collect_historical(60)
        else:
            results = collector.collect_today(args.days)
        
        # Summary
        logger.info(f"\n{'='*50}")
        logger.info(f"COLLECTION COMPLETE")
        logger.info(f"{'='*50}")
        logger.info(f"Successful: {len(results['success'])} stocks")
        logger.info(f"Failed: {len(results['failed'])} stocks")
        logger.info(f"New candles: {results['total_candles']:,}")
        
        if results['failed']:
            logger.warning(f"Failed stocks: {', '.join(results['failed'])}")
        
        # Notification
        if args.notify:
            send_notification(
                "Zerodha Collector",
                f"Done! {results['total_candles']:,} new candles from {len(results['success'])} stocks"
            )
        
    except Exception as e:
        logger.error(f"Collection failed: {e}")
        if args.notify:
            send_notification("Zerodha Collector", f"Error: {e}")
    
    finally:
        collector.close()


if __name__ == "__main__":
    main()
