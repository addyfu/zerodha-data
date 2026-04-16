"""
Regular Divergence Trading Strategy (Multi-Indicator)
- Bullish: Price lower low + Indicator higher low
- Bearish: Price higher high + Indicator lower high
- Uses RSI, MACD, or Stochastic
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import rsi, macd, stochastic
from ..indicators.volatility import atr


class RegularDivergenceStrategy(BaseStrategy):
    """Regular Divergence Strategy using multiple indicators."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'rsi_period': 14,
            'macd_fast': 12,
            'macd_slow': 26,
            'macd_signal': 9,
            'stoch_k': 14,
            'stoch_d': 3,
            'divergence_lookback': 20,
            'min_indicators': 2,  # Minimum indicators showing divergence
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def _detect_divergence(self, price: pd.Series, indicator: pd.Series, 
                          lookback: int, idx: int) -> tuple:
        """Detect bullish and bearish divergence."""
        if idx < lookback * 2:
            return False, False
        
        window_price = price.iloc[idx-lookback:idx+1]
        window_ind = indicator.iloc[idx-lookback:idx+1]
        
        current_price = price.iloc[idx]
        current_ind = indicator.iloc[idx]
        
        # Find swing lows for bullish divergence
        price_min_idx = window_price.idxmin()
        if price_min_idx != price.index[idx]:
            prev_price = price.loc[price_min_idx]
            prev_ind = indicator.loc[price_min_idx]
            
            # Bullish: Price lower low, indicator higher low
            bullish = (current_price < prev_price) and (current_ind > prev_ind)
        else:
            bullish = False
        
        # Find swing highs for bearish divergence
        price_max_idx = window_price.idxmax()
        if price_max_idx != price.index[idx]:
            prev_price = price.loc[price_max_idx]
            prev_ind = indicator.loc[price_max_idx]
            
            # Bearish: Price higher high, indicator lower high
            bearish = (current_price > prev_price) and (current_ind < prev_ind)
        else:
            bearish = False
        
        return bullish, bearish
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on multi-indicator divergence."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate indicators
        df['rsi'] = rsi(df['close'], self.params['rsi_period'])
        
        macd_line, signal_line, histogram = macd(
            df['close'],
            self.params['macd_fast'],
            self.params['macd_slow'],
            self.params['macd_signal']
        )
        df['macd'] = macd_line
        
        stoch_k, stoch_d = stochastic(df, self.params['stoch_k'], self.params['stoch_d'])
        df['stoch'] = stoch_k
        
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        lookback = self.params['divergence_lookback']
        min_ind = self.params['min_indicators']
        
        for i in range(lookback * 2, len(df)):
            idx = df.index[i]
            
            # Check divergence on each indicator
            rsi_bull, rsi_bear = self._detect_divergence(
                df['low'], df['rsi'], lookback, i
            )
            macd_bull, macd_bear = self._detect_divergence(
                df['low'], df['macd'], lookback, i
            )
            stoch_bull, stoch_bear = self._detect_divergence(
                df['low'], df['stoch'], lookback, i
            )
            
            # Count bullish divergences
            bullish_count = sum([rsi_bull, macd_bull, stoch_bull])
            bearish_count = sum([rsi_bear, macd_bear, stoch_bear])
            
            # Signal if minimum indicators show divergence
            if bullish_count >= min_ind:
                df.loc[idx, 'signal'] = Signal.BUY.value
            elif bearish_count >= min_ind:
                df.loc[idx, 'signal'] = Signal.SELL.value
        
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
