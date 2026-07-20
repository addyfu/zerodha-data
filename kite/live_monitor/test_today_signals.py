"""
Test Today's Signals
====================
Run the scanner logic for today to check if any signals were missed.
This is a standalone test script that doesn't modify the original scanner.

Usage:
    python kite/live_monitor/test_today_signals.py
"""
import os
import sys
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
import logging
from datetime import datetime
from typing import Dict, List

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_enctoken_auto() -> str:
    """Get enctoken using auto-login with TOTP."""
    user_id = os.environ.get("ZERODHA_USER_ID")
    password = os.environ.get("ZERODHA_PASSWORD")
    totp_secret = os.environ.get("ZERODHA_TOTP_SECRET")
    
    if all([user_id, password, totp_secret]):
        try:
            from zerodha_auto_login import get_enctoken
            logger.info("Attempting auto-login with TOTP...")
            enctoken = get_enctoken(user_id, password, totp_secret)
            logger.info("Auto-login successful!")
            return enctoken
        except Exception as e:
            logger.warning(f"Auto-login failed: {e}")
    
    # Fallback to manual enctoken
    enctoken = os.environ.get("ZERODHA_ENCTOKEN", "")
    if enctoken:
        logger.info("Using manual ZERODHA_ENCTOKEN")
        return enctoken
    
    # Try reading from file
    enctoken_file = Path(__file__).parent.parent.parent / "enctoken.txt"
    if enctoken_file.exists():
        enctoken = enctoken_file.read_text().strip()
        if enctoken:
            logger.info("Using enctoken from file")
            return enctoken
    
    logger.warning("No Zerodha credentials available")
    return ""


def get_stocks_to_scan(use_all_nse=True):
    """Get list of stocks to scan."""
    # NIFTY 50 stocks - always reliable
    NIFTY_50 = [
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
    
    if not use_all_nse:
        logger.info(f"Using NIFTY 50 stocks ({len(NIFTY_50)} stocks)")
        return NIFTY_50
    
    try:
        from cloud_collector import CloudCollector
        stocks = CloudCollector.load_all_nse_stocks()
        # Filter out indices (they have spaces in names)
        equity_stocks = [s for s in stocks.keys() if ' ' not in s and not s.endswith('-BE') and not s.endswith('-SM')]
        logger.info(f"Loaded {len(equity_stocks)} equity stocks for scanning")
        return equity_stocks
    except Exception as e:
        logger.warning(f"Could not load all stocks: {e}, using NIFTY 50")
        return NIFTY_50


def test_today_signals(use_all_nse=False, strategy="fib_3wave"):
    """
    Test scanner on today's data to find any signals that were missed.
    
    Args:
        use_all_nse: If True, scan all NSE stocks. If False, scan only NIFTY 50.
        strategy: Strategy name to use for signal detection.
    """
    print("=" * 70)
    print("TEST TODAY'S SIGNALS - Checking for missed trading opportunities")
    print("=" * 70)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Strategy: {strategy}")
    print()
    
    # Get enctoken
    enctoken = get_enctoken_auto()
    if not enctoken:
        print("[ERROR] Could not get Zerodha enctoken. Please set credentials.")
        return
    
    # Initialize data fetcher
    from kite.live_monitor.data_fetcher import ZerodhaDataFetcher
    from kite.live_monitor.signal_detector import SignalDetector
    
    fetcher = ZerodhaDataFetcher(enctoken)
    
    # Initialize signal detector
    detector = SignalDetector(
        strategy_name=strategy,
        capital=100000,
        risk_per_trade=0.02,
        min_rr_ratio=1.5
    )
    
    # Get stocks to scan
    stocks = get_stocks_to_scan(use_all_nse=use_all_nse)
    
    print(f"Scanning {len(stocks)} stocks for signals...")
    print("-" * 70)
    
    signals_found = []
    errors = []
    scanned = 0
    
    for i, symbol in enumerate(stocks):
        try:
            # Progress indicator
            if (i + 1) % 100 == 0:
                print(f"  Progress: {i + 1}/{len(stocks)} stocks scanned, {len(signals_found)} signals found...")
            
            # Get historical data (60 days for indicator calculation)
            df = fetcher.get_historical_data(symbol, "day", 60)
            
            if df is None or len(df) < 50:
                continue
            
            scanned += 1
            
            # Detect signal (bypass cooldown for testing)
            detector.last_signals = {}  # Reset cooldown for each stock
            signal = detector.detect_signal(symbol, df)
            
            if signal:
                signals_found.append(signal)
                print(f"\n  ✅ SIGNAL: {symbol}")
                print(f"     Direction: {signal.direction}")
                print(f"     Entry: Rs {signal.entry_price:.2f}")
                print(f"     Stop Loss: Rs {signal.stop_loss:.2f} ({signal.risk_pct:.1f}% risk)")
                print(f"     Target: Rs {signal.take_profit:.2f} ({signal.reward_pct:.1f}% reward)")
                print(f"     R:R Ratio: 1:{signal.rr_ratio:.1f}")
                print(f"     Quantity: {signal.quantity} shares")
                print(f"     Position Value: Rs {signal.position_value:,.2f}")
                print(f"     Confidence: {signal.confidence:.0f}%")
        
        except Exception as e:
            errors.append(f"{symbol}: {str(e)}")
    
    # Summary
    print("\n" + "=" * 70)
    print("SCAN COMPLETE - SUMMARY")
    print("=" * 70)
    print(f"  Stocks scanned: {scanned}")
    print(f"  Signals found: {len(signals_found)}")
    print(f"  Errors: {len(errors)}")
    
    if signals_found:
        print("\n" + "-" * 70)
        print("ALL SIGNALS FOR TODAY:")
        print("-" * 70)
        
        # Sort by confidence
        signals_found.sort(key=lambda x: x.confidence, reverse=True)
        
        for i, signal in enumerate(signals_found, 1):
            print(f"\n{i}. {signal.symbol} - {signal.direction}")
            print(f"   Entry: Rs {signal.entry_price:.2f} | SL: Rs {signal.stop_loss:.2f} | TP: Rs {signal.take_profit:.2f}")
            print(f"   Risk: {signal.risk_pct:.1f}% | Reward: {signal.reward_pct:.1f}% | R:R: 1:{signal.rr_ratio:.1f}")
            print(f"   Qty: {signal.quantity} | Value: Rs {signal.position_value:,.2f} | Confidence: {signal.confidence:.0f}%")
        
        # Save to file
        output_file = Path(__file__).parent.parent.parent / f"signals_today_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        signals_data = [s.to_dict() for s in signals_found]
        with open(output_file, 'w') as f:
            json.dump(signals_data, f, indent=2, default=str)
        print(f"\n✅ Signals saved to: {output_file}")
    else:
        print("\n⚠️  No signals found for today based on the fib_3wave strategy.")
        print("   This could mean:")
        print("   1. No stocks met the entry criteria today")
        print("   2. R:R ratio was below minimum (1.5)")
        print("   3. Strategy didn't generate BUY/SELL signals")
    
    if errors and len(errors) < 20:
        print("\n" + "-" * 70)
        print("ERRORS (first 20):")
        for err in errors[:20]:
            print(f"  - {err}")
    
    print("\n" + "=" * 70)
    
    return signals_found


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test today's trading signals")
    parser.add_argument("--all-nse", action="store_true", help="Scan all NSE stocks (slower)")
    parser.add_argument("--strategy", default="fib_3wave", help="Strategy to use")
    
    args = parser.parse_args()
    
    test_today_signals(use_all_nse=args.all_nse, strategy=args.strategy)
