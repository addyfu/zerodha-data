# Strategy Reviews

## Cross-Cutting Notes
- Most strategies assume input `df` includes `open/high/low/close/volume` and rely on `validate_data()` from `BaseStrategy`.
- Several strategies assume a `DatetimeIndex` (or a `date` column) for daily/intraday logic (`PivotPoint`, `LondonBreakout`, `DoubleVWAPHA`).
- Ichimoku-based strategies use leading spans shifted forward; confirm intended alignment when comparing current price to cloud.

## Issues (Actionable)
- `cpr_strategy.py`: breakout branches are unreachable due to duplicated `elif` checks for `cpr_bearish`/`cpr_bullish`, so breakout signals never fire.
- `mfi_divergence.py`: divergence confirmation checks require `current_mfi` to be both below and above the threshold in the same bar; signals likely never fire.
- `regular_divergence.py`: divergence detection uses `df['low']` for both bullish and bearish checks; bearish divergence should use highs (or at least `df['high']`) to detect higher highs.

## Needs Review
- `combined_strategy.py`: weights normalization can divide by zero if weights sum to 0; no validation for weights length vs strategies.
- `fib_3wave.py`: `min_wave_pct` is computed but unused; `calculate_3wave_setup()` hardcodes `min_wave_size=0.02`.
- `macd_divergence.py`: divergence logic uses value-sorted extrema, not time-ordered swing points, which can mis-detect hidden divergence.
- `pivot_point.py`: assumes `DatetimeIndex` for daily pivot computation; fails on non-datetime index.
- `double_vwap_ha.py`: assumes `DatetimeIndex` for grouping by date; fails on non-datetime index.
- `london_breakout.py`: assumes `date` column or `DatetimeIndex`; “daily” fallback uses rolling bars, not true sessions.
- `atr_breakout.py`: uses prior bar high/low, not prior day/session; verify intended timeframe behavior.
- `ichimoku_trend.py`, `ichimoku_ha.py`, `kumo_breakout.py`: spans are shifted forward; confirm that comparing current price to shifted spans is intended.

## Per-Strategy Review

