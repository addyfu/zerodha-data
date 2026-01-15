"""
Zerodha Real-Time Tick Data Collector
=====================================
Captures live tick data (every price change) via WebSocket.
This is the ONLY way to get sub-minute data from Zerodha.

IMPORTANT:
- This captures LIVE data only - no historical tick data exists
- Must run during market hours (9:15 AM - 3:30 PM IST)
- Stores every tick (can be 1-10 ticks per second per stock!)
- Data grows FAST: ~50-100 MB per day for 50 stocks

Usage:
    python tick_collector.py --stocks RELIANCE,TCS,INFY
    python tick_collector.py --nifty50  # All NIFTY 50 stocks
"""

import os
import sys
import json
import sqlite3
import struct
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
import logging

import websocket
import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
TICK_DB_PATH = DATA_DIR / "tick_data.db"


class TickDatabase:
    """SQLite database optimized for tick data storage."""
    
    def __init__(self, db_path: str = TICK_DB_PATH):
        DATA_DIR.mkdir(exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.lock = threading.Lock()
        self._create_tables()
        self.buffer = []
        self.buffer_size = 1000  # Flush every 1000 ticks
    
    def _create_tables(self):
        """Create tick data table."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS ticks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                instrument_token INTEGER,
                timestamp TEXT NOT NULL,
                last_price REAL,
                volume INTEGER,
                buy_quantity INTEGER,
                sell_quantity INTEGER,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                change REAL,
                oi INTEGER DEFAULT 0
            )
        """)
        
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticks_symbol_time 
            ON ticks(symbol, timestamp)
        """)
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tick_sessions (
                id INTEGER PRIMARY KEY,
                start_time TEXT,
                end_time TEXT,
                symbols TEXT,
                tick_count INTEGER
            )
        """)
        
        self.conn.commit()
    
    def insert_tick(self, tick: dict):
        """Buffer a tick for batch insert."""
        with self.lock:
            self.buffer.append(tick)
            if len(self.buffer) >= self.buffer_size:
                self._flush()
    
    def _flush(self):
        """Flush buffer to database."""
        if not self.buffer:
            return
        
        cursor = self.conn.cursor()
        cursor.executemany("""
            INSERT INTO ticks 
            (symbol, instrument_token, timestamp, last_price, volume, 
             buy_quantity, sell_quantity, open, high, low, close, change, oi)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (t['symbol'], t['instrument_token'], t['timestamp'], t['last_price'],
             t['volume'], t['buy_quantity'], t['sell_quantity'], 
             t['open'], t['high'], t['low'], t['close'], t['change'], t['oi'])
            for t in self.buffer
        ])
        self.conn.commit()
        
        count = len(self.buffer)
        self.buffer = []
        return count
    
    def flush(self):
        """Public flush method."""
        with self.lock:
            return self._flush()
    
    def get_stats(self) -> dict:
        """Get database statistics."""
        cursor = self.conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM ticks")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT symbol, COUNT(*) as cnt, MIN(timestamp), MAX(timestamp)
            FROM ticks GROUP BY symbol ORDER BY cnt DESC
        """)
        by_symbol = cursor.fetchall()
        
        db_size = TICK_DB_PATH.stat().st_size / (1024 * 1024) if TICK_DB_PATH.exists() else 0
        
        return {
            'total_ticks': total,
            'by_symbol': by_symbol,
            'db_size_mb': round(db_size, 2)
        }
    
    def close(self):
        self.flush()
        self.conn.close()


