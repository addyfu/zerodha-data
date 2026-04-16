"""
Heikin-Ashi Trend Trading Strategy
- Green HA candles with no lower wick = Strong uptrend
- Red HA candles with no upper wick = Strong downtrend
- Enter on pullback in trend
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import atr


def calculate_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate Heikin Ashi candles."""
    ha_df = df.copy()
    
    ha_df['ha_close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha_df['ha_open'] = (df['open'].shift(1) + df['close'].shift(1)) / 2
    ha_df['ha_open'].iloc[0] = df['open'].iloc[0]
    
    for i in range(1, len(ha_df)):
        ha_df['ha_open'].iloc[i] = (ha_df['ha_open'].iloc[i-1] + ha_df['ha_close'].iloc[i-1]) / 2
    
    ha_df['ha_high'] = ha_df[['high', 'ha_open', 'ha_close']].max(axis=1)
    ha_df['ha_low'] = ha_df[['low', 'ha_open', 'ha_close']].min(axis=1)
    
    return ha_df


class HATrendStrategy(BaseStrategy):
    """Heikin-Ashi Trend Trading Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'trend_bars': 3,  # Minimum bars for trend confirmation
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on Heikin-Ashi trend."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate Heikin Ashi
        ha_df = calculate_heikin_ashi(df)
        df['ha_close'] = ha_df['ha_close']
        df['ha_open'] = ha_df['ha_open']
        df['ha_high'] = ha_df['ha_high']
        df['ha_low'] = ha_df['ha_low']
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # HA candle characteristics
        df['ha_green'] = df['ha_close'] > df['ha_open']
        df['ha_red'] = df['ha_close'] < df['ha_open']
        
        # Strong trend candles (no lower wick for bullish, no upper wick for bearish)
        df['ha_strong_bull'] = df['ha_green'] & (df['ha_open'] == df['ha_low'])
        df['ha_strong_bear'] = df['ha_red'] & (df['ha_open'] == df['ha_high'])
        
        # Pullback candles (small body, opposite color)
        df['ha_pullback_bull'] = df['ha_red'] & (abs(df['ha_close'] - df['ha_open']) < df['atr'] * 0.5)
        df['ha_pullback_bear'] = df['ha_green'] & (abs(df['ha_close'] - df['ha_open']) < df['atr'] * 0.5)
        
        # Initialize signal column
        df['signal'] = 0
        
        trend_bars = self.params['trend_bars']
        
        for i in range(trend_bars + 1, len(df)):
            idx = df.index[i]
            
            # Check for strong uptrend (N consecutive strong bull candles)
            strong_uptrend = all(df['ha_strong_bull'].iloc[i-trend_bars:i])
            
            # Check for strong downtrend
            strong_downtrend = all(df['ha_strong_bear'].iloc[i-trend_bars:i])
            
            # Long: Strong uptrend followed by pullback, then green candle
            if strong_uptrend and df['ha_pullback_bull'].iloc[i-1] and df['ha_green'].iloc[i]:
                df.loc[idx, 'signal'] = Signal.BUY.value
            
            # Short: Strong downtrend followed by pullback, then red candle
            elif strong_downtrend and df['ha_pullback_bear'].iloc[i-1] and df['ha_red'].iloc[i]:
                df.loc[idx, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using ATR."""
        atr_val = df.loc[idx, 'atr']
        entry_price = df.loc[idx, 'close']
        mult = self.params['atr_multiplier']
        
        if direction == Signal.BUY:
            return entry_price - (atr_val * mult)
        else:
            return entry_price + (atr_val * mult)
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, 
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """Calculate take profit based on risk-reward ratio."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
