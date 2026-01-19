"""
Configuration for Live Monitor
==============================
Set your credentials here or use environment variables.
"""
import os

# Zerodha credentials
# Get enctoken from browser cookies after logging into Kite web
ZERODHA_ENCTOKEN = os.environ.get('ZERODHA_ENCTOKEN', '')

# Telegram Bot credentials
# 1. Create a bot via @BotFather on Telegram
# 2. Get your chat_id by messaging @userinfobot
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

# Trading settings
INITIAL_CAPITAL = 100000  # Rs 1,00,000
RISK_PER_TRADE = 0.02     # 2% risk per trade
MAX_POSITIONS = 5          # Maximum concurrent positions
STRATEGY = 'fib_3wave'     # Strategy to use

# Monitoring settings
SCAN_INTERVAL = 60         # Seconds between scans
USE_TRAILING_STOP = True   # Enable trailing stops
TRAILING_STOP_PCT = 0.02   # 2% trailing stop

# Stock list (NIFTY 50)
STOCKS = [
    'ADANIPORTS', 'APOLLOHOSP', 'ASIANPAINT', 'AXISBANK', 'BAJAJ-AUTO',
    'BAJAJFINSV', 'BAJFINANCE', 'BHARTIARTL', 'BPCL', 'BRITANNIA',
    'CIPLA', 'COALINDIA', 'DIVISLAB', 'DRREDDY', 'EICHERMOT',
    'GRASIM', 'HCLTECH', 'HDFCBANK', 'HDFCLIFE', 'HEROMOTOCO',
    'HINDALCO', 'HINDUNILVR', 'ICICIBANK', 'INDUSINDBK', 'INFY',
    'ITC', 'JSWSTEEL', 'KOTAKBANK', 'LT', 'M&M',
    'MARUTI', 'NESTLEIND', 'NTPC', 'ONGC', 'POWERGRID',
    'RELIANCE', 'SBIN', 'SHREECEM', 'SUNPHARMA', 'TATACONSUM',
    'TATAMOTORS', 'TATASTEEL', 'TCS', 'TECHM', 'TITAN',
    'ULTRACEMCO', 'UPL', 'WIPRO'
]


def print_config():
    """Print current configuration."""
    print("="*60)
    print("LIVE MONITOR CONFIGURATION")
    print("="*60)
    print(f"Zerodha Token: {'SET' if ZERODHA_ENCTOKEN else 'NOT SET'}")
    print(f"Telegram Bot:  {'SET' if TELEGRAM_BOT_TOKEN else 'NOT SET'}")
    print(f"Telegram Chat: {'SET' if TELEGRAM_CHAT_ID else 'NOT SET'}")
    print(f"Capital:       Rs {INITIAL_CAPITAL:,}")
    print(f"Risk/Trade:    {RISK_PER_TRADE*100}%")
    print(f"Max Positions: {MAX_POSITIONS}")
    print(f"Strategy:      {STRATEGY}")
    print(f"Scan Interval: {SCAN_INTERVAL}s")
    print(f"Stocks:        {len(STOCKS)}")
    print("="*60)


if __name__ == '__main__':
    print_config()
