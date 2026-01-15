"""
Combined Multi-Strategy Framework

Combines multiple strategies using different voting/confirmation methods:
1. Unanimous: ALL strategies must agree
2. Majority: More than 50% must agree
3. Weighted: Strategies weighted by their historical performance
4. Confirmation: Primary strategy + confirmation from others
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Type, Tuple
from enum import Enum

from .base_strategy import BaseStrategy, Signal


class CombinationMethod(Enum):
    UNANIMOUS = "unanimous"      # All must agree
    MAJORITY = "majority"        # >50% must agree
    WEIGHTED = "weighted"        # Weighted by performance
    TWO_OF_THREE = "two_of_three"  # At least 2 of 3
    PRIMARY_CONFIRM = "primary_confirm"  # Primary + 1 confirmation


class CombinedStrategy(BaseStrategy):
    """
    Combines multiple strategies for higher probability signals.
    """
    
    def __init__(self, 
                 strategies: List[BaseStrategy],
                 method: CombinationMethod = CombinationMethod.MAJORITY,
                 weights: List[float] = None,
                 params: Dict[str, Any] = None):
        """
        Initialize combined strategy.
        
        Args:
            strategies: List of strategy instances to combine
            method: How to combine signals
            weights: Optional weights for weighted method
            params: Additional parameters
        """
        default_params = {
            'atr_period': 14,
            'atr_sl_multiplier': 2.0,
            'risk_reward': 2.0,
            'min_agreement': 0.5,  # For majority voting
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        
        self.strategies = strategies
        self.method = method
        self.weights = weights or [1.0] * len(strategies)
        
        # Normalize weights
        total_weight = sum(self.weights)
        self.weights = [w / total_weight for w in self.weights]
        
        # Build name from component strategies
        strategy_names = [s.name for s in strategies]
        self.name = f"Combined_{method.value}_{'+'.join(strategy_names[:3])}"
        if len(strategy_names) > 3:
            self.name += f"_+{len(strategy_names)-3}more"
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate combined signals from all strategies."""
        df = df.copy()
        self.validate_data(df)
        
        # Get signals from each strategy
        strategy_signals = []
        for strategy in self.strategies:
            try:
                result_df = strategy.generate_signals(df.copy())
                strategy_signals.append(result_df['signal'].values)
            except Exception as e:
                # If a strategy fails, use neutral signals
                strategy_signals.append(np.zeros(len(df)))
        
        # Convert to numpy array for easier manipulation
        signals_matrix = np.array(strategy_signals)  # Shape: (n_strategies, n_bars)
        
        # Initialize combined signal
        df['signal'] = 0
        
        # Add ATR for stop loss calculations
        from ..indicators.volatility import atr
        df['atr'] = atr(df, self.params['atr_period'])
        
        # Combine signals based on method
        if self.method == CombinationMethod.UNANIMOUS:
            df['signal'] = self._unanimous_signals(signals_matrix)
        elif self.method == CombinationMethod.MAJORITY:
            df['signal'] = self._majority_signals(signals_matrix)
        elif self.method == CombinationMethod.WEIGHTED:
            df['signal'] = self._weighted_signals(signals_matrix)
        elif self.method == CombinationMethod.TWO_OF_THREE:
            df['signal'] = self._two_of_three_signals(signals_matrix)
        elif self.method == CombinationMethod.PRIMARY_CONFIRM:
            df['signal'] = self._primary_confirm_signals(signals_matrix)
        
        # Store individual strategy signals for analysis
        for i, strategy in enumerate(self.strategies):
            df[f'signal_{strategy.name}'] = signals_matrix[i]
        
        return df
    
    def _unanimous_signals(self, signals_matrix: np.ndarray) -> np.ndarray:
        """All strategies must agree."""
        n_bars = signals_matrix.shape[1]
        combined = np.zeros(n_bars)
        
        for i in range(n_bars):
            signals = signals_matrix[:, i]
            
            # All must be BUY
            if np.all(signals == Signal.BUY.value):
                combined[i] = Signal.BUY.value
            # All must be SELL
            elif np.all(signals == Signal.SELL.value):
                combined[i] = Signal.SELL.value
        
        return combined
    
    def _majority_signals(self, signals_matrix: np.ndarray) -> np.ndarray:
        """More than 50% must agree."""
        n_strategies = signals_matrix.shape[0]
        n_bars = signals_matrix.shape[1]
        combined = np.zeros(n_bars)
        
        threshold = n_strategies * self.params['min_agreement']
        
        for i in range(n_bars):
            signals = signals_matrix[:, i]
            
            buy_count = np.sum(signals == Signal.BUY.value)
            sell_count = np.sum(signals == Signal.SELL.value)
            
            if buy_count >= threshold:
                combined[i] = Signal.BUY.value
            elif sell_count >= threshold:
                combined[i] = Signal.SELL.value
        
        return combined
    
    def _weighted_signals(self, signals_matrix: np.ndarray) -> np.ndarray:
        """Weighted voting based on strategy weights."""
        n_bars = signals_matrix.shape[1]
        combined = np.zeros(n_bars)
        
        for i in range(n_bars):
            signals = signals_matrix[:, i]
            
            buy_weight = sum(w for w, s in zip(self.weights, signals) if s == Signal.BUY.value)
            sell_weight = sum(w for w, s in zip(self.weights, signals) if s == Signal.SELL.value)
            
            # Need >50% weighted agreement
            if buy_weight > 0.5:
                combined[i] = Signal.BUY.value
            elif sell_weight > 0.5:
                combined[i] = Signal.SELL.value
        
        return combined
    
    def _two_of_three_signals(self, signals_matrix: np.ndarray) -> np.ndarray:
        """At least 2 out of 3 (or 2 out of n) must agree."""
        n_bars = signals_matrix.shape[1]
        combined = np.zeros(n_bars)
        
        for i in range(n_bars):
            signals = signals_matrix[:, i]
            
            buy_count = np.sum(signals == Signal.BUY.value)
            sell_count = np.sum(signals == Signal.SELL.value)
            
            if buy_count >= 2:
                combined[i] = Signal.BUY.value
            elif sell_count >= 2:
                combined[i] = Signal.SELL.value
        
        return combined
    
    def _primary_confirm_signals(self, signals_matrix: np.ndarray) -> np.ndarray:
        """First strategy is primary, needs at least 1 confirmation."""
        n_strategies = signals_matrix.shape[0]
        n_bars = signals_matrix.shape[1]
        combined = np.zeros(n_bars)
        
        if n_strategies < 2:
            return signals_matrix[0] if n_strategies == 1 else combined
        
        primary_signals = signals_matrix[0]
        confirm_signals = signals_matrix[1:]
        
        for i in range(n_bars):
            primary = primary_signals[i]
            
            if primary == Signal.BUY.value:
                # Need at least 1 confirmation
                if np.any(confirm_signals[:, i] == Signal.BUY.value):
                    combined[i] = Signal.BUY.value
            elif primary == Signal.SELL.value:
                if np.any(confirm_signals[:, i] == Signal.SELL.value):
                    combined[i] = Signal.SELL.value
        
        return combined
    
    def calculate_stop_loss(self, df: pd.DataFrame, idx: int, direction: Signal) -> float:
        """Calculate stop loss using ATR."""
        entry_price = df.loc[idx, 'close']
        current_atr = df.loc[idx, 'atr']
        
        if direction == Signal.BUY:
            return entry_price - (current_atr * self.params['atr_sl_multiplier'])
        else:
            return entry_price + (current_atr * self.params['atr_sl_multiplier'])
    
    def calculate_take_profit(self, df: pd.DataFrame, idx: int, direction: Signal,
                             entry_price: float, stop_loss: float) -> float:
        """Calculate take profit based on risk-reward ratio."""
        risk = abs(entry_price - stop_loss)
        reward = risk * self.params['risk_reward']
        
        if direction == Signal.BUY:
            return entry_price + reward
        else:
            return entry_price - reward


