# Trading Strategies Module
from .base_strategy import BaseStrategy, Signal, TradeSignal
from .ema_21_55 import EMA2155Strategy
from .rsi_divergence import RSIDivergenceStrategy
from .vwap_pullback import VWAPPullbackStrategy
from .bb_squeeze import BBSqueezeStrategy
from .ema_3_scalping import EMA3ScalpingStrategy
from .supply_demand import SupplyDemandStrategy
from .stochastic_confluence import StochasticConfluenceStrategy
from .fib_3wave import Fib3WaveStrategy
from .multi_timeframe import MultiTimeframeStrategy

# New Underrated Strategies
from .cpr_strategy import CPRStrategy
from .chandelier_strategy import ChandelierExitStrategy
from .donchian_turtle import DonchianTurtleStrategy
from .vwma_sma_strategy import VWMASMAStrategy
from .hull_slope_strategy import HullSlopeStrategy
from .psar_ichimoku import PSARIchimokuStrategy
from .roc_ma_strategy import ROCMAStrategy
from .cmf_ichimoku import CMFIchimokuStrategy
from .alligator_strategy import AlligatorStrategy
from .fib_pivot_strategy import FibPivotStrategy

# Combined Strategy Framework
from .combined_strategy import (
    CombinedStrategy, CombinationMethod, COMBO_STRATEGIES,
    create_trend_momentum_combo,
    create_volume_price_combo,
    create_breakout_combo,
    create_sr_bounce_combo,
    create_trend_following_combo,
    create_best_performers_combo,
    create_scalping_combo,
)

# Batch 2 - More Underrated Strategies
from .adx_dmi_obv import ADXDMIOBVStrategy
from .cci_divergence import CCIDivergenceStrategy
from .stochrsi_macd import StochRSIMACDStrategy
from .tdi_strategy import TDIStrategy
from .ma_envelopes import MAEnvelopesStrategy
from .gmma_strategy import GMMAStrategy
from .mfi_divergence import MFIDivergenceStrategy
from .momentum_zero import MomentumZeroStrategy
from .ascending_triangle import AscendingTriangleStrategy
from .london_breakout import LondonBreakoutStrategy

__all__ = [
    'BaseStrategy',
    'Signal',
    'TradeSignal',
    # Original Strategies
    'EMA2155Strategy',
    'RSIDivergenceStrategy',
    'VWAPPullbackStrategy',
    'BBSqueezeStrategy',
    'EMA3ScalpingStrategy',
    'SupplyDemandStrategy',
    'StochasticConfluenceStrategy',
    'Fib3WaveStrategy',
    'MultiTimeframeStrategy',
    # New Underrated Strategies
    'CPRStrategy',
    'ChandelierExitStrategy',
    'DonchianTurtleStrategy',
    'VWMASMAStrategy',
    'HullSlopeStrategy',
    'PSARIchimokuStrategy',
    'ROCMAStrategy',
    'CMFIchimokuStrategy',
    'AlligatorStrategy',
    'FibPivotStrategy',
    # Combined Strategy Framework
    'CombinedStrategy',
    'CombinationMethod',
    'COMBO_STRATEGIES',
    'create_trend_momentum_combo',
    'create_volume_price_combo',
    'create_breakout_combo',
    'create_sr_bounce_combo',
    'create_trend_following_combo',
    'create_best_performers_combo',
    'create_scalping_combo',
    # Batch 2 - More Underrated Strategies
    'ADXDMIOBVStrategy',
    'CCIDivergenceStrategy',
    'StochRSIMACDStrategy',
    'TDIStrategy',
    'MAEnvelopesStrategy',
    'GMMAStrategy',
    'MFIDivergenceStrategy',
    'MomentumZeroStrategy',
    'AscendingTriangleStrategy',
    'LondonBreakoutStrategy',
]

# Strategy registry for easy access
STRATEGY_REGISTRY = {
    # Original Strategies
    'ema_21_55': EMA2155Strategy,
    'rsi_divergence': RSIDivergenceStrategy,
    'vwap_pullback': VWAPPullbackStrategy,
    'bb_squeeze': BBSqueezeStrategy,
    'ema_3_scalping': EMA3ScalpingStrategy,
    'supply_demand': SupplyDemandStrategy,
    'stochastic_confluence': StochasticConfluenceStrategy,
    'fib_3wave': Fib3WaveStrategy,
    'multi_timeframe': MultiTimeframeStrategy,
    # New Underrated Strategies
    'cpr': CPRStrategy,
    'chandelier_exit': ChandelierExitStrategy,
    'donchian_turtle': DonchianTurtleStrategy,
    'vwma_sma': VWMASMAStrategy,
    'hull_slope': HullSlopeStrategy,
    'psar_ichimoku': PSARIchimokuStrategy,
    'roc_ma': ROCMAStrategy,
    'cmf_ichimoku': CMFIchimokuStrategy,
    'alligator': AlligatorStrategy,
    'fib_pivot': FibPivotStrategy,
    # Batch 2 - More Underrated Strategies
    'adx_dmi_obv': ADXDMIOBVStrategy,
    'cci_divergence': CCIDivergenceStrategy,
    'stochrsi_macd': StochRSIMACDStrategy,
    'tdi': TDIStrategy,
    'ma_envelopes': MAEnvelopesStrategy,
    'gmma': GMMAStrategy,
    'mfi_divergence': MFIDivergenceStrategy,
    'momentum_zero': MomentumZeroStrategy,
    'ascending_triangle': AscendingTriangleStrategy,
    'london_breakout': LondonBreakoutStrategy,
}
