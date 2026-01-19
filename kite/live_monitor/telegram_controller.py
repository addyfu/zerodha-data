"""
Telegram Controller
===================
Control the trading bot via Telegram commands.
This allows you to manage the bot remotely without SSH.

Commands:
    /start - Start monitoring
    /stop - Stop monitoring
    /status - Get current status
    /positions - View open positions
    /performance - Get performance summary
    /token <token> - Update Zerodha enctoken
    /scan - Force a scan now
    /help - Show help
"""
import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

import requests
import time
import threading
import json
from datetime import datetime
from typing import Callable, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class TelegramController:
    """
    Telegram bot that accepts commands to control the trading monitor.
    """
    
    def __init__(self, bot_token: str, chat_id: str, monitor=None):
        """
        Initialize controller.
        
        Args:
            bot_token: Telegram bot token
            chat_id: Authorized chat ID (only responds to this)
            monitor: LiveMonitor instance to control
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.monitor = monitor
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.running = False
        self.last_update_id = 0
        
        # Command handlers
        self.commands: Dict[str, Callable] = {
            '/start': self.cmd_start,
            '/stop': self.cmd_stop,
            '/status': self.cmd_status,
            '/positions': self.cmd_positions,
            '/performance': self.cmd_performance,
            '/token': self.cmd_token,
            '/scan': self.cmd_scan,
            '/help': self.cmd_help,
            '/ping': self.cmd_ping,
        }
    
    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the authorized chat."""
        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode
            }
            response = requests.post(url, data=data, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Send message error: {e}")
            return False
    
    def get_updates(self) -> list:
        """Get new messages from Telegram."""
        try:
            url = f"{self.base_url}/getUpdates"
            params = {
                "offset": self.last_update_id + 1,
                "timeout": 30
            }
            response = requests.get(url, params=params, timeout=35)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    return data.get('result', [])
        except Exception as e:
            logger.error(f"Get updates error: {e}")
        
        return []
    
    def process_update(self, update: dict):
        """Process a single update."""
        try:
            message = update.get('message', {})
            chat_id = str(message.get('chat', {}).get('id', ''))
            text = message.get('text', '')
            
            # Only respond to authorized chat
            if chat_id != self.chat_id:
                logger.warning(f"Unauthorized chat: {chat_id}")
                return
            
            # Parse command
            parts = text.split()
            command = parts[0].lower() if parts else ''
            args = parts[1:] if len(parts) > 1 else []
            
            # Execute command
            if command in self.commands:
                self.commands[command](args)
            elif command.startswith('/'):
                self.send_message(f"Unknown command: {command}\nUse /help for available commands.")
                
        except Exception as e:
            logger.error(f"Process update error: {e}")
    
    def poll_loop(self):
        """Main polling loop for updates."""
        logger.info("Telegram controller started")
        
        while self.running:
            try:
                updates = self.get_updates()
                
                for update in updates:
                    self.last_update_id = update.get('update_id', self.last_update_id)
                    self.process_update(update)
                
            except Exception as e:
                logger.error(f"Poll loop error: {e}")
                time.sleep(5)
    
    def start(self):
        """Start the controller in a background thread."""
        if self.running:
            return
        
        self.running = True
        self._thread = threading.Thread(target=self.poll_loop, daemon=True)
        self._thread.start()
        
        self.send_message(
            "<b>Bot Controller Started</b>\n\n"
            "I'm now listening for commands.\n"
            "Use /help to see available commands."
        )
    
    def stop(self):
        """Stop the controller."""
        self.running = False
    
    # ==================== Command Handlers ====================
    
    def cmd_start(self, args):
        """Start monitoring."""
        if self.monitor:
            if not self.monitor.running:
                # Start in background thread
                threading.Thread(target=self.monitor.start, daemon=True).start()
                self.send_message("Monitoring STARTED")
            else:
                self.send_message("Monitor is already running")
        else:
            self.send_message("Monitor not initialized")
    
    def cmd_stop(self, args):
        """Stop monitoring."""
        if self.monitor:
            self.monitor.stop()
            self.send_message("Monitoring STOPPED")
        else:
            self.send_message("Monitor not initialized")
    
    def cmd_status(self, args):
        """Get current status."""
        if not self.monitor:
            self.send_message("Monitor not initialized")
            return
        
        status = "RUNNING" if self.monitor.running else "STOPPED"
        market = "OPEN" if self.monitor.is_market_hours() else "CLOSED"
        
        summary = self.monitor.trader.get_performance_summary()
        
        msg = f"""
<b>STATUS</b>

<b>Monitor:</b> {status}
<b>Market:</b> {market}
<b>Mode:</b> {'LIVE' if not self.monitor.offline else 'OFFLINE'}

<b>Capital:</b> Rs {summary.get('capital', 0):,.2f}
<b>Open Positions:</b> {summary.get('open_positions', 0)}
<b>Total Trades:</b> {summary.get('total_trades', 0)}
<b>Win Rate:</b> {summary.get('win_rate', 0):.1f}%

<b>Last Scan:</b> {datetime.now().strftime('%H:%M:%S')}
        """.strip()
        
        self.send_message(msg)
    
    def cmd_positions(self, args):
        """Show open positions."""
        if not self.monitor:
            self.send_message("Monitor not initialized")
            return
        
        positions = self.monitor.trader.get_open_positions()
        
        if not positions:
            self.send_message("No open positions")
            return
        
        msg = "<b>OPEN POSITIONS</b>\n\n"
        
        for pos in positions:
            msg += f"""
<b>{pos['symbol']}</b> ({pos['direction']})
Entry: Rs {pos['entry_price']:.2f}
SL: Rs {pos['stop_loss']:.2f}
TP: Rs {pos['take_profit']:.2f}
Qty: {pos['quantity']}
---
"""
        
        self.send_message(msg.strip())
    
    def cmd_performance(self, args):
        """Show performance summary."""
        if not self.monitor:
            self.send_message("Monitor not initialized")
            return
        
        summary = self.monitor.trader.get_performance_summary()
        
        msg = f"""
<b>PERFORMANCE SUMMARY</b>

<b>Capital:</b> Rs {summary.get('capital', 0):,.2f}
<b>Initial:</b> Rs {self.monitor.trader.initial_capital:,.2f}
<b>Return:</b> {summary.get('return_pct', 0):+.2f}%

<b>Total Trades:</b> {summary.get('total_trades', 0)}
<b>Wins:</b> {summary.get('wins', 0)}
<b>Losses:</b> {summary.get('losses', 0)}
<b>Win Rate:</b> {summary.get('win_rate', 0):.1f}%

<b>Total P&L:</b> Rs {summary.get('total_pnl', 0):+,.2f}
<b>Avg Win:</b> Rs {summary.get('avg_win', 0):,.2f}
<b>Avg Loss:</b> Rs {summary.get('avg_loss', 0):,.2f}
<b>Profit Factor:</b> {summary.get('profit_factor', 0):.2f}
        """.strip()
        
        self.send_message(msg)
    
    def cmd_token(self, args):
        """Update Zerodha enctoken."""
        if not args:
            self.send_message("Usage: /token <new_enctoken>")
            return
        
        new_token = args[0]
        
        # Update environment variable
        os.environ['ZERODHA_ENCTOKEN'] = new_token
        
        # Update fetcher if monitor exists
        if self.monitor and hasattr(self.monitor, 'fetcher'):
            self.monitor.fetcher.enctoken = new_token
        
        self.send_message("Token updated successfully!\nRestart monitoring for changes to take effect.")
    
    def cmd_scan(self, args):
        """Force a scan now."""
        if not self.monitor:
            self.send_message("Monitor not initialized")
            return
        
        self.send_message("Running scan...")
        
        try:
            signals = self.monitor.scan_for_signals()
            
            if signals:
                msg = f"Found {len(signals)} signal(s):\n\n"
                for s in signals:
                    msg += f"- {s.symbol}: {s.direction} @ Rs {s.entry_price:.2f}\n"
                self.send_message(msg)
            else:
                self.send_message("No signals found")
                
        except Exception as e:
            self.send_message(f"Scan error: {str(e)[:100]}")
    
    def cmd_ping(self, args):
        """Check if bot is alive."""
        self.send_message(f"Pong! Bot is alive.\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    def cmd_help(self, args):
        """Show help."""
        msg = """
<b>AVAILABLE COMMANDS</b>

/status - Get current status
/positions - View open positions
/performance - Get performance summary
/scan - Force a market scan
/token &lt;token&gt; - Update Zerodha token

/start - Start monitoring
/stop - Stop monitoring
/ping - Check if bot is alive
/help - Show this help

<i>Bot monitors NIFTY 50 stocks using Fib 3-Wave strategy</i>
        """.strip()
        
        self.send_message(msg)


def create_controlled_monitor():
    """Create a monitor with Telegram control."""
    from kite.live_monitor.monitor import LiveMonitor
    
    # Get credentials
    enctoken = os.environ.get('ZERODHA_ENCTOKEN', '')
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
    
    if not bot_token or not chat_id:
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required")
        return None
    
    # Create monitor
    monitor = LiveMonitor(
        enctoken=enctoken,
        telegram_token=bot_token,
        telegram_chat=chat_id,
        strategy='fib_3wave',
        capital=100000,
        offline=not bool(enctoken),
        scan_interval=60
    )
    
    # Create controller
    controller = TelegramController(bot_token, chat_id, monitor)
    
    return monitor, controller


if __name__ == '__main__':
    # Test the controller
    print("Starting Telegram-controlled trading bot...")
    
    result = create_controlled_monitor()
    
    if result:
        monitor, controller = result
        
        # Start controller (listens for commands)
        controller.start()
        
        print("Bot is running. Send /help to your Telegram bot.")
        print("Press Ctrl+C to stop.")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping...")
            controller.stop()
            if monitor.running:
                monitor.stop()
