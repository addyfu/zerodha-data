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

# Load .env file if it exists (local development)
_env_file = Path(__file__).parent.parent.parent / '.env'
if _env_file.exists():
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _key, _, _val = _line.partition('=')
                _val = _val.strip()
                if _val.startswith(('"', "'")) and _val.endswith(_val[0]):
                    _val = _val[1:-1]  # strip surrounding quotes
                else:
                    _val = _val.split('#')[0].strip()  # strip inline comments
                os.environ.setdefault(_key.strip(), _val)
import time
import argparse
import schedule
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as dtime
from typing import Dict, List, Optional
import logging
import pandas as pd

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
from kite.live_monitor.db_manager import DBManager

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

    Two-phase approach for fast scanning:
    1. At startup/market open: fetch 60-day historical data for all stocks (slow, once)
    2. Every scan: fetch bulk quotes (fast), update cached data, run strategies
    """

    INTRADAY_STRATEGIES = ['fib_3wave']
    SWING_STRATEGIES = ['ema_21_55', 'vwap_pullback', 'elliott_wave3']

    def __init__(self,
                 enctoken: str = None,
                 telegram_token: str = None,
                 telegram_chat: str = None,
                 strategy: str = None,
                 capital: float = 100000,
                 offline: bool = False,
                 scan_interval: int = 300):  # 5 minutes — matches 5-min candle interval
        self.scan_interval = scan_interval
        self.offline = offline
        self.running = False

        logger.info("Initializing Live Monitor...")

        # Auto-login if no enctoken provided
        if not offline and not enctoken:
            enctoken = self._auto_login()

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

        # Signal detectors — separate lists per mode
        max_positions = 5
        slot_size = capital / max_positions

        if strategy:
            self.intraday_detectors = [
                SignalDetector(strategy_name=strategy, capital=capital,
                               risk_per_trade=0.02, min_rr_ratio=1.5,
                               max_position_pct=slot_size / capital)
            ]
            self.swing_detectors = []
        else:
            self.intraday_detectors = [
                SignalDetector(strategy_name=s, capital=capital,
                               risk_per_trade=0.02, min_rr_ratio=1.5,
                               max_position_pct=slot_size / capital)
                for s in self.INTRADAY_STRATEGIES
            ]
            self.swing_detectors = [
                SignalDetector(strategy_name=s, capital=capital,
                               risk_per_trade=0.02, min_rr_ratio=1.5,
                               max_position_pct=slot_size / capital)
                for s in self.SWING_STRATEGIES
            ]

        all_strategies = [d.strategy_name for d in self.intraday_detectors + self.swing_detectors]
        logger.info(f"Strategies: {', '.join(all_strategies)} | Slot size: Rs {slot_size:,.0f}")

        # Paper trader
        self.trader = PaperTrader(
            initial_capital=capital,
            max_positions=max_positions,
            use_trailing_stop=True,
            trailing_stop_pct=0.02
        )
        logger.info(f"Paper trader initialized with Rs {capital:,.2f}")

        # Stock list — use NIFTY 50 for fast local scanning
        self.stocks = NIFTY_50

        # Historical data cache (loaded once, updated with quotes)
        self.data_cache: Dict[str, pd.DataFrame] = {}
        self.daily_data_cache: Dict[str, pd.DataFrame] = {}
        self.swing_scanned_today = False
        self.history_loaded = False
        self.db = DBManager()

    @staticmethod
    def _auto_login() -> Optional[str]:
        """Auto-login to Zerodha using env credentials."""
        try:
            from zerodha_auto_login import get_enctoken
            user = os.environ.get('ZERODHA_USER_ID', '')
            pwd = os.environ.get('ZERODHA_PASSWORD', '')
            totp = os.environ.get('ZERODHA_TOTP_SECRET', '')
            if all([user, pwd, totp]):
                token = get_enctoken(user, pwd, totp)
                return token
        except Exception as e:
            logger.error(f"Auto-login failed: {e}")
        return None

    def _refresh_token_if_needed(self):
        """Re-login and update fetcher token if expired."""
        if self.offline or not hasattr(self.fetcher, 'token_expired') or not self.fetcher.token_expired:
            return
        logger.info("Token expired — attempting re-login...")
        new_token = self._auto_login()
        if new_token:
            self.fetcher.set_enctoken(new_token)
            logger.info("Token refreshed successfully")
        else:
            logger.error("Token refresh failed — API calls will continue to fail")

    def is_market_hours(self) -> bool:
        """Check if market is open."""
        now = datetime.now()
        if now.weekday() >= 5:
            return False
        market_open = dtime(9, 15)
        market_close = dtime(15, 30)
        return market_open <= now.time() <= market_close

    def load_historical_data(self):
        """Load 5-min data from local DB (seeded from GitHub release if needed)."""
        logger.info("Loading historical data from local DB...")

        # In offline mode skip GitHub release check — use whatever DB is local
        if not self.offline:
            if not self.db.ensure_seeded():
                logger.error("DB unavailable — falling back to Zerodha API fetch")
                self._load_from_zerodha_fallback()
                return
        elif not self.db.db_path.exists():
            logger.error("Offline mode but local DB not found — no data available")
            return

        # Load NIFTY 50 5-min data from DB
        self.data_cache = self.db.load_nifty50(self.stocks, resample='5min')

        # Load daily data for swing strategies
        if self.swing_detectors:
            self.daily_data_cache = self.db.load_nifty50(self.stocks, resample='1D')
            logger.info(f"Loaded daily data for {len(self.daily_data_cache)}/{len(self.stocks)} stocks (swing mode)")

        self.history_loaded = True
        logger.info(f"Loaded 5-min data for {len(self.data_cache)}/{len(self.stocks)} stocks from DB")

    def _load_from_zerodha_fallback(self):
        """Fallback: fetch from Zerodha API if DB unavailable (original logic)."""
        logger.info(f"Fallback: fetching 5-min data for {len(self.stocks)} stocks from Zerodha...")

        def fetch_one(symbol):
            try:
                df = self.fetcher.get_historical_data(symbol, '5minute', 60)
                if df is not None and len(df) >= 60:
                    if df.index.tz is not None:
                        df = df.copy()
                        df.index = df.index.tz_localize(None)
                    return symbol, df
            except Exception as e:
                logger.error(f"Failed to load {symbol}: {e}")
            return symbol, None

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(fetch_one, s): s for s in self.stocks}
            for future in as_completed(futures):
                symbol, df = future.result()
                if df is not None:
                    self.data_cache[symbol] = df
                time.sleep(0.3)

        self.history_loaded = True
        logger.info(f"Fallback loaded {len(self.data_cache)}/{len(self.stocks)} stocks")

    def update_with_latest_candle(self):
        """Fetch the latest completed 5-min candle and append to cache."""
        if self.offline or not self.data_cache:
            return

        def fetch_latest(symbol):
            try:
                df = self.fetcher.get_historical_data(symbol, '5minute', 1)
                if df is not None and len(df) > 0:
                    if df.index.tz is not None:
                        df = df.copy()
                        df.index = df.index.tz_localize(None)
                    return symbol, df
            except Exception:
                pass
            return symbol, None

        try:
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(fetch_latest, s): s for s in self.data_cache}
                for future in as_completed(futures):
                    symbol, new_df = future.result()
                    if new_df is None:
                        continue
                    cached = self.data_cache[symbol]
                    # Append only candles newer than what we have
                    new_rows = new_df[new_df.index > cached.index[-1]]
                    if not new_rows.empty:
                        self.data_cache[symbol] = pd.concat([cached, new_rows])
                        # Persist new candle to local DB (5-minute interval)
                        self.db.append_candles({symbol: new_rows}, interval='5minute')
        except Exception as e:
            logger.error(f"Candle update failed: {e}", exc_info=True)

    def scan_for_signals(self) -> List[TradeSignal]:
        """Scan cached data for trading signals across all strategies (fast — no API calls)."""
        signals = []
        seen = set()  # avoid duplicate symbol+direction signals from multiple strategies

        for symbol, df in self.data_cache.items():
            if df is None or len(df) < 50:
                continue
            for detector in self.intraday_detectors:
                try:
                    signal = detector.detect_signal(symbol, df)
                    if signal:
                        key = (symbol, signal.direction)
                        if key not in seen:
                            signal.trade_mode = "INTRADAY"
                            seen.add(key)
                            signals.append(signal)
                            logger.info(f"SIGNAL [{signal.strategy}]: {symbol} {signal.direction} @ Rs {signal.entry_price:.2f}")
                except Exception as e:
                    logger.error(f"Error scanning {symbol} with {detector.strategy_name}: {e}", exc_info=True)

        return signals
    
    def scan_for_swing_signals(self) -> List[TradeSignal]:
        """Scan daily data for swing trading signals (run once per day)."""
        if not self.swing_detectors or not self.daily_data_cache:
            return []

        signals = []
        seen = set()

        for symbol, df in self.daily_data_cache.items():
            if df is None or len(df) < 50:
                continue
            for detector in self.swing_detectors:
                try:
                    signal = detector.detect_signal(symbol, df)
                    if signal:
                        key = (symbol, signal.direction)
                        if key not in seen:
                            signal.trade_mode = "SWING"
                            seen.add(key)
                            signals.append(signal)
                            logger.info(f"SWING SIGNAL [{signal.strategy}]: {symbol} {signal.direction} @ Rs {signal.entry_price:.2f}")
                except Exception as e:
                    logger.error(f"Error scanning {symbol} with {detector.strategy_name} (swing): {e}", exc_info=True)

        return signals

    def check_open_positions(self):
        """Check open positions for SL/TP hits."""
        if not self.trader.positions:
            return

        # Get current prices — try quote API first, fall back to cached candle close
        symbols = list(self.trader.positions.keys())
        quotes = self.fetcher.get_quote(symbols)

        if quotes:
            current_prices = {s: q['last_price'] for s, q in quotes.items()}
        elif self.data_cache:
            current_prices = {}
            for s in symbols:
                if s in self.data_cache and len(self.data_cache[s]) > 0:
                    current_prices[s] = float(self.data_cache[s].iloc[-1]['close'])
        else:
            return

        if not current_prices:
            return

        # Save prices for dashboard
        self.trader.save_latest_prices(current_prices)

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
            # Refresh token if expired (auto re-login)
            self._refresh_token_if_needed()

            # Check if market is open (skip for offline mode)
            if not self.offline and not self.is_market_hours():
                logger.info("Outside market hours — skipping scan")
                return

            logger.info(f"--- Scan cycle starting ({datetime.now().strftime('%H:%M:%S')}) ---")

            # Load historical data once
            if not self.history_loaded:
                self.load_historical_data()

            # Fetch latest 5-min candle and append to cache
            self.update_with_latest_candle()

            # Check open positions first
            self.check_open_positions()

            # Scan for new signals (fast — uses cached data only)
            signals = self.scan_for_signals()
            logger.info(f"Scan complete: {len(self.data_cache)} stocks scanned | {len(signals)} signal(s) found")

            # Process signals
            if signals:
                self.process_signals(signals)

            # Swing scan — once per day at market open
            now = datetime.now()
            if not self.swing_scanned_today and now.time() >= dtime(9, 25):
                swing_signals = self.scan_for_swing_signals()
                logger.info(f"Swing scan: {len(swing_signals)} signal(s) found")
                if swing_signals:
                    self.process_signals(swing_signals)
                self.swing_scanned_today = True

            # Reset swing scan flag for next day
            if now.time() < dtime(9, 20):
                self.swing_scanned_today = False

            summary = self.trader.get_performance_summary()
            logger.info(f"Status: Capital=Rs {summary.get('capital', 0):,.2f} | "
                       f"Open={summary.get('open_positions', 0)} | "
                       f"Trades={summary.get('total_trades', 0)} | "
                       f"Win={summary.get('win_rate', 0):.1f}%")

        except Exception as e:
            logger.error(f"Scan cycle error: {e}", exc_info=True)
    
    def close_all_positions_eod(self):
        """Close all positions at end of day (India intraday square-off at 3:20 PM)."""
        if not self.trader.positions:
            logger.info("No open positions to close at EOD")
            return

        logger.info("=" * 60)
        logger.info("END OF DAY - CLOSING INTRADAY POSITIONS")
        logger.info("=" * 60)

        # Get current prices — quote API or cached candle
        symbols = list(self.trader.positions.keys())
        quotes = self.fetcher.get_quote(symbols)

        if quotes:
            current_prices = {s: q['last_price'] for s, q in quotes.items()}
        elif self.data_cache:
            current_prices = {}
            for s in symbols:
                if s in self.data_cache and len(self.data_cache[s]) > 0:
                    current_prices[s] = float(self.data_cache[s].iloc[-1]['close'])
        else:
            logger.error("Could not fetch prices for EOD close")
            return

        from kite.live_monitor.paper_trader import ExitReason
        closed = self.trader.close_all_positions(current_prices, ExitReason.END_OF_DAY, trade_mode="INTRADAY")

        for position in closed:
            self.telegram.send_exit_alert({
                'symbol': position.symbol,
                'direction': position.direction,
                'entry_price': position.entry_price,
                'exit_price': position.exit_price,
                'exit_reason': 'end_of_day',
                'pnl': position.pnl,
                'pnl_pct': position.pnl_pct,
                'duration': str(position.exit_time - position.entry_time),
                'total_pnl': self.trader.capital - self.trader.initial_capital,
                'win_rate': self.trader.get_performance_summary()['win_rate']
            })

        logger.info(f"Closed {len(closed)} intraday positions at EOD")

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
        if not self.offline and datetime.now().weekday() >= 5:
            logger.info("Weekend — not starting monitor")
            return

        self.running = True

        logger.info("="*60)
        logger.info("LIVE TRADING MONITOR STARTED")
        logger.info("="*60)
        intraday_names = [d.strategy_name for d in self.intraday_detectors]
        swing_names = [d.strategy_name for d in self.swing_detectors]
        logger.info(f"Intraday strategies: {', '.join(intraday_names)}")
        logger.info(f"Swing strategies: {', '.join(swing_names)}")
        logger.info(f"Stocks: {len(self.stocks)}")
        logger.info(f"Scan interval: {self.scan_interval}s ({self.scan_interval//60} min)")
        logger.info(f"Mode: {'OFFLINE' if self.offline else 'LIVE'}")
        logger.info("="*60)
        
        # Send startup message only during market hours
        if self.is_market_hours() or self.offline:
            self.telegram.send_startup_message()

        # Schedule tasks
        schedule.every(self.scan_interval).seconds.do(self.run_scan_cycle)
        schedule.every().day.at("15:20").do(self.close_all_positions_eod)
        schedule.every().day.at("15:35").do(self.send_daily_summary)
        schedule.every().day.at("15:36").do(self.stop)

        # Run initial scan
        self.run_scan_cycle()

        # Main loop
        try:
            while self.running:
                try:
                    schedule.run_pending()
                except Exception as e:
                    logger.error(f"Scheduled job error: {e}", exc_info=True)
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
    parser.add_argument('--strategy', type=str, default=None, help='Strategy to use (default: uses top 3 strategies)')
    parser.add_argument('--capital', type=float, default=100000, help='Initial capital')
    parser.add_argument('--interval', type=int, default=300, help='Scan interval in seconds (default 300 = 5 min)')
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
