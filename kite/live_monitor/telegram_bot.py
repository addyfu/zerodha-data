"""
Telegram Bot for Trade Alerts
=============================
Sends real-time trading signals to your Telegram.

Setup:
1. Create a bot via @BotFather on Telegram
2. Get your bot token
3. Get your chat_id by messaging @userinfobot
4. Set the values in config below or via environment variables
"""
import os
import time
import logging
import requests
from datetime import datetime
from typing import Dict, Optional
import json

logger = logging.getLogger(__name__)

# Canonical exit-reason display order/labels for the daily-summary breakdown,
# e.g. "4 TP / 7 trail / 3 EOD". Any exit_reason not in this map still shows
# (verbatim) so a new ExitReason value never silently disappears.
_EXIT_REASON_ORDER = ['take_profit', 'stop_loss', 'trailing_stop', 'end_of_day',
                      'strategy_exit', 'manual']
_EXIT_REASON_LABELS = {
    'take_profit': 'TP',
    'stop_loss': 'SL',
    'trailing_stop': 'trail',
    'end_of_day': 'EOD',
    'strategy_exit': 'strat',
    'manual': 'manual',
}


class TelegramBot:
    """Send trading alerts via Telegram."""

    def __init__(self, bot_token: str = None, chat_id: str = None):
        """
        Initialize Telegram bot.
        
        Args:
            bot_token: Telegram bot token from @BotFather
            chat_id: Your Telegram chat ID
        """
        self.bot_token = bot_token or os.environ.get('TELEGRAM_BOT_TOKEN', '')
        self.chat_id = chat_id or os.environ.get('TELEGRAM_CHAT_ID', '')
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.enabled = bool(self.bot_token and self.chat_id)
        
        if not self.enabled:
            print("[!] Telegram not configured. Alerts will be printed to console only.")
    
    def send_message(self, message: str, parse_mode: str = "HTML") -> bool:
        """
        Send a text message, with one automatic retry.

        Retries exactly once, after a 3s pause, when the first attempt hits a
        network exception (timeout, connection error, ...) or a 5xx response —
        never on 4xx (bad token/chat_id/payload won't fix itself on retry).
        If both attempts fail, the message is dropped and a warning is logged
        with its first 80 chars so silent drops are at least visible in logs.

        Args:
            message: Message text (supports HTML formatting)
            parse_mode: "HTML" or "Markdown"

        Returns:
            True if sent successfully
        """
        if not self.enabled:
            print(f"[TELEGRAM] {message}")
            return False

        url = f"{self.base_url}/sendMessage"
        data = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }

        last_error = None
        for attempt in range(2):  # first try + one retry
            response = None
            try:
                response = requests.post(url, data=data, timeout=10)
            except requests.exceptions.RequestException as e:
                last_error = str(e)

            if response is not None and response.status_code == 200:
                return True

            retryable = response is None or response.status_code >= 500
            if response is not None:
                last_error = f"HTTP {response.status_code}"

            if attempt == 0 and retryable:
                time.sleep(3)
                continue
            break

        logger.warning(f"Telegram send failed ({last_error}) — message lost: {message[:80]!r}")
        return False
    
    @staticmethod
    def _esc(value) -> str:
        """Escape HTML special chars so parse_mode=HTML never chokes on a
        symbol/strategy/exit-reason string that happens to contain <, > or &."""
        text = str(value)
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    def send_trade_alert(self, signal: Dict) -> bool:
        """
        Compact main-book entry alert, consistent with EntryPipeline's own
        '[INCUBATOR]/[CANDIDATE]/[ROTATION]' entry lines (entry_pipeline.py) —
        this is the '[MAIN]' counterpart. Sent by monitor.py's process_signals,
        which enters main-book positions with alert=False on the pipeline so
        this is the only alert for a main-book entry (no double-send).

        Example: '[MAIN] momo_rotation_63: BUY INDUSINDBK x18 @ 1055.00 |
                  SL 897.00 | TP 2110.00'

        Args:
            signal: Dictionary with trade details (TradeSignal.to_dict())

        Returns:
            True if sent successfully
        """
        source = self._esc(signal.get('source', 'MAIN'))
        strategy = self._esc(signal.get('strategy', 'unknown'))
        direction = signal.get('direction', 'BUY')
        symbol = self._esc(signal.get('symbol', 'UNKNOWN'))
        quantity = signal.get('quantity', 0)
        entry_price = signal.get('entry_price', 0) or 0
        stop_loss = signal.get('stop_loss', 0) or 0
        take_profit = signal.get('take_profit', 0) or 0

        message = (f"[{source}] {strategy}: {direction} {symbol} x{quantity} "
                   f"@ {entry_price:.2f} | SL {stop_loss:.2f} | TP {take_profit:.2f}")

        return self.send_message(message)

    def send_exit_alert(self, trade: Dict) -> bool:
        """
        Compact exit alert for a closed main-book position.

        Example: '[MAIN] EXIT INDUSINDBK @ 1057.60 +46.00 (trailing_stop) |
                   day P&L: Rs +120.00'

        Args:
            trade: Dictionary with trade exit details (symbol, exit_price, pnl,
                   exit_reason, day_pnl, ...)

        Returns:
            True if sent successfully
        """
        source = self._esc(trade.get('source', 'MAIN'))
        symbol = self._esc(trade.get('symbol', 'UNKNOWN'))
        exit_price = trade.get('exit_price', 0) or 0
        pnl = trade.get('pnl', 0) or 0
        reason = self._esc(trade.get('exit_reason', 'unknown'))
        day_pnl = trade.get('day_pnl', 0) or 0

        message = (f"[{source}] EXIT {symbol} @ {exit_price:.2f} {pnl:+,.2f} "
                   f"({reason}) | day P&L: Rs {day_pnl:+,.2f}")

        return self.send_message(message)
    
    @classmethod
    def _format_exit_breakdown(cls, breakdown: Dict[str, int]) -> str:
        """{'take_profit': 4, 'trailing_stop': 7} -> '4 TP / 7 trail'."""
        if not breakdown:
            return ""
        parts = []
        seen = set()
        for reason in _EXIT_REASON_ORDER:
            count = breakdown.get(reason, 0)
            if count:
                parts.append(f"{count} {_EXIT_REASON_LABELS[reason]}")
                seen.add(reason)
        for reason, count in breakdown.items():
            if reason not in seen and count:
                parts.append(f"{count} {cls._esc(reason)}")
        return " / ".join(parts)

    def _format_book_line(self, book: Dict) -> str:
        """One book's line in the daily summary: P&L, closed-trade breakdown,
        open positions + unrealized, capital."""
        label = self._esc(book.get('label', 'BOOK'))
        day_pnl = book.get('day_pnl', 0) or 0
        closed = book.get('closed_count', 0) or 0
        breakdown = self._format_exit_breakdown(book.get('exit_breakdown') or {})
        open_positions = book.get('open_positions', 0) or 0
        unrealized = book.get('unrealized_pnl', 0) or 0
        capital = book.get('capital', 0) or 0

        closed_part = f"{closed} ({breakdown})" if breakdown else str(closed)

        return (f"<b>[{label}]</b> Day P&L: Rs {day_pnl:+,.2f} | "
                f"Closed: {closed_part} | "
                f"Open: {open_positions} (unrealized Rs {unrealized:+,.2f}) | "
                f"Capital: Rs {capital:,.2f}")

    def send_daily_summary(self, summary: Dict) -> bool:
        """
        Send end-of-day summary covering every book.

        New shape (monitor.py, both the main and incubator books):
            {'date': 'YYYY-MM-DD',
             'books': [{'label': 'MAIN', 'day_pnl': ..., 'closed_count': ...,
                        'exit_breakdown': {'take_profit': 4, 'trailing_stop': 7},
                        'open_positions': ..., 'unrealized_pnl': ..., 'capital': ...},
                       {'label': 'INCUBATOR', ...}],
             'combined_day_pnl': ...}

        Legacy flat shape (single implicit book — e.g. github_scanner.py's older
        order-book summary) is still accepted and rendered as one book, so
        other callers don't break.

        Args:
            summary: Dictionary with daily performance (see above)

        Returns:
            True if sent successfully
        """
        date = summary.get('date', datetime.now().strftime('%Y-%m-%d'))
        books = summary.get('books')
        if not books:
            books = [{
                'label': summary.get('label', 'MAIN'),
                'day_pnl': summary.get('day_pnl', 0),
                'closed_count': summary.get('trades_today', summary.get('total_trades', 0)),
                'exit_breakdown': summary.get('exit_breakdown', {}),
                'open_positions': summary.get('open_positions', 0),
                'unrealized_pnl': summary.get('unrealized_pnl', 0),
                'capital': summary.get('capital', 0),
            }]
        combined_day_pnl = summary.get('combined_day_pnl')
        if combined_day_pnl is None:
            combined_day_pnl = sum(b.get('day_pnl', 0) or 0 for b in books)

        lines = [f"<b>DAILY SUMMARY</b> — {self._esc(date)}"]
        for book in books:
            lines.append("")
            lines.append(self._format_book_line(book))
        lines.append("")
        lines.append(f"<b>Combined day P&L: Rs {combined_day_pnl:+,.2f}</b>")

        return self.send_message("\n".join(lines))
    
    def send_startup_message(self, config: Dict = None) -> bool:
        """Send bot startup notification."""
        config = config or {}
        
        message = f"""
<b>TRADING BOT STARTED</b>

<b>Strategy:</b> {config.get('strategy', 'Fib 3-Wave')}
<b>Stocks:</b> NIFTY 50
<b>Capital:</b> Rs {config.get('capital', 100000):,.2f}
<b>Risk/Trade:</b> {config.get('risk_pct', 2)}%

<b>Started:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Bot is now monitoring the market for trading signals.
You will receive alerts when patterns are detected.

<i>Note: This is paper trading mode.</i>
        """.strip()
        
        return self.send_message(message)
    
    def send_position_opened(self, position: Dict) -> bool:
        """
        Send position opened notification.
        
        Args:
            position: Dictionary with position details
            
        Returns:
            True if sent successfully
        """
        direction = position.get('direction', 'BUY')
        symbol = position.get('symbol', 'UNKNOWN')
        
        emoji = "[LONG]" if direction == "BUY" else "[SHORT]"
        
        message = f"""
{emoji} <b>POSITION OPENED</b> {emoji}

<b>Stock:</b> {symbol}
<b>Direction:</b> {direction}
<b>Strategy:</b> {position.get('strategy', 'Fib 3-Wave')}

<b>Entry Price:</b> Rs {position.get('entry_price', 0):.2f}
<b>Quantity:</b> {position.get('quantity', 0)} shares
<b>Position Value:</b> Rs {position.get('entry_price', 0) * position.get('quantity', 0):,.2f}

<b>Stop Loss:</b> Rs {position.get('stop_loss', 0):.2f}
<b>Take Profit:</b> Rs {position.get('take_profit', 0):.2f}
<b>Trailing Stop:</b> {'Enabled' if position.get('trailing_stop') else 'Disabled'}

<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

<i>Order Book Updated</i>
        """.strip()
        
        return self.send_message(message)
    
    def send_status_update(self, summary: Dict) -> bool:
        """
        Send periodic status update.
        
        Args:
            summary: Dictionary with current status
            
        Returns:
            True if sent successfully
        """
        message = f"""
<b>STATUS UPDATE</b>

<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

<b>Account:</b>
- Capital: Rs {summary.get('current_capital', 100000):,.2f}
- Total P&L: Rs {summary.get('total_pnl', 0):+,.2f} ({summary.get('return_pct', 0):+.2f}%)
- Unrealized P&L: Rs {summary.get('unrealized_pnl', 0):+,.2f}

<b>Performance:</b>
- Total Trades: {summary.get('total_trades', 0)}
- Win Rate: {summary.get('win_rate', 0):.1f}%
- Profit Factor: {summary.get('profit_factor', 0):.2f}
- Max Drawdown: {summary.get('max_drawdown', 0):.2f}%

<b>Open Positions ({summary.get('open_positions', 0)}):</b>
{summary.get('positions_detail', 'None')}
        """.strip()
        
        return self.send_message(message)
    
    def send_order_book_update(self, action: str, details: Dict) -> bool:
        """
        Send order book update notification.
        
        Args:
            action: Action type ('opened', 'closed', 'updated')
            details: Dictionary with action details
            
        Returns:
            True if sent successfully
        """
        if action == "opened":
            return self.send_position_opened(details)
        elif action == "closed":
            return self.send_exit_alert(details)
        else:
            # Generic update
            message = f"""
<b>ORDER BOOK UPDATE</b>

<b>Action:</b> {action.upper()}
<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

{json.dumps(details, indent=2)}
            """.strip()
            return self.send_message(message)
    
    def send_error_alert(self, error: str, context: str = "") -> bool:
        """
        Send error notification.
        
        Args:
            error: Error message
            context: Additional context
            
        Returns:
            True if sent successfully
        """
        message = f"""
<b>[ERROR] TRADING BOT ERROR</b>

<b>Error:</b> {error}
<b>Context:</b> {context or 'N/A'}
<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Please check the logs for more details.
        """.strip()
        
        return self.send_message(message)
    
    def test_connection(self) -> bool:
        """Test if Telegram connection works."""
        if not self.enabled:
            return False
        
        try:
            url = f"{self.base_url}/getMe"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    bot_name = data['result'].get('username', 'Unknown')
                    print(f"[OK] Telegram connected: @{bot_name}")
                    return True
        except Exception as e:
            print(f"[!] Telegram test failed: {e}")
        
        return False


# Singleton instance
_bot_instance = None

def get_telegram_bot(bot_token: str = None, chat_id: str = None) -> TelegramBot:
    """Get or create Telegram bot instance."""
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = TelegramBot(bot_token, chat_id)
    return _bot_instance


if __name__ == '__main__':
    # Test the bot
    print("Testing Telegram Bot...")
    print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables")
    print("Or pass them directly to TelegramBot()")
    
    bot = TelegramBot()
    if bot.test_connection():
        bot.send_startup_message()
    else:
        print("Telegram not configured. Running in console-only mode.")
