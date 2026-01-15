"""
Central Pivot Range (CPR) Strategy

Uses the daily pivot range to identify bullish/bearish bias and key S/R zones.
Based on Mark Fisher's "The Logical Trader" methodology.

Rules:
- Long: Price bounces off CPR acting as support (previous close above range)
- Short: Price rejects CPR acting as resistance (previous close below range)
- Stop Loss: Other side of the pivot range
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.trend import central_pivot_range
from ..indicators.volatility import atr


class CPRStrategy(BaseStrategy):
    """
    Central Pivot Range Trading Strategy.
    
    Uses daily pivot range for intraday support/resistance trading.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'atr_period': 14,
            'atr_sl_multiplier': 1.5,
            'risk_reward': 2.0,
            'min_cpr_width_atr': 0.3,  # Minimum CPR width as multiple of ATR
            'max_cpr_width_atr': 2.0,  # Maximum CPR width
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.name = "CPR_Strategy"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate trading signals based on CPR."""
        df = df.copy()
        self.validate_data(df)
        
        # Add CPR levels
        df = central_pivot_range(df)
        
        # Add ATR for stop loss and filtering
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Initialize signal column
        df['signal'] = 0
        
        # Skip if not enough data
        if len(df) < self.params['atr_period'] + 2:
            return df
        
        for i in range(self.params['atr_period'] + 1, len(df)):
            idx = df.index[i]
            prev_idx = df.index[i - 1]
            
            # Skip if CPR data not available
            if pd.isna(df.loc[idx, 'cpr_pivot']) or pd.isna(df.loc[idx, 'atr']):
                continue
            
            current_close = df.loc[idx, 'close']
            current_low = df.loc[idx, 'low']
            current_high = df.loc[idx, 'high']
            prev_close = df.loc[prev_idx, 'close']
            
            cpr_tc = df.loc[idx, 'cpr_tc']
            cpr_bc = df.loc[idx, 'cpr_bc']
            cpr_pivot = df.loc[idx, 'cpr_pivot']
            cpr_width = df.loc[idx, 'cpr_width']
            current_atr = df.loc[idx, 'atr']
            
            # Filter: CPR width should be reasonable
            min_width = current_atr * self.params['min_cpr_width_atr']
            max_width = current_atr * self.params['max_cpr_width_atr']
            
            if cpr_width < min_width or cpr_width > max_width:
                continue
            
            # LONG SIGNAL: Bullish bias + price bounces off CPR support
            if df.loc[idx, 'cpr_bullish']:
                # Price touched CPR zone and bounced (low touched BC/TC area)
                touched_support = current_low <= cpr_tc * 1.002 and current_low >= cpr_bc * 0.998
                closed_above = current_close > cpr_tc
                
                if touched_support and closed_above:
                    df.loc[idx, 'signal'] = Signal.BUY.value
            
            # SHORT SIGNAL: Bearish bias + price rejects CPR resistance
            elif df.loc[idx, 'cpr_bearish']:
                # Price touched CPR zone and rejected (high touched BC/TC area)
                touched_resistance = current_high >= cpr_bc * 0.998 and current_high <= cpr_tc * 1.002
                closed_below = current_close < cpr_bc
                
                if touched_resistance and closed_below:
                    df.loc[idx, 'signal'] = Signal.SELL.value
            
            # BREAKOUT SIGNALS
            # Bullish breakout: Price breaks above CPR resistance in bearish bias
            elif df.loc[idx, 'cpr_bearish']:
                prev_below = prev_close < cpr_tc
                current_above = current_close > cpr_tc * 1.005  # Clear break
                
                if prev_below and current_above:
                    df.loc[idx, 'signal'] = Signal.BUY.value
            
            # Bearish breakout: Price breaks below CPR support in bullish bias
            elif df.loc[idx, 'cpr_bullish']:
                prev_above = prev_close > cpr_bc
                current_below = current_close < cpr_bc * 0.995  # Clear break
                
                if prev_above and current_below:
                    df.loc[idx, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss based on CPR and ATR."""
        current_atr = df.loc[idx, 'atr']
        entry_price = df.loc[idx, 'close']
        
        cpr_tc = df.loc[idx, 'cpr_tc']
        cpr_bc = df.loc[idx, 'cpr_bc']
        
        if direction == Signal.BUY:
            # Stop below CPR bottom or ATR-based, whichever is tighter but reasonable
            cpr_stop = cpr_bc * 0.998
            atr_stop = entry_price - (current_atr * self.params['atr_sl_multiplier'])
            return max(cpr_stop, atr_stop)  # Use tighter stop
        else:
            # Stop above CPR top or ATR-based
            cpr_stop = cpr_tc * 1.002
            atr_stop = entry_price + (current_atr * self.params['atr_sl_multiplier'])
            return min(cpr_stop, atr_stop)  # Use tighter stop
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, direction: Signal,
                             entry_price: float, stop_loss: float) -> float:
        """Calculate take profit based on risk-reward ratio."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            # Use R1 or R2 as potential targets
            r1 = df.loc[idx, 'cpr_r1']
            target = entry_price + reward
            return max(target, r1) if not pd.isna(r1) else target
        else:
            # Use S1 or S2 as potential targets
            s1 = df.loc[idx, 'cpr_s1']
            target = entry_price - reward
            return min(target, s1) if not pd.isna(s1) else target