# Pre-built combination templates
def create_trend_momentum_combo() -> CombinedStrategy:
    """Trend + Momentum combination: EMA trend + RSI confirmation."""
    from .ema_21_55 import EMA2155Strategy
    from .rsi_divergence import RSIDivergenceStrategy
    from .hull_slope_strategy import HullSlopeStrategy
    
    strategies = [
        EMA2155Strategy(),
        RSIDivergenceStrategy(),
        HullSlopeStrategy(),
    ]
    return CombinedStrategy(strategies, CombinationMethod.TWO_OF_THREE)


def create_volume_price_combo() -> CombinedStrategy:
    """Volume + Price combination: VWAP + CMF + OBV-based."""
    from .vwap_pullback import VWAPPullbackStrategy
    from .cmf_ichimoku import CMFIchimokuStrategy
    from .vwma_sma_strategy import VWMASMAStrategy
    
    strategies = [
        VWAPPullbackStrategy(),
        CMFIchimokuStrategy(),
        VWMASMAStrategy(),
    ]
    return CombinedStrategy(strategies, CombinationMethod.TWO_OF_THREE)


def create_breakout_combo() -> CombinedStrategy:
    """Breakout combination: Donchian + BB Squeeze + Supply/Demand."""
    from .donchian_turtle import DonchianTurtleStrategy
    from .bb_squeeze import BBSqueezeStrategy
    from .supply_demand import SupplyDemandStrategy
    
    strategies = [
        DonchianTurtleStrategy(),
        BBSqueezeStrategy(),
        SupplyDemandStrategy(),
    ]
    return CombinedStrategy(strategies, CombinationMethod.TWO_OF_THREE)


