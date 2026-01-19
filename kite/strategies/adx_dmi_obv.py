"""
ADX + DMI + OBV Strategy

Uses ADX for trend strength, DMI for direction, and OBV for volume confirmation.
- ADX > 25 indicates strong trend
- +DMI > -DMI = bullish, -DMI > +DMI = bearish
- OBV above/below its MA confirms momentum
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.oscillators import adx, obv
from ..indicators.moving_averages import sma
from ..indicators.volatility import atr


class ADXDMIOBVStrategy(BaseStrategy):
    """ADX + DMI + OBV trend following strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'adx_period': 14,
            'adx_threshold': 25,
            'obv_ma_period': 100,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "ADX_DMI_OBV"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        self.validate_data(df)
        
        # Calculate indicators
        df['adx'], df['plus_di'], df['minus_di'] = adx(df, self.params['adx_period'])
        df['obv'] = obv(df)
        df['obv_ma'] = sma(df['obv'], self.params['obv_ma_period'])
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal
        df['signal'] = 0
        
        # Strong trend filter
        strong_trend = df['adx'] > self.params['adx_threshold']
        
        # DMI crossover signals
        dmi_bullish = df['plus_di'] > df['minus_di']
        dmi_bearish = df['minus_di'] > df['plus_di']
        
        # DMI crossover detection
        dmi_cross_up = dmi_bullish & ~dmi_bullish.shift(1).fillna(False)
        dmi_cross_down = dmi_bearish & ~dmi_bearish.shift(1).fillna(False)
        
        # OBV momentum confirmation
        obv_bullish = df['obv'] > df['obv_ma']
        obv_bearish = df['obv'] < df['obv_ma']
        
        # Generate signals
        # Buy: ADX > 25, +DMI crosses above -DMI, OBV > OBV MA
        buy_signal = strong_trend & dmi_cross_up & obv_bullish
        
        # Sell: ADX > 25, -DMI crosses above +DMI, OBV < OBV MA
        sell_signal = strong_trend & dmi_cross_down & obv_bearish
        
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
