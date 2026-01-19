"""
Live Trading Simulation - Run strategy on today's real data
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from kiteconnect import KiteConnect
import warnings
warnings.filterwarnings('ignore')

from kite.strategies import STRATEGY_REGISTRY
from kite.backtesting.engine import BacktestEngine
from kite.strategies.base_strategy import Signal

# Your Zerodha API credentials
API_KEY = "5v0pt3vy3gx8gqmw"
ACCESS_TOKEN = "7FEvmFy70gI79icNva5U1u0+jwZEKgP3C/CARYogQp6ZOby4GOBfwPkmgje9UKeB3dvYff8XJ/6VZE8UBH6SCwoDlkPBDQq2Q7cuDJnXUpFlfjUwSikXiw=="

# NIFTY 50 stocks to analyze
STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "TITAN",
    "BAJFINANCE", "WIPRO", "HCLTECH", "SUNPHARMA", "TATAMOTORS"
]


def fetch_historical_data(kite, symbol: str, days: int = 60, interval: str = "day"):
    """Fetch historical data from Zerodha."""
    try:
        # Get instrument token
        instruments = kite.instruments("NSE")
        instrument_df = pd.DataFrame(instruments)
        
        token_row = instrument_df[instrument_df['tradingsymbol'] == symbol]
        if token_row.empty:
            print(f"  {symbol}: Not found in NSE")
            return None
        
        instrument_token = token_row.iloc[0]['instrument_token']
        
        # Fetch data
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days)
        
        data = kite.historical_data(
            instrument_token,
            from_date,
            to_date,
            interval
        )
        
        if not data:
            return None
        
        df = pd.DataFrame(data)
        df.columns = ['datetime', 'open', 'high', 'low', 'close', 'volume']
        df['datetime'] = pd.to_datetime(df['datetime'])
        df.set_index('datetime', inplace=True)
        df['symbol'] = symbol
        
        return df
        
    except Exception as e:
        print(f"  {symbol}: Error - {str(e)[:50]}")
        return None


def analyze_today_signals(df: pd.DataFrame, strategy, symbol: str):
    """Analyze signals for today."""
    try:
        # Generate signals
        signals_df = strategy.generate_signals(df)
        
        # Get today's data
        today = datetime.now().date()
        today_data = signals_df[signals_df.index.date == today]
        
        if today_data.empty:
            # Get the most recent trading day
            latest_date = signals_df.index[-1].date()
            today_data = signals_df[signals_df.index.date == latest_date]
            today_str = latest_date.strftime('%Y-%m-%d')
        else:
            today_str = today.strftime('%Y-%m-%d')
        
        if today_data.empty:
            return None
        
        # Get the latest signal
        latest = today_data.iloc[-1]
        signal = latest.get('signal', Signal.HOLD)
        
        # Get price info
        current_price = latest['close']
        open_price = today_data.iloc[0]['open']
        high = today_data['high'].max()
        low = today_data['low'].min()
        
        # Calculate day's change
        prev_close = signals_df.iloc[-2]['close'] if len(signals_df) > 1 else open_price
        day_change = (current_price - prev_close) / prev_close * 100
        
        result = {
            'symbol': symbol,
            'date': today_str,
            'open': open_price,
            'high': high,
            'low': low,
            'close': current_price,
            'change_pct': day_change,
            'signal': signal.name if hasattr(signal, 'name') else str(signal),
        }
        
        # If there's a signal, calculate SL/TP
        if signal in [Signal.BUY, Signal.SELL]:
            idx = len(signals_df) - 1
            sl = strategy.calculate_stop_loss(signals_df, idx, signal)
            tp = strategy.calculate_take_profit(signals_df, idx, signal, current_price, sl)
            
            result['entry_price'] = current_price
            result['stop_loss'] = sl
            result['take_profit'] = tp
            result['risk_pct'] = abs(current_price - sl) / current_price * 100
            result['reward_pct'] = abs(tp - current_price) / current_price * 100
            result['rr_ratio'] = result['reward_pct'] / result['risk_pct'] if result['risk_pct'] > 0 else 0
        
        return result
        
    except Exception as e:
        print(f"  {symbol}: Analysis error - {str(e)[:50]}")
        return None


def run_backtest_recent(df: pd.DataFrame, strategy, symbol: str):
    """Run backtest on recent data to show recent performance."""
    try:
        engine = BacktestEngine()
        result = engine.run(strategy, df, symbol)
        
        if result and result.total_trades > 0:
            return {
                'total_trades': result.total_trades,
                'win_rate': result.win_rate,
                'total_return_pct': result.total_return_pct,
                'sharpe': result.sharpe_ratio,
                'profit_factor': result.profit_factor,
            }
    except:
        pass
    return None


def main():
    print("\n" + "="*75)
    print("LIVE TRADING ANALYSIS - Fib 3-Wave Strategy")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*75)
    
    # Initialize Kite Connect
    print("\nConnecting to Zerodha...")
    kite = KiteConnect(api_key=API_KEY)
    kite.set_access_token(ACCESS_TOKEN)
    
    # Verify connection
    try:
        profile = kite.profile()
        print(f"Connected as: {profile['user_name']} ({profile['user_id']})")
    except Exception as e:
        print(f"Connection error: {e}")
        print("Please check your access token.")
        return
    
    # Initialize strategy
    strategy = STRATEGY_REGISTRY['fib_3wave']({})
    
    print(f"\nAnalyzing {len(STOCKS)} stocks...")
    print("-"*75)
    
    buy_signals = []
    sell_signals = []
    all_results = []
    
    for symbol in STOCKS:
        print(f"Fetching {symbol}...", end=" ")
        
        # Fetch 60 days of daily data (needed for indicators)
        df = fetch_historical_data(kite, symbol, days=60, interval="day")
        
        if df is None or len(df) < 30:
            print("Insufficient data")
            continue
        
        # Analyze today's signals
        result = analyze_today_signals(df, strategy, symbol)
        
        if result:
            all_results.append(result)
            
            if result['signal'] == 'BUY':
                buy_signals.append(result)
                print(f"BUY SIGNAL! Entry: {result['close']:.2f}")
            elif result['signal'] == 'SELL':
                sell_signals.append(result)
                print(f"SELL SIGNAL! Entry: {result['close']:.2f}")
            else:
                print(f"HOLD ({result['change_pct']:+.2f}%)")
        else:
            print("No signal")
    
    # Print Summary
    print("\n" + "="*75)
    print("TODAY'S TRADING SIGNALS")
    print("="*75)
    
    if buy_signals:
        print(f"\n{'='*30} BUY SIGNALS {'='*30}")
        print(f"{'Symbol':<12} {'Price':>10} {'Stop Loss':>12} {'Target':>12} {'Risk%':>8} {'R:R':>6}")
        print("-"*65)
        for s in buy_signals:
            print(f"{s['symbol']:<12} {s['close']:>10.2f} {s['stop_loss']:>12.2f} "
                  f"{s['take_profit']:>12.2f} {s['risk_pct']:>7.2f}% {s['rr_ratio']:>6.1f}")
    else:
        print("\nNo BUY signals today.")
    
    if sell_signals:
        print(f"\n{'='*30} SELL SIGNALS {'='*29}")
        print(f"{'Symbol':<12} {'Price':>10} {'Stop Loss':>12} {'Target':>12} {'Risk%':>8} {'R:R':>6}")
        print("-"*65)
        for s in sell_signals:
            print(f"{s['symbol']:<12} {s['close']:>10.2f} {s['stop_loss']:>12.2f} "
                  f"{s['take_profit']:>12.2f} {s['risk_pct']:>7.2f}% {s['rr_ratio']:>6.1f}")
    else:
        print("\nNo SELL signals today.")
    
    # Market Overview
    print(f"\n{'='*30} MARKET OVERVIEW {'='*27}")
    if all_results:
        gainers = sorted([r for r in all_results if r['change_pct'] > 0], 
                        key=lambda x: x['change_pct'], reverse=True)[:5]
        losers = sorted([r for r in all_results if r['change_pct'] < 0], 
                       key=lambda x: x['change_pct'])[:5]
        
        print("\nTop Gainers:")
        for r in gainers:
            print(f"  {r['symbol']:<12} {r['change_pct']:>+6.2f}%  (Rs {r['close']:.2f})")
        
        print("\nTop Losers:")
        for r in losers:
            print(f"  {r['symbol']:<12} {r['change_pct']:>+6.2f}%  (Rs {r['close']:.2f})")
    
    # Position Sizing Recommendation
    if buy_signals or sell_signals:
        print(f"\n{'='*30} POSITION SIZING {'='*27}")
        print("\nAssuming Rs 1,00,000 capital with 2% risk per trade:")
        print("-"*65)
        
        for s in buy_signals + sell_signals:
            risk_amount = 100000 * 0.02  # 2% of capital
            risk_per_share = abs(s['close'] - s['stop_loss'])
            quantity = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0
            position_value = quantity * s['close']
            
            print(f"\n{s['symbol']} ({s['signal']}):")
            print(f"  Entry Price:    Rs {s['close']:.2f}")
            print(f"  Stop Loss:      Rs {s['stop_loss']:.2f} ({s['risk_pct']:.2f}% risk)")
            print(f"  Target:         Rs {s['take_profit']:.2f} ({s['reward_pct']:.2f}% reward)")
            print(f"  Quantity:       {quantity} shares")
            print(f"  Position Value: Rs {position_value:,.2f}")
            print(f"  Max Loss:       Rs {risk_amount:,.2f}")
            print(f"  Potential Gain: Rs {quantity * abs(s['take_profit'] - s['close']):,.2f}")
    
    print("\n" + "="*75)
    print("ANALYSIS COMPLETE!")
    print("="*75)
    
    # Save results
    if all_results:
        df_results = pd.DataFrame(all_results)
        filename = f"live_signals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df_results.to_csv(filename, index=False)
        print(f"\nResults saved to {filename}")


if __name__ == '__main__':
    main()