def create_sr_bounce_combo() -> CombinedStrategy:
    """Support/Resistance bounce: Fib Pivot + CPR + Fib 3Wave."""
    from .fib_pivot_strategy import FibPivotStrategy
    from .cpr_strategy import CPRStrategy
    from .fib_3wave import Fib3WaveStrategy
    
    strategies = [
        Fib3WaveStrategy(),  # Primary (best performer)
        FibPivotStrategy(),
        CPRStrategy(),
    ]
    return CombinedStrategy(strategies, CombinationMethod.PRIMARY_CONFIRM)


def create_trend_following_combo() -> CombinedStrategy:
    """Trend following: Chandelier + PSAR + Alligator."""
    from .chandelier_strategy import ChandelierExitStrategy
    from .psar_ichimoku import PSARIchimokuStrategy
    from .alligator_strategy import AlligatorStrategy
    
    strategies = [
        ChandelierExitStrategy(),
        PSARIchimokuStrategy(),
        AlligatorStrategy(),
    ]
    return CombinedStrategy(strategies, CombinationMethod.MAJORITY)


def create_best_performers_combo() -> CombinedStrategy:
    """Top 3 best performing strategies combined."""
    from .fib_3wave import Fib3WaveStrategy
    from .ema_21_55 import EMA2155Strategy
    from .multi_timeframe import MultiTimeframeStrategy
    
    strategies = [
        Fib3WaveStrategy(),      # Weight: 0.5 (best Sharpe)
        EMA2155Strategy(),       # Weight: 0.3
        MultiTimeframeStrategy(), # Weight: 0.2
    ]
    return CombinedStrategy(
        strategies, 
        CombinationMethod.WEIGHTED,
        weights=[0.5, 0.3, 0.2]
    )


def create_scalping_combo() -> CombinedStrategy:
    """Scalping combination for intraday."""
    from .ema_3_scalping import EMA3ScalpingStrategy
    from .stochastic_confluence import StochasticConfluenceStrategy
    from .roc_ma_strategy import ROCMAStrategy
    
    strategies = [
        EMA3ScalpingStrategy(),
        StochasticConfluenceStrategy(),
        ROCMAStrategy(),
    ]
    return CombinedStrategy(strategies, CombinationMethod.TWO_OF_THREE)


# Registry of all combo strategies
COMBO_STRATEGIES = {
    'trend_momentum': create_trend_momentum_combo,
    'volume_price': create_volume_price_combo,
    'breakout': create_breakout_combo,
    'sr_bounce': create_sr_bounce_combo,
    'trend_following': create_trend_following_combo,
    'best_performers': create_best_performers_combo,
    'scalping': create_scalping_combo,
}
