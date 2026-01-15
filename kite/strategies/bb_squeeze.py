"""
Strategy 4: Bollinger Bands Squeeze Breakout

This strategy identifies low-volatility periods (squeeze) and trades the breakout.
- Squeeze: When bands contract (low volatility)
- Breakout: When bands expand and price breaks out
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

from kite.strategies.base_strategy import BaseStrategy, Signal
from kite.indicators.volatility import (
    add_bollinger_bands, detect_bb_squeeze, atr
)
from kite.config import strategy_params


class BBSqueezeStrategy(BaseStrategy):
    """
    Bollinger Bands Squeeze Breakout Strategy.
    
    Trades breakouts after periods of low volatility (squeeze).
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = strategy_params.bb_squeeze.copy()
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "BB_Squeeze"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate buy/sell signals based on BB squeeze breakout.
        
        Signal Logic:
        - BUY: After squeeze, price breaks above upper band with expanding bands
        - SELL: After squeeze, price breaks below lower band with expanding bands
        """
        self.validate_data(df)
        df = df.copy()
        
        # Calculate Bollinger Bands
        df = add_bollinger_bands(df, self.params['bb_period'], self.params['bb_std'])
        
        # Detect squeeze
        df = detect_bb_squeeze(df, self.params['squeeze_threshold'])
        
        # Calculate ATR
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Band hooks (expansion detection)
        df['upper_hook'] = df['bb_upper'] > df['bb_upper'].shift(1)
        df['lower_hook'] = df['bb_lower'] < df['bb_lower'].shift(1)
        df['bands_expanding'] = df['upper_hook'] & df['lower_hook']
        
        # Price position relative to bands
        df['above_upper'] = df['close'] > df['bb_upper']
        df['below_lower'] = df['close'] < df['bb_lower']
        
        # Was in squeeze recently (within last 5 candles)
        df['was_squeezed'] = df['bb_squeeze'].rolling(window=5).max().shift(1) > 0
        
        # Strong candle (bullish or bearish)
        df['bullish_candle'] = (df['close'] > df['open']) & \
                               ((df['close'] - df['open']) > df['atr'] * 0.5)
        df['bearish_candle'] = (df['close'] < df['open']) & \
                               ((df['open'] - df['close']) > df['atr'] * 0.5)
        
        # Generate signals
        df['signal'] = 0
        
        # BUY: Was squeezed + bands expanding + close above upper band + bullish candle
        buy_condition = (
            df['was_squeezed'] &
            df['bands_expanding'] &
            df['above_upper'] &
            df['bullish_candle']
        )
        df.loc[buy_condition, 'signal'] = Signal.BUY.value
        
        # SELL: Was squeezed + bands expanding + close below lower band + bearish candle
        sell_condition = (
            df['was_squeezed'] &
            df['bands_expanding'] &
            df['below_lower'] &
            df['bearish_candle']
        )
        df.loc[sell_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, 
                           direction: Signal) -> float:
        """
        Calculate stop loss at the middle band or ATR-based.
        """
        atr_val = df.loc[idx, 'atr']
        middle_band = df.loc[idx, 'bb_middle']
        multiplier = self.params['atr_multiplier']
        
        if direction == Signal.BUY:
            # Stop at middle band or ATR below entry
            stop = min(middle_band, df.loc[idx, 'close'] - (atr_val * multiplier))
        else:
            # Stop at middle band or ATR above entry
            stop = max(middle_band, df.loc[idx, 'close'] + (atr_val * multiplier))
        
        return stop
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int,
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """
        Calculate take profit based on risk-reward ratio.
        """
        risk = abs(entry_price - stop_loss)
        reward = risk * 2.5  # 2.5:1 R:R for breakout trades
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
