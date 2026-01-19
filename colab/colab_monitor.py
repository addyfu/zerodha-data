"""
Google Colab Trading Monitor
============================
Copy this entire code to a Google Colab notebook cell and run it.

Setup:
1. Go to https://colab.research.google.com/
2. Create new notebook
3. Copy this code into a cell
4. Update the credentials below
5. Run the cell

Anti-Disconnect: Run this in browser console (F12):
    function KeepAlive() { document.querySelector("colab-connect-button").click(); }
    setInterval(KeepAlive, 60000);
"""

# ==================== CONFIGURATION ====================
# Update these with your credentials!

ZERODHA_ENCTOKEN = ""  # Get from kite.zerodha.com cookies
TELEGRAM_BOT_TOKEN = ""  # Get from @BotFather
TELEGRAM_CHAT_ID = ""  # Get from @userinfobot

INITIAL_CAPITAL = 100000  # Rs 1,00,000
SCAN_INTERVAL_MINUTES = 5  # Scan every 5 minutes

# ==================== INSTALL DEPENDENCIES ====================
import subprocess
subprocess.run(['pip', 'install', 'pandas', 'numpy', 'requests', '-q'])

# ==================== IMPORTS ====================
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta, time as dtime
import time
from typing import Dict, List, Optional
from enum import Enum

# ==================== TELEGRAM BOT ====================
class TelegramBot:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.enabled = bool(token and chat_id)
    
    def send(self, message):
        if not self.enabled:
            print(f"[TELEGRAM] {message}")
            return False
        try:
            url = f"{self.base_url}/sendMessage"
            data = {"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"}
            response = requests.post(url, data=data, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"Telegram error: {e}")
            return False
    
    def send_signal(self, signal):
        direction_text = "[BUY]" if signal['direction'] == 'BUY' else "[SELL]"
        msg = f"""
<b>{direction_text} TRADE ALERT</b>

<b>Stock:</b> {signal['symbol']}
<b>Direction:</b> {signal['direction']}

<b>Entry:</b> Rs {signal['entry_price']:.2f}
<b>Stop Loss:</b> Rs {signal['stop_loss']:.2f} ({signal['risk_pct']:.1f}% risk)
<b>Target:</b> Rs {signal['take_profit']:.2f} ({signal['reward_pct']:.1f}% reward)

<b>R:R Ratio:</b> 1:{signal['rr_ratio']:.1f}
<b>Quantity:</b> {signal['quantity']} shares
<b>Position Size:</b> Rs {signal['position_value']:,.2f}

<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """.strip()
        return self.send(msg)

