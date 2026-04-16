"""
Renko + SMA + OBV Strategy
- Simulates Renko-like behavior using ATR-based bricks
- Green brick above SMA + OBV rising = Long
- Red brick below SMA + OBV falling = Short
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_strategy import BaseStrategy, Signal
from ..indicators.volume import obv
from ..indicators.moving_averages import sma
from ..indicators.volatility import atr


class RenkoSMAOBVStrategy(BaseStrategy):
    """Renko-style Strategy with SMA and OBV."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'brick_atr_mult': 1.0,  # Brick size as ATR multiple
            'sma_period': 10,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'risk_reward': 2.0,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
    
    def _calculate_renko_bricks(self, df: pd.DataFrame, brick_size: pd.Series) -> pd.DataFrame:
        """Calculate Renko-like brick colors based on price movement."""
        df = df.copy()
        
        # Initialize brick tracking
        df['brick_color'] = 0  # 1 = green, -1 = red, 0 = none
        df['brick_high'] = np.nan
        df['brick_low'] = np.nan
        
        # Use close price for brick calculation
        current_brick_high = df['close'].iloc[0]
        current_brick_low = df['close'].iloc[0]
        
        for i in range(1, len(df)):
            price = df['close'].iloc[i]
            brick = brick_size.iloc[i] if not pd.isna(brick_size.iloc[i]) else brick_size.mean()
            
            # Check for new green brick
            if price >= current_brick_high + brick:
                df.iloc[i, df.columns.get_loc('brick_color')] = 1
                current_brick_low = current_brick_high
                current_brick_high = price
            # Check for new red brick
            elif price <= current_brick_low - brick:
                df.iloc[i, df.columns.get_loc('brick_color')] = -1
                current_brick_high = current_brick_low
                current_brick_low = price
            
            df.iloc[i, df.columns.get_loc('brick_high')] = current_brick_high
            df.iloc[i, df.columns.get_loc('brick_low')] = current_brick_low
        
        return df
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate signals based on Renko + SMA + OBV."""
        df = df.copy()
        self.validate_data(df)
        
        # Calculate indicators
        df['atr'] = atr(df, self.params['atr_period'])
        brick_size = df['atr'] * self.params['brick_atr_mult']
        
        # Calculate Renko bricks
        df = self._calculate_renko_bricks(df, brick_size)
        
        # SMA of brick highs/lows (simulating Renko SMA)
        df['renko_sma'] = sma(df['close'], self.params['sma_period'])
        df['sma_slope'] = df['renko_sma'] - df['renko_sma'].shift(1)
        
        # OBV
        df['obv'] = obv(df)
        df['obv_rising'] = df['obv'] > df['obv'].shift(5)
        df['obv_falling'] = df['obv'] < df['obv'].shift(5)
        
        # Initialize signal column
        df['signal'] = 0
        
        # Long: Green brick + price above SMA + SMA rising + OBV rising
        long_condition = (
            (df['brick_color'] == 1) &
            (df['close'] > df['renko_sma']) &
            (df['sma_slope'] > 0) &
            df['obv_rising']
        )
        
        # Short: Red brick + price below SMA + SMA falling + OBV falling
        short_condition = (
            (df['brick_color'] == -1) &
            (df['close'] < df['renko_sma']) &
            (df['sma_slope'] < 0) &
            df['obv_falling']
        )
        
        df.loc[long_condition, 'signal'] = Signal.BUY.value
        df.loc[short_condition, 'signal'] = Signal.SELL.value
        
        return df
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Stop loss 2 bricks from entry."""
        atr_val = df.loc[idx, 'atr']
        entry_price = df.loc[idx, 'close']
        brick_size = atr_val * self.params['brick_atr_mult']
        
        if direction == Signal.BUY:
            return entry_price - (2 * brick_size)
        else:
            return entry_price + (2 * brick_size)
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, 
                             direction: Signal, entry_price: float,
                             stop_loss: float) -> float:
        """Target 3+ bricks."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward
