"""
Double VWAP + Heikin Ashi Strategy
- Uses current VWAP and previous day VWAP
- Heikin Ashi for trend confirmation
- Scalping strategy for intraday
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volume import vwap
from ..indicators.volatility import atr


def calculate_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate Heikin Ashi candles."""
    ha_df = df.copy()
    
    # HA Close = (Open + High + Low + Close) / 4
    ha_df['ha_close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    
    # HA Open = (Previous HA Open + Previous HA Close) / 2
    ha_df['ha_open'] = (df['open'].shift(1) + df['close'].shift(1)) / 2
    ha_df['ha_open'].iloc[0] = df['open'].iloc[0]
    
    # Recalculate HA Open properly
    for i in range(1, len(ha_df)):
        ha_df['ha_open'].iloc[i] = (ha_df['ha_open'].iloc[i-1] + ha_df['ha_close'].iloc[i-1]) / 2
    
    # HA High = Max(High, HA Open, HA Close)
    ha_df['ha_high'] = ha_df[['high', 'ha_open', 'ha_close']].max(axis=1)
    
    # HA Low = Min(Low, HA Open, HA Close)
    ha_df['ha_low'] = ha_df[['low', 'ha_open', 'ha_close']].min(axis=1)
    
    return ha_df


class DoubleVWAPHAStrategy(BaseStrategy):
    """Double VWAP with Heikin Ashi Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'atr_period': 14,
            'atr_multiplier': 1.5,
            'risk_reward': 1.5,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on Double VWAP + Heikin Ashi."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate current VWAP
        df['vwap'] = vwap(df, reset_daily=True)
        
        # Calculate previous day's VWAP (use rolling approach)
        df['date'] = df.index.date
        df['prev_vwap'] = df.groupby('date')['vwap'].transform('last').shift(1)
        
        # Fill forward previous VWAP within each day
        df['prev_vwap'] = df['prev_vwap'].ffill()
        
        # Calculate Heikin Ashi
        ha_df = calculate_heikin_ashi(df)
        df['ha_close'] = ha_df['ha_close']
        df['ha_open'] = ha_df['ha_open']
        
        # HA trend signals
        df['ha_green'] = df['ha_close'] > df['ha_open']
        df['ha_red'] = df['ha_close'] < df['ha_open']
        
        # Strong HA candles (no lower wick for bullish, no upper wick for bearish)
        df['ha_strong_bull'] = df['ha_green'] & (df['ha_open'] == ha_df['ha_low'])
        df['ha_strong_bear'] = df['ha_red'] & (df['ha_open'] == ha_df['ha_high'])
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        # Long: Price above both VWAPs + HA green (strong)
        long_condition = (
            (df['close'] > df['vwap']) &
            (df['close'] > df['prev_vwap']) &
            df['ha_green'] &
            # Pullback to current VWAP
            (df['low'] <= df['vwap'] * 1.002)  # Within 0.2% of VWAP
        )
        
        # Short: Price below both VWAPs + HA red (strong)
        short_condition = (
            (df['close'] < df['vwap']) &
            (df['close'] < df['prev_vwap']) &
            df['ha_red'] &
            # Rally to current VWAP
            (df['high'] >= df['vwap'] * 0.998)  # Within 0.2% of VWAP
        )
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
        # Clean up
        df.drop(['date'], axis=1, inplace=True, errors='ignore')
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using ATR."""
        atr_val = df.loc[idx, 'atr'] if 'atr' in df.columns else df['atr'].iloc[-1]
        entry_price = df.loc[idx, 'close']
        multiplier = self.params['atr_multiplier']
        
        if direction == Signal.BUY:
            return entry_price - (atr_val * multiplier)
        else:
            return entry_price + (atr_val * multiplier)
    
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
