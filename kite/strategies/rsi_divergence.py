"""
Strategy 2: RSI Divergence + Support/Resistance Confluence

This strategy trades divergences ONLY at key support/resistance levels.
- Regular Divergence: Price makes higher high, RSI makes lower high = potential reversal
- Hidden Divergence: Price makes higher low, RSI makes lower low = trend continuation
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

from kite.strategies.base_strategy import BaseStrategy, Signal
from kite.indicators.oscillators import rsi, rsi_divergence
from kite.indicators.volatility import atr
from kite.indicators.support_resistance import add_support_resistance, detect_sr_touch
from kite.config import strategy_params


class RSIDivergenceStrategy(BaseStrategy):
    """
    RSI Divergence Strategy with S/R Confluence.
    
    Trades divergences only when price is at key support/resistance levels.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = strategy_params.rsi_divergence.copy()
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "RSI_Divergence"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate buy/sell signals based on RSI divergence at S/R levels.
        
        Signal Logic:
        - BUY: Bullish divergence at support level
        - SELL: Bearish divergence at resistance level
        """
        self.validate_data(df)
        df = df.copy()
        
        # Calculate RSI
        rsi_period = self.params['rsi_period']
        df[f'rsi_{rsi_period}'] = rsi(df['close'], rsi_period)
        
        # Calculate ATR
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Detect divergences
        df = rsi_divergence(df, f'rsi_{rsi_period}', 'close', self.params['lookback'])
        
        # Add support/resistance levels
        df = add_support_resistance(df, lookback=50, num_levels=3)
        
        # Detect S/R touches
        df = detect_sr_touch(df, tolerance=0.01)
        
        # Generate signals
        df['signal'] = 0
        
        # BUY: Bullish divergence at support
        buy_condition = (
            (df['bullish_divergence'] | df['hidden_bullish_div']) &
            df['support_touch'] &
            (df[f'rsi_{rsi_period}'] < self.params['oversold'] + 20)  # RSI relatively low
        )
        df.loc[buy_condition, 'signal'] = Signal.BUY.value
        
        # SELL: Bearish divergence at resistance
        sell_condition = (
            (df['bearish_divergence'] | df['hidden_bearish_div']) &
            df['resistance_touch'] &
            (df[f'rsi_{rsi_period}'] > self.params['overbought'] - 20)  # RSI relatively high
        )
        df.loc[sell_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, 
                           direction: Signal) -> float:
        """
        Calculate stop loss using ATR beyond the S/R level.
        """
        atr_val = df.loc[idx, 'atr']
        multiplier = self.params['atr_multiplier']
        
        if direction == Signal.BUY:
            # Stop below the support level
            support = df.loc[idx, 'support_1']
            if pd.isna(support):
                support = df.loc[idx, 'low']
            stop = support - (atr_val * multiplier)
        else:
            # Stop above the resistance level
            resistance = df.loc[idx, 'resistance_1']
            if pd.isna(resistance):
                resistance = df.loc[idx, 'high']
            stop = resistance + (atr_val * multiplier)
        
        return stop
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int,
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """
        Calculate take profit - target the opposite S/R level or 2:1 R:R.
        """
        risk = abs(entry_price - stop_loss)
        
        if direction == Signal.BUY:
            # Target resistance or 2:1
            resistance = df.loc[idx, 'resistance_1']
            if pd.notna(resistance) and resistance > entry_price:
                return resistance
            return entry_price + (risk * 2)
        else:
            # Target support or 2:1
            support = df.loc[idx, 'support_1']
            if pd.notna(support) and support < entry_price:
                return support
            return entry_price - (risk * 2)