| Strategy File | Status | Notes |
| --- | --- | --- |
| `__init__.py` | OK | Registry and exports look consistent with strategy classes. |
| `base_strategy.py` | OK | Standard interface; `get_trade_signals()` uses per-row calc; assumes indicators already in `df`. |
| `adx_dmi_obv.py` | OK | Clear trend + volume confirmation. |
| `adx_filter.py` | OK | ADX trend filter + DI crosses are consistent. |
| `alligator_strategy.py` | OK | Pullback logic aligns with Alligator rules. |
| `ascending_triangle.py` | OK | Basic triangle breakout with volume filter. |
| `atr_breakout.py` | Needs Review | Uses prior bar high/low as “previous day”; confirm timeframe intention. |
| `atr_trailing_stop.py` | OK | Breakout + ATR trailing stop logic is consistent. |
| `bb_mean_reversion.py` | OK | Mean-reversion logic consistent with BB/RSI. |
| `bb_squeeze.py` | OK | Squeeze + expansion logic is consistent. |
| `candlestick_patterns.py` | OK | Pattern logic + SR confluence is reasonable. |
| `cci_divergence.py` | OK | Divergence logic is coherent; double-extreme check. |
| `cci_zero_cross.py` | OK | Zero-line cross with MA filter is consistent. |
| `chandelier_strategy.py` | OK | Flip detection + EMA filter consistent. |
| `choppiness_breakout.py` | OK | CI consolidation + breakout rules consistent. |
| `choppiness_filter.py` | OK | CI filter + EMA cross logic consistent. |
| `choppiness_volume.py` | OK | CI/volume-based breakout confirmation consistent. |
| `cmf_ichimoku.py` | OK | CMF threshold cross + cloud filter consistent. |
| `cmf_strategy.py` | OK | CMF threshold cross + EMA filter consistent. |
| `combined_strategy.py` | Needs Review | No guard for zero-sum weights or mismatch lengths. |
| `cpr_strategy.py` | Issue | Breakout logic unreachable due to duplicated `elif` branches. |
| `donchian_turtle.py` | OK | Uses prior channel to avoid lookahead; consistent. |
| `double_bb.py` | OK | Zone-based logic consistent. |
| `double_vwap_ha.py` | Needs Review | Requires `DatetimeIndex` for `date` grouping; ensure index is datetime. |
| `elliott_abc.py` | OK | Heuristic ABC detection consistent with description. |
| `elliott_wave3.py` | OK | Wave 1/2 heuristics consistent with stop/target logic. |
| `ema_21_55.py` | OK | EMA zone breakout + ATR stops consistent. |
| `ema_3_scalping.py` | OK | Multi-EMA alignment + pullback logic consistent. |
| `ema_scalping_1min.py` | OK | EMA alignment + pullback logic consistent for scalping. |
| `fib_3wave.py` | Needs Review | Parameter `min_wave_pct` unused; hardcoded `min_wave_size=0.02`. |
| `fib_confluence.py` | OK | Confluence cluster logic consistent. |
| `fib_pivot_strategy.py` | OK | Trend + Fibonacci pivot bounce logic consistent. |
| `fib_retracement.py` | OK | Pullback entries and fib levels consistent. |
| `gmma_strategy.py` | OK | Short/long group crossover + expansion logic consistent. |
| `golden_ratio.py` | OK | Golden zone rejection logic consistent. |
| `ha_rsi.py` | OK | HA turn + RSI filter consistent. |
| `ha_trend.py` | OK | Trend + pullback logic consistent. |
| `hidden_divergence.py` | OK | Hidden divergence + trend filter consistent. |
| `hull_slope_strategy.py` | OK | Fast/slow HMA slope hooks consistent. |
| `ichimoku_ha.py` | Needs Review | Uses shifted spans; confirm cloud alignment for entry logic. |
| `ichimoku_trend.py` | Needs Review | Uses shifted spans; verify cloud alignment intended. |
| `kumo_breakout.py` | Needs Review | Uses shifted spans; verify breakout vs cloud alignment. |
| `london_breakout.py` | Needs Review | Assumes `date` or `DatetimeIndex`; daily vs intraday handling may be ambiguous. |
| `macd_divergence.py` | Needs Review | Divergence uses value-sorted extrema rather than time-ordered swings. |
| `macd_ma_filter.py` | OK | MACD cross + 200 SMA filter consistent. |
| `macd_zero_line.py` | OK | Histogram cross + swing confirmation consistent. |
| `ma_crossover_swing.py` | OK | EMA cross + volume confirmation consistent. |
| `ma_envelopes.py` | OK | Envelope mean reversion logic consistent. |
| `market_swing.py` | OK | Swing direction change logic consistent. |
| `mcginley_dynamic.py` | OK | MD cross + slope confirmation consistent. |
| `mfi_divergence.py` | Issue | Confirmation checks are contradictory; signals likely never fire. |
| `momentum_zero.py` | OK | Momentum zero-cross + trend filter consistent. |
| `multi_timeframe.py` | OK | Higher TF mapping + divergence filter consistent. |
| `obv_strategy.py` | OK | OBV + price trend confirmation consistent. |
| `pivot_point.py` | Needs Review | Assumes `DatetimeIndex` for daily pivots. |
| `psar_ichimoku.py` | OK | PSAR flip + cloud filter consistent. |
| `regular_divergence.py` | Issue | Uses lows for bearish divergence; should use highs for bearish checks. |
| `renko_sma_obv.py` | OK | Renko-style bricks + SMA/OBV confirmation consistent. |
| `renko_sr.py` | OK | S/R clustering logic consistent. |
| `roc_divergence.py` | OK | ROC divergence logic consistent. |
| `roc_ma_strategy.py` | OK | ROC zero-cross + MA filter consistent. |
| `rsi_centerline.py` | OK | RSI centerline confirmation consistent. |
| `rsi_divergence.py` | OK | RSI divergence + S/R confluence consistent. |
| `rsi_trend_confirmation.py` | OK | RSI cross + EMA trend filter consistent. |
| `stochastic_confluence.py` | OK | EMA+S/R+stoch logic consistent. |
| `stochastic_divergence.py` | OK | Stoch divergence logic consistent. |
| `stochrsi_macd.py` | OK | StochRSI 50-cross + MACD confirmation consistent. |
| `supply_demand.py` | OK | Zone detection + touch logic consistent. |
| `swing_pivot.py` | OK | Swing point bounce logic consistent. |
| `tdi_strategy.py` | OK | TDI cross + trend/volatility filters consistent. |
| `trix_divergence.py` | OK | TRIX divergence + zero-cross confirm consistent. |
| `trix_zero_line.py` | OK | TRIX zero cross + S/R breakout consistent. |
| `ttm_squeeze.py` | OK | Squeeze fire + momentum filter consistent. |
| `ttm_squeeze_trend.py` | OK | Squeeze fire + trend filter consistent. |
| `volume_oscillator.py` | OK | Volume oscillator cross + price trend consistent. |
| `vwap_pullback.py` | OK | VWAP pullback + trend filter consistent. |
| `vwap_scalping.py` | OK | VWAP touch + candle bias consistent. |
| `vwap_sd_bands.py` | OK | Mean reversion to VWAP consistent. |
| `vwma_sma_strategy.py` | OK | VWMA vs SMA separation logic consistent. |
| `wyckoff_accumulation.py` | OK | Spring/LPS heuristics consistent. |
| `wyckoff_distribution.py` | OK | UTAD/LPSY heuristics consistent. |
