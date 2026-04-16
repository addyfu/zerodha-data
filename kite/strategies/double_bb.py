"""
Double Bollinger Bands Strategy
- BB(20,1) and BB(20,2) create zones
- Buy Zone: Price between upper BB(1) and upper BB(2)
- Sell Zone: Price between lower BB(1) and lower BB(2)
- Neutral Zone: Between inner bands
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volatility import bollinger_bands, atr


class DoubleBBStrategy(BaseStrategy):
    """Double Bollinger Bands Strategy."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'bb_period': 20,
            'bb_std_inner': 1.0,
            'bb_std_outer': 2.0,
            'confirmation_bars': 2,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 1.5,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on Double BB zones."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate inner BB (1 std)
        upper_inner, middle, lower_inner = bollinger_bands(
            df, 
            self.params['bb_period'],
            self.params['bb_std_inner']
        )
        
        # Calculate outer BB (2 std)
        upper_outer, _, lower_outer = bollinger_bands(
            df, 
            self.params['bb_period'],
            self.params['bb_std_outer']
        )
        
        df['bb_upper_inner'] = upper_inner
        df['bb_upper_outer'] = upper_outer
        df['bb_lower_inner'] = lower_inner
        df['bb_lower_outer'] = lower_outer
        df['bb_middle'] = middle
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Define zones
        # Buy zone: between upper inner and upper outer
        df['in_buy_zone'] = (df['close'] > upper_inner) & (df['close'] <= upper_outer)
        # Sell zone: between lower inner and lower outer
        df['in_sell_zone'] = (df['close'] < lower_inner) & (df['close'] >= lower_outer)
        # Neutral zone: between inner bands
        df['in_neutral'] = (df['close'] >= lower_inner) & (df['close'] <= upper_inner)
        
        # Initialize signal column
        df['signal'] = 0
        
        conf_bars = self.params['confirmation_bars']
        
        # Long: Price enters and stays in buy zone
        in_buy_zone_confirmed = df['in_buy_zone'].copy()
        for i in range(1, conf_bars):
            in_buy_zone_confirmed &= df['in_buy_zone'].shift(i)
        
        # Entry when first entering buy zone (was in neutral)
        long_condition = in_buy_zone_confirmed & df['in_neutral'].shift(conf_bars)
        
        # Short: Price enters and stays in sell zone
        in_sell_zone_confirmed = df['in_sell_zone'].copy()
        for i in range(1, conf_bars):
            in_sell_zone_confirmed &= df['in_sell_zone'].shift(i)
        
        short_condition = in_sell_zone_confirmed & df['in_neutral'].shift(conf_bars)
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
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
        """Exit when price returns to neutral zone (middle band)."""
        return df.loc[idx, 'bb_middle']
