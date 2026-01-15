"""
Fetch All NSE Instruments
=========================
Downloads the complete list of NSE stocks from Zerodha
and generates the token mapping for data collection.
"""

import requests
import pandas as pd
from pathlib import Path
import json

def fetch_instruments():
    """
    Fetch all instruments from Zerodha's public API.
    This doesn't require authentication.
    """
    print("Downloading instruments list from Zerodha...")
    
    url = "https://api.kite.trade/instruments"
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    
    # Save raw CSV
    Path("data").mkdir(exist_ok=True)
    with open("data/instruments.csv", "wb") as f:
        f.write(response.content)
    
    # Parse
    df = pd.read_csv("data/instruments.csv")
    
    print(f"Total instruments: {len(df)}")
    print(f"Exchanges: {df['exchange'].unique().tolist()}")
    
    return df

def get_nse_stocks(df: pd.DataFrame) -> dict:
    """Get all NSE equity stocks as {symbol: token} dict."""
    nse_eq = df[
        (df['exchange'] == 'NSE') & 
        (df['instrument_type'] == 'EQ')
    ]
    
    return dict(zip(nse_eq['tradingsymbol'], nse_eq['instrument_token']))

def get_nse_fno(df: pd.DataFrame) -> dict:
    """Get NSE F&O stocks."""
    nfo = df[
        (df['exchange'] == 'NFO') & 
        (df['segment'] == 'NFO-FUT')
    ]
    # Get unique underlying symbols
    symbols = nfo['name'].unique().tolist()
    return symbols

def generate_stocks_file(output_path: str = "all_nse_stocks.py"):
    """Generate Python file with all NSE stock tokens."""
    df = fetch_instruments()
    
    nse_stocks = get_nse_stocks(df)
    
    print(f"\nNSE Equity Stocks: {len(nse_stocks)}")
    
    # Generate Python file
    with open(output_path, "w") as f:
        f.write('"""\nAll NSE Equity Stocks\nAuto-generated from Zerodha instruments API\n"""\n\n')
        f.write(f"# Total: {len(nse_stocks)} stocks\n\n")
        f.write("ALL_NSE_STOCKS = {\n")
        
        for symbol, token in sorted(nse_stocks.items()):
            f.write(f'    "{symbol}": {token},\n')
        
        f.write("}\n")
    
    print(f"Generated {output_path} with {len(nse_stocks)} stocks")
    
    # Also save as JSON for easy loading
    with open("data/nse_stocks.json", "w") as f:
        json.dump(nse_stocks, f, indent=2)
    
    print(f"Saved data/nse_stocks.json")
    
    return nse_stocks

if __name__ == "__main__":
    stocks = generate_stocks_file()
    
    print(f"\nSample stocks:")
    for i, (symbol, token) in enumerate(list(stocks.items())[:10]):
        print(f"  {symbol}: {token}")
    print(f"  ... and {len(stocks) - 10} more")
