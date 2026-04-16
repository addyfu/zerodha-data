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

# Batch 3 - RSI, MACD, BB Strategies
from .rsi_trend_confirmation import RSITrendConfirmationStrategy
from .rsi_centerline import RSICenterlineStrategy
from .macd_zero_line import MACDZeroLineStrategy
from .macd_divergence import MACDDivergenceStrategy
from .macd_ma_filter import MACDMAFilterStrategy
from .bb_mean_reversion import BBMeanReversionStrategy
from .double_bb import DoubleBBStrategy

# Batch 4 - Stoch, ADX, MA, VWAP Strategies
from .stochastic_divergence import StochasticDivergenceStrategy
from .adx_filter import ADXFilterStrategy
from .ma_crossover_swing import MACrossoverSwingStrategy
from .mcginley_dynamic import McGinleyDynamicStrategy
from .vwap_sd_bands import VWAPSDBandsStrategy
from .double_vwap_ha import DoubleVWAPHAStrategy

# Batch 5 - Ichimoku, Pivot, Divergence Strategies
from .ichimoku_trend import IchimokuTrendStrategy
from .kumo_breakout import KumoBreakoutStrategy
from .ichimoku_ha import IchimokuHAStrategy
from .pivot_point import PivotPointStrategy
from .regular_divergence import RegularDivergenceStrategy
from .hidden_divergence import HiddenDivergenceStrategy

# Batch 6 - Wyckoff, Volume, ATR Strategies
from .wyckoff_accumulation import WyckoffAccumulationStrategy
from .wyckoff_distribution import WyckoffDistributionStrategy
from .obv_strategy import OBVStrategy
from .cmf_strategy import CMFStrategy
from .volume_oscillator import VolumeOscillatorStrategy
from .atr_trailing_stop import ATRTrailingStopStrategy
from .atr_breakout import ATRBreakoutStrategy

# Batch 7 - Fib, Renko, Heikin-Ashi Strategies
from .fib_retracement import FibRetracementStrategy
from .golden_ratio import GoldenRatioStrategy
from .fib_confluence import FibConfluenceStrategy
from .renko_sma_obv import RenkoSMAOBVStrategy
from .ha_trend import HATrendStrategy
from .ha_rsi import HARSIStrategy
from .renko_sr import RenkoSRStrategy

# Batch 8 - Elliott, CCI, TTM, Choppiness Strategies
from .elliott_wave3 import ElliottWave3Strategy
from .elliott_abc import ElliottABCStrategy
from .cci_zero_cross import CCIZeroCrossStrategy
from .ttm_squeeze import TTMSqueezeStrategy
from .ttm_squeeze_trend import TTMSqueezeTrendStrategy
from .choppiness_filter import ChoppinessFilterStrategy
from .choppiness_breakout import ChoppinessBreakoutStrategy
from .choppiness_volume import ChoppinessVolumeStrategy

