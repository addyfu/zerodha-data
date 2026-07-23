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
import json

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
from kite.live_monitor.momentum_rotation import MomentumRotation
from kite.live_monitor.announcement_filter import AnnouncementFilter
from kite.live_monitor.entry_pipeline import EntryPipeline

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
    'TATASTEEL', 'TCS', 'TECHM', 'TITAN',  # TATAMOTORS removed: token dead post-2025 demerger
    'ULTRACEMCO', 'UPL', 'WIPRO'
]

# Wide swing-candidate universe (679 NSE stocks — kite/research/universe_lab.py's
# backtest pond). rsi_trend_confirmation/cci_divergence's expectation cards assume
# this universe's trade rates; scanning only NIFTY_50 was a backtest-live parity
# gap. Rotation and intraday strategies stay on NIFTY_50 (self.stocks) untouched.
WIDE_UNIVERSE_FILE = Path(__file__).parent / 'universe_symbols.txt'


def _load_wide_universe() -> List[str]:
    """Fail-soft: missing/empty file -> NIFTY_50 so swing scanning never dies."""
    try:
        text = WIDE_UNIVERSE_FILE.read_text()
    except OSError as e:
        logger.warning(f"{WIDE_UNIVERSE_FILE.name} not found ({e}) — "
                        f"swing universe falling back to NIFTY_50")
        return list(NIFTY_50)
    symbols = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not symbols:
        logger.warning(f"{WIDE_UNIVERSE_FILE.name} is empty — swing universe falling back to NIFTY_50")
        return list(NIFTY_50)
    return symbols


