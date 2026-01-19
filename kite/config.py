"""
Configuration settings for the trading strategy backtesting system.
"""
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DAILY_DATA_DIR = DATA_DIR / "daily"
HOURLY_DATA_DIR = DATA_DIR / "hourly"
REPORTS_DIR = PROJECT_ROOT / "kite" / "reports"

# Create reports directory if it doesn't exist
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class TradingConfig:
    """Trading configuration parameters."""
    
    # Capital settings
    initial_capital: float = 100_000.0  # ₹1,00,000
    
    # Risk management
    risk_per_trade: float = 0.02  # 2% risk per trade
    max_positions: int = 5  # Maximum concurrent positions
    max_daily_loss: float = 0.05  # 5% daily loss limit
    
    # Position sizing
    use_risk_based_sizing: bool = True
    fixed_quantity: int = 1  # Used if risk_based_sizing is False
    
    # Trading direction
    allow_long: bool = True
    allow_short: bool = True
    
    # Market hours (IST)
    market_open: str = "09:15"
    market_close: str = "15:30"
    
    # Slippage (percentage)
    slippage: float = 0.0001  # 0.01%


@dataclass
class ZerodhaCharges:
    """Zerodha brokerage and charges structure."""
    
    # Equity Intraday
    intraday_brokerage_pct: float = 0.0003  # 0.03% or ₹20, whichever is lower
    intraday_brokerage_max: float = 20.0  # ₹20 max per order
    
    # Equity Delivery
    delivery_brokerage: float = 0.0  # Zero brokerage for delivery
    
    # STT (Securities Transaction Tax)
    stt_intraday_sell: float = 0.00025  # 0.025% on sell side
    stt_delivery: float = 0.001  # 0.1% on both buy and sell
    
    # Exchange Transaction Charges
    exchange_txn_charge: float = 0.0000345  # NSE: 0.00345%
    
    # GST on brokerage + transaction charges
    gst: float = 0.18  # 18%
    
    # SEBI Charges
    sebi_charges: float = 0.000001  # ₹10 per crore
    
    # Stamp Duty (varies by state, using Maharashtra)
    stamp_duty_buy: float = 0.00015  # 0.015% on buy side
    
    def calculate_charges(self, buy_value: float, sell_value: float, 
                         is_intraday: bool = True) -> Dict[str, float]:
        """Calculate all charges for a round-trip trade."""
        charges = {}
        
        # Brokerage
        if is_intraday:
            buy_brokerage = min(buy_value * self.intraday_brokerage_pct, 
                               self.intraday_brokerage_max)
            sell_brokerage = min(sell_value * self.intraday_brokerage_pct, 
                                self.intraday_brokerage_max)
        else:
            buy_brokerage = 0
            sell_brokerage = 0
        
        charges['brokerage'] = buy_brokerage + sell_brokerage
        
        # STT
        if is_intraday:
            charges['stt'] = sell_value * self.stt_intraday_sell
        else:
            charges['stt'] = (buy_value + sell_value) * self.stt_delivery
        
        # Exchange charges
        charges['exchange'] = (buy_value + sell_value) * self.exchange_txn_charge
        
        # GST on brokerage + exchange charges
        charges['gst'] = (charges['brokerage'] + charges['exchange']) * self.gst
        
        # SEBI charges
        charges['sebi'] = (buy_value + sell_value) * self.sebi_charges
        
        # Stamp duty
        charges['stamp_duty'] = buy_value * self.stamp_duty_buy
        
        # Total
        charges['total'] = sum(charges.values())
        
        return charges


@dataclass
class StrategyParams:
    """Default parameters for all strategies."""
    
    # Strategy 1: 21/55 EMA
    ema_21_55: Dict = field(default_factory=lambda: {
        'fast_period': 21,
        'slow_period': 55,
        'atr_period': 14,
        'atr_multiplier': 2.0,
        'risk_reward': 1.5,
    })
    
    # Strategy 2: RSI Divergence
    rsi_divergence: Dict = field(default_factory=lambda: {
        'rsi_period': 14,
        'overbought': 70,
        'oversold': 30,
        'lookback': 20,
        'atr_period': 14,
        'atr_multiplier': 2.0,
    })
    
    # Strategy 3: VWAP Pullback
    vwap_pullback: Dict = field(default_factory=lambda: {
        'atr_period': 14,
        'atr_multiplier': 1.5,
        'min_pullback_pct': 0.002,  # 0.2% minimum pullback
    })
    
    # Strategy 4: Bollinger Bands Squeeze
    bb_squeeze: Dict = field(default_factory=lambda: {
        'bb_period': 20,
        'bb_std': 2.0,
        'squeeze_threshold': 0.1,  # 10th percentile for squeeze
        'atr_period': 14,
        'atr_multiplier': 2.0,
    })
    
    # Strategy 5: 3-EMA Scalping
    ema_3_scalping: Dict = field(default_factory=lambda: {
        'ema_fast': 50,
        'ema_medium': 100,
        'ema_slow': 150,
        'min_slope': 0.0001,  # Minimum EMA slope
        'atr_period': 14,
        'atr_multiplier': 1.5,
    })
    
    # Strategy 6: Supply & Demand
    supply_demand: Dict = field(default_factory=lambda: {
        'min_impulse_atr': 1.5,  # Minimum impulse size in ATR
        'zone_atr_buffer': 0.5,  # Zone buffer in ATR
        'max_zone_age': 50,  # Maximum candles since zone formed
        'atr_period': 14,
        'atr_multiplier': 2.0,
    })
    
    # Strategy 7: ATR Management (used by all strategies)
    atr_management: Dict = field(default_factory=lambda: {
        'atr_period': 14,
        'stop_multiplier': 2.0,
        'trail_multiplier': 2.0,
        'profit_target_multiplier': 3.0,
    })
    
    # Strategy 8: Stochastic Confluence
    stochastic_confluence: Dict = field(default_factory=lambda: {
        'stoch_k': 14,
        'stoch_d': 3,
        'stoch_smooth': 3,
        'ema_period': 200,
        'overbought': 80,
        'oversold': 20,
        'atr_period': 14,
        'atr_multiplier': 2.0,
    })
    
    # Strategy 9: 3-Wave Fibonacci
    fib_3wave: Dict = field(default_factory=lambda: {
        'min_wave_atr': 2.0,  # Minimum AB wave size in ATR
        'fib_entry': 0.5,  # 50% retracement
        'fib_stop': 0.236,  # 23.6% for stop
        'fib_target': 1.618,  # 161.8% extension
        'max_retracement': 0.618,  # Maximum allowed retracement
        'atr_period': 14,
    })
    
    # Strategy 10: Multi-Timeframe
    multi_timeframe: Dict = field(default_factory=lambda: {
        'higher_tf': 'D',  # Daily for trend
        'medium_tf': '1H',  # Hourly for setup
        'lower_tf': '5T',  # 5-min for entry
        'trend_ema_fast': 50,
        'trend_ema_slow': 200,
        'rsi_period': 14,
        'atr_period': 14,
        'atr_multiplier': 2.0,
    })


# NIFTY 50 Stocks list
NIFTY_50_STOCKS = [
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


# Default instances
trading_config = TradingConfig()
zerodha_charges = ZerodhaCharges()
strategy_params = StrategyParams()
