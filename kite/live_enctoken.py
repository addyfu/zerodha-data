"""
Live Trading Analysis using Zerodha Web API (enctoken)
Fetches real-time data and runs Fib 3-Wave strategy
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

from kite.strategies import STRATEGY_REGISTRY
from kite.strategies.base_strategy import Signal

# Your enctoken from Zerodha web login
ENCTOKEN = "7FEvmFy70gI79icNva5U1u0+jwZEKgP3C/CARYogQp6ZOby4GOBfwPkmgje9UKeB3dvYff8XJ/6VZE8UBH6SCwoDlkPBDQq2Q7cuDJnXUpFlfjUwSikXiw=="

# API endpoints
BASE_URL = "https://kite.zerodha.com/orca"
INSTRUMENTS_URL = "https://api.kite.trade/instruments"

# NIFTY 50 stocks
STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "TITAN",
    "BAJFINANCE", "WIPRO", "HCLTECH", "SUNPHARMA", "TATAMOTORS"
]


def get_headers():
    """Get headers with auth token."""
    return {
        "Authorization": f"enctoken {ENCTOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }


def get_instruments():
    """Get instrument list from Zerodha."""
    try:
        response = requests.get(INSTRUMENTS_URL)
        if response.status_code == 200:
            lines = response.text.strip().split('\n')
            instruments = {}
            for line in lines[1:]:  # Skip header
                parts = line.split(',')
                if len(parts) >= 3 and parts[2] == 'NSE':
                    instruments[parts[1]] = int(parts[0])
            return instruments
    except Exception as e:
        print(f"Error fetching instruments: {e}")
    return {}


def fetch_historical_data(symbol: str, instrument_token: int, days: int = 60):
    """Fetch historical OHLCV data."""
    try:
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days)
        
        url = f"{BASE_URL}/instruments/historical/{instrument_token}/day"
        params = {
            "from": from_date.strftime("%Y-%m-%d"),
            "to": to_date.strftime("%Y-%m-%d"),
            "oi": 1
        }
        
        response = requests.get(url, headers=get_headers(), params=params)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success' and data.get('data', {}).get('candles'):
                candles = data['data']['candles']
                df = pd.DataFrame(candles, columns=['datetime', 'open', 'high', 'low', 'close', 'volume', 'oi'])
                df['datetime'] = pd.to_datetime(df['datetime'])
                df.set_index('datetime', inplace=True)
                df['symbol'] = symbol
                return df
        else:
            print(f"  {symbol}: HTTP {response.status_code}")
            
    except Exception as e:
        print(f"  {symbol}: Error - {str(e)[:40]}")
    
    return None


def analyze_stock(df: pd.DataFrame, strategy, symbol: str):
    """Analyze a single stock and return today's signal."""
    try:
        if len(df) < 30:
            return None
        
        # Generate signals
        signals_df = strategy.generate_signals(df)
        
        # Get the most recent day
        latest = signals_df.iloc[-1]
        prev = signals_df.iloc[-2] if len(signals_df) > 1 else latest
        
        signal = latest.get('signal', Signal.HOLD)
        
        result = {
            'symbol': symbol,
            'date': signals_df.index[-1].strftime('%Y-%m-%d'),
            'open': latest['open'],
            'high': latest['high'],
            'low': latest['low'],
            'close': latest['close'],
            'volume': latest.get('volume', 0),
            'change_pct': (latest['close'] - prev['close']) / prev['close'] * 100,
            'signal': signal.name if hasattr(signal, 'name') else str(signal),
        }
        
        # If there's a signal, calculate SL/TP
        if signal in [Signal.BUY, Signal.SELL]:
            idx = len(signals_df) - 1
            sl = strategy.calculate_stop_loss(signals_df, idx, signal)
            tp = strategy.calculate_take_profit(signals_df, idx, signal, latest['close'], sl)
            
            result['entry_price'] = latest['close']
            result['stop_loss'] = sl
            result['take_profit'] = tp
            result['risk_pct'] = abs(latest['close'] - sl) / latest['close'] * 100
            result['reward_pct'] = abs(tp - latest['close']) / latest['close'] * 100
            result['rr_ratio'] = result['reward_pct'] / result['risk_pct'] if result['risk_pct'] > 0 else 0
        
        return result
        
    except Exception as e:
        return None