class ZerodhaTickCollector:
    """
    Real-time tick data collector using Zerodha WebSocket.
    """
    
    WEBSOCKET_URL = "wss://ws.kite.trade"
    
    # Instrument tokens for NIFTY 50
    NIFTY50_TOKENS = {
        738561: "RELIANCE", 2953217: "TCS", 341249: "HDFCBANK", 408065: "INFY",
        1270529: "ICICIBANK", 356865: "HINDUNILVR", 779521: "SBIN", 2714625: "BHARTIARTL",
        492033: "KOTAKBANK", 424961: "ITC", 2939649: "LT", 1510401: "AXISBANK",
        60417: "ASIANPAINT", 2815745: "MARUTI", 81153: "BAJFINANCE", 1850625: "HCLTECH",
        897537: "TITAN", 857857: "SUNPHARMA", 969473: "WIPRO", 2952193: "ULTRACEMCO",
        4598529: "NESTLEIND", 3465729: "TECHM", 3834113: "POWERGRID", 2977281: "NTPC",
        519937: "M&M", 884737: "TATAMOTORS", 633601: "ONGC", 895745: "TATASTEEL",
        3001089: "JSWSTEEL", 5215745: "COALINDIA", 4268801: "BAJAJFINSV", 3861249: "ADANIPORTS",
        315393: "GRASIM", 2800641: "DIVISLAB", 225537: "DRREDDY", 177665: "CIPLA",
        232961: "EICHERMOT", 140033: "BRITANNIA", 40193: "APOLLOHOSP", 348929: "HINDALCO",
        1346049: "INDUSINDBK", 119553: "HDFCLIFE", 4267265: "BAJAJ-AUTO", 134657: "BPCL",
        878593: "TATACONSUM", 345089: "HEROMOTOCO", 2889473: "UPL", 794369: "SHREECEM",
        256265: "NIFTY 50", 260105: "NIFTY BANK",
    }
    
    def __init__(self, enctoken: str, tokens: list = None):
        """
        Initialize tick collector.
        
        Args:
            enctoken: Zerodha session token
            tokens: List of instrument tokens to subscribe (default: NIFTY 50)
        """
        self.enctoken = enctoken
        self.tokens = tokens or list(self.NIFTY50_TOKENS.keys())
        self.token_to_symbol = {t: s for t, s in self.NIFTY50_TOKENS.items()}
        
        self.db = TickDatabase()
        self.ws = None
        self.running = False
        self.tick_count = 0
        self.start_time = None
        
        # Stats
        self.ticks_per_second = 0
        self.last_tick_time = None
    
    def _on_open(self, ws):
        """WebSocket connected."""
        logger.info("WebSocket connected!")
        
        # Subscribe to instruments
        # Mode: 1=LTP, 2=Quote, 3=Full (we want Full for all data)
        subscribe_msg = {
            "a": "subscribe",
            "v": self.tokens
        }
        ws.send(json.dumps(subscribe_msg))
        
        # Set mode to Full
        mode_msg = {
            "a": "mode",
            "v": ["full", self.tokens]
        }
        ws.send(json.dumps(mode_msg))
        
        logger.info(f"Subscribed to {len(self.tokens)} instruments")
        self.start_time = datetime.now()
    
    def _on_message(self, ws, message):
        """Process incoming tick data."""
        if isinstance(message, bytes):
            ticks = self._parse_binary(message)
            for tick in ticks:
                self.db.insert_tick(tick)
                self.tick_count += 1
            
            # Log stats every 1000 ticks
            if self.tick_count % 1000 == 0:
                elapsed = (datetime.now() - self.start_time).seconds or 1
                rate = self.tick_count / elapsed
                logger.info(f"Ticks: {self.tick_count:,} | Rate: {rate:.1f}/sec")
    
    def _parse_binary(self, data: bytes) -> list:
        """Parse binary tick data from Zerodha."""
        ticks = []
        
        # Number of packets
        if len(data) < 2:
            return ticks
        
        num_packets = struct.unpack(">H", data[0:2])[0]
        offset = 2
        
        for _ in range(num_packets):
            if offset + 2 > len(data):
                break
            
            packet_len = struct.unpack(">H", data[offset:offset+2])[0]
            offset += 2
            
            if offset + packet_len > len(data):
                break
            
            packet = data[offset:offset+packet_len]
            offset += packet_len
            
            tick = self._parse_packet(packet)
            if tick:
                ticks.append(tick)
        
        return ticks
    
    def _parse_packet(self, packet: bytes) -> dict:
        """Parse a single tick packet."""
        if len(packet) < 8:
            return None
        
        token = struct.unpack(">I", packet[0:4])[0]
        symbol = self.token_to_symbol.get(token, f"UNKNOWN_{token}")
        
        tick = {
            'symbol': symbol,
            'instrument_token': token,
            'timestamp': datetime.now().isoformat(),
            'last_price': 0,
            'volume': 0,
            'buy_quantity': 0,
            'sell_quantity': 0,
            'open': 0,
            'high': 0,
            'low': 0,
            'close': 0,
            'change': 0,
            'oi': 0
        }
        
        # Parse based on packet length (different modes have different lengths)
        if len(packet) >= 8:
            tick['last_price'] = struct.unpack(">I", packet[4:8])[0] / 100
        
        if len(packet) >= 44:  # Full mode
            tick['high'] = struct.unpack(">I", packet[8:12])[0] / 100
            tick['low'] = struct.unpack(">I", packet[12:16])[0] / 100
            tick['open'] = struct.unpack(">I", packet[16:20])[0] / 100
            tick['close'] = struct.unpack(">I", packet[20:24])[0] / 100
            tick['change'] = struct.unpack(">i", packet[24:28])[0] / 100
            tick['volume'] = struct.unpack(">I", packet[32:36])[0]
            tick['buy_quantity'] = struct.unpack(">I", packet[36:40])[0]
            tick['sell_quantity'] = struct.unpack(">I", packet[40:44])[0]
        
        if len(packet) >= 184:  # With OI
            tick['oi'] = struct.unpack(">I", packet[44:48])[0]
        
        return tick
    
    def _on_error(self, ws, error):
        """WebSocket error."""
        logger.error(f"WebSocket error: {error}")
    
    def _on_close(self, ws, close_status_code, close_msg):
        """WebSocket closed."""
        logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")
        self.running = False
        
        # Flush remaining ticks
        self.db.flush()
    
    def start(self):
        """Start collecting tick data."""
        logger.info("Starting tick collector...")
        logger.info(f"Instruments: {len(self.tokens)}")
        
        # Build WebSocket URL with auth
        ws_url = f"{self.WEBSOCKET_URL}?api_key=kitefront&user_id=web&enctoken={self.enctoken}"
        
        self.ws = websocket.WebSocketApp(
            ws_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )
        
        self.running = True
        
        # Run in separate thread
        ws_thread = threading.Thread(target=self.ws.run_forever)
        ws_thread.daemon = True
        ws_thread.start()
        
        logger.info("Tick collector started! Press Ctrl+C to stop.")
        
        try:
            while self.running:
                time.sleep(10)
                # Periodic flush
                self.db.flush()
                
                # Check market hours
                now = datetime.now()
                if now.hour >= 16:  # After 4 PM
                    logger.info("Market closed, stopping...")
                    break
                    
        except KeyboardInterrupt:
            logger.info("Stopping...")
        
        self.stop()
    
    def stop(self):
        """Stop collecting."""
        self.running = False
        if self.ws:
            self.ws.close()
        
        self.db.flush()
        
        # Print summary
        stats = self.db.get_stats()
        duration = (datetime.now() - self.start_time).seconds if self.start_time else 0
        
        logger.info(f"\n{'='*50}")
        logger.info(f"COLLECTION SUMMARY")
        logger.info(f"{'='*50}")
        logger.info(f"Duration: {duration} seconds")
        logger.info(f"Total ticks: {self.tick_count:,}")
        logger.info(f"Rate: {self.tick_count/max(duration,1):.1f} ticks/sec")
        logger.info(f"Database size: {stats['db_size_mb']} MB")
        
        self.db.close()


