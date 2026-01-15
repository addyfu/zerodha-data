"""
Zerodha Data Manager
====================
Utilities for managing, querying, and exporting your collected data.
"""

import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import os

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "data" / "zerodha_data.db"


class DataManager:
    """Manage and query collected data."""
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
    
    def get_symbols(self) -> list:
        """Get list of all symbols in database."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT DISTINCT symbol FROM ohlcv ORDER BY symbol")
        return [row[0] for row in cursor.fetchall()]
    
    def get_data(self, symbol: str, start_date: str = None, end_date: str = None,
                 interval: str = "minute") -> pd.DataFrame:
        """
        Get OHLCV data for a symbol.
        
        Args:
            symbol: Stock symbol
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            interval: Data interval (minute, day, etc.)
        
        Returns:
            DataFrame with OHLCV data
        """
        query = "SELECT datetime, open, high, low, close, volume, oi FROM ohlcv WHERE symbol = ? AND interval = ?"
        params = [symbol.upper(), interval]
        
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
    
    def get_multiple(self, symbols: list, start_date: str = None, end_date: str = None,
                     interval: str = "minute") -> dict:
        """Get data for multiple symbols."""
        return {symbol: self.get_data(symbol, start_date, end_date, interval) 
                for symbol in symbols}
    
    def export_to_csv(self, symbol: str, output_path: str = None, 
                      start_date: str = None, end_date: str = None):
        """Export symbol data to CSV."""
        df = self.get_data(symbol, start_date, end_date)
        if df.empty:
            print(f"No data for {symbol}")
            return None
        
        if output_path is None:
            output_path = BASE_DIR / "exports" / f"{symbol}_{datetime.now().strftime('%Y%m%d')}.csv"
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path)
        print(f"Exported {len(df)} rows to {output_path}")
        return output_path
    
    def export_all(self, output_dir: str = None, start_date: str = None, end_date: str = None):
        """Export all symbols to CSV files."""
        if output_dir is None:
            output_dir = BASE_DIR / "exports" / datetime.now().strftime('%Y%m%d')
        
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        symbols = self.get_symbols()
        for symbol in symbols:
            output_path = Path(output_dir) / f"{symbol}.csv"
            self.export_to_csv(symbol, output_path, start_date, end_date)
    
    def get_stats(self) -> dict:
        """Get comprehensive statistics."""
        cursor = self.conn.cursor()
        
        # Total records
        cursor.execute("SELECT COUNT(*) FROM ohlcv")
        total = cursor.fetchone()[0]
        
        # By symbol
        cursor.execute("""
            SELECT symbol, 
                   COUNT(*) as records,
                   MIN(datetime) as first_date,
                   MAX(datetime) as last_date,
                   COUNT(DISTINCT DATE(datetime)) as trading_days
            FROM ohlcv 
            WHERE interval = 'minute'
            GROUP BY symbol 
            ORDER BY symbol
        """)
        by_symbol = cursor.fetchall()
        
        # Collection history
        cursor.execute("""
            SELECT date, SUM(candles_added) as candles
            FROM collection_log
            GROUP BY date
            ORDER BY date DESC
            LIMIT 10
        """)
        recent_collections = cursor.fetchall()
        
        # Database size
        db_size = os.path.getsize(self.db_path) / (1024 * 1024)
        
        return {
            'total_records': total,
            'symbols': len(by_symbol),
            'by_symbol': by_symbol,
            'recent_collections': recent_collections,
            'db_size_mb': round(db_size, 2)
        }
    
    def resample(self, symbol: str, interval: str = "5min", 
                 start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """
        Resample 1-minute data to larger intervals.
        
        Args:
            symbol: Stock symbol
            interval: Target interval (5min, 15min, 30min, 1H, 1D)
            start_date: Start date
            end_date: End date
        
        Returns:
            Resampled DataFrame
        """
        df = self.get_data(symbol, start_date, end_date, "minute")
        if df.empty:
            return df
        
        # Resample OHLCV
        resampled = df.resample(interval).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum',
            'oi': 'last'
        }).dropna()
        
        return resampled
    
    def get_date_range(self, symbol: str) -> tuple:
        """Get date range for a symbol."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT MIN(datetime), MAX(datetime) 
            FROM ohlcv 
            WHERE symbol = ? AND interval = 'minute'
        """, (symbol.upper(),))
        return cursor.fetchone()
    
    def delete_data(self, symbol: str = None, before_date: str = None):
        """Delete data (use carefully!)."""
        if symbol and before_date:
            self.conn.execute(
                "DELETE FROM ohlcv WHERE symbol = ? AND datetime < ?",
                (symbol.upper(), before_date)
            )
        elif symbol:
            self.conn.execute("DELETE FROM ohlcv WHERE symbol = ?", (symbol.upper(),))
        elif before_date:
            self.conn.execute("DELETE FROM ohlcv WHERE datetime < ?", (before_date,))
        
        self.conn.commit()
        self.conn.execute("VACUUM")  # Reclaim space
    
    def close(self):
        self.conn.close()


def print_stats(stats: dict):
    """Pretty print statistics."""
    print(f"\n{'='*70}")
    print(f"{'DATABASE STATISTICS':^70}")
    print(f"{'='*70}")
    print(f"\nTotal Records: {stats['total_records']:,}")
    print(f"Total Symbols: {stats['symbols']}")
    print(f"Database Size: {stats['db_size_mb']} MB")
    
    print(f"\n{'Recent Collections':^70}")
    print("-" * 70)
    for date, candles in stats['recent_collections']:
        print(f"  {date}: {candles:,} candles")
    
    print(f"\n{'Data by Symbol':^70}")
    print("-" * 70)
    print(f"{'Symbol':<12} {'Records':>10} {'Days':>6} {'First Date':<20} {'Last Date':<20}")
    print("-" * 70)
    for symbol, records, first, last, days in stats['by_symbol']:
        first_short = first[:10] if first else "N/A"
        last_short = last[:10] if last else "N/A"
        print(f"{symbol:<12} {records:>10,} {days:>6} {first_short:<20} {last_short:<20}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Zerodha Data Manager")
    parser.add_argument("--stats", action="store_true", help="Show database statistics")
    parser.add_argument("--symbols", action="store_true", help="List all symbols")
    parser.add_argument("--query", "-q", help="Query data for a symbol")
    parser.add_argument("--start", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", help="End date (YYYY-MM-DD)")
    parser.add_argument("--export", help="Export symbol to CSV")
    parser.add_argument("--export-all", action="store_true", help="Export all symbols")
    parser.add_argument("--resample", help="Resample interval (5min, 15min, 1H, 1D)")
    parser.add_argument("--tail", type=int, default=20, help="Number of rows to show")
    
    args = parser.parse_args()
    
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        print("Run daily_collector.py first to create the database")
        return
    
    manager = DataManager()
    
    try:
        if args.stats:
            stats = manager.get_stats()
            print_stats(stats)
        
        elif args.symbols:
            symbols = manager.get_symbols()
            print(f"\nSymbols in database ({len(symbols)}):")
            for i, sym in enumerate(symbols, 1):
                print(f"  {i:2}. {sym}")
        
        elif args.query:
            symbol = args.query.upper()
            
            if args.resample:
                df = manager.resample(symbol, args.resample, args.start, args.end)
                print(f"\n{symbol} - Resampled to {args.resample}")
            else:
                df = manager.get_data(symbol, args.start, args.end)
                print(f"\n{symbol} - 1 Minute Data")
            
            if df.empty:
                print("No data found")
            else:
                first, last = manager.get_date_range(symbol)
                print(f"Date Range: {first} to {last}")
                print(f"Total Records: {len(df):,}")
                print(f"\nLast {args.tail} rows:")
                print(df.tail(args.tail).to_string())
        
        elif args.export:
            manager.export_to_csv(args.export.upper(), start_date=args.start, end_date=args.end)
        
        elif args.export_all:
            manager.export_all(start_date=args.start, end_date=args.end)
        
        else:
            parser.print_help()
    
    finally:
        manager.close()


if __name__ == "__main__":
    main()
