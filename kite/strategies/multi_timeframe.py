"""
Strategy 10: Multi-Timeframe Strategy

This strategy combines multiple timeframes for trend and entry.
- Higher TF (Daily): Identify trend direction
- Medium TF (Hourly): Look for setups (divergences)
- Lower TF (5-min): Time precise entries
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

from kite.strategies.base_strategy import BaseStrategy, Signal
from kite.indicators.moving_averages import ema
from kite.indicators.oscillators import rsi, rsi_divergence
from kite.indicators.volatility import atr
from kite.utils.data_loader import resample_timeframe
from kite.config import strategy_params


class MultiTimeframeStrategy(BaseStrategy):
    """
    Multi-Timeframe Strategy.
    
    Uses multiple timeframes for trend confirmation and entry timing.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = strategy_params.multi_timeframe.copy()
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "Multi_Timeframe"
        
        # Store higher timeframe data
        self.higher_tf_data: Optional[pd.DataFrame] = None
    
    def set_higher_tf_data(self, df: pd.DataFrame):
        """Set higher timeframe data for trend analysis."""
        self.higher_tf_data = df
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate buy/sell signals using multi-timeframe analysis.
        
        Signal Logic:
        - Determine trend from higher TF EMAs
        - Look for RSI divergence on current TF
        - Only trade in direction of higher TF trend
        """
        self.validate_data(df)
        df = df.copy()
        
        # Calculate indicators on current timeframe
        df['ema_fast'] = ema(df['close'], self.params['trend_ema_fast'])
        df['ema_slow'] = ema(df['close'], self.params['trend_ema_slow'])
        df['rsi'] = rsi(df['close'], self.params['rsi_period'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Detect divergences
        df = rsi_divergence(df, 'rsi', 'close', lookback=20)
        
        # Determine trend from current TF (or higher TF if available)
        if self.higher_tf_data is not None:
            df = self._add_higher_tf_trend(df)
        else:
            # Use current TF for trend
            df['higher_tf_uptrend'] = df['ema_fast'] > df['ema_slow']
            df['higher_tf_downtrend'] = df['ema_fast'] < df['ema_slow']
        
        # Current TF trend alignment
        df['current_uptrend'] = df['close'] > df['ema_fast']
        df['current_downtrend'] = df['close'] < df['ema_fast']
        
        # Generate signals
        df['signal'] = 0
        
        # BUY: Higher TF uptrend + bullish divergence + price above fast EMA
        buy_condition = (
            df['higher_tf_uptrend'] &
            (df['bullish_divergence'] | df['hidden_bullish_div']) &
            df['current_uptrend']
        )
        df.loc[buy_condition, 'signal'] = Signal.BUY.value
        
        # SELL: Higher TF downtrend + bearish divergence + price below fast EMA
        sell_condition = (
            df['higher_tf_downtrend'] &
            (df['bearish_divergence'] | df['hidden_bearish_div']) &
            df['current_downtrend']
        )
        df.loc[sell_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def _add_higher_tf_trend(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add higher timeframe trend information."""
        # Calculate trend on higher TF
        htf = self.higher_tf_data.copy()
        htf['htf_ema_fast'] = ema(htf['close'], self.params['trend_ema_fast'])
        htf['htf_ema_slow'] = ema(htf['close'], self.params['trend_ema_slow'])
        htf['htf_uptrend'] = htf['htf_ema_fast'] > htf['htf_ema_slow']
        htf['htf_downtrend'] = htf['htf_ema_fast'] < htf['htf_ema_slow']
        
        # Map higher TF trend to lower TF
        # For each bar in df, find the corresponding higher TF bar
        df['higher_tf_uptrend'] = False
        df['higher_tf_downtrend'] = False
        
        for idx in df.index:
            # Find the most recent higher TF bar before this time
            htf_before = htf[htf.index <= idx]
            if len(htf_before) > 0:
                last_htf_idx = htf_before.index[-1]
                df.loc[idx, 'higher_tf_uptrend'] = htf.loc[last_htf_idx, 'htf_uptrend']
                df.loc[idx, 'higher_tf_downtrend'] = htf.loc[last_htf_idx, 'htf_downtrend']
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, 
                           direction: Signal) -> float:
        """
        Calculate stop loss using ATR.
        """
        atr_val = df.loc[idx, 'atr']
        multiplier = self.params['atr_multiplier']
        
        if direction == Signal.BUY:
            return df.loc[idx, 'low'] - (atr_val * multiplier)
        else:
            return df.loc[idx, 'high'] + (atr_val * multiplier)
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int,
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """
        Calculate take profit based on risk-reward ratio.
        """
        risk = abs(entry_price - stop_loss)
        reward = risk * 2.5  # 2.5:1 R:R
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
