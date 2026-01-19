"""
Replit Trading Monitor
======================
Runs CONTINUOUSLY on Replit's free tier.

Setup:
1. Go to https://replit.com/ (sign up free, no credit card)
2. Create new Python Repl
3. Copy all files from this folder
4. Add Secrets (Environment Variables):
   - ZERODHA_ENCTOKEN
   - TELEGRAM_BOT_TOKEN
   - TELEGRAM_CHAT_ID
5. Click Run!

To keep it alive 24/7:
1. Go to https://uptimerobot.com/ (free)
2. Add HTTP monitor pointing to your Repl's URL
3. It pings every 5 min, keeping Repl alive
"""

import os
import time
import threading
from datetime import datetime, time as dtime, timedelta
from flask import Flask
import requests
import pandas as pd
import numpy as np

# ==================== FLASK SERVER (Keeps Replit Alive) ====================
app = Flask(__name__)

@app.route('/')
def home():
    return f"""
    <h1>Trading Monitor Running</h1>
    <p>Status: Active</p>
    <p>Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p>Market: {'OPEN' if is_market_hours() else 'CLOSED'}</p>
    """

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# ==================== CONFIGURATION ====================
ZERODHA_ENCTOKEN = os.environ.get('ZERODHA_ENCTOKEN', '')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

INITIAL_CAPITAL = 100000
SCAN_INTERVAL_SECONDS = 60  # Scan every 60 seconds for near real-time

