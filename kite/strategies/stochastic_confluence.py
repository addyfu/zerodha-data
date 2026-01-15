"""
Strategy 8: Stochastic Confluence Strategy

This strategy uses 200 EMA + Stochastic + S/R for confluence entries.
- Find confluence of static S/R + 200 EMA + Stochastic divergence
- Entry on Stochastic crossover at confluence area
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

from kite.strategies.base_strategy import BaseStrategy, Signal
from kite.indicators.moving_averages import ema
from kite.indicators.oscillators import stochastic, stochastic_crossover
from kite.indicators.volatility import atr
from kite.indicators.support_resistance import add_support_resistance
from kite.config import strategy_params


class StochasticConfluenceStrategy(BaseStrategy):
    """
    Stochastic Confluence Strategy.
    
    Combines 200 EMA, Stochastic, and S/R for high-probability entries.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = strategy_params.stochastic_confluence.copy()
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "Stochastic_Confluence"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate buy/sell signals based on confluence.
        
        Signal Logic:
        - BUY: Price at 200 EMA + near support + Stochastic oversold crossover
        - SELL: Price at 200 EMA + near resistance + Stochastic overbought crossover
        """
        self.validate_data(df)
        df = df.copy()
        
        # Calculate 200 EMA
        df['ema_200'] = ema(df['close'], self.params['ema_period'])
        
        # Calculate Stochastic
        df['stoch_k'], df['stoch_d'] = stochastic(
            df, 
            self.params['stoch_k'],
            self.params['stoch_d'],
            self.params['stoch_smooth']
        )
        
        # Calculate ATR
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Add S/R levels
        df = add_support_resistance(df, lookback=50, num_levels=2)
        
        # Stochastic crossover
        df['stoch_cross'] = stochastic_crossover(df['stoch_k'], df['stoch_d'])
        
        # Price near 200 EMA (within 1 ATR)
        ema_tolerance = df['atr']
        df['near_ema_200'] = (
            (df['low'] <= df['ema_200'] + ema_tolerance) &
            (df['high'] >= df['ema_200'] - ema_tolerance)
        )
        
        # Price near support/resistance
        sr_tolerance = df['atr'] * 0.5
        
        df['near_support'] = False
        df['near_resistance'] = False
        
        for i in range(len(df)):
            idx = df.index[i]
            low = df.loc[idx, 'low']
            high = df.loc[idx, 'high']
            tol = sr_tolerance.iloc[i] if isinstance(sr_tolerance, pd.Series) else sr_tolerance
            
            # Check support levels
            for level_col in ['support_1', 'support_2']:
                if level_col in df.columns:
                    level = df.loc[idx, level_col]
                    if pd.notna(level) and low <= level + tol and high >= level - tol:
                        df.loc[idx, 'near_support'] = True
                        break
            
            # Check resistance levels
            for level_col in ['resistance_1', 'resistance_2']:
                if level_col in df.columns:
                    level = df.loc[idx, level_col]
                    if pd.notna(level) and low <= level + tol and high >= level - tol:
                        df.loc[idx, 'near_resistance'] = True
                        break
        
        # Stochastic conditions
        df['stoch_oversold'] = df['stoch_k'] < self.params['oversold']
        df['stoch_overbought'] = df['stoch_k'] > self.params['overbought']
        
        # Generate signals
        df['signal'] = 0
        
        # BUY: Confluence of 200 EMA + support + stochastic bullish crossover from oversold
        buy_condition = (
            df['near_ema_200'] &
            df['near_support'] &
            (df['stoch_cross'] == 1) &
            (df['stoch_k'].shift(1) < self.params['oversold'] + 10)
        )
        df.loc[buy_condition, 'signal'] = Signal.BUY.value
        
        # SELL: Confluence of 200 EMA + resistance + stochastic bearish crossover from overbought
        sell_condition = (
            df['near_ema_200'] &
            df['near_resistance'] &
            (df['stoch_cross'] == -1) &
            (df['stoch_k'].shift(1) > self.params['overbought'] - 10)
        )
        df.loc[sell_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, 
                           direction: Signal) -> float:
        """
        Calculate stop loss below/above the confluence area.
        """
        atr_val = df.loc[idx, 'atr']
        multiplier = self.params['atr_multiplier']
        
        if direction == Signal.BUY:
            # Stop below confluence area
            ema_200 = df.loc[idx, 'ema_200']
            support = df.loc[idx, 'support_1'] if pd.notna(df.loc[idx, 'support_1']) else df.loc[idx, 'low']
            confluence_low = min(ema_200, support)
            stop = confluence_low - (atr_val * multiplier)
        else:
            # Stop above confluence area
            ema_200 = df.loc[idx, 'ema_200']
            resistance = df.loc[idx, 'resistance_1'] if pd.notna(df.loc[idx, 'resistance_1']) else df.loc[idx, 'high']
            confluence_high = max(ema_200, resistance)
            stop = confluence_high + (atr_val * multiplier)
        
        return stop
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int,
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """
        Calculate take profit based on risk-reward ratio.
        """
        risk = abs(entry_price - stop_loss)
        reward = risk * 2.0  # 2:1 R:R
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