# Batch 9 - Price Action, TRIX, ROC, Scalping Strategies
from .swing_pivot import SwingPivotStrategy
from .candlestick_patterns import CandlestickPatternStrategy
from .trix_zero_line import TRIXZeroLineStrategy
from .trix_divergence import TRIXDivergenceStrategy
from .roc_divergence import ROCDivergenceStrategy
from .vwap_scalping import VWAPScalpingStrategy
from .ema_scalping_1min import EMAScalping1MinStrategy
from .market_swing import MarketSwingStrategy

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
    # Batch 3 - RSI, MACD, BB
    'RSITrendConfirmationStrategy',
    'RSICenterlineStrategy',
    'MACDZeroLineStrategy',
    'MACDDivergenceStrategy',
    'MACDMAFilterStrategy',
    'BBMeanReversionStrategy',
    'DoubleBBStrategy',
    # Batch 4 - Stoch, ADX, MA, VWAP
    'StochasticDivergenceStrategy',
    'ADXFilterStrategy',
    'MACrossoverSwingStrategy',
    'McGinleyDynamicStrategy',
    'VWAPSDBandsStrategy',
    'DoubleVWAPHAStrategy',
    # Batch 5 - Ichimoku, Pivot, Divergence
    'IchimokuTrendStrategy',
    'KumoBreakoutStrategy',
    'IchimokuHAStrategy',
    'PivotPointStrategy',
    'RegularDivergenceStrategy',
    'HiddenDivergenceStrategy',
    # Batch 6 - Wyckoff, Volume, ATR
    'WyckoffAccumulationStrategy',
    'WyckoffDistributionStrategy',
    'OBVStrategy',
    'CMFStrategy',
    'VolumeOscillatorStrategy',
    'ATRTrailingStopStrategy',
    'ATRBreakoutStrategy',
    # Batch 7 - Fib, Renko, Heikin-Ashi
    'FibRetracementStrategy',
    'GoldenRatioStrategy',
    'FibConfluenceStrategy',
    'RenkoSMAOBVStrategy',
    'HATrendStrategy',
    'HARSIStrategy',
    'RenkoSRStrategy',
    # Batch 8 - Elliott, CCI, TTM, Choppiness
    'ElliottWave3Strategy',
    'ElliottABCStrategy',
    'CCIZeroCrossStrategy',
    'TTMSqueezeStrategy',
    'TTMSqueezeTrendStrategy',
    'ChoppinessFilterStrategy',
    'ChoppinessBreakoutStrategy',
    'ChoppinessVolumeStrategy',
    # Batch 9 - Price Action, TRIX, ROC, Scalping
    'SwingPivotStrategy',
    'CandlestickPatternStrategy',
    'TRIXZeroLineStrategy',
    'TRIXDivergenceStrategy',
    'ROCDivergenceStrategy',
    'VWAPScalpingStrategy',
    'EMAScalping1MinStrategy',
    'MarketSwingStrategy',
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
    # Batch 3 - RSI, MACD, BB
    'rsi_trend_confirmation': RSITrendConfirmationStrategy,
    'rsi_centerline': RSICenterlineStrategy,
    'macd_zero_line': MACDZeroLineStrategy,
    'macd_divergence': MACDDivergenceStrategy,
    'macd_ma_filter': MACDMAFilterStrategy,
    'bb_mean_reversion': BBMeanReversionStrategy,
    'double_bb': DoubleBBStrategy,
    # Batch 4 - Stoch, ADX, MA, VWAP
    'stochastic_divergence': StochasticDivergenceStrategy,
    'adx_filter': ADXFilterStrategy,
    'ma_crossover_swing': MACrossoverSwingStrategy,
    'mcginley_dynamic': McGinleyDynamicStrategy,
    'vwap_sd_bands': VWAPSDBandsStrategy,
    'double_vwap_ha': DoubleVWAPHAStrategy,
    # Batch 5 - Ichimoku, Pivot, Divergence
    'ichimoku_trend': IchimokuTrendStrategy,
    'kumo_breakout': KumoBreakoutStrategy,
    'ichimoku_ha': IchimokuHAStrategy,
    'pivot_point': PivotPointStrategy,
    'regular_divergence': RegularDivergenceStrategy,
    'hidden_divergence': HiddenDivergenceStrategy,
    # Batch 6 - Wyckoff, Volume, ATR
    'wyckoff_accumulation': WyckoffAccumulationStrategy,
    'wyckoff_distribution': WyckoffDistributionStrategy,
    'obv_strategy': OBVStrategy,
    'cmf_strategy': CMFStrategy,
    'volume_oscillator': VolumeOscillatorStrategy,
    'atr_trailing_stop': ATRTrailingStopStrategy,
    'atr_breakout': ATRBreakoutStrategy,
    # Batch 7 - Fib, Renko, Heikin-Ashi
    'fib_retracement': FibRetracementStrategy,
    'golden_ratio': GoldenRatioStrategy,
    'fib_confluence': FibConfluenceStrategy,
    'renko_sma_obv': RenkoSMAOBVStrategy,
    'ha_trend': HATrendStrategy,
    'ha_rsi': HARSIStrategy,
    'renko_sr': RenkoSRStrategy,
    # Batch 8 - Elliott, CCI, TTM, Choppiness
    'elliott_wave3': ElliottWave3Strategy,
    'elliott_abc': ElliottABCStrategy,
    'cci_zero_cross': CCIZeroCrossStrategy,
    'ttm_squeeze': TTMSqueezeStrategy,
    'ttm_squeeze_trend': TTMSqueezeTrendStrategy,
    'choppiness_filter': ChoppinessFilterStrategy,
    'choppiness_breakout': ChoppinessBreakoutStrategy,
    'choppiness_volume': ChoppinessVolumeStrategy,
    # Batch 9 - Price Action, TRIX, ROC, Scalping
    'swing_pivot': SwingPivotStrategy,
    'candlestick_patterns': CandlestickPatternStrategy,
    'trix_zero_line': TRIXZeroLineStrategy,
    'trix_divergence': TRIXDivergenceStrategy,
    'roc_divergence': ROCDivergenceStrategy,
    'vwap_scalping': VWAPScalpingStrategy,
    'ema_scalping_1min': EMAScalping1MinStrategy,
    'market_swing': MarketSwingStrategy,
}
