"""
TDI (Traders Dynamic Index) Strategy

Hybrid indicator combining RSI + Moving Average + Bollinger Bands.
- Green line (RSI) crosses red line (MA of RSI) for entries
- Yellow line (50 SMA) for overall trend
- BB squeeze for volatility
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import tdi
from ..indicators.volatility import atr


class TDIStrategy(BaseStrategy):
    """Traders Dynamic Index strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'rsi_period': 13,
            'fast_ma': 2,
            'slow_ma': 7,
            'bb_period': 34,
            'bb_std': 1.6185,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "TDI"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        self.validate_data(df)
        
        # Calculate TDI
        tdi_data = tdi(
            df,
            self.params['rsi_period'],
            self.params['fast_ma'],
            self.params['slow_ma'],
            self.params['bb_period'],
            self.params['bb_std']
        )
        
        df['tdi_green'] = tdi_data['green']      # RSI (market sentiment)
        df['tdi_red'] = tdi_data['red']          # Signal line
        df['tdi_yellow'] = tdi_data['yellow']    # Market base
        df['tdi_upper'] = tdi_data['upper_bb']   # Volatility upper
        df['tdi_lower'] = tdi_data['lower_bb']   # Volatility lower
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal
        df['signal'] = 0
        
        # Green crosses red (RSI crosses its MA)
        green_cross_up = (df['tdi_green'] > df['tdi_red']) & \
                        (df['tdi_green'].shift(1) <= df['tdi_red'].shift(1))
        green_cross_down = (df['tdi_green'] < df['tdi_red']) & \
                          (df['tdi_green'].shift(1) >= df['tdi_red'].shift(1))
        
        # Trend filter: green above/below yellow (50 level)
        bullish_trend = df['tdi_green'] > df['tdi_yellow']
        bearish_trend = df['tdi_green'] < df['tdi_yellow']
        
        # Volatility filter: BB not too squeezed
        bb_width = df['tdi_upper'] - df['tdi_lower']
        avg_bb_width = bb_width.rolling(20).mean()
        not_squeezed = bb_width > avg_bb_width * 0.5
        
        # Generate signals
        # Buy: Green crosses above red, green above yellow, not squeezed
        buy_signal = green_cross_up & bullish_trend & not_squeezed
        
        # Sell: Green crosses below red, green below yellow, not squeezed
        sell_signal = green_cross_down & bearish_trend & not_squeezed
        
        df.loc[buy_signal, 'signal'] = Signal.BUY.value
        df.loc[sell_signal, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        entry_price = df.loc[idx, 'close']
        current_atr = df.loc[idx, 'atr']
        
        if direction == Signal.BUY:
            return entry_price - (current_atr * self.params['atr_multiplier'])
        else:
            return entry_price + (current_atr * self.params['atr_multiplier'])
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, direction: Signal,
                             entry_price: float, stop_loss: float) -> float:
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
