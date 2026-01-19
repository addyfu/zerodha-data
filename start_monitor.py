#!/usr/bin/env python
"""
Quick Start Script for Live Trading Monitor
============================================

Usage:
    python start_monitor.py                    # Run with local data (testing)
    python start_monitor.py --live             # Run with live Zerodha data
    python start_monitor.py --live --telegram  # Run with Telegram alerts

Before running with --live:
1. Login to Kite web (kite.zerodha.com)
2. Open browser DevTools (F12) -> Application -> Cookies
3. Copy the 'enctoken' value
4. Set it: set ZERODHA_ENCTOKEN=your_token_here

For Telegram alerts:
1. Create bot via @BotFather, get token
2. Message @userinfobot to get your chat_id
3. Set: set TELEGRAM_BOT_TOKEN=your_bot_token
4. Set: set TELEGRAM_CHAT_ID=your_chat_id
"""
import sys
import os
import argparse

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kite.live_monitor.monitor import LiveMonitor


def main():
    parser = argparse.ArgumentParser(
        description='Live Trading Monitor - Fib 3-Wave Strategy',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument('--live', action='store_true', 
                       help='Use live Zerodha data (requires enctoken)')
    parser.add_argument('--telegram', action='store_true',
                       help='Enable Telegram alerts')
    parser.add_argument('--enctoken', type=str,
                       help='Zerodha enctoken (or set ZERODHA_ENCTOKEN env var)')
    parser.add_argument('--capital', type=float, default=100000,
                       help='Initial capital (default: 100000)')
    parser.add_argument('--interval', type=int, default=60,
                       help='Scan interval in seconds (default: 60)')
    parser.add_argument('--strategy', type=str, default='fib_3wave',
                       choices=['fib_3wave', 'ema_21_55', 'stochrsi_macd', 'gmma'],
                       help='Strategy to use (default: fib_3wave)')
    
    args = parser.parse_args()
    
    # Get credentials
    enctoken = args.enctoken or os.environ.get('ZERODHA_ENCTOKEN', '')
    telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    telegram_chat = os.environ.get('TELEGRAM_CHAT_ID', '')
    
    # Validate
    if args.live and not enctoken:
        print("ERROR: --live requires enctoken")
        print("Set ZERODHA_ENCTOKEN environment variable or use --enctoken")
        print("\nTo get enctoken:")
        print("1. Login to kite.zerodha.com")
        print("2. Open DevTools (F12) -> Application -> Cookies")
        print("3. Copy 'enctoken' value")
        sys.exit(1)
    
    if args.telegram and not (telegram_token and telegram_chat):
        print("WARNING: Telegram not configured. Alerts will be console only.")
        print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables")
    
    # Print banner
    print("""
    ================================================================
    |       LIVE TRADING MONITOR - Fib 3-Wave Strategy             |
    ================================================================
    |  Continuously monitors NIFTY 50 for trading signals          |
    |  Paper trades automatically and tracks performance           |
    ================================================================
    """)
    
    print(f"Mode:     {'LIVE' if args.live else 'OFFLINE (Testing)'}")
    print(f"Strategy: {args.strategy}")
    print(f"Capital:  Rs {args.capital:,.2f}")
    print(f"Interval: {args.interval}s")
    print(f"Telegram: {'Enabled' if args.telegram and telegram_token else 'Disabled'}")
    print()
    
    # Create and start monitor
    monitor = LiveMonitor(
        enctoken=enctoken if args.live else None,
        telegram_token=telegram_token if args.telegram else None,
        telegram_chat=telegram_chat if args.telegram else None,
        strategy=args.strategy,
        capital=args.capital,
        offline=not args.live,
        scan_interval=args.interval
    )
    
    print("Starting monitor... Press Ctrl+C to stop.\n")
    monitor.start()


if __name__ == '__main__':
    main()
