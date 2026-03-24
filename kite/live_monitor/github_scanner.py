"""
GitHub Actions Scanner
======================
Lightweight scanner designed for GitHub Actions.
Runs a single scan cycle, updates order book, sends alerts, and exits.

Uses auto-login with TOTP - no manual enctoken refresh needed!
"""
import os
import sys
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
import logging
from datetime import datetime, time as dtime, timezone, timedelta
from typing import Dict, List, Optional

# IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from concurrent.futures import ThreadPoolExecutor, as_completed

from kite.live_monitor.order_book import OrderBook
from kite.live_monitor.data_fetcher import ZerodhaDataFetcher, OfflineDataFetcher
from kite.live_monitor.signal_detector import SignalDetector
from kite.live_monitor.telegram_bot import TelegramBot


def get_enctoken_auto() -> str:
    """
    Get enctoken using auto-login with TOTP.
    Falls back to ZERODHA_ENCTOKEN env var if auto-login fails.
    """
    # First try auto-login
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
    
    logger.warning("No Zerodha credentials available")
    return ""


def get_all_stocks():
    """Get all NSE stocks from cloud_collector."""
    try:
        from cloud_collector import CloudCollector
        stocks = CloudCollector.load_all_nse_stocks()
        logger.info(f"Loaded {len(stocks)} stocks for scanning")
        return list(stocks.keys())
    except Exception as e:
        logger.warning(f"Could not load all stocks: {e}, using NIFTY 50")
        # Fallback to NIFTY 50
        return [
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


class GitHubScanner:
    """
    Scanner optimized for GitHub Actions.
    Runs a single scan, updates state, and exits.
    """
    
    def __init__(self,
                 enctoken: str = None,
                 telegram_token: str = None,
                 telegram_chat: str = None,
                 state_file: str = "order_book.json",
                 strategy: str = "ema_21_55",
                 capital: float = 100000,
                 offline: bool = False):
        """
        Initialize scanner.
        
        Args:
            enctoken: Zerodha enctoken
            telegram_token: Telegram bot token
            telegram_chat: Telegram chat ID
            state_file: Path to order book state file
            strategy: Strategy to use
            capital: Initial capital (only used if no existing state)
            offline: Use offline data for testing
        """
        self.offline = offline
        self.strategy_name = strategy
        
        # Initialize data fetcher
        if offline:
            self.fetcher = OfflineDataFetcher()
            logger.info("Using OFFLINE data")
        else:
            self.fetcher = ZerodhaDataFetcher(enctoken)
            logger.info("Using LIVE Zerodha data")
        
        # Initialize Telegram
        self.telegram = TelegramBot(telegram_token, telegram_chat)
        
        # Initialize order book
        self.order_book = OrderBook(state_file)
        
        # Set initial capital if new order book
        if self.order_book.account["total_trades"] == 0 and self.order_book.account["current_capital"] == 100000:
            self.order_book.account["initial_capital"] = capital
            self.order_book.account["current_capital"] = capital
            self.order_book.account["peak_capital"] = capital
        
        # Initialize signal detector
        self.detector = SignalDetector(
            strategy_name=strategy,
            capital=self.order_book.account["current_capital"],
            risk_per_trade=self.order_book.settings["risk_per_trade"],
            min_rr_ratio=1.5
        )
        
        # Stock list - load ALL NSE stocks
        self.stocks = get_all_stocks()
    
    def is_market_hours(self) -> bool:
        """Check if market is open (IST)."""
        # Get current time in IST (GitHub Actions runs in UTC)
        now_ist = datetime.now(IST)
        
        # Check weekday
        if now_ist.weekday() >= 5:
            return False
        
        # Market hours: 9:15 AM to 3:30 PM IST
        market_open = dtime(9, 15)
        market_close = dtime(15, 30)
        current_time = now_ist.time()
        
        logger.info(f"Current IST time: {now_ist.strftime('%Y-%m-%d %H:%M:%S')} (weekday={now_ist.weekday()})")
        logger.info(f"Market hours: {market_open} - {market_close}, current: {current_time}")
        
        return market_open <= current_time <= market_close
    
    def is_end_of_day(self) -> bool:
        """Check if it's end of trading day (3:25-3:35 PM IST)."""
        now_ist = datetime.now(IST)
        current_time = now_ist.time()
        return dtime(15, 25) <= current_time <= dtime(15, 35)
    
    def get_current_prices(self) -> Dict[str, float]:
        """Get current prices for all stocks with open positions."""
        symbols = [pos["symbol"] for pos in self.order_book.open_positions]
        
        if not symbols:
            return {}
        
        quotes = self.fetcher.get_quote(symbols)
        return {s: q["last_price"] for s, q in quotes.items()}
    
    def _prefilter_stocks(self) -> List[str]:
        """
        Pre-filter stocks using bulk quotes to find active ones.
        Fetches quotes in batches (cheap), keeps only stocks with decent volume/movement.
        Returns a shortlist for expensive historical data fetch.
        """
        if self.offline or not hasattr(self.fetcher, 'get_quote'):
            return self.stocks

        active_stocks = []
        batch_size = 50  # Zerodha quote API supports ~50 per call

        logger.info(f"Pre-filtering {len(self.stocks)} stocks using bulk quotes...")

        for i in range(0, len(self.stocks), batch_size):
            batch = self.stocks[i:i + batch_size]
            try:
                quotes = self.fetcher.get_quote(batch)
                for symbol, quote in quotes.items():
                    volume = quote.get('volume', 0)
                    change_pct = abs(quote.get('change_pct', 0))
                    last_price = quote.get('last_price', 0)

                    # Keep stocks with: price > 10, some volume, OR notable price change
                    if last_price > 10 and (volume > 50000 or change_pct > 1.5):
                        active_stocks.append(symbol)
            except Exception as e:
                # On error, include the whole batch as fallback
                active_stocks.extend(batch)

        logger.info(f"Pre-filter: {len(active_stocks)} active stocks from {len(self.stocks)}")
        return active_stocks

    def _fetch_and_detect(self, symbol: str) -> Optional[Dict]:
        """Fetch historical data and detect signal for a single stock (thread-safe)."""
        try:
            df = self.fetcher.get_historical_data(symbol, "day", 60)

            if df is None or len(df) < 50:
                return None

            signal = self.detector.detect_signal(symbol, df)

            if signal:
                logger.info(f"SIGNAL: {symbol} {signal.direction} @ Rs {signal.entry_price:.2f}")
                return signal.to_dict()
        except Exception as e:
            logger.error(f"Error scanning {symbol}: {e}")

        return None

    def scan_for_signals(self) -> List[Dict]:
        """Scan stocks for trading signals with pre-filtering and parallel fetches."""
        # Step 1: Pre-filter using cheap bulk quotes
        shortlist = self._prefilter_stocks()

        if not shortlist:
            logger.info("No active stocks after pre-filter")
            return []

        logger.info(f"Scanning {len(shortlist)} stocks (parallel, {min(10, len(shortlist))} workers)...")

        # Step 2: Fetch historical data + detect signals in parallel
        signals = []
        max_workers = min(10, len(shortlist))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self._fetch_and_detect, sym): sym for sym in shortlist}

            for future in as_completed(futures):
                result = future.result()
                if result:
                    signals.append(result)

        logger.info(f"Found {len(signals)} signals")
        return signals
    
    def check_open_positions(self) -> List[Dict]:
        """Check open positions for SL/TP hits."""
        if not self.order_book.open_positions:
            return []
        
        current_prices = self.get_current_prices()
        
        if not current_prices:
            logger.warning("Could not fetch current prices")
            return []
        
        # Check exits
        closed_trades = self.order_book.check_exits(current_prices)
        
        return closed_trades
    
    def process_signals(self, signals: List[Dict]) -> List[Dict]:
        """Process signals and open positions."""
        opened = []
        
        for signal in signals:
            # Try to open position
            position = self.order_book.open_position(signal)
            
            if position:
                opened.append(position)
                logger.info(f"Opened position: {signal['symbol']} {signal['direction']}")
        
        return opened
    
    def send_alerts(self, new_signals: List[Dict], opened_positions: List[Dict], 
                   closed_trades: List[Dict]):
        """Send Telegram alerts for all events."""
        
        # Alert for new signals (even if not opened)
        for signal in new_signals:
            self.telegram.send_trade_alert(signal)
        
        # Alert for opened positions
        for pos in opened_positions:
            self.telegram.send_position_opened(pos)
        
        # Alert for closed trades
        for trade in closed_trades:
            # Add running totals
            trade["total_pnl"] = self.order_book.account["total_pnl"]
            trade["win_rate"] = self.order_book.account["win_rate"]
            trade["current_capital"] = self.order_book.account["current_capital"]
            self.telegram.send_exit_alert(trade)
    
    def send_status_update(self):
        """Send periodic status update."""
        current_prices = self.get_current_prices()
        unrealized_pnl = self.order_book.get_unrealized_pnl(current_prices)
        
        summary = self.order_book.get_performance_summary()
        summary["unrealized_pnl"] = round(unrealized_pnl, 2)
        summary["positions_detail"] = self.order_book.format_open_positions(current_prices)
        
        self.telegram.send_status_update(summary)
    
    def send_daily_summary(self):
        """Send end-of-day summary."""
        daily = self.order_book.get_daily_summary()
        overall = self.order_book.get_performance_summary()
        
        summary = {
            **daily,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "total_trades": overall["total_trades"],
            "win_rate": overall["win_rate"],
            "total_pnl": overall["total_pnl"],
            "capital": overall["current_capital"],
            "open_positions": overall["open_positions"],
            "return_pct": overall["return_pct"]
        }
        
        self.telegram.send_daily_summary(summary)
    
    def close_all_positions(self, reason: str = "end_of_day"):
        """Close all open positions (e.g., at end of day)."""
        current_prices = self.get_current_prices()
        closed = []
        
        for pos in list(self.order_book.open_positions):
            symbol = pos["symbol"]
            if symbol in current_prices:
                trade = self.order_book.close_position(symbol, current_prices[symbol], reason)
                if trade:
                    closed.append(trade)
        
        return closed
    
    def run(self) -> Dict:
        """
        Run a single scan cycle.
        
        Returns:
            Summary of actions taken
        """
        logger.info("=" * 60)
        logger.info("GITHUB ACTIONS SCANNER - STARTING SCAN")
        logger.info("=" * 60)
        logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Strategy: {self.strategy_name}")
        logger.info(f"Capital: Rs {self.order_book.account['current_capital']:,.2f}")
        logger.info(f"Open positions: {len(self.order_book.open_positions)}")
        
        result = {
            "timestamp": datetime.now().isoformat(),
            "signals_found": 0,
            "positions_opened": 0,
            "positions_closed": 0,
            "alerts_sent": 0,
            "errors": []
        }
        
        try:
            # Check if market hours (skip for offline)
            if not self.offline and not self.is_market_hours():
                logger.info("Market is closed. Skipping scan.")
                result["status"] = "market_closed"
                return result
            
            # 1. Check open positions for exits
            closed_trades = self.check_open_positions()
            result["positions_closed"] = len(closed_trades)
            
            # 2. Scan for new signals
            signals = self.scan_for_signals()
            result["signals_found"] = len(signals)
            
            # 3. Process signals (open positions)
            opened_positions = self.process_signals(signals)
            result["positions_opened"] = len(opened_positions)
            
            # 4. Send alerts
            self.send_alerts(signals, opened_positions, closed_trades)
            result["alerts_sent"] = len(signals) + len(opened_positions) + len(closed_trades)
            
            # 5. Check if end of day - send summary
            if self.is_end_of_day():
                self.send_daily_summary()
                logger.info("Sent daily summary")
            
            # 6. Save state
            self.order_book.save_state()
            
            result["status"] = "success"
            
        except Exception as e:
            logger.error(f"Scan error: {e}")
            result["status"] = "error"
            result["errors"].append(str(e))
        
        # Log summary
        logger.info("-" * 60)
        logger.info(f"Scan complete:")
        logger.info(f"  Signals found: {result['signals_found']}")
        logger.info(f"  Positions opened: {result['positions_opened']}")
        logger.info(f"  Positions closed: {result['positions_closed']}")
        logger.info(f"  Current capital: Rs {self.order_book.account['current_capital']:,.2f}")
        logger.info(f"  Total P&L: Rs {self.order_book.account['total_pnl']:+,.2f}")
        logger.info("=" * 60)
        
        return result


def main():
    """Main entry point for GitHub Actions."""
    import argparse
    
    parser = argparse.ArgumentParser(description="GitHub Actions Trading Scanner")
    parser.add_argument("--state-file", default="order_book.json", help="Path to state file")
    parser.add_argument("--strategy", default="ema_21_55", help="Strategy to use")
    parser.add_argument("--capital", type=float, default=100000, help="Initial capital")
    parser.add_argument("--offline", action="store_true", help="Use offline data")
    parser.add_argument("--status", action="store_true", help="Send status update only")
    parser.add_argument("--summary", action="store_true", help="Send daily summary only")
    
    args = parser.parse_args()
    
    # Get credentials - try auto-login first, then fallback to manual enctoken
    enctoken = get_enctoken_auto()
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    telegram_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    
    # Create scanner
    scanner = GitHubScanner(
        enctoken=enctoken,
        telegram_token=telegram_token,
        telegram_chat=telegram_chat,
        state_file=args.state_file,
        strategy=args.strategy,
        capital=args.capital,
        offline=args.offline
    )
    
    # Run appropriate action
    if args.status:
        scanner.send_status_update()
    elif args.summary:
        scanner.send_daily_summary()
    else:
        result = scanner.run()
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
