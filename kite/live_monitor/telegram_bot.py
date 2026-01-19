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
import requests
from datetime import datetime
from typing import Dict, Optional
import json


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
        Send a text message.
        
        Args:
            message: Message text (supports HTML formatting)
            parse_mode: "HTML" or "Markdown"
            
        Returns:
            True if sent successfully
        """
        if not self.enabled:
            print(f"[TELEGRAM] {message}")
            return False
        
        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }
            response = requests.post(url, data=data, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"[!] Telegram error: {e}")
            return False
    
    def send_trade_alert(self, signal: Dict) -> bool:
        """
        Send a formatted trade alert.
        
        Args:
            signal: Dictionary with trade details
            
        Returns:
            True if sent successfully
        """
        direction = signal.get('direction', 'BUY')
        symbol = signal.get('symbol', 'UNKNOWN')
        
        # Emoji based on direction
        emoji = "[BUY]" if direction == "BUY" else "[SELL]"
        action = "BUY" if direction == "BUY" else "SELL/SHORT"
        
        message = f"""
{emoji} <b>TRADE ALERT - {action}</b> {emoji}

<b>Stock:</b> {symbol}
<b>Signal:</b> {direction}
<b>Strategy:</b> {signal.get('strategy', 'Fib 3-Wave')}

<b>Entry Price:</b> Rs {signal.get('entry_price', 0):.2f}
<b>Stop Loss:</b> Rs {signal.get('stop_loss', 0):.2f} ({signal.get('risk_pct', 0):.1f}% risk)
<b>Target:</b> Rs {signal.get('take_profit', 0):.2f} ({signal.get('reward_pct', 0):.1f}% reward)

<b>Risk:Reward:</b> 1:{signal.get('rr_ratio', 0):.1f}
<b>Quantity:</b> {signal.get('quantity', 0)} shares
<b>Position Size:</b> Rs {signal.get('position_value', 0):,.2f}

<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """.strip()
        
        return self.send_message(message)
    
    def send_exit_alert(self, trade: Dict) -> bool:
        """
        Send trade exit notification.
        
        Args:
            trade: Dictionary with trade exit details
            
        Returns:
            True if sent successfully
        """
        pnl = trade.get('pnl', 0)
        pnl_pct = trade.get('pnl_pct', 0)
        
        # Status based on profit/loss
        if pnl > 0:
            status = "[WIN] PROFIT"
        else:
            status = "[LOSS]"
        
        message = f"""
<b>TRADE CLOSED - {status}</b>

<b>Stock:</b> {trade.get('symbol', 'UNKNOWN')}
<b>Direction:</b> {trade.get('direction', 'BUY')}
<b>Exit Reason:</b> {trade.get('exit_reason', 'Unknown')}

<b>Entry:</b> Rs {trade.get('entry_price', 0):.2f}
<b>Exit:</b> Rs {trade.get('exit_price', 0):.2f}

<b>P&L:</b> Rs {pnl:+,.2f} ({pnl_pct:+.2f}%)
<b>Duration:</b> {trade.get('duration', 'N/A')}

<b>Running Total:</b> Rs {trade.get('total_pnl', 0):+,.2f}
<b>Win Rate:</b> {trade.get('win_rate', 0):.1f}%

<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """.strip()
        
        return self.send_message(message)
    
    def send_daily_summary(self, summary: Dict) -> bool:
        """
        Send end-of-day summary.
        
        Args:
            summary: Dictionary with daily performance
            
        Returns:
            True if sent successfully
        """
        message = f"""
<b>DAILY TRADING SUMMARY</b>

<b>Date:</b> {summary.get('date', datetime.now().strftime('%Y-%m-%d'))}

<b>Today's Performance:</b>
- Trades Taken: {summary.get('trades_today', 0)}
- Wins: {summary.get('wins', 0)} | Losses: {summary.get('losses', 0)}
- Day P&L: Rs {summary.get('day_pnl', 0):+,.2f}

<b>Overall Performance:</b>
- Total Trades: {summary.get('total_trades', 0)}
- Win Rate: {summary.get('win_rate', 0):.1f}%
- Total P&L: Rs {summary.get('total_pnl', 0):+,.2f}
- Sharpe Ratio: {summary.get('sharpe', 0):.2f}

<b>Open Positions:</b> {summary.get('open_positions', 0)}
<b>Capital:</b> Rs {summary.get('capital', 100000):,.2f}

Market closed. See you tomorrow!
        """.strip()
        
        return self.send_message(message)
    
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
                    print(f"[✓] Telegram connected: @{bot_name}")
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
