"""
Zerodha Telegram Bot
====================
Control your data collection from Telegram!

Features:
- /status - Check system status
- /collect - Trigger data collection
- /stats - View database statistics
- /download - Get data file
- Automatic alerts on success/failure

Setup:
1. Create bot via @BotFather on Telegram
2. Get your bot token
3. Get your chat ID (message @userinfobot)
4. Set environment variables or config
"""

import os
import sys
import asyncio
import logging
from datetime import datetime
from pathlib import Path

# Telegram library
try:
    from telegram import Update, Bot
    from telegram.ext import Application, CommandHandler, ContextTypes
except ImportError:
    print("Installing python-telegram-bot...")
    os.system(f"{sys.executable} -m pip install python-telegram-bot")
    from telegram import Update, Bot
    from telegram.ext import Application, CommandHandler, ContextTypes

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Paths
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "data" / "zerodha_data.db"


class ZerodhaTelegramBot:
    """Telegram bot for controlling Zerodha data collection."""
    
    def __init__(self, bot_token: str, chat_id: str, 
                 zerodha_user_id: str = None, 
                 zerodha_password: str = None,
                 zerodha_totp_secret: str = None):
        """
        Initialize bot.
        
        Args:
            bot_token: Telegram bot token from @BotFather
            chat_id: Your Telegram chat ID
            zerodha_*: Zerodha credentials for auto-login
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.zerodha_user_id = zerodha_user_id
        self.zerodha_password = zerodha_password
        self.zerodha_totp_secret = zerodha_totp_secret
        
        self.bot = Bot(token=bot_token)
        self.app = None
    
    async def send_message(self, text: str, parse_mode: str = "HTML"):
        """Send a message to the configured chat."""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode
            )
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
    
    async def send_file(self, file_path: str, caption: str = None):
        """Send a file to the configured chat."""
        try:
            with open(file_path, 'rb') as f:
                await self.bot.send_document(
                    chat_id=self.chat_id,
                    document=f,
                    caption=caption
                )
        except Exception as e:
            logger.error(f"Failed to send file: {e}")
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        await update.message.reply_text(
            "🚀 <b>Zerodha Data Collector Bot</b>\n\n"
            "Commands:\n"
            "/status - System status\n"
            "/collect - Start data collection\n"
            "/stats - Database statistics\n"
            "/download [SYMBOL] - Download data\n"
            "/help - Show help",
            parse_mode="HTML"
        )
    
    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        status_text = "📊 <b>System Status</b>\n\n"
        
        # Check database
        if DB_PATH.exists():
            import sqlite3
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM ohlcv")
            total_records = cursor.fetchone()[0]
            
            cursor.execute("SELECT MAX(datetime) FROM ohlcv WHERE interval='minute'")
            last_update = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(DISTINCT symbol) FROM ohlcv")
            symbols = cursor.fetchone()[0]
            
            db_size = DB_PATH.stat().st_size / (1024 * 1024)
            
            conn.close()
            
            status_text += f"✅ Database: Online\n"
            status_text += f"📁 Size: {db_size:.2f} MB\n"
            status_text += f"📈 Records: {total_records:,}\n"
            status_text += f"🏷️ Symbols: {symbols}\n"
            status_text += f"🕐 Last Update: {last_update or 'Never'}\n"
        else:
            status_text += "❌ Database: Not found\n"
        
        # Check credentials
        if all([self.zerodha_user_id, self.zerodha_password, self.zerodha_totp_secret]):
            status_text += f"\n✅ Credentials: Configured ({self.zerodha_user_id})"
        else:
            status_text += "\n⚠️ Credentials: Not configured"
        
        await update.message.reply_text(status_text, parse_mode="HTML")
    
    async def cmd_collect(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /collect command."""
        await update.message.reply_text("🔄 Starting data collection...")
        
        try:
            # Auto-login
            from zerodha_auto_login import get_enctoken
            
            await update.message.reply_text("🔐 Logging into Zerodha...")
            
            enctoken = get_enctoken(
                self.zerodha_user_id,
                self.zerodha_password,
                self.zerodha_totp_secret
            )
            
            await update.message.reply_text("✅ Login successful! Collecting data...")
            
            # Collect data
            from daily_collector import DailyCollector
            
            collector = DailyCollector(enctoken)
            results = collector.collect_today(days=1)
            collector.close()
            
            # Report results
            msg = (
                f"✅ <b>Collection Complete!</b>\n\n"
                f"📈 Stocks: {len(results['success'])}\n"
                f"📊 New candles: {results['total_candles']:,}\n"
            )
            
            if results['failed']:
                msg += f"⚠️ Failed: {', '.join(results['failed'][:5])}"
            
            await update.message.reply_text(msg, parse_mode="HTML")
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
    
    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command."""
        if not DB_PATH.exists():
            await update.message.reply_text("❌ Database not found")
            return
        
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Get stats
        cursor.execute("SELECT COUNT(*) FROM ohlcv WHERE interval='minute'")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT symbol, COUNT(*) as cnt, MIN(datetime), MAX(datetime)
            FROM ohlcv WHERE interval='minute'
            GROUP BY symbol ORDER BY cnt DESC LIMIT 10
        """)
        top_symbols = cursor.fetchall()
        
        cursor.execute("""
            SELECT date, SUM(candles_added) FROM collection_log
            GROUP BY date ORDER BY date DESC LIMIT 5
        """)
        recent = cursor.fetchall()
        
        conn.close()
        
        msg = f"📊 <b>Database Statistics</b>\n\n"
        msg += f"Total Records: {total:,}\n\n"
        
        msg += "<b>Top Symbols:</b>\n"
        for sym, cnt, first, last in top_symbols[:5]:
            msg += f"  {sym}: {cnt:,} candles\n"
        
        if recent:
            msg += f"\n<b>Recent Collections:</b>\n"
            for date, candles in recent:
                msg += f"  {date}: +{candles:,}\n"
        
        await update.message.reply_text(msg, parse_mode="HTML")
    
    async def cmd_download(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /download command."""
        if not context.args:
            await update.message.reply_text(
                "Usage: /download SYMBOL\n"
                "Example: /download RELIANCE"
            )
            return
        
        symbol = context.args[0].upper()
        
        if not DB_PATH.exists():
            await update.message.reply_text("❌ Database not found")
            return
        
        await update.message.reply_text(f"📤 Exporting {symbol}...")
        
        try:
            from data_manager import DataManager
            
            dm = DataManager()
            df = dm.get_data(symbol)
            dm.close()
            
            if df.empty:
                await update.message.reply_text(f"❌ No data for {symbol}")
                return
            
            # Export to CSV
            export_path = BASE_DIR / "exports" / f"{symbol}_{datetime.now().strftime('%Y%m%d')}.csv"
            export_path.parent.mkdir(exist_ok=True)
            df.to_csv(export_path)
            
            await self.send_file(
                str(export_path),
                f"📊 {symbol} - {len(df):,} candles"
            )
            
            # Cleanup
            export_path.unlink()
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
    
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        help_text = """
<b>🤖 Zerodha Data Collector Bot</b>

<b>Commands:</b>
/status - Check system status
/collect - Start data collection (auto-login)
/stats - View database statistics
/download SYMBOL - Download data as CSV

<b>How it works:</b>
1. Bot automatically logs into Zerodha using your credentials
2. Fetches 1-minute data for all NIFTY 50 stocks
3. Stores in SQLite database
4. Sends you a summary

<b>Automation:</b>
Deploy on GitHub Actions for free daily collection!
        """
        await update.message.reply_text(help_text.strip(), parse_mode="HTML")
    
    def run(self):
        """Run the bot."""
        self.app = Application.builder().token(self.bot_token).build()
        
        # Add handlers
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("collect", self.cmd_collect))
        self.app.add_handler(CommandHandler("stats", self.cmd_stats))
        self.app.add_handler(CommandHandler("download", self.cmd_download))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        
        logger.info("Bot starting...")
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)


async def send_alert(bot_token: str, chat_id: str, message: str):
    """Send a one-time alert message."""
    bot = Bot(token=bot_token)
    await bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")


def load_config():
    """Load configuration from environment or file."""
    config = {
        'bot_token': os.environ.get('TELEGRAM_BOT_TOKEN'),
        'chat_id': os.environ.get('TELEGRAM_CHAT_ID'),
        'zerodha_user_id': os.environ.get('ZERODHA_USER_ID'),
        'zerodha_password': os.environ.get('ZERODHA_PASSWORD'),
        'zerodha_totp_secret': os.environ.get('ZERODHA_TOTP_SECRET'),
    }
    
    # Try loading from config file
    config_file = BASE_DIR / "secrets.py"
    if config_file.exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("secrets", config_file)
        secrets = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(secrets)
        
        for key in config:
            if not config[key]:
                config[key] = getattr(secrets, key.upper(), None)
    
    return config


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Zerodha Telegram Bot")
    parser.add_argument("--run", action="store_true", help="Run the bot")
    parser.add_argument("--alert", help="Send a one-time alert message")
    
    args = parser.parse_args()
    
    config = load_config()
    
    if args.alert:
        if not config['bot_token'] or not config['chat_id']:
            print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
            exit(1)
        asyncio.run(send_alert(config['bot_token'], config['chat_id'], args.alert))
    
    elif args.run:
        if not config['bot_token']:
            print("Missing TELEGRAM_BOT_TOKEN")
            exit(1)
        
        bot = ZerodhaTelegramBot(
            bot_token=config['bot_token'],
            chat_id=config['chat_id'],
            zerodha_user_id=config['zerodha_user_id'],
            zerodha_password=config['zerodha_password'],
            zerodha_totp_secret=config['zerodha_totp_secret']
        )
        bot.run()
    
    else:
        parser.print_help()
