"""
Live Trading Monitor
====================
Main script that continuously monitors the market for trading signals,
sends Telegram alerts, and tracks paper trading performance.

Usage:
    python monitor.py --enctoken YOUR_ENCTOKEN
    python monitor.py --telegram-token BOT_TOKEN --telegram-chat CHAT_ID
    python monitor.py --offline  # Use local data for testing
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

import os
import time
import argparse
import schedule
from datetime import datetime, time as dtime
from typing import Dict, List
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent.parent.parent / 'data' / 'monitor.log')
    ]
)
logger = logging.getLogger(__name__)

from kite.live_monitor.telegram_bot import TelegramBot
from kite.live_monitor.data_fetcher import ZerodhaDataFetcher, OfflineDataFetcher
from kite.live_monitor.signal_detector import SignalDetector, TradeSignal
from kite.live_monitor.paper_trader import PaperTrader, ExitReason

# NIFTY 50 stocks
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


class LiveMonitor:
    """
    Main monitoring class that orchestrates all components.
    """
    
    def __init__(self,
                 enctoken: str = None,
                 telegram_token: str = None,
                 telegram_chat: str = None,
                 strategy: str = 'fib_3wave',
                 capital: float = 100000,
                 offline: bool = False,
                 scan_interval: int = 60):
        """
        Initialize live monitor.
        
        Args:
            enctoken: Zerodha enctoken
            telegram_token: Telegram bot token
            telegram_chat: Telegram chat ID
            strategy: Strategy to use
            capital: Initial capital
            offline: Use offline data (for testing)
            scan_interval: Seconds between scans
        """
        self.scan_interval = scan_interval
        self.offline = offline
        self.running = False
        
        # Initialize components
        logger.info("Initializing Live Monitor...")
        
        # Data fetcher
        if offline:
            self.fetcher = OfflineDataFetcher()
            logger.info("Using OFFLINE data (testing mode)")
        else:
            self.fetcher = ZerodhaDataFetcher(enctoken)
            logger.info("Using LIVE Zerodha data")
        
        # Telegram bot
        self.telegram = TelegramBot(telegram_token, telegram_chat)
        if self.telegram.test_connection():
            logger.info("Telegram connected")
        else:
            logger.warning("Telegram not configured - alerts will be console only")
        
        # Signal detector
        self.detector = SignalDetector(
            strategy_name=strategy,
            capital=capital,
            risk_per_trade=0.02,
            min_rr_ratio=1.5
        )
        logger.info(f"Strategy: {strategy}")
        
        # Paper trader
        self.trader = PaperTrader(
            initial_capital=capital,
            max_positions=5,
            use_trailing_stop=True,
            trailing_stop_pct=0.02
        )
        logger.info(f"Paper trader initialized with Rs {capital:,.2f}")
        
        # Stock list
        self.stocks = NIFTY_50
        
        # Cache for historical data
        self.data_cache: Dict[str, any] = {}
        self.cache_time: Dict[str, datetime] = {}
        self.cache_duration = 300  # 5 minutes
    
    def is_market_hours(self) -> bool:
        """Check if market is open."""
        now = datetime.now()
        
        # Check if weekday
        if now.weekday() >= 5:  # Saturday or Sunday
            return False
        
        # Check time (9:15 AM to 3:30 PM IST)
        market_open = dtime(9, 15)
        market_close = dtime(15, 30)
        current_time = now.time()
        
        return market_open <= current_time <= market_close
    
    def get_historical_data(self, symbol: str, force_refresh: bool = False):
        """Get historical data with caching."""
        now = datetime.now()
        
        # Check cache
        if not force_refresh and symbol in self.data_cache:
            cache_age = (now - self.cache_time.get(symbol, now)).seconds
            if cache_age < self.cache_duration:
                return self.data_cache[symbol]
        
        # Fetch fresh data
        df = self.fetcher.get_historical_data(symbol, 'day', 60)
        
        if df is not None:
            self.data_cache[symbol] = df
            self.cache_time[symbol] = now
        
        return df
    
    def scan_for_signals(self) -> List[TradeSignal]:
        """Scan all stocks for trading signals."""
        signals = []
        
        logger.info(f"Scanning {len(self.stocks)} stocks...")
        
        for symbol in self.stocks:
            try:
                df = self.get_historical_data(symbol)
                
                if df is None or len(df) < 50:
                    continue
                
                signal = self.detector.detect_signal(symbol, df)
                
                if signal:
                    signals.append(signal)
                    logger.info(f"SIGNAL: {symbol} {signal.direction} @ {signal.entry_price:.2f}")
                    
            except Exception as e:
                logger.error(f"Error scanning {symbol}: {e}")
        
        logger.info(f"Scan complete. Found {len(signals)} signals.")
        return signals
    
    def check_open_positions(self):
        """Check open positions for SL/TP hits."""
        if not self.trader.positions:
            return
        
        # Get current prices
        symbols = list(self.trader.positions.keys())
        quotes = self.fetcher.get_quote(symbols)
        
        if not quotes:
            return
        
        current_prices = {s: q['last_price'] for s, q in quotes.items()}
        
        # Check exits
        closed = self.trader.check_exits(current_prices)
        
        for position in closed:
            # Send exit alert
            self.telegram.send_exit_alert({
                'symbol': position.symbol,
                'direction': position.direction,
                'entry_price': position.entry_price,
                'exit_price': position.exit_price,
                'exit_reason': position.exit_reason,
                'pnl': position.pnl,
                'pnl_pct': position.pnl_pct,
                'duration': str(position.exit_time - position.entry_time),
                'total_pnl': self.trader.capital - self.trader.initial_capital,
                'win_rate': self.trader.get_performance_summary()['win_rate']
            })
    
    def process_signals(self, signals: List[TradeSignal]):
        """Process detected signals - open positions and send alerts."""
        for signal in signals:
            # Try to open position
            position = self.trader.open_position(signal)
            
            if position:
                # Send Telegram alert
                self.telegram.send_trade_alert(signal.to_dict())
                
                logger.info(f"Position opened: {signal.symbol} {signal.direction}")
    
    def run_scan_cycle(self):
        """Run one scan cycle."""
        try:
            # Check if market is open (skip for offline mode)
            if not self.offline and not self.is_market_hours():
                logger.debug("Market closed. Skipping scan.")
                return
            
            # Check open positions first
            self.check_open_positions()
            
            # Scan for new signals
            signals = self.scan_for_signals()
            
            # Process signals
            if signals:
                self.process_signals(signals)
            
            # Log status
            summary = self.trader.get_performance_summary()
            logger.info(f"Status: Capital=Rs {summary.get('capital', 0):,.2f} | "
                       f"Open={summary.get('open_positions', 0)} | "
                       f"Trades={summary.get('total_trades', 0)} | "
                       f"Win={summary.get('win_rate', 0):.1f}%")
            
        except Exception as e:
            logger.error(f"Scan cycle error: {e}")
    
    def send_daily_summary(self):
        """Send end-of-day summary."""
        summary = self.trader.get_performance_summary()
        daily = self.trader.get_daily_summary()
        
        self.telegram.send_daily_summary({
            **daily,
            'total_trades': summary['total_trades'],
            'win_rate': summary['win_rate'],
            'total_pnl': summary['total_pnl'],
            'sharpe': 0,  # Calculate if needed
            'open_positions': summary['open_positions'],
            'capital': summary['capital']
        })
    
    def start(self):
        """Start the monitor."""
        self.running = True
        
        logger.info("="*60)
        logger.info("LIVE TRADING MONITOR STARTED")
        logger.info("="*60)
        logger.info(f"Strategy: {self.detector.strategy_name}")
        logger.info(f"Stocks: {len(self.stocks)}")
        logger.info(f"Scan interval: {self.scan_interval}s")
        logger.info(f"Mode: {'OFFLINE' if self.offline else 'LIVE'}")
        logger.info("="*60)
        
        # Send startup message
        self.telegram.send_startup_message()
        
        # Schedule tasks
        schedule.every(self.scan_interval).seconds.do(self.run_scan_cycle)
        schedule.every().day.at("15:35").do(self.send_daily_summary)
        
        # Run initial scan
        self.run_scan_cycle()
        
        # Main loop
        try:
            while self.running:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping monitor...")
            self.stop()
    
    def stop(self):
        """Stop the monitor."""
        self.running = False
        
        # Send final summary
        summary = self.trader.get_performance_summary()
        logger.info("="*60)
        logger.info("MONITOR STOPPED")
        logger.info(f"Final Capital: ₹{summary['capital']:,.2f}")
        logger.info(f"Total P&L: ₹{summary['total_pnl']:+,.2f} ({summary['return_pct']:+.2f}%)")
        logger.info(f"Total Trades: {summary['total_trades']}")
        logger.info(f"Win Rate: {summary['win_rate']:.1f}%")
        logger.info("="*60)


def main():
    parser = argparse.ArgumentParser(description='Live Trading Monitor')
    parser.add_argument('--enctoken', type=str, help='Zerodha enctoken')
    parser.add_argument('--telegram-token', type=str, help='Telegram bot token')
    parser.add_argument('--telegram-chat', type=str, help='Telegram chat ID')
    parser.add_argument('--strategy', type=str, default='fib_3wave', help='Strategy to use')
    parser.add_argument('--capital', type=float, default=100000, help='Initial capital')
    parser.add_argument('--interval', type=int, default=60, help='Scan interval in seconds')
    parser.add_argument('--offline', action='store_true', help='Use offline data')
    
    args = parser.parse_args()
    
    # Get credentials from args or environment
    enctoken = args.enctoken or os.environ.get('ZERODHA_ENCTOKEN')
    telegram_token = args.telegram_token or os.environ.get('TELEGRAM_BOT_TOKEN')
    telegram_chat = args.telegram_chat or os.environ.get('TELEGRAM_CHAT_ID')
    
    # Create and start monitor
    monitor = LiveMonitor(
        enctoken=enctoken,
        telegram_token=telegram_token,
        telegram_chat=telegram_chat,
        strategy=args.strategy,
        capital=args.capital,
        offline=args.offline,
        scan_interval=args.interval
    )
    
    monitor.start()


if __name__ == '__main__':
    main()