def main():
    print("\n" + "="*80)
    print("LIVE TRADING ANALYSIS - Fib 3-Wave Strategy")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    # Get instruments
    print("\nFetching instrument list...")
    instruments = get_instruments()
    
    if not instruments:
        print("Failed to fetch instruments. Using cached data...")
        # Fallback to simulation
        from kite.simulate_today import main as simulate_main
        simulate_main()
        return
    
    print(f"Found {len(instruments)} NSE instruments")
    
    # Initialize strategy
    strategy = STRATEGY_REGISTRY['fib_3wave']({})
    
    print(f"\nAnalyzing {len(STOCKS)} stocks...")
    print("-"*80)
    
    buy_signals = []
    sell_signals = []
    all_results = []
    
    for symbol in STOCKS:
        if symbol not in instruments:
            print(f"  {symbol}: Not found")
            continue
        
        token = instruments[symbol]
        print(f"Fetching {symbol}...", end=" ")
        
        df = fetch_historical_data(symbol, token, days=60)
        
        if df is None or len(df) < 30:
            print("Insufficient data")
            continue
        
        result = analyze_stock(df, strategy, symbol)
        
        if result:
            all_results.append(result)
            
            if result['signal'] == 'BUY':
                buy_signals.append(result)
                print(f"BUY SIGNAL! Entry: Rs {result['close']:.2f}")
            elif result['signal'] == 'SELL':
                sell_signals.append(result)
                print(f"SELL SIGNAL! Entry: Rs {result['close']:.2f}")
            else:
                print(f"HOLD ({result['change_pct']:+.2f}%)")
        else:
            print("Analysis failed")
    
    # Print Summary
    print("\n" + "="*80)
    print("TODAY'S TRADING SIGNALS")
    print("="*80)
    
    if buy_signals:
        print(f"\n{'='*35} BUY SIGNALS {'='*32}")
        print(f"{'Symbol':<12} {'Price':>10} {'Stop Loss':>12} {'Target':>12} {'Risk%':>8} {'R:R':>6}")
        print("-"*65)
        for s in buy_signals:
            print(f"{s['symbol']:<12} {s['close']:>10.2f} {s['stop_loss']:>12.2f} "
                  f"{s['take_profit']:>12.2f} {s['risk_pct']:>7.2f}% {s['rr_ratio']:>6.1f}")
    else:
        print("\n[!] No BUY signals today.")
    
    if sell_signals:
        print(f"\n{'='*34} SELL SIGNALS {'='*32}")
        print(f"{'Symbol':<12} {'Price':>10} {'Stop Loss':>12} {'Target':>12} {'Risk%':>8} {'R:R':>6}")
        print("-"*65)
        for s in sell_signals:
            print(f"{s['symbol']:<12} {s['close']:>10.2f} {s['stop_loss']:>12.2f} "
                  f"{s['take_profit']:>12.2f} {s['risk_pct']:>7.2f}% {s['rr_ratio']:>6.1f}")
    else:
        print("\n[!] No SELL signals today.")
    
    # Market Overview
    if all_results:
        print(f"\n{'='*35} MARKET OVERVIEW {'='*28}")
        
        gainers = sorted([r for r in all_results if r['change_pct'] > 0], 
                        key=lambda x: x['change_pct'], reverse=True)[:5]
        losers = sorted([r for r in all_results if r['change_pct'] < 0], 
                       key=lambda x: x['change_pct'])[:5]
        
        avg_change = np.mean([r['change_pct'] for r in all_results])
        
        print(f"\nMarket Sentiment: {'BULLISH' if avg_change > 0 else 'BEARISH'} (Avg: {avg_change:+.2f}%)")
        
        print("\nTop Gainers:")
        for r in gainers:
            signal_marker = " [BUY]" if r['signal'] == 'BUY' else ""
            print(f"  {r['symbol']:<12} {r['change_pct']:>+6.2f}%  Rs {r['close']:>10.2f}{signal_marker}")
        
        print("\nTop Losers:")
        for r in losers:
            signal_marker = " [SELL]" if r['signal'] == 'SELL' else ""
            print(f"  {r['symbol']:<12} {r['change_pct']:>+6.2f}%  Rs {r['close']:>10.2f}{signal_marker}")
    
    # Position Sizing
    if buy_signals or sell_signals:
        print(f"\n{'='*32} POSITION SIZING {'='*31}")
        print("\nCapital: Rs 1,00,000 | Risk per trade: 2% (Rs 2,000)")
        print("-"*80)
        
        for s in buy_signals + sell_signals:
            risk_amount = 100000 * 0.02
            risk_per_share = abs(s['close'] - s['stop_loss'])
            quantity = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0
            position_value = quantity * s['close']
            potential_profit = quantity * abs(s['take_profit'] - s['close'])
            
            print(f"\n{s['symbol']} - {s['signal']}")
            print(f"  Entry:          Rs {s['close']:>10.2f}")
            print(f"  Stop Loss:      Rs {s['stop_loss']:>10.2f} ({s['risk_pct']:.1f}% risk)")
            print(f"  Target:         Rs {s['take_profit']:>10.2f} ({s['reward_pct']:.1f}% reward)")
            print(f"  Risk:Reward:    1:{s['rr_ratio']:.1f}")
            print(f"  Quantity:       {quantity} shares")
            print(f"  Position Size:  Rs {position_value:>10,.2f}")
            print(f"  Max Loss:       Rs {risk_amount:>10,.2f}")
            print(f"  Max Profit:     Rs {potential_profit:>10,.2f}")
    
    print("\n" + "="*80)
    print("ANALYSIS COMPLETE!")
    print("="*80)
    
    # Save results
    if all_results:
        df_results = pd.DataFrame(all_results)
        filename = f"live_signals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df_results.to_csv(filename, index=False)
        print(f"\nResults saved to {filename}")


if __name__ == '__main__':
    main()