def resample_ticks(db_path: str, symbol: str, interval: str = '10S') -> 'pd.DataFrame':
    """
    Resample tick data to OHLCV candles.
    
    Args:
        db_path: Path to tick database
        symbol: Stock symbol
        interval: Resample interval (e.g., '5S', '10S', '30S', '1min')
    
    Returns:
        DataFrame with OHLCV data
    """
    import pandas as pd
    
    conn = sqlite3.connect(db_path)
    
    df = pd.read_sql_query(
        "SELECT timestamp, last_price, volume FROM ticks WHERE symbol = ? ORDER BY timestamp",
        conn,
        params=(symbol,)
    )
    conn.close()
    
    if df.empty:
        return df
    
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)
    
    # Resample to OHLCV
    ohlcv = df['last_price'].resample(interval).ohlc()
    ohlcv['volume'] = df['volume'].resample(interval).last().diff().fillna(0)
    
    return ohlcv.dropna()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Zerodha Tick Data Collector")
    parser.add_argument("--enctoken", "-e", help="Enctoken (or from env/file)")
    parser.add_argument("--stocks", "-s", help="Comma-separated stock symbols")
    parser.add_argument("--nifty50", action="store_true", help="Collect all NIFTY 50")
    parser.add_argument("--stats", action="store_true", help="Show tick database stats")
    parser.add_argument("--resample", help="Resample ticks to interval (e.g., 10S, 30S)")
    parser.add_argument("--symbol", help="Symbol for resampling")
    
    args = parser.parse_args()
    
    # Stats mode
    if args.stats:
        if not TICK_DB_PATH.exists():
            print("No tick database found")
            return
        
        db = TickDatabase()
        stats = db.get_stats()
        db.close()
        
        print(f"\n{'='*60}")
        print(f"TICK DATABASE STATISTICS")
        print(f"{'='*60}")
        print(f"Total Ticks: {stats['total_ticks']:,}")
        print(f"Database Size: {stats['db_size_mb']} MB")
        print(f"\nBy Symbol:")
        for symbol, count, first, last in stats['by_symbol'][:10]:
            print(f"  {symbol}: {count:,} ticks ({first[:19]} to {last[:19]})")
        return
    
    # Resample mode
    if args.resample and args.symbol:
        import pandas as pd
        
        ohlcv = resample_ticks(str(TICK_DB_PATH), args.symbol.upper(), args.resample)
        if ohlcv.empty:
            print(f"No data for {args.symbol}")
        else:
            print(f"\n{args.symbol} - {args.resample} candles:")
            print(ohlcv.tail(20))
            
            # Save to CSV
            output = f"data/{args.symbol}_{args.resample.replace('S','sec')}.csv"
            ohlcv.to_csv(output)
            print(f"\nSaved to {output}")
        return
    
    # Collection mode
    enctoken = args.enctoken
    if not enctoken:
        # Try loading from file
        token_file = BASE_DIR / "enctoken.txt"
        if token_file.exists():
            enctoken = token_file.read_text().strip()
        else:
            # Try auto-login
            try:
                from zerodha_auto_login import get_enctoken
                enctoken = get_enctoken()
            except Exception as e:
                print(f"Could not get enctoken: {e}")
                print("Provide via --enctoken or set up auto-login")
                return
    
    # Determine tokens to subscribe
    tokens = None
    if args.stocks:
        # Convert symbols to tokens
        symbol_to_token = {v: k for k, v in ZerodhaTickCollector.NIFTY50_TOKENS.items()}
        tokens = []
        for sym in args.stocks.upper().split(','):
            if sym in symbol_to_token:
                tokens.append(symbol_to_token[sym])
            else:
                print(f"Unknown symbol: {sym}")
    
    # Start collector
    collector = ZerodhaTickCollector(enctoken, tokens)
    collector.start()


if __name__ == "__main__":
    main()
