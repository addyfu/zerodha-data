"""
MACD Divergence Strategy (Hidden Divergence for trend continuation)
- Hidden Bullish: Price higher low + MACD lower low = Buy in uptrend
- Hidden Bearish: Price lower high + MACD higher high = Sell in downtrend
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import macd
from ..indicators.moving_averages import ema
from ..indicators.volatility import atr


class MACDDivergenceStrategy(BaseStrategy):
    """MACD Hidden Divergence Strategy for trend continuation."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'fast_period': 12,
            'slow_period': 26,
            'signal_period': 9,
            'ema_period': 50,
            'divergence_lookback': 20,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def _find_swing_points(self, series: pd.Series, lookback: int = 5) -> tuple:
        """Find swing highs and lows."""
        swing_highs = []
        swing_lows = []
        
        for i in range(lookback, len(series) - lookback):
            # Swing high: higher than surrounding bars
            if series.iloc[i] == series.iloc[i-lookback:i+lookback+1].max():
                swing_highs.append((i, series.iloc[i]))
            # Swing low: lower than surrounding bars
            if series.iloc[i] == series.iloc[i-lookback:i+lookback+1].min():
                swing_lows.append((i, series.iloc[i]))
        
        return swing_highs, swing_lows
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on MACD hidden divergence."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate indicators
        macd_line, signal_line, histogram = macd(
            df['close'], 
            self.params['fast_period'],
            self.params['slow_period'],
            self.params['signal_period']
        )
        
        df['macd'] = macd_line
        df['macd_signal'] = signal_line
        df['macd_hist'] = histogram
        df['ema'] = ema(df['close'], self.params['ema_period'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        lookback = self.params['divergence_lookback']
        
        for i in range(lookback * 2, len(df)):
            window_price = df['low'].iloc[i-lookback:i+1]
            window_price_high = df['high'].iloc[i-lookback:i+1]
            window_macd = df['macd'].iloc[i-lookback:i+1]
            
            current_idx = df.index[i]
            current_price = df.loc[current_idx, 'close']
            current_ema = df.loc[current_idx, 'ema']
            
            # Find recent swing lows for hidden bullish divergence
            price_lows = window_price.nsmallest(2)
            macd_at_price_lows = window_macd.iloc[window_price.values.argsort()[:2]]
            
            # Hidden Bullish: Price higher low, MACD lower low (in uptrend)
            if len(price_lows) >= 2 and current_price > current_ema:
                if (price_lows.iloc[0] > price_lows.iloc[1] and 
                    macd_at_price_lows.iloc[0] < macd_at_price_lows.iloc[1]):
                    # Confirm with MACD crossing signal line
                    if (df.loc[current_idx, 'macd'] > df.loc[current_idx, 'macd_signal'] and
                        df['macd'].iloc[i-1] <= df['macd_signal'].iloc[i-1]):
                        df.loc[current_idx, 'signal'] = Signal.BUY.value
            
            # Find recent swing highs for hidden bearish divergence
            price_highs = window_price_high.nlargest(2)
            macd_at_price_highs = window_macd.iloc[window_price_high.values.argsort()[-2:]]
            
            # Hidden Bearish: Price lower high, MACD higher high (in downtrend)
            if len(price_highs) >= 2 and current_price < current_ema:
                if (price_highs.iloc[0] < price_highs.iloc[1] and 
                    macd_at_price_highs.iloc[0] > macd_at_price_highs.iloc[1]):
                    # Confirm with MACD crossing below signal line
                    if (df.loc[current_idx, 'macd'] < df.loc[current_idx, 'macd_signal'] and
                        df['macd'].iloc[i-1] >= df['macd_signal'].iloc[i-1]):
                        df.loc[current_idx, 'signal'] = Signal.SELL.value
        
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