# ==================== DATA FETCHER ====================
class DataFetcher:
    BASE_URL = "https://kite.zerodha.com/orca"
    INSTRUMENTS_URL = "https://api.kite.trade/instruments"
    
    def __init__(self, enctoken):
        self.enctoken = enctoken
        self.instruments = {}
        self._load_instruments()
    
    def _get_headers(self):
        return {
            "Authorization": f"enctoken {self.enctoken}",
            "User-Agent": "Mozilla/5.0"
        }
    
    def _load_instruments(self):
        try:
            response = requests.get(self.INSTRUMENTS_URL, timeout=30)
            if response.status_code == 200:
                for line in response.text.strip().split('\n')[1:]:
                    parts = line.split(',')
                    if len(parts) >= 3 and parts[2] == 'NSE':
                        self.instruments[parts[1]] = int(parts[0])
                print(f"Loaded {len(self.instruments)} instruments")
        except Exception as e:
            print(f"Failed to load instruments: {e}")
    
    def get_historical(self, symbol, days=60):
        if symbol not in self.instruments:
            return None
        try:
            token = self.instruments[symbol]
            to_date = datetime.now()
            from_date = to_date - timedelta(days=days)
            
            url = f"{self.BASE_URL}/instruments/historical/{token}/day"
            params = {
                "from": from_date.strftime("%Y-%m-%d"),
                "to": to_date.strftime("%Y-%m-%d"),
                "oi": 1
            }
            
            response = requests.get(url, headers=self._get_headers(), params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success' and data.get('data', {}).get('candles'):
                    candles = data['data']['candles']
                    df = pd.DataFrame(candles, columns=['datetime', 'open', 'high', 'low', 'close', 'volume', 'oi'])
                    df['datetime'] = pd.to_datetime(df['datetime'])
                    df.set_index('datetime', inplace=True)
                    return df
        except:
            pass
        return None

# ==================== FIB 3-WAVE STRATEGY ====================
class Fib3WaveStrategy:
    def __init__(self):
        self.min_wave_atr = 2.0
        self.fib_entry = 0.5
        self.fib_stop = 0.236
        self.fib_target = 1.618
        self.max_retracement = 0.618
        self.atr_period = 14
    
    def calculate_atr(self, df, period=14):
        high, low, close = df['high'], df['low'], df['close']
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()
    
    def find_swing_points(self, df, lookback=5):
        highs, lows = [], []
        for i in range(lookback, len(df) - lookback):
            if df['high'].iloc[i] == df['high'].iloc[i-lookback:i+lookback+1].max():
                highs.append((i, df['high'].iloc[i]))
            if df['low'].iloc[i] == df['low'].iloc[i-lookback:i+lookback+1].min():
                lows.append((i, df['low'].iloc[i]))
        return highs, lows
    
    def detect_signal(self, df):
        if len(df) < 50:
            return None
        
        df = df.copy()
        df['atr'] = self.calculate_atr(df, self.atr_period)
        highs, lows = self.find_swing_points(df)
        
        if len(highs) < 2 or len(lows) < 2:
            return None
        
        current_price = df['close'].iloc[-1]
        current_atr = df['atr'].iloc[-1]
        
        # Bullish ABC pattern
        recent_low = lows[-1] if lows else None
        recent_high = highs[-1] if highs else None
        
        if recent_low and recent_high and recent_high[0] > recent_low[0]:
            a_price, b_price = recent_low[1], recent_high[1]
            wave_size = b_price - a_price
            
            if wave_size > current_atr * self.min_wave_atr:
                retracement = (b_price - current_price) / wave_size
                if self.fib_entry - 0.1 <= retracement <= self.max_retracement:
                    return {
                        'direction': 'BUY',
                        'entry_price': current_price,
                        'stop_loss': a_price - (wave_size * self.fib_stop),
                        'take_profit': b_price + (wave_size * (self.fib_target - 1))
                    }
        
        # Bearish ABC pattern
        if recent_high and recent_low and recent_low[0] > recent_high[0]:
            a_price, b_price = recent_high[1], recent_low[1]
            wave_size = a_price - b_price
            
            if wave_size > current_atr * self.min_wave_atr:
                retracement = (current_price - b_price) / wave_size
                if self.fib_entry - 0.1 <= retracement <= self.max_retracement:
                    return {
                        'direction': 'SELL',
                        'entry_price': current_price,
                        'stop_loss': a_price + (wave_size * self.fib_stop),
                        'take_profit': b_price - (wave_size * (self.fib_target - 1))
                    }
        
        return None

# ==================== SIGNAL DETECTOR ====================
class SignalDetector:
    def __init__(self, capital=100000, risk_per_trade=0.02):
        self.strategy = Fib3WaveStrategy()
        self.capital = capital
        self.risk_per_trade = risk_per_trade
    
    def detect(self, symbol, df):
        signal = self.strategy.detect_signal(df)
        if not signal:
            return None
        
        entry, sl, tp = signal['entry_price'], signal['stop_loss'], signal['take_profit']
        risk_pct = abs(entry - sl) / entry * 100
        reward_pct = abs(tp - entry) / entry * 100
        rr_ratio = reward_pct / risk_pct if risk_pct > 0 else 0
        
        if rr_ratio < 1.5:
            return None
        
        risk_amount = self.capital * self.risk_per_trade
        risk_per_share = abs(entry - sl)
        quantity = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0
        
        if quantity <= 0:
            return None
        
        return {
            'symbol': symbol,
            'direction': signal['direction'],
            'entry_price': entry,
            'stop_loss': sl,
            'take_profit': tp,
            'risk_pct': risk_pct,
            'reward_pct': reward_pct,
            'rr_ratio': rr_ratio,
            'quantity': quantity,
            'position_value': quantity * entry
        }

# ==================== NIFTY 50 STOCKS ====================
STOCKS = [
    'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
    'HINDUNILVR', 'ITC', 'SBIN', 'BHARTIARTL', 'KOTAKBANK',
    'LT', 'AXISBANK', 'ASIANPAINT', 'MARUTI', 'TITAN',
    'BAJFINANCE', 'WIPRO', 'HCLTECH', 'SUNPHARMA', 'TATAMOTORS',
    'ADANIPORTS', 'APOLLOHOSP', 'BAJAJ-AUTO', 'BAJAJFINSV', 'BPCL',
    'BRITANNIA', 'CIPLA', 'COALINDIA', 'DIVISLAB', 'DRREDDY',
    'EICHERMOT', 'GRASIM', 'HDFCLIFE', 'HEROMOTOCO', 'HINDALCO',
    'INDUSINDBK', 'JSWSTEEL', 'M&M', 'NESTLEIND', 'NTPC',
    'ONGC', 'POWERGRID', 'SHREECEM', 'TATACONSUM', 'TATASTEEL',
    'TECHM', 'ULTRACEMCO', 'UPL'
]

# ==================== HELPER FUNCTIONS ====================
def is_market_hours():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    current_time = now.time()
    return dtime(9, 15) <= current_time <= dtime(15, 30)

def run_scan(fetcher, detector, telegram):
    print(f"\n{'='*50}")
    print(f"Scanning at {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*50}")
    
    signals_found = []
    for symbol in STOCKS:
        try:
            df = fetcher.get_historical(symbol)
            if df is not None and len(df) >= 50:
                signal = detector.detect(symbol, df)
                if signal:
                    signals_found.append(signal)
                    print(f"SIGNAL: {symbol} {signal['direction']} @ Rs {signal['entry_price']:.2f}")
                    telegram.send_signal(signal)
        except:
            pass
    
    print(f"\nScan complete. Found {len(signals_found)} signals.")
    return signals_found

# ==================== MAIN ====================
if __name__ == '__main__':
    print("="*50)
    print("TRADING MONITOR - Google Colab")
    print("="*50)
    
    # Check credentials
    if not ZERODHA_ENCTOKEN:
        print("\n[!] WARNING: ZERODHA_ENCTOKEN not set!")
        print("    Get it from: kite.zerodha.com -> F12 -> Application -> Cookies -> enctoken")
    
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("\n[!] WARNING: Telegram not configured!")
        print("    Alerts will only print to console.")
    
    # Initialize
    print("\nInitializing...")
    fetcher = DataFetcher(ZERODHA_ENCTOKEN)
    detector = SignalDetector(INITIAL_CAPITAL)
    telegram = TelegramBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    
    # Send startup message
    telegram.send(f"<b>Trading Monitor Started (Colab)</b>\n\nScanning {len(STOCKS)} stocks every {SCAN_INTERVAL_MINUTES} minutes.")
    
    print(f"\nStocks: {len(STOCKS)}")
    print(f"Scan Interval: {SCAN_INTERVAL_MINUTES} minutes")
    print(f"Capital: Rs {INITIAL_CAPITAL:,}")
    print("="*50)
    
    # Main loop
    scan_count = 0
    while True:
        try:
            if is_market_hours():
                scan_count += 1
                print(f"\n[Scan #{scan_count}]")
                run_scan(fetcher, detector, telegram)
            else:
                print(f"\rMarket closed. Waiting... ({datetime.now().strftime('%H:%M:%S')})", end="")
            
            time.sleep(SCAN_INTERVAL_MINUTES * 60)
            
        except KeyboardInterrupt:
            print("\n\nMonitor stopped.")
            telegram.send("<b>Trading Monitor Stopped</b>")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(60)