class LiveMonitor:
    """
    Main monitoring class that orchestrates all components.

    Two-phase approach for fast scanning:
    1. At startup/market open: fetch 60-day historical data for all stocks (slow, once)
    2. Every scan: fetch bulk quotes (fast), update cached data, run strategies
    """

    # July 2026 audit: fib_3wave cannot fire live (lookahead-dependent swing detection),
    # ema_21_55/vwap_pullback/elliott_wave3 failed honest walk-forward validation.
    # Only momo_rotation_63 (kite/research/honest_lab.py) survived — it runs separately below.
    INTRADAY_STRATEGIES = []
    SWING_STRATEGIES = []
    # Incubator: leak-free near-breakeven candidates paper-traded on a SEPARATE virtual book
    # (data/incubator_trades.db) to gather live execution data. Not expected to profit —
    # promotion requires passing honest_lab validation, not incubator P&L.
    INCUBATOR_STRATEGIES = ['choppiness_filter', 'cci_divergence', 'bb_mean_reversion', 'adx_filter']
    # Daily-bar candidates from the July 2026 honest retest (kite/research/retest_all.py):
    # leak-clean, beat B&H 2022-26 with lower DD, but flat pre-2020 — regime-dependent,
    # hence incubator not main book. Trade like the retest sim: own SL/TP, no trailing.
    SWING_CANDIDATES = ['rsi_trend_confirmation', 'cci_divergence']

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

        # Momentum rotation — the validated strategy (monthly, daily bars)
        self.rotation = MomentumRotation(capital=capital, max_positions=max_positions)

        # Red-flag announcement filter (July 2026 event study) — blocks new entries
        # in freshly-flagged stocks, alerts on held ones, fails open when feed is down
        self.ann_filter = AnnouncementFilter()

        # Single gate for ALL new positions: cutoff + pause + red-flag + open/alert
        self.entry = EntryPipeline(self.ann_filter, self.telegram, offline=offline)

        # Daily-bar swing candidates (incubator book, no trailing — parity with retest sim)
        self.swing_candidate_detectors = [
            SignalDetector(strategy_name=s, capital=capital,
                           risk_per_trade=0.02, min_rr_ratio=1.0,
                           max_position_pct=slot_size / capital)
            for s in self.SWING_CANDIDATES
        ]

        # Incubator — candidate strategies on their own virtual book
        self.incubator_detectors = [
            SignalDetector(strategy_name=s, capital=capital,
                           risk_per_trade=0.02, min_rr_ratio=1.5,
                           max_position_pct=slot_size / capital)
            for s in self.INCUBATOR_STRATEGIES
        ]
        self.incubator = PaperTrader(
            initial_capital=capital,
            max_positions=max_positions,
            db_path=str(Path(__file__).parent.parent.parent / 'data' / 'incubator_trades.db'),
            use_trailing_stop=True,
            trailing_stop_pct=0.02
        )

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

        # Wide swing-candidate universe (679 stocks) — backtest-parity pond for
        # swing_candidate_detectors only. Rotation/intraday keep using self.stocks.
        self.wide_universe = _load_wide_universe()
        logger.info(f"Wide swing universe: {len(self.wide_universe)} symbols loaded")

        # Historical data cache (loaded once, updated with quotes)
        self.data_cache: Dict[str, pd.DataFrame] = {}
        self.daily_data_cache: Dict[str, pd.DataFrame] = {}
        self.wide_daily_cache: Dict[str, pd.DataFrame] = {}
        self.swing_scanned_today = False
        self.history_loaded = False
        self.db = DBManager()
        self._paused_strategies: set = set()  # refreshed once per scan cycle

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
                if token:
                    # This exact phrase is what parity_monitor's P9 (login-loop
                    # detector) counts in monitor.log — keep them in sync.
                    logger.info("Login successful (auto-login)")
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

        # Load daily data for rotation (needs 200+ bars for regime SMA) and swing strategies.
        # Local DB only holds ~1 week of minute data, so daily history must come from the API
        # (or CSV cache in offline mode) — not from the DB resample.
        self.load_daily_data()

        # Wide swing-candidate universe (679 stocks) — backtest parity for
        # swing_candidate_detectors. Runs after the NIFTY_50 daily load so rotation/
        # intraday data is never blocked on this larger, slower fetch.
        self.load_wide_daily_data()

        self.history_loaded = True
        logger.info(f"Loaded 5-min data for {len(self.data_cache)}/{len(self.stocks)} stocks from DB")

    def load_daily_data(self):
        """Fetch ~400 daily bars per stock (rotation needs 200SMA regime + 63d momentum)."""
        logger.info(f"Loading daily data for {len(self.stocks)} stocks...")

        def fetch_one(symbol):
            return symbol, self.fetcher.get_historical_data(symbol, 'day', 400)

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(fetch_one, s) for s in self.stocks]
            for future in as_completed(futures):
                try:
                    symbol, df = future.result()
                    if df is not None and len(df) >= 250:
                        self.daily_data_cache[symbol] = df
                except Exception as e:
                    logger.warning(f"Daily fetch failed: {e}")

        logger.info(f"Daily data loaded for {len(self.daily_data_cache)}/{len(self.stocks)} stocks")

    def load_wide_daily_data(self):
        """Fetch ~400 daily bars per wide-universe symbol (swing-candidate backtest
        parity). max_workers=5 — rate-probe validated the API clean up to 8 req/s.

        Offline mode: OfflineDataFetcher only has NIFTY-50 CSVs, so most symbols
        will fail to load — fail-soft, scan_swing_candidates falls back to
        daily_data_cache when wide_daily_cache ends up (near-)empty.
        """
        start = time.time()
        logger.info(f"Loading wide daily data for {len(self.wide_universe)} symbols...")

        def fetch_one(symbol):
            return symbol, self.fetcher.get_historical_data(symbol, 'day', 400)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(fetch_one, s) for s in self.wide_universe]
            for future in as_completed(futures):
                try:
                    symbol, df = future.result()
                    if df is not None and len(df) >= 250:
                        self.wide_daily_cache[symbol] = df
                except Exception as e:
                    logger.warning(f"Wide daily fetch failed: {e}")

        elapsed = time.time() - start
        logger.info(f"Wide daily data loaded for {len(self.wide_daily_cache)}/{len(self.wide_universe)} "
                    f"stocks in {elapsed:.1f}s")

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

    def run_momentum_rotation(self):
        """Monthly momentum rotation on daily data (no-op unless a new month started)."""
        if not self.daily_data_cache:
            return
        held = [s for s, p in self.trader.positions.items() if p.trade_mode == 'ROTATION']
        blocked = {s for s in self.daily_data_cache if self.ann_filter.is_flagged(s)}
        if blocked:
            logger.info(f"ROTATION entry-blocked by ann-filter: {sorted(blocked)}")
        try:
            signals, exits = self.rotation.scan(self.daily_data_cache, held, blocked)
        except Exception as e:
            logger.error(f"Momentum rotation scan error: {e}", exc_info=True)
            return
        if not signals and not exits:
            return

        prices = {}
        quotes = self.fetcher.get_quote(list(set(exits + [s.symbol for s in signals])))
        if quotes:
            prices = {s: q['last_price'] for s, q in quotes.items()}

        for sym in exits:
            price = prices.get(sym) or float(self.daily_data_cache[sym].iloc[-1]['close'])
            position = self.trader.close_position(sym, price, ExitReason.STRATEGY_EXIT)
            if position:
                logger.info(f"ROTATION exit: {sym} @ Rs {price:.2f} (pnl {position.pnl:+.0f})")

        for signal in signals:
            live = prices.get(signal.symbol)
            if live:  # refresh entry to live price; keep sizing from daily close
                signal.entry_price = live
                signal.stop_loss = live * MomentumRotation.DISASTER_SL
                signal.take_profit = live * 2.0
            self.entry.try_enter(self.trader, signal, 'ROTATION')

    def scan_incubator(self):
        """Scan candidate strategies on 5-min data; trades go to the separate incubator book."""
        if not self.incubator_detectors or not self.data_cache:
            return
        seen = set()
        for symbol, df in self.data_cache.items():
            if df is None or len(df) < 50:
                continue
            for detector in self.incubator_detectors:
                try:
                    signal = detector.detect_signal(symbol, df)
                    if not signal:
                        continue
                    key = (symbol, signal.direction)
                    if key in seen:
                        continue
                    seen.add(key)
                    signal.trade_mode = "INTRADAY"
                    self.entry.try_enter(self.incubator, signal, 'INCUBATOR')
                except Exception as e:
                    logger.error(f"Incubator scan error {symbol}/{detector.strategy_name}: {e}", exc_info=True)

    def scan_swing_candidates(self):
        """Daily scan of swing candidates on daily bars -> incubator book.

        trade_mode ROTATION so no trailing stop interferes: exits are the
        strategy's own SL/TP (checked by check_exits) or an opposite signal here.

        Scans the wide 679-stock universe (backtest-parity pond the cards were
        validated on), falling back to the NIFTY_50 daily_data_cache if the wide
        fetch came up empty (e.g. offline mode). Each symbol must also clear the
        same liquidity gate kite/research/universe_lab.py's retest applied — 60d
        median turnover > 2e7 and last close > 20 — otherwise the live scan would
        trade illiquid names the backtest excluded.
        """
        if not self.swing_candidate_detectors:
            return
        universe = self.wide_daily_cache or self.daily_data_cache
        if not universe:
            return
        for symbol, df in universe.items():
            if df is None or len(df) < 50:
                continue
            turnover_med = (df['close'] * df['volume']).rolling(60).median().iloc[-1]
            last_close = float(df['close'].iloc[-1])
            if pd.isna(turnover_med) or turnover_med <= 2e7 or last_close <= 20:
                continue
            for detector in self.swing_candidate_detectors:
                try:
                    signal = detector.detect_signal(symbol, df)
                    if not signal:
                        continue
                    held = self.incubator.positions.get(symbol)
                    if signal.direction == 'SELL':
                        if held and held.direction == 'BUY':
                            price = float(df.iloc[-1]['close'])
                            self.incubator.close_position(symbol, price, ExitReason.STRATEGY_EXIT)
                            logger.info(f"CANDIDATE exit [{detector.strategy_name}]: {symbol}")
                        continue
                    if held:
                        continue
                    signal.trade_mode = "ROTATION"
                    self.entry.try_enter(self.incubator, signal, 'CANDIDATE')
                except Exception as e:
                    logger.error(f"Candidate scan error {symbol}/{detector.strategy_name}: {e}", exc_info=True)

    def check_results_reactions(self):
        """Results-miss gate (docs/superpowers/specs/2026-07-22-results-miss-gate-design.md):
        for each results-family announcement ann_filter.refresh() picked up in
        the last ~2 trading days, test whether the symbol's latest daily bar
        reacted < -2% vs the NIFTY-47 EW same-day move; if so, flag it via
        ann_filter.flag_results_miss() so EntryPipeline blocks new entries in
        it for ~20 trading days.

        Guarded on both caches being loaded; fail-soft (any error just skips
        this cycle, never blocks the rest of the swing scan).
        """
        if not self.daily_data_cache:
            return
        universe = self.wide_daily_cache or self.daily_data_cache
        if not universe:
            return
        candidates = getattr(self.ann_filter, 'results_announcements', None)
        if not candidates:
            return
        try:
            moves = []
            for sym in self.stocks:
                df = self.daily_data_cache.get(sym)
                if df is None or len(df) < 2:
                    continue
                prev_close = float(df['close'].iloc[-2])
                close = float(df['close'].iloc[-1])
                if prev_close > 0:
                    moves.append(close / prev_close - 1.0)
            if not moves:
                return
            nifty47_ew_move = sum(moves) / len(moves)

            for symbol in candidates:
                df = universe.get(symbol)
                if df is None or len(df) < 2:
                    continue
                prev_close = float(df['close'].iloc[-2])
                close = float(df['close'].iloc[-1])
                if prev_close <= 0:
                    continue
                reaction = (close / prev_close - 1.0) - nifty47_ew_move
                if reaction < -0.02:
                    self.ann_filter.flag_results_miss(symbol)
        except Exception as e:
            logger.warning(f"check_results_reactions failed (fail-soft, skipping): {e}")

    def _alert_flagged_holdings(self):
        """Telegram warning (no auto-exit) for held positions with fresh red flags."""
        held = list(self.trader.positions) + list(self.incubator.positions)
        for sym, reason in self.ann_filter.check_holdings(held):
            logger.warning(f"HOLDING RED FLAG: {sym} — {reason}")
            self.telegram.send_message(f"⚠ [FLAG] holding {sym}: {reason} — review, no auto-exit")

    def _send_morning_heartbeat(self):
        """Daily pipeline-health ping — proves auth/data/scan worked even on no-trade days."""
        try:
            rotation_held = [s for s, p in self.trader.positions.items()
                             if p.trade_mode == 'ROTATION']
            self.telegram.send_message(
                f"[HEARTBEAT] Monitor alive {datetime.now().strftime('%d-%b %H:%M')}\n"
                f"Daily data: {len(self.daily_data_cache)}/{len(self.stocks)} stocks\n"
                f"Swing universe: {len(self.wide_daily_cache)}/{len(self.wide_universe)} loaded\n"
                f"5-min data: {len(self.data_cache)}/{len(self.stocks)} stocks\n"
                f"Rotation: last rebalance {self.rotation.state.get('last_rebalance') or 'never'} "
                f"| holding: {', '.join(rotation_held) or 'cash'}\n"
                f"Capital: Rs {self.trader.capital:,.0f}\n"
                f"Incubator: {len(self.incubator.positions)} open | "
                f"Rs {self.incubator.capital:,.0f} | "
                f"{len(self.INCUBATOR_STRATEGIES)} candidates\n"
                f"{self.ann_filter.status_line()}")
        except Exception as e:
            logger.warning(f"Heartbeat send failed: {e}")

    def check_open_positions(self):
        """Check open positions for SL/TP hits (main book + incubator book)."""
        if not self.trader.positions and not self.incubator.positions:
            return

        # Get current prices — try quote API first, fall back to cached candle close
        symbols = list(set(self.trader.positions) | set(self.incubator.positions))
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

        # Incubator exits (own book, log-only alerts)
        for position in self.incubator.check_exits(current_prices):
            reason = getattr(position.exit_reason, 'value', position.exit_reason)
            logger.info(f"INCUBATOR exit [{position.strategy}]: {position.symbol} "
                        f"{reason} pnl {position.pnl:+.0f}")

        # Check exits
        closed = self.trader.check_exits(current_prices)
        
        for position in closed:
            # Send exit alert (compact '[MAIN] EXIT ... | day P&L: ...' style)
            self.telegram.send_exit_alert({
                'source': 'MAIN',
                'symbol': position.symbol,
                'direction': position.direction,
                'entry_price': position.entry_price,
                'exit_price': position.exit_price,
                'exit_reason': position.exit_reason,
                'pnl': position.pnl,
                'pnl_pct': position.pnl_pct,
                'duration': str(position.exit_time - position.entry_time),
                'day_pnl': self.trader.get_daily_summary().get('day_pnl', 0)
            })
    
    def process_signals(self, signals: List[TradeSignal]):
        """Route detected signals through the entry pipeline (main book)."""
        for signal in signals:
            position = self.entry.try_enter(self.trader, signal, 'MAIN', alert=False)
            if position:
                self.telegram.send_trade_alert(signal.to_dict())
    
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

            # Refresh the entry pipeline's paused-strategy cache (entries only)
            self.entry.reload_paused()

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

            # Incubator candidates (separate virtual book)
            self.scan_incubator()

            # Swing scan — once per day at market open
            now = datetime.now()
            if not self.swing_scanned_today and now.time() >= dtime(9, 25):
                # Daily load can fail if the token was stale at startup — retry here
                # and hold the once-per-day gate open until it succeeds. The WIDE
                # load gets the same retry (2026-07-23: its absence left the 679
                # swing universe silently empty on first live morning).
                if not self.daily_data_cache:
                    self.load_daily_data()
                    if not self.daily_data_cache:
                        logger.warning("Daily data still unavailable — will retry next cycle")
                        return
                if not self.wide_daily_cache:
                    self.load_wide_daily_data()
                    if not self.wide_daily_cache:
                        logger.warning("Wide daily data still unavailable — swing scan "
                                       "will fall back to NIFTY_50 this cycle")
                self.ann_filter.refresh()
                self.check_results_reactions()
                self._alert_flagged_holdings()
                swing_signals = self.scan_for_swing_signals()
                logger.info(f"Swing scan: {len(swing_signals)} signal(s) found")
                if swing_signals:
                    self.process_signals(swing_signals)
                self.run_momentum_rotation()
                self.scan_swing_candidates()
                self._send_morning_heartbeat()
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
        if not self.trader.positions and not self.incubator.positions:
            logger.info("No open positions to close at EOD")
            return

        logger.info("=" * 60)
        logger.info("END OF DAY - CLOSING INTRADAY POSITIONS")
        logger.info("=" * 60)

        # Get current prices — quote API or cached candle
        symbols = list(set(self.trader.positions) | set(self.incubator.positions))
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

        closed = self.trader.close_eod_positions(current_prices)
        inc_closed = self.incubator.close_eod_positions(current_prices)
        if inc_closed:
            logger.info(f"INCUBATOR: closed {len(inc_closed)} positions at EOD "
                        f"(day pnl {sum(p.pnl for p in inc_closed):+.0f})")

        for position in closed:
            self.telegram.send_exit_alert({
                'source': 'MAIN',
                'symbol': position.symbol,
                'direction': position.direction,
                'entry_price': position.entry_price,
                'exit_price': position.exit_price,
                'exit_reason': position.exit_reason,  # already ExitReason.END_OF_DAY.value
                'pnl': position.pnl,
                'pnl_pct': position.pnl_pct,
                'duration': str(position.exit_time - position.entry_time),
                'day_pnl': self.trader.get_daily_summary().get('day_pnl', 0)
            })

        logger.info(f"Closed {len(closed)} intraday positions at EOD")

    def _unrealized_pnl(self, trader: PaperTrader, current_prices: Dict[str, float]) -> float:
        """Sum of mark-to-market P&L across a book's still-open positions."""
        total = 0.0
        for pos in trader.positions.values():
            price = current_prices.get(pos.symbol)
            if price is None:
                continue
            if pos.direction == 'BUY':
                total += (price - pos.entry_price) * pos.quantity
            else:
                total += (pos.entry_price - price) * pos.quantity
        return total

    def _book_summary(self, label: str, trader: PaperTrader,
                       current_prices: Dict[str, float]) -> Dict:
        """Build one book's slice of the Telegram daily-summary dict — today's
        realized P&L, closed-trade count with exit-reason breakdown, open
        positions + unrealized P&L, and capital. See PaperTrader.get_daily_summary
        / get_todays_exit_breakdown / get_performance_summary for the sources."""
        daily = trader.get_daily_summary()
        perf = trader.get_performance_summary()
        return {
            'label': label,
            'day_pnl': daily.get('day_pnl', 0),
            'closed_count': daily.get('trades_today', 0),
            'exit_breakdown': trader.get_todays_exit_breakdown(),
            'open_positions': perf.get('open_positions', len(trader.positions)),
            'unrealized_pnl': self._unrealized_pnl(trader, current_prices),
            'capital': perf.get('capital', trader.capital),
        }

    def send_daily_summary(self):
        """Send end-of-day summary covering BOTH books (main + incubator)."""
        symbols = list(set(self.trader.positions) | set(self.incubator.positions))
        current_prices: Dict[str, float] = {}
        if symbols:
            try:
                quotes = self.fetcher.get_quote(symbols)
            except Exception as e:
                logger.warning(f"Daily summary quote fetch failed: {e}")
                quotes = {}
            if quotes:
                current_prices = {s: q['last_price'] for s, q in quotes.items()}
            # Fall back to cached candle close for any symbol the quote missed
            for s in symbols:
                if s not in current_prices and s in self.data_cache and len(self.data_cache[s]) > 0:
                    current_prices[s] = float(self.data_cache[s].iloc[-1]['close'])

        main_summary = self._book_summary('MAIN', self.trader, current_prices)
        incubator_summary = self._book_summary('INCUBATOR', self.incubator, current_prices)

        self.telegram.send_daily_summary({
            'date': datetime.now().strftime('%Y-%m-%d'),
            'books': [main_summary, incubator_summary],
            'combined_day_pnl': main_summary['day_pnl'] + incubator_summary['day_pnl'],
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
