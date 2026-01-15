"""
Zerodha Instruments List Downloader
====================================
Downloads the complete list of all tradeable instruments from Zerodha.
This helps you find the instrument_token for any stock.
"""

import requests
import pandas as pd
import os
from datetime import datetime


def download_instruments(output_dir: str = "data") -> pd.DataFrame:
    """
    Download the complete instruments list from Zerodha.
    This is publicly available and doesn't require authentication.
    
    Returns:
        DataFrame with all instruments
    """
    url = "https://api.kite.trade/instruments"
    
    print("📥 Downloading instruments list from Zerodha...")
    
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        
        # Save raw CSV
        os.makedirs(output_dir, exist_ok=True)
        csv_path = f"{output_dir}/instruments_{datetime.now().strftime('%Y%m%d')}.csv"
        
        with open(csv_path, 'wb') as f:
            f.write(response.content)
        
        print(f"✅ Saved to {csv_path}")
        
        # Parse and return
        df = pd.read_csv(csv_path)
        
        print(f"\n📊 Total instruments: {len(df)}")
        print(f"   Exchanges: {df['exchange'].unique().tolist()}")
        
        return df
        
    except Exception as e:
        print(f"❌ Error downloading instruments: {e}")
        return pd.DataFrame()


def search_instruments(df: pd.DataFrame, query: str, exchange: str = None) -> pd.DataFrame:
    """
    Search for instruments by name or symbol.
    
    Args:
        df: Instruments DataFrame
        query: Search query
        exchange: Filter by exchange (NSE, BSE, NFO, etc.)
    
    Returns:
        Filtered DataFrame
    """
    mask = (
        df['tradingsymbol'].str.contains(query, case=False, na=False) |
        df['name'].str.contains(query, case=False, na=False)
    )
    
    results = df[mask]
    
    if exchange:
        results = results[results['exchange'] == exchange]
    
    return results[['instrument_token', 'exchange', 'tradingsymbol', 'name', 'instrument_type', 'segment']]


def get_nse_stocks(df: pd.DataFrame) -> pd.DataFrame:
    """Get all NSE equity stocks."""
    return df[
        (df['exchange'] == 'NSE') & 
        (df['instrument_type'] == 'EQ')
    ][['instrument_token', 'tradingsymbol', 'name']].sort_values('tradingsymbol')


def generate_token_dict(df: pd.DataFrame, exchange: str = "NSE") -> dict:
    """
    Generate a Python dict of symbol -> token mappings.
    Useful for adding to zerodha_scraper.py
    """
    stocks = df[
        (df['exchange'] == exchange) & 
        (df['instrument_type'] == 'EQ')
    ]
    
    return dict(zip(stocks['tradingsymbol'], stocks['instrument_token']))


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Download and search Zerodha instruments")
    parser.add_argument("--search", "-s", help="Search for instruments")
    parser.add_argument("--exchange", "-e", help="Filter by exchange (NSE, BSE, NFO)")
    parser.add_argument("--list-nse", action="store_true", help="List all NSE stocks")
    parser.add_argument("--output", "-o", default="data", help="Output directory")
    
    args = parser.parse_args()
    
    # Download instruments
    df = download_instruments(args.output)
    
    if df.empty:
        exit(1)
    
    if args.search:
        results = search_instruments(df, args.search, args.exchange)
        print(f"\n🔍 Search results for '{args.search}':\n")
        print(results.to_string(index=False))
    
    elif args.list_nse:
        nse_stocks = get_nse_stocks(df)
        print(f"\n📊 NSE Stocks ({len(nse_stocks)} total):\n")
        print(nse_stocks.head(50).to_string(index=False))
        print(f"\n... and {len(nse_stocks) - 50} more")
        
        # Save to file
        nse_path = f"{args.output}/nse_stocks.csv"
        nse_stocks.to_csv(nse_path, index=False)
        print(f"\n✅ Full list saved to {nse_path}")
    
    else:
        print("\n💡 Usage examples:")
        print("   python instruments_downloader.py --search RELIANCE")
        print("   python instruments_downloader.py --search NIFTY --exchange NFO")
        print("   python instruments_downloader.py --list-nse")