# ==================== TELEGRAM ====================
class TelegramBot:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.enabled = bool(token and chat_id)
    
    def send(self, message):
        if not self.enabled:
            print(f"[TELEGRAM] {message[:100]}...")
            return False
        try:
            url = f"{self.base_url}/sendMessage"
            data = {"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"}
            requests.post(url, data=data, timeout=10)
            return True
        except:
            return False
    
    def send_signal(self, signal):
        msg = f"""
<b>{'[BUY]' if signal['direction'] == 'BUY' else '[SELL]'} TRADE ALERT</b>

<b>Stock:</b> {signal['symbol']}
<b>Entry:</b> Rs {signal['entry_price']:.2f}
<b>Stop Loss:</b> Rs {signal['stop_loss']:.2f}
<b>Target:</b> Rs {signal['take_profit']:.2f}
<b>R:R:</b> 1:{signal['rr_ratio']:.1f}
<b>Qty:</b> {signal['quantity']} shares

<b>Time:</b> {datetime.now().strftime('%H:%M:%S')}
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
        return {"Authorization": f"enctoken {self.enctoken}", "User-Agent": "Mozilla/5.0"}
    
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
            print(f"Instrument load error: {e}")
    
    def get_quote(self, symbols):
        """Get real-time quotes."""
        if not self.enctoken:
            return {}
        try:
            instruments = [f"NSE:{s}" for s in symbols if s in self.instruments]
            if not instruments:
                return {}
            
            url = f"https://kite.zerodha.com/orca/quote?i={'&i='.join(instruments)}"
            response = requests.get(url, headers=self._get_headers(), timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    quotes = {}
                    for key, value in data.get('data', {}).items():
                        symbol = key.replace('NSE:', '')
                        quotes[symbol] = {
                            'price': value.get('last_price', 0),
                            'open': value.get('ohlc', {}).get('open', 0),
                            'high': value.get('ohlc', {}).get('high', 0),
                            'low': value.get('ohlc', {}).get('low', 0),
                            'close': value.get('ohlc', {}).get('close', 0),
                            'change_pct': value.get('change', 0) / value.get('ohlc', {}).get('close', 1) * 100 if value.get('ohlc', {}).get('close') else 0
                        }
                    return quotes
        except:
            pass
        return {}
    
    def get_historical(self, symbol, days=60):
        if symbol not in self.instruments:
            return None
        try:
            token = self.instruments[symbol]
            to_date = datetime.now()
            from_date = to_date - timedelta(days=days)
            
            url = f"{self.BASE_URL}/instruments/historical/{token}/day"
            params = {"from": from_date.strftime("%Y-%m-%d"), "to": to_date.strftime("%Y-%m-%d")}
            
            response = requests.get(url, headers=self._get_headers(), params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success' and data.get('data', {}).get('candles'):
                    df = pd.DataFrame(data['data']['candles'], 
                                     columns=['datetime', 'open', 'high', 'low', 'close', 'volume', 'oi'])
                    df['datetime'] = pd.to_datetime(df['datetime'])
                    df.set_index('datetime', inplace=True)
                    return df
        except:
            pass
        return None

# ==================== STRATEGY ====================
class Fib3WaveStrategy:
    def __init__(self):
        self.min_wave_atr = 2.0
        self.atr_period = 14
    
    def calculate_atr(self, df, period=14):
        tr = pd.concat([
            df['high'] - df['low'],
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        ], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()
    
    def find_swings(self, df, lookback=5):
        highs, lows = [], []
        for i in range(lookback, len(df) - lookback):
            if df['high'].iloc[i] == df['high'].iloc[i-lookback:i+lookback+1].max():
                highs.append((i, df['high'].iloc[i]))
            if df['low'].iloc[i] == df['low'].iloc[i-lookback:i+lookback+1].min():
                lows.append((i, df['low'].iloc[i]))
        return highs, lows
    
    def detect(self, df):
        if len(df) < 50:
            return None
        
        df = df.copy()
        df['atr'] = self.calculate_atr(df)
        highs, lows = self.find_swings(df)
        
        if len(highs) < 2 or len(lows) < 2:
            return None
        
        price = df['close'].iloc[-1]
        atr = df['atr'].iloc[-1]
        
        # Bullish pattern
        if lows and highs and highs[-1][0] > lows[-1][0]:
            a, b = lows[-1][1], highs[-1][1]
            wave = b - a
            if wave > atr * self.min_wave_atr:
                ret = (b - price) / wave
                if 0.4 <= ret <= 0.618:
                    return {
                        'direction': 'BUY',
                        'entry_price': price,
                        'stop_loss': a - (wave * 0.236),
                        'take_profit': b + (wave * 0.618)
                    }
        
        # Bearish pattern
        if highs and lows and lows[-1][0] > highs[-1][0]:
            a, b = highs[-1][1], lows[-1][1]
            wave = a - b
            if wave > atr * self.min_wave_atr:
                ret = (price - b) / wave
                if 0.4 <= ret <= 0.618:
                    return {
                        'direction': 'SELL',
                        'entry_price': price,
                        'stop_loss': a + (wave * 0.236),
                        'take_profit': b - (wave * 0.618)
                    }
        
        return None

# ==================== SIGNAL DETECTOR ====================
class SignalDetector:
    def __init__(self, capital=100000):
        self.strategy = Fib3WaveStrategy()
        self.capital = capital
        self.last_signals = {}  # Prevent duplicate alerts
    
    def detect(self, symbol, df):
        signal = self.strategy.detect(df)
        if not signal:
            return None
        
        # Check for duplicate
        key = f"{symbol}_{signal['direction']}"
        if key in self.last_signals:
            last_time = self.last_signals[key]
            if datetime.now() - last_time < timedelta(hours=4):
                return None  # Already alerted recently
        
        entry, sl, tp = signal['entry_price'], signal['stop_loss'], signal['take_profit']
        risk_pct = abs(entry - sl) / entry * 100
        reward_pct = abs(tp - entry) / entry * 100
        rr = reward_pct / risk_pct if risk_pct > 0 else 0
        
        if rr < 1.5:
            return None
        
        risk_amt = self.capital * 0.02
        qty = int(risk_amt / abs(entry - sl)) if abs(entry - sl) > 0 else 0
        
        if qty <= 0:
            return None
        
        self.last_signals[key] = datetime.now()
        
        return {
            'symbol': symbol,
            'direction': signal['direction'],
            'entry_price': entry,
            'stop_loss': sl,
            'take_profit': tp,
            'risk_pct': risk_pct,
            'reward_pct': reward_pct,
            'rr_ratio': rr,
            'quantity': qty,
            'position_value': qty * entry
        }

# ==================== STOCKS ====================
STOCKS = [
    'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'HINDUNILVR', 'ITC', 'SBIN',
    'BHARTIARTL', 'KOTAKBANK', 'LT', 'AXISBANK', 'ASIANPAINT', 'MARUTI', 'TITAN',
    'BAJFINANCE', 'WIPRO', 'HCLTECH', 'SUNPHARMA', 'TATAMOTORS', 'ADANIPORTS',
    'BAJAJ-AUTO', 'NESTLEIND', 'NTPC', 'ONGC', 'POWERGRID', 'TATASTEEL', 'TECHM'
]

# ==================== HELPERS ====================
def is_market_hours():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dtime(9, 15) <= t <= dtime(15, 30)

# ==================== MAIN MONITOR ====================
def run_monitor():
    print("="*50)
    print("CONTINUOUS TRADING MONITOR")
    print("="*50)
    
    fetcher = DataFetcher(ZERODHA_ENCTOKEN)
    detector = SignalDetector(INITIAL_CAPITAL)
    telegram = TelegramBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    
    telegram.send("<b>Trading Monitor Started (Replit)</b>\n\nRunning continuously during market hours.")
    
    scan_count = 0
    
    while True:
        try:
            if is_market_hours():
                scan_count += 1
                print(f"\n[Scan #{scan_count}] {datetime.now().strftime('%H:%M:%S')}")
                
                for symbol in STOCKS:
                    try:
                        df = fetcher.get_historical(symbol, days=60)
                        if df is not None and len(df) >= 50:
                            signal = detector.detect(symbol, df)
                            if signal:
                                print(f"  SIGNAL: {symbol} {signal['direction']}")
                                telegram.send_signal(signal)
                    except:
                        pass
                
                print(f"  Scanned {len(STOCKS)} stocks")
            else:
                print(f"\rMarket closed. Waiting... {datetime.now().strftime('%H:%M:%S')}", end="")
            
            time.sleep(SCAN_INTERVAL_SECONDS)
            
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(60)

# ==================== START ====================
if __name__ == '__main__':
    # Start Flask in background (keeps Replit alive)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("Web server started on port 8080")
    
    # Start monitor
    run_monitor()
