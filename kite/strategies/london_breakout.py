"""
London Breakout Strategy (Session-Based)

Trade the volatility spike at session open.
For Indian markets: Use first hour range as "Asian session" equivalent.
Trade breakout of this range.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr


class LondonBreakoutStrategy(BaseStrategy):
    """
    Session breakout strategy.
    
    For daily data: Uses previous day's range
    For intraday: Uses first N bars as consolidation range
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'range_bars': 5,  # First N bars for range (for intraday)
            'breakout_buffer': 0.001,  # 0.1% buffer above/below range
            'atr_period': 14,
            'atr_multiplier': 1.5,
            'risk_reward': 2.0,
            'max_trades_per_session': 1,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "London_Breakout"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        self.validate_data(df)
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal
        df['signal'] = 0
        
        # Detect if data is daily or intraday
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        elif df.index.name == 'date' or isinstance(df.index, pd.DatetimeIndex):
            df['date'] = df.index.date if isinstance(df.index, pd.DatetimeIndex) else df.index
        else:
            # Assume daily data - use rolling range
            self._generate_daily_signals(df)
            return df
        
        # For intraday data - group by date
        self._generate_intraday_signals(df)
        return df
    
    def _generate_daily_signals(self, df: pd.DataFrame):
        """Generate signals for daily data using previous day's range."""
        range_bars = self.params['range_bars']
        buffer = self.params['breakout_buffer']
        
        for i in range(range_bars + 1, len(df)):
            # Previous range
            prev_range = df.iloc[i-range_bars:i]
            range_high = prev_range['high'].max()
            range_low = prev_range['low'].min()
            
            current_idx = df.index[i]
            current_close = df.loc[current_idx, 'close']
            current_high = df.loc[current_idx, 'high']
            current_low = df.loc[current_idx, 'low']
            prev_close = df.iloc[i-1]['close']
            
            # Breakout above range high
            breakout_up = current_close > range_high * (1 + buffer) and \
                         prev_close <= range_high * (1 + buffer)
            
            # Breakdown below range low
            breakout_down = current_close < range_low * (1 - buffer) and \
                           prev_close >= range_low * (1 - buffer)
            
            if breakout_up:
                df.loc[current_idx, 'signal'] = Signal.BUY.value
            elif breakout_down:
                df.loc[current_idx, 'signal'] = Signal.SELL.value
    
    def _generate_intraday_signals(self, df: pd.DataFrame):
        """Generate signals for intraday data using first hour range."""
        range_bars = self.params['range_bars']
        buffer = self.params['breakout_buffer']
        
        # Group by date
        dates = df['date'].unique()
        
        for date in dates:
            day_data = df[df['date'] == date]
            
            if len(day_data) < range_bars + 1:
                continue
            
            # First N bars define the range
            range_data = day_data.iloc[:range_bars]
            range_high = range_data['high'].max()
            range_low = range_data['low'].min()
            
            # Look for breakout in remaining bars
            remaining = day_data.iloc[range_bars:]
            traded = False
            
            for idx in remaining.index:
                if traded:
                    break
                
                current_close = df.loc[idx, 'close']
                
                # Breakout above range
                if current_close > range_high * (1 + buffer):
                    df.loc[idx, 'signal'] = Signal.BUY.value
                    traded = True
                # Breakdown below range
                elif current_close < range_low * (1 - buffer):
                    df.loc[idx, 'signal'] = Signal.SELL.value
                    traded = True
    
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
