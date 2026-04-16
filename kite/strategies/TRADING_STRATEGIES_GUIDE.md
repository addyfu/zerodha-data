# Trading Strategies Implementation Guide

A comprehensive collection of trading strategies extracted from video tutorials, organized by category with implementation details for the kite trading system.

---

## Table of Contents

1. [RSI Strategies](#1-rsi-strategies)
2. [MACD Strategies](#2-macd-strategies)
3. [Bollinger Bands Strategies](#3-bollinger-bands-strategies)
4. [Stochastic Strategies](#4-stochastic-strategies)
5. [ADX/DMI Strategies](#5-adxdmi-strategies)
6. [Moving Average Strategies](#6-moving-average-strategies)
7. [VWAP Strategies](#7-vwap-strategies)
8. [Ichimoku Cloud Strategies](#8-ichimoku-cloud-strategies)
9. [Pivot Point Strategies](#9-pivot-point-strategies)
10. [Divergence Strategies](#10-divergence-strategies)
11. [Supply & Demand Strategies](#11-supply--demand-strategies)
12. [Wyckoff Method Strategies](#12-wyckoff-method-strategies)
13. [Volume-Based Strategies](#13-volume-based-strategies)
14. [ATR & Volatility Strategies](#14-atr--volatility-strategies)
15. [Fibonacci Strategies](#15-fibonacci-strategies)
16. [Renko Chart Strategies](#16-renko-chart-strategies)
17. [Heikin-Ashi Strategies](#17-heikin-ashi-strategies)
18. [Elliott Wave Strategies](#18-elliott-wave-strategies)
19. [CCI Strategies](#19-cci-strategies)
20. [Momentum Indicator Strategies](#20-momentum-indicator-strategies)
21. [TTM Squeeze Strategies](#21-ttm-squeeze-strategies)
22. [GMMA Strategies](#22-gmma-strategies)
23. [Choppiness Index Strategies](#23-choppiness-index-strategies)
24. [Exit Indicator Strategies](#24-exit-indicator-strategies)
25. [Price Action Strategies](#25-price-action-strategies)
26. [TRIX Strategies](#26-trix-strategies)
27. [Rate of Change Strategies](#27-rate-of-change-strategies)
28. [StochRSI Strategies](#28-stochrsi-strategies)
29. [Scalping Strategies](#29-scalping-strategies)
30. [Risk Management Guidelines](#30-risk-management-guidelines)

---

## 1. RSI Strategies

### Strategy 1.1: RSI Trend Confirmation
**Category:** Momentum/Trend Following  
**Timeframe:** Any (4H+ recommended)  
**Indicators:** RSI(14), 200 EMA

**Entry Rules - Long:**
- Price above 200 EMA (uptrend confirmed)
- RSI crosses above 50 level
- Look for RSI to pull back to 40-50 zone and bounce

**Entry Rules - Short:**
- Price below 200 EMA (downtrend confirmed)
- RSI crosses below 50 level
- Look for RSI to rally to 50-60 zone and reject

**Exit Rules:**
- Take profit when RSI reaches 70 (longs) or 30 (shorts)
- Stop loss: Below recent swing low (longs) or above swing high (shorts)

**Implementation Notes:**
```python
# Use existing oscillators.py RSI implementation
from kite.indicators.oscillators import calculate_rsi
from kite.indicators.moving_averages import calculate_ema

rsi = calculate_rsi(close, period=14)
ema_200 = calculate_ema(close, period=200)

# Long signal
long_signal = (close > ema_200) & (rsi > 50) & (rsi.shift(1) <= 50)
```

---

### Strategy 1.2: RSI Divergence Trading
**Category:** Reversal  
**Timeframe:** 1H, 4H, Daily  
**Indicators:** RSI(14)

**Bullish Divergence (Long):**
- Price makes lower low
- RSI makes higher low
- Enter when RSI crosses above 30

**Bearish Divergence (Short):**
- Price makes higher high
- RSI makes lower high
- Enter when RSI crosses below 70

**Exit Rules:**
- Target: Previous swing high/low
- Stop loss: Below/above the divergence low/high

---

### Strategy 1.3: RSI 50-Level Centerline Strategy
**Category:** Trend Following  
**Timeframe:** Any  
**Indicators:** RSI(14)

**Rules:**
- RSI above 50 = Bullish bias (only take longs)
- RSI below 50 = Bearish bias (only take shorts)
- Use RSI 50 crossover as confirmation, not primary signal

---

## 2. MACD Strategies

### Strategy 2.1: MACD Zero-Line Crossover
**Category:** Trend Following  
**Timeframe:** 4H, Daily  
**Indicators:** MACD(12,26,9)

**Entry Rules - Long:**
- MACD histogram crosses above zero line
- MACD line above signal line
- Confirm with price above recent swing high

**Entry Rules - Short:**
- MACD histogram crosses below zero line
- MACD line below signal line
- Confirm with price below recent swing low

**Exit Rules:**
- Exit when MACD histogram starts declining (longs) or rising (shorts)
- Alternative: Exit on opposite signal

**Implementation Notes:**
```python
from kite.indicators.oscillators import calculate_macd

macd_line, signal_line, histogram = calculate_macd(close, fast=12, slow=26, signal=9)

# Long signal
long_signal = (histogram > 0) & (histogram.shift(1) <= 0)
```

---

### Strategy 2.2: MACD Divergence Strategy
**Category:** Reversal  
**Timeframe:** 1H+  
**Indicators:** MACD(12,26,9)

**Hidden Bullish Divergence:**
- Price makes higher low
- MACD makes lower low
- Signals trend continuation in uptrend

**Hidden Bearish Divergence:**
- Price makes lower high
- MACD makes higher high
- Signals trend continuation in downtrend

---

### Strategy 2.3: MACD + Moving Average Filter
**Category:** Trend Following  
**Timeframe:** Any  
**Indicators:** MACD(12,26,9), 200 SMA

**Rules:**
- Only take MACD buy signals when price > 200 SMA
- Only take MACD sell signals when price < 200 SMA
- Reduces false signals significantly

---

## 3. Bollinger Bands Strategies

### Strategy 3.1: Bollinger Band Squeeze Breakout
**Category:** Volatility Breakout  
**Timeframe:** 15m, 1H, 4H  
**Indicators:** Bollinger Bands(20,2)

**Setup:**
- Wait for bands to contract (squeeze)
- Bandwidth at multi-period low

**Entry Rules - Long:**
- Price closes above upper band after squeeze
- Volume confirmation (above average)

**Entry Rules - Short:**
- Price closes below lower band after squeeze
- Volume confirmation

**Exit Rules:**
- Trail stop using middle band (20 SMA)
- Take profit at 2x ATR from entry

**Implementation Notes:**
```python
from kite.indicators.volatility import calculate_bollinger_bands

upper, middle, lower = calculate_bollinger_bands(close, period=20, std_dev=2)
bandwidth = (upper - lower) / middle

# Squeeze detection
squeeze = bandwidth < bandwidth.rolling(50).quantile(0.1)
```

---

### Strategy 3.2: Bollinger Band Mean Reversion
**Category:** Mean Reversion  
**Timeframe:** 1H+  
**Indicators:** Bollinger Bands(20,2), RSI(14)

**Entry Rules - Long:**
- Price touches or closes below lower band
- RSI below 30 (oversold)
- Wait for bullish candle confirmation

**Entry Rules - Short:**
- Price touches or closes above upper band
- RSI above 70 (overbought)
- Wait for bearish candle confirmation

**Exit Rules:**
- Target: Middle band (20 SMA)
- Stop loss: 1 ATR beyond the band

---

### Strategy 3.3: Double Bollinger Bands Strategy
**Category:** Trend Following  
**Timeframe:** Any  
**Indicators:** BB(20,1), BB(20,2)

**Zones:**
- Buy Zone: Price between upper BB(1) and upper BB(2)
- Sell Zone: Price between lower BB(1) and lower BB(2)
- Neutral Zone: Price between the two inner bands

**Rules:**
- Buy when price enters and stays in buy zone
- Sell when price enters and stays in sell zone
- Exit when price returns to neutral zone

---

## 4. Stochastic Strategies

### Strategy 4.1: Stochastic Trend Trading
**Category:** Trend Following  
**Timeframe:** 1H, 4H  
**Indicators:** Stochastic(14,3,3), 50 EMA

**Entry Rules - Long:**
- Price above 50 EMA
- Stochastic crosses up from below 20
- %K crosses above %D

**Entry Rules - Short:**
- Price below 50 EMA
- Stochastic crosses down from above 80
- %K crosses below %D

**Exit Rules:**
- Exit longs when Stochastic reaches 80
- Exit shorts when Stochastic reaches 20
- Or use trailing stop

---

### Strategy 4.2: Stochastic Divergence
**Category:** Reversal  
**Timeframe:** 4H, Daily  
**Indicators:** Stochastic(14,3,3)

**Bullish Divergence:**
- Price makes lower low
- Stochastic makes higher low in oversold zone (<20)

**Bearish Divergence:**
- Price makes higher high
- Stochastic makes lower high in overbought zone (>80)

---

## 5. ADX/DMI Strategies

### Strategy 5.1: ADX Trend Strength Trading
**Category:** Trend Following  
**Timeframe:** 1H, 4H, Daily  
**Indicators:** ADX(14), +DI, -DI

**Entry Rules - Long:**
- ADX > 25 (strong trend)
- +DI crosses above -DI
- ADX rising

**Entry Rules - Short:**
- ADX > 25 (strong trend)
- -DI crosses above +DI
- ADX rising

**Exit Rules:**
- Exit when ADX starts falling below 25
- Or when DI lines cross in opposite direction

**Implementation Notes:**
```python
from kite.indicators.trend import calculate_adx

adx, plus_di, minus_di = calculate_adx(high, low, close, period=14)

# Strong uptrend signal
long_signal = (adx > 25) & (plus_di > minus_di) & (plus_di.shift(1) <= minus_di.shift(1))
```

---

### Strategy 5.2: ADX Filter Strategy
**Category:** Filter  
**Timeframe:** Any  
**Indicators:** ADX(14)

**Rules:**
- Only trade when ADX > 25 (trending market)
- Avoid trades when ADX < 20 (ranging market)
- Use ADX as filter for other strategies

---

## 6. Moving Average Strategies

### Strategy 6.1: 3-EMA Scalping Strategy
**Category:** Scalping  
**Timeframe:** 1m, 5m  
**Indicators:** EMA(9), EMA(21), EMA(55)

**Entry Rules - Long:**
- EMA 9 > EMA 21 > EMA 55 (aligned)
- Price pulls back to EMA 9 or EMA 21
- Bullish candle forms at EMA

**Entry Rules - Short:**
- EMA 9 < EMA 21 < EMA 55 (aligned)
- Price pulls back to EMA 9 or EMA 21
- Bearish candle forms at EMA

**Exit Rules:**
- Take profit: 1.5x risk
- Stop loss: Below EMA 55 (longs) or above EMA 55 (shorts)

**Implementation Notes:**
```python
from kite.indicators.moving_averages import calculate_ema

ema_9 = calculate_ema(close, period=9)
ema_21 = calculate_ema(close, period=21)
ema_55 = calculate_ema(close, period=55)

# Bullish alignment
bullish_alignment = (ema_9 > ema_21) & (ema_21 > ema_55)
```

---

### Strategy 6.2: Moving Average Crossover (Swing Trading)
**Category:** Swing Trading  
**Timeframe:** Daily  
**Indicators:** EMA(10), EMA(20)

**Entry Rules - Long:**
- EMA 10 crosses above EMA 20
- Price above both EMAs
- Volume above average

**Entry Rules - Short:**
- EMA 10 crosses below EMA 20
- Price below both EMAs

**Exit Rules:**
- Exit on opposite crossover
- Or trail stop below EMA 20

---

### Strategy 6.3: 21/55 EMA Strategy
**Category:** Day Trading/Scalping  
**Timeframe:** 5m, 15m  
**Indicators:** EMA(21), EMA(55)

**Entry Rules - Long:**
- EMA 21 above EMA 55
- Price pulls back to EMA 21
- Bullish rejection candle

**Entry Rules - Short:**
- EMA 21 below EMA 55
- Price rallies to EMA 21
- Bearish rejection candle

---

### Strategy 6.4: McGinley Dynamic Strategy
**Category:** Trend Following  
**Timeframe:** Any  
**Indicators:** McGinley Dynamic(14)

**Calculation:**
```
MD = MD_prev + (Price - MD_prev) / (N * (Price/MD_prev)^4)
```

**Rules:**
- Price above MD = Bullish
- Price below MD = Bearish
- Less whipsaws than traditional MAs

---

## 7. VWAP Strategies

### Strategy 7.1: VWAP Bounce Strategy
**Category:** Intraday  
**Timeframe:** 1m, 5m, 15m  
**Indicators:** VWAP

**Entry Rules - Long:**
- Price above VWAP (bullish bias)
- Price pulls back to VWAP
- Bullish candle at VWAP (support)

**Entry Rules - Short:**
- Price below VWAP (bearish bias)
- Price rallies to VWAP
- Bearish candle at VWAP (resistance)

**Exit Rules:**
- Target: Previous high/low
- Stop loss: 1 ATR beyond VWAP

---

### Strategy 7.2: VWAP Standard Deviation Bands
**Category:** Intraday  
**Timeframe:** 5m, 15m  
**Indicators:** VWAP, VWAP +/- 1SD, +/- 2SD

**Rules:**
- Price at +2SD = Overbought (short opportunity)
- Price at -2SD = Oversold (long opportunity)
- VWAP acts as magnet (mean reversion target)

---

### Strategy 7.3: Double VWAP + Heikin Ashi
**Category:** Scalping  
**Timeframe:** 1m, 5m  
**Indicators:** VWAP, Previous Day VWAP, Heikin Ashi

**Entry Rules - Long:**
- Price above both VWAPs
- Heikin Ashi candles green (no lower wick)
- Enter on pullback to current VWAP

**Entry Rules - Short:**
- Price below both VWAPs
- Heikin Ashi candles red (no upper wick)
- Enter on rally to current VWAP

---

## 8. Ichimoku Cloud Strategies

### Strategy 8.1: Ichimoku Trend Trading
**Category:** Trend Following  
**Timeframe:** 4H, Daily  
**Indicators:** Ichimoku Cloud (9,26,52)

**Entry Rules - Long:**
- Price above cloud (Kumo)
- Tenkan-sen crosses above Kijun-sen
- Chikou Span above price
- Cloud is green (bullish)

**Entry Rules - Short:**
- Price below cloud
- Tenkan-sen crosses below Kijun-sen
- Chikou Span below price
- Cloud is red (bearish)

**Exit Rules:**
- Exit when price enters cloud
- Or when Tenkan/Kijun cross opposite

---

### Strategy 8.2: Kumo Breakout Strategy
**Category:** Breakout  
**Timeframe:** 1H, 4H  
**Indicators:** Ichimoku Cloud

**Entry Rules - Long:**
- Price breaks above cloud
- Cloud ahead is green (bullish)
- Volume confirmation

**Entry Rules - Short:**
- Price breaks below cloud
- Cloud ahead is red (bearish)
- Volume confirmation

**Exit Rules:**
- Stop loss: Inside cloud
- Target: 2x cloud thickness

---

### Strategy 8.3: Ichimoku + Heikin Ashi
**Category:** Trend Following  
**Timeframe:** Any  
**Indicators:** Ichimoku Cloud, Heikin Ashi

**Entry Rules - Long:**
- Price above Kumo cloud
- Kumo cloud is green
- Heikin Ashi candle changes from red to green

**Entry Rules - Short:**
- Price below Kumo cloud
- Kumo cloud is red
- Heikin Ashi candle changes from green to red

---

## 9. Pivot Point Strategies

### Strategy 9.1: Standard Pivot Point Trading
**Category:** Intraday  
**Timeframe:** 5m, 15m  
**Indicators:** Daily Pivot Points (P, R1, R2, R3, S1, S2, S3)

**Entry Rules - Long:**
- Price bounces from S1 or S2
- Bullish candle confirmation
- Target: Pivot Point or R1

**Entry Rules - Short:**
- Price rejects from R1 or R2
- Bearish candle confirmation
- Target: Pivot Point or S1

---

### Strategy 9.2: Central Pivot Range (CPR) Strategy
**Category:** Intraday  
**Timeframe:** 15m, 1H  
**Indicators:** CPR (TC, Pivot, BC)

**Setup:**
- TC = Top Central Pivot
- BC = Bottom Central Pivot
- Pivot = Central Pivot

**Rules:**
- Narrow CPR = Trending day expected
- Wide CPR = Ranging day expected
- Price above CPR = Bullish bias
- Price below CPR = Bearish bias

---

### Strategy 9.3: Fibonacci Pivot Points
**Category:** Intraday  
**Timeframe:** 15m, 1H  
**Indicators:** Fibonacci Pivot Points

**Calculation:**
- R1 = P + (0.382 × Range)
- R2 = P + (0.618 × Range)
- R3 = P + (1.000 × Range)
- S1 = P - (0.382 × Range)
- S2 = P - (0.618 × Range)
- S3 = P - (1.000 × Range)

**Rules:**
- Trade bounces from Fibonacci pivot levels
- 61.8% levels are strongest

---

## 10. Divergence Strategies

### Strategy 10.1: Regular Divergence Trading
**Category:** Reversal  
**Timeframe:** 1H, 4H, Daily  
**Indicators:** RSI(14) or MACD or Stochastic

**Bullish Regular Divergence:**
- Price: Lower Low
- Indicator: Higher Low
- Signal: Potential bullish reversal

**Bearish Regular Divergence:**
- Price: Higher High
- Indicator: Lower High
- Signal: Potential bearish reversal

**Entry Rules:**
- Wait for divergence to complete
- Enter on break of trendline
- Or enter on indicator signal line cross

---

### Strategy 10.2: Hidden Divergence Trading
**Category:** Trend Continuation  
**Timeframe:** 1H, 4H  
**Indicators:** RSI(14) or MACD

**Bullish Hidden Divergence:**
- Price: Higher Low (in uptrend)
- Indicator: Lower Low
- Signal: Trend continuation (buy)

**Bearish Hidden Divergence:**
- Price: Lower High (in downtrend)
- Indicator: Higher High
- Signal: Trend continuation (sell)

---

### Strategy 10.3: Multi-Indicator Divergence
**Category:** High Probability Reversal  
**Timeframe:** 4H, Daily  
**Indicators:** RSI, MACD, Stochastic

**Rules:**
- Look for divergence on multiple indicators
- 2+ indicators showing divergence = stronger signal
- Combine with support/resistance levels

---

## 11. Supply & Demand Strategies

### Strategy 11.1: Supply & Demand Zone Trading
**Category:** Price Action  
**Timeframe:** 1H, 4H, Daily  
**Indicators:** None (pure price action)

**Identifying Demand Zones:**
- Strong bullish move away from a level
- Base formation before the move
- Little time spent at the level

**Identifying Supply Zones:**
- Strong bearish move away from a level
- Base formation before the move
- Little time spent at the level

**Entry Rules - Long:**
- Price returns to demand zone
- Look for bullish rejection candle
- Enter with stop below zone

**Entry Rules - Short:**
- Price returns to supply zone
- Look for bearish rejection candle
- Enter with stop above zone

---

### Strategy 11.2: Fresh vs Tested Zones
**Category:** Price Action  
**Timeframe:** Any  
**Indicators:** None

**Rules:**
- Fresh zones (never tested) = Strongest
- Once-tested zones = Still valid
- Multiple-tested zones = Weakening
- Broken zones = Invalid (flip to opposite)

---

## 12. Wyckoff Method Strategies

### Strategy 12.1: Wyckoff Accumulation Trading
**Category:** Market Structure  
**Timeframe:** Daily, Weekly  
**Indicators:** Volume, Price Action

**Accumulation Phases:**
1. PS (Preliminary Support) - Buying appears
2. SC (Selling Climax) - Panic selling, high volume
3. AR (Automatic Rally) - Short covering
4. ST (Secondary Test) - Test of SC low
5. Spring - False breakdown, shakeout
6. SOS (Sign of Strength) - Breakout with volume
7. LPS (Last Point of Support) - Pullback entry

**Entry Rules:**
- Enter on Spring (aggressive)
- Enter on SOS breakout (moderate)
- Enter on LPS pullback (conservative)

---

### Strategy 12.2: Wyckoff Distribution Trading
**Category:** Market Structure  
**Timeframe:** Daily, Weekly  
**Indicators:** Volume, Price Action

**Distribution Phases:**
1. PSY (Preliminary Supply) - Selling appears
2. BC (Buying Climax) - Euphoric buying
3. AR (Automatic Reaction) - Profit taking
4. ST (Secondary Test) - Test of BC high
5. UTAD (Upthrust After Distribution) - False breakout
6. SOW (Sign of Weakness) - Breakdown
7. LPSY (Last Point of Supply) - Rally to short

**Entry Rules:**
- Short on UTAD (aggressive)
- Short on SOW breakdown (moderate)
- Short on LPSY rally (conservative)

---

## 13. Volume-Based Strategies

### Strategy 13.1: On-Balance Volume (OBV) Strategy
**Category:** Volume Confirmation  
**Timeframe:** Any  
**Indicators:** OBV

**Rules:**
- OBV rising + Price rising = Confirmed uptrend
- OBV falling + Price falling = Confirmed downtrend
- OBV divergence from price = Warning signal

**Implementation Notes:**
```python
from kite.indicators.volume import calculate_obv

obv = calculate_obv(close, volume)

# OBV confirmation
bullish_confirmation = (close > close.shift(1)) & (obv > obv.shift(1))
```

---

### Strategy 13.2: Money Flow Index (MFI) Strategy
**Category:** Volume + Momentum  
**Timeframe:** 1H, 4H  
**Indicators:** MFI(14)

**Entry Rules - Long:**
- MFI below 10 (extreme oversold)
- Bullish candle confirmation
- Volume increasing

**Entry Rules - Short:**
- MFI above 90 (extreme overbought)
- Bearish candle confirmation

---

### Strategy 13.3: Chaikin Money Flow (CMF) Strategy
**Category:** Volume Analysis  
**Timeframe:** Daily  
**Indicators:** CMF(20)

**Rules:**
- CMF > 0 = Buying pressure (bullish)
- CMF < 0 = Selling pressure (bearish)
- CMF divergence = Potential reversal

---

### Strategy 13.4: Volume Oscillator Strategy
**Category:** Volume Analysis  
**Timeframe:** Any  
**Indicators:** Volume Oscillator (14, 34)

**Calculation:**
- Fast Volume MA - Slow Volume MA

**Rules:**
- Oscillator > 0 = Volume expanding (confirms trend)
- Oscillator < 0 = Volume contracting (trend weakening)

---

## 14. ATR & Volatility Strategies

### Strategy 14.1: ATR-Based Stop Loss
**Category:** Risk Management  
**Timeframe:** Any  
**Indicators:** ATR(14)

**Rules:**
- Stop loss = Entry - (2 × ATR) for longs
- Stop loss = Entry + (2 × ATR) for shorts
- Adjusts automatically to volatility

**Implementation Notes:**
```python
from kite.indicators.volatility import calculate_atr

atr = calculate_atr(high, low, close, period=14)
stop_loss_long = entry_price - (2 * atr)
stop_loss_short = entry_price + (2 * atr)
```

---

### Strategy 14.2: ATR Trailing Stop
**Category:** Exit Strategy  
**Timeframe:** Any  
**Indicators:** ATR(14)

**Rules:**
- Initial stop: 2-3 × ATR from entry
- Trail stop: Highest high - (2 × ATR) for longs
- Trail stop: Lowest low + (2 × ATR) for shorts

---

### Strategy 14.3: ATR Breakout Strategy
**Category:** Volatility Breakout  
**Timeframe:** Daily  
**Indicators:** ATR(14)

**Entry Rules - Long:**
- Price breaks above previous day high + (0.5 × ATR)
- Volume above average

**Entry Rules - Short:**
- Price breaks below previous day low - (0.5 × ATR)
- Volume above average

---

## 15. Fibonacci Strategies

### Strategy 15.1: Fibonacci Retracement Trading
**Category:** Trend Following  
**Timeframe:** 1H, 4H, Daily  
**Indicators:** Fibonacci Retracement

**Key Levels:**
- 23.6% - Shallow retracement (strong trend)
- 38.2% - Common retracement
- 50.0% - Psychological level
- 61.8% - Golden ratio (strongest)
- 78.6% - Deep retracement

**Entry Rules - Long (Uptrend):**
- Draw Fib from swing low to swing high
- Wait for pullback to 38.2%, 50%, or 61.8%
- Enter on bullish candle at Fib level

**Exit Rules:**
- Target: Previous swing high or Fib extension
- Stop loss: Below 78.6% level

**Implementation Notes:**
```python
from kite.indicators.fibonacci import calculate_fibonacci_levels

fib_levels = calculate_fibonacci_levels(swing_low, swing_high)
# Returns: 0%, 23.6%, 38.2%, 50%, 61.8%, 78.6%, 100%
```

---

### Strategy 15.2: Golden Ratio (61.8%) Strategy
**Category:** Trend Following  
**Timeframe:** 4H, Daily  
**Indicators:** Fibonacci Retracement

**Rules:**
- Price retraces to 50-61.8% zone
- Candle wick can break 61.8% but must close below
- Enter on rejection from 61.8%
- Stop loss above 78.6%

---

### Strategy 15.3: Fibonacci Confluence Strategy
**Category:** High Probability  
**Timeframe:** 4H, Daily  
**Indicators:** Multiple Fibonacci Retracements

**Rules:**
- Draw Fibs from multiple swing points
- Look for cluster of Fib levels (confluence)
- Trade at confluence zones
- Stronger signal when 2+ Fibs align

---

### Strategy 15.4: Fibonacci + Moving Average Confluence
**Category:** High Probability  
**Timeframe:** Any  
**Indicators:** Fibonacci, 200 EMA

**Rules:**
- Fib level aligns with 200 EMA = Strong support/resistance
- Enter when price reacts at confluence
- Higher probability setup

---

## 16. Renko Chart Strategies

### Strategy 16.1: Renko + SMA + OBV Strategy
**Category:** Trend Following  
**Timeframe:** Renko (100 brick)  
**Indicators:** SMA(10), OBV

**Entry Rules - Long:**
- Green Renko bar forms above SMA(10)
- OBV making new highs
- SMA slope pointing upward

**Entry Rules - Short:**
- Red Renko bar forms below SMA(10)
- OBV making new lows
- SMA slope pointing downward

**Exit Rules:**
- Stop loss: 2 Renko bars from entry
- Take profit: 3+ Renko bars minimum
- Exit if price crosses SMA

---

### Strategy 16.2: Renko Support/Resistance
**Category:** Price Action  
**Timeframe:** Renko  
**Indicators:** None

**Rules:**
- Renko charts make S/R levels clearer
- Trade bounces from clear Renko S/R
- Cleaner trends visible

---

## 17. Heikin-Ashi Strategies

### Strategy 17.1: Heikin-Ashi Trend Trading
**Category:** Trend Following  
**Timeframe:** Any  
**Indicators:** Heikin-Ashi candles

**Trend Identification:**
- Green candles with no lower wick = Strong uptrend
- Red candles with no upper wick = Strong downtrend
- Doji-like candles = Potential reversal

**Entry Rules - Long:**
- Series of green HA candles
- No lower wicks
- Enter on pullback (small red candle)

**Entry Rules - Short:**
- Series of red HA candles
- No upper wicks
- Enter on rally (small green candle)

---

### Strategy 17.2: Heikin-Ashi + RSI Strategy
**Category:** Trend Following  
**Timeframe:** Any  
**Indicators:** Heikin-Ashi, RSI(14)

**Entry Rules - Long:**
- HA candle changes from red to green
- RSI above 50

**Entry Rules - Short:**
- HA candle changes from green to red
- RSI below 50

---

### Strategy 17.3: Heikin-Ashi + Ichimoku
**Category:** Trend Following  
**Timeframe:** 4H, Daily  
**Indicators:** Heikin-Ashi, Ichimoku Cloud

**Entry Rules - Long:**
- HA candle changes from red to green
- Price above Kumo cloud
- Cloud is green

**Entry Rules - Short:**
- HA candle changes from green to red
- Price below Kumo cloud
- Cloud is red

---

## 18. Elliott Wave Strategies

### Strategy 18.1: Wave 3 Entry Strategy
**Category:** Trend Following  
**Timeframe:** 4H, Daily  
**Indicators:** Elliott Wave count

**Rules:**
- Identify Wave 1 (initial impulse)
- Wait for Wave 2 correction (50-61.8% retracement)
- Enter at end of Wave 2 for Wave 3 ride
- Wave 3 is typically the longest and strongest

**Wave 2 Characteristics:**
- Typically retraces 50-61.8% of Wave 1
- Cannot retrace more than 100% of Wave 1

---

### Strategy 18.2: ABC Correction Entry
**Category:** Trend Following  
**Timeframe:** 4H, Daily  
**Indicators:** Elliott Wave count

**Rules:**
- After 5-wave impulse, expect ABC correction
- A wave: Initial correction
- B wave: Counter-trend rally
- C wave: Final correction
- Enter at end of C wave for new impulse

---

### Strategy 18.3: Elliott Wave Rules
**Category:** Wave Counting  
**Timeframe:** Any  

**Three Golden Rules:**
1. Wave 3 can NEVER be the shortest impulse wave
2. Wave 2 can NEVER retrace more than 100% of Wave 1
3. Wave 4 can NEVER overlap Wave 1 price territory

**Guidelines:**
- Wave 5 ≈ Wave 1 (when Wave 3 is longest)
- Wave 2 and Wave 4 alternate (sharp vs flat)
- ABC correction ends near Wave 4 low

---

## 19. CCI Strategies

### Strategy 19.1: CCI Double Oversold Strategy
**Category:** Reversal  
**Timeframe:** 4H, Daily  
**Indicators:** CCI(21)

**Entry Rules - Long:**
1. CCI reaches -200 level (first time)
2. CCI reaches -200 level again (second time)
3. Regular divergence forms between CCI and price
4. Trendline breakout on price chart
5. Enter long after breakout confirmation

**Exit Rules:**
- Stop loss: Below recent swing low
- Target: Previous resistance levels

---

### Strategy 19.2: CCI Zero-Line Cross
**Category:** Trend Following  
**Timeframe:** 1H, 4H  
**Indicators:** CCI(21)

**Entry Rules - Long:**
- CCI crosses above zero
- Price above moving average

**Entry Rules - Short:**
- CCI crosses below zero
- Price below moving average

---

## 20. Momentum Indicator Strategies

### Strategy 20.1: Momentum Zero-Line Strategy
**Category:** Trend Following  
**Timeframe:** 1H, 4H, Daily  
**Indicators:** Momentum(14), 200 EMA

**Entry Rules - Long:**
- Price above 200 EMA (uptrend)
- Momentum crosses above zero
- Support/resistance breakout confirmation

**Entry Rules - Short:**
- Price below 200 EMA (downtrend)
- Momentum crosses below zero
- Support/resistance breakout confirmation

---

### Strategy 20.2: Momentum Divergence Strategy
**Category:** Reversal  
**Timeframe:** 1H, 4H  
**Indicators:** Momentum(14), 200 EMA

**Rules:**
- Only trade divergences in direction of main trend (200 EMA)
- If price > 200 EMA: Look for divergences on lower side of momentum
- If price < 200 EMA: Look for divergences on upper side of momentum
- Enter when momentum crosses zero line after divergence

---

## 21. TTM Squeeze Strategies

### Strategy 21.1: TTM Squeeze Breakout
**Category:** Volatility Breakout  
**Timeframe:** 15m, 1H, 4H  
**Indicators:** TTM Squeeze (Bollinger Bands + Keltner Channels)

**Components:**
- Red dots = Squeeze ON (low volatility, consolidation)
- Green dots = Squeeze OFF (volatility expanding)
- Histogram = Momentum direction

**Entry Rules - Long:**
- Red dots turn to green (squeeze fires)
- Histogram above zero and rising (green)
- Enter on first green dot

**Entry Rules - Short:**
- Red dots turn to green (squeeze fires)
- Histogram below zero and falling (red)
- Enter on first green dot

**Exit Rules:**
- Exit when histogram changes direction
- Or when histogram shows 2 bars in opposite color

---

### Strategy 21.2: TTM Squeeze + Trend Filter
**Category:** Trend Following  
**Timeframe:** 1H, 4H  
**Indicators:** TTM Squeeze, 200 EMA or Ichimoku

**Rules:**
- Only take long squeezes when price above 200 EMA
- Only take short squeezes when price below 200 EMA
- Confirm squeeze direction with higher timeframe

---

## 22. GMMA Strategies

### Strategy 22.1: GMMA Trend Trading
**Category:** Trend Following  
**Timeframe:** Any  
**Indicators:** GMMA (12 EMAs)

**Short-term EMAs:** 3, 5, 8, 10, 12, 15  
**Long-term EMAs:** 30, 35, 40, 45, 50, 60

**Trend Identification:**
- Wide separation between groups = Strong trend
- Narrow separation = Weak trend or consolidation
- Groups crossing = Trend reversal

**Entry Rules - Long:**
- Short-term group crosses above long-term group
- Both groups trending upward
- Wide separation developing

**Entry Rules - Short:**
- Short-term group crosses below long-term group
- Both groups trending downward

**Exit Rules:**
- Exit when groups start converging
- Or when short-term group touches long-term group

---

### Strategy 22.2: GMMA Pullback Entry
**Category:** Trend Following  
**Timeframe:** Any  
**Indicators:** GMMA

**Rules:**
- In uptrend: Short-term EMAs pull back toward long-term EMAs
- Enter when short-term EMAs bounce off long-term EMAs
- Stop loss below long-term EMA group

---

## 23. Choppiness Index Strategies

### Strategy 23.1: Choppiness Index Filter
**Category:** Market Condition Filter  
**Timeframe:** Any  
**Indicators:** Choppiness Index(14)

**Readings:**
- Above 61.8 = Choppy/Ranging market
- Below 38.2 = Trending market
- Below 25 = Trend may be ending

**Rules:**
- Only trade when CI < 45 (trending)
- Avoid trades when CI > 61.8 (choppy)
- Use as filter for other strategies

---

### Strategy 23.2: Choppiness Breakout Strategy
**Category:** Breakout  
**Timeframe:** 1H, 4H  
**Indicators:** Choppiness Index(14), Volume

**Entry Rules:**
- CI above 61.8 for extended period (consolidation)
- CI drops below 61.8 (trend starting)
- Price breaks support/resistance
- Volume increasing

---

### Strategy 23.3: Choppiness + Volume Strategy
**Category:** Breakout Confirmation  
**Timeframe:** 1H, 4H  
**Indicators:** Choppiness Index, Volume

**Rules:**
- High CI + Low volume = Consolidation
- CI drops + Volume increases = Breakout confirmation
- Trade in direction of breakout

---

## 24. Exit Indicator Strategies

### Strategy 24.1: Chandelier Exit Strategy
**Category:** Exit/Trailing Stop  
**Timeframe:** Any  
**Indicators:** Chandelier Exit (ATR-based)

**Calculation:**
- Long: Highest High - (ATR × Multiplier)
- Short: Lowest Low + (ATR × Multiplier)
- Default: 22 period, 3× ATR multiplier

**Rules:**
- Use as trailing stop loss
- Exit long when price closes below Chandelier Exit
- Exit short when price closes above Chandelier Exit
- Increase multiplier (4-5×) for volatile stocks

---

### Strategy 24.2: Donchian Channel Strategy
**Category:** Trend Following/Exit  
**Timeframe:** Daily  
**Indicators:** Donchian Channel(20)

**Components:**
- Upper band = Highest high of N periods
- Lower band = Lowest low of N periods
- Middle band = Average of upper and lower

**Entry Rules - Long (Turtle Trading):**
- Price breaks above upper band
- Enter on breakout

**Entry Rules - Short:**
- Price breaks below lower band
- Enter on breakdown

**Exit Rules:**
- Exit long when price touches lower band
- Exit short when price touches upper band
- Or use middle band for earlier exit

---

## 25. Price Action Strategies

### Strategy 25.1: Market Swing Analysis
**Category:** Price Action  
**Timeframe:** Any  
**Indicators:** None

**Bar Classification:**
- Up bar: Higher high, higher low
- Down bar: Lower high, lower low
- Inside bar: Lower high, higher low
- Outside bar: Higher high, lower low

**Swing Rules:**
- Up bar starts upswing, confirms end of downswing
- Down bar starts downswing, confirms end of upswing
- Inside bars don't affect current swing
- Outside bars continue current swing direction

---

### Strategy 25.2: Swing Pivot Trading
**Category:** Support/Resistance  
**Timeframe:** Any  
**Indicators:** None

**Rules:**
- Swing highs = Resistance levels
- Swing lows = Support levels
- Failed resistance becomes support
- Failed support becomes resistance

---

### Strategy 25.3: Candlestick Pattern Strategy
**Category:** Price Action  
**Timeframe:** 4H, Daily  
**Indicators:** None

**Key Patterns at S/R:**
- Hammer at support = Bullish
- Shooting star at resistance = Bearish
- Engulfing patterns = Strong reversal signal

**Rules:**
- Only trade patterns at key levels
- Confirm with volume
- Use pattern high/low for stop loss

---

## 26. TRIX Strategies

### Strategy 26.1: TRIX Zero-Line Strategy
**Category:** Trend Following  
**Timeframe:** 4H, Daily  
**Indicators:** TRIX(15)

**Entry Rules - Long:**
- TRIX crosses above zero
- Price breaks above trendline or resistance
- Higher swing high or higher swing low

**Entry Rules - Short:**
- TRIX crosses below zero
- Price breaks below trendline or support
- Lower swing high or lower swing low

**Exit Rules:**
- Stop loss: Above recent high (shorts) or below recent low (longs)
- Don't rely on TRIX for exit timing

---

### Strategy 26.2: TRIX Divergence Strategy
**Category:** Reversal  
**Timeframe:** 4H, Daily  
**Indicators:** TRIX(15)

**Rules:**
- Bullish divergence: Price lower low, TRIX higher low
- Bearish divergence: Price higher high, TRIX lower high
- Divergences work better at extremes
- Confirm with price action breakout

---

## 27. Rate of Change Strategies

### Strategy 27.1: ROC + Moving Average Strategy
**Category:** Trend Following  
**Timeframe:** 4H, Daily  
**Indicators:** ROC(14), SMA(50)

**Entry Rules - Long:**
- Price above 50 SMA
- ROC crosses above zero
- Exit when ROC slope turns negative

**Entry Rules - Short:**
- Price below 50 SMA
- ROC crosses below zero
- Exit when ROC slope turns positive

---

### Strategy 27.2: ROC Divergence Strategy
**Category:** Reversal  
**Timeframe:** 4H, Daily  
**Indicators:** ROC(14)

**Rules:**
- Bullish divergence: Price lower low, ROC higher low
- Bearish divergence: Price higher high, ROC lower high
- Confirm with trendline breakout
- Wait for ROC to cross zero for entry

---

## 28. StochRSI Strategies

### Strategy 28.1: StochRSI 50-Level Strategy
**Category:** Trend Following  
**Timeframe:** 1H, 4H  
**Indicators:** StochRSI(100,100), MACD(10,100,1)

**Setup:**
- Use only %D line of StochRSI
- Add 50 level as key reference
- MACD settings track 10/100 EMA crossover

**Entry Rules - Long:**
- StochRSI above 50 (bullish pressure)
- MACD above zero (confirms bullish)

**Entry Rules - Short:**
- StochRSI below 50 (bearish pressure)
- MACD below zero (confirms bearish)

---

### Strategy 28.2: StochRSI Divergence Strategy
**Category:** Reversal  
**Timeframe:** 4H, Daily  
**Indicators:** StochRSI(14), 200 EMA

**Rules:**
- Only trade divergences in direction of 200 EMA trend
- If price > 200 EMA: Look for bullish divergences only
- If price < 200 EMA: Look for bearish divergences only
- Use %D line for cleaner divergence signals

---

## 29. Scalping Strategies

### Strategy 29.1: 1-Minute EMA Scalping
**Category:** Scalping  
**Timeframe:** 1m  
**Indicators:** EMA(9), EMA(21), EMA(55)

**Entry Rules - Long:**
- All EMAs aligned bullish (9 > 21 > 55)
- Price pulls back to EMA 9 or 21
- Bullish candle at EMA
- Enter with tight stop below EMA 55

**Entry Rules - Short:**
- All EMAs aligned bearish (9 < 21 < 55)
- Price rallies to EMA 9 or 21
- Bearish candle at EMA

**Exit Rules:**
- Take profit: 1-1.5× risk
- Time-based exit if no movement

---

### Strategy 29.2: VWAP Scalping
**Category:** Scalping  
**Timeframe:** 1m, 5m  
**Indicators:** VWAP, VWAP bands

**Rules:**
- Trade bounces from VWAP
- Long bias when price above VWAP
- Short bias when price below VWAP
- Target: VWAP band or previous swing

---

### Strategy 29.3: TICK Index Scalping
**Category:** Scalping  
**Timeframe:** 1m  
**Indicators:** NYSE TICK Index

**Rules:**
- TICK > +800 = Overbought (short opportunity)
- TICK < -800 = Oversold (long opportunity)
- TICK crossing zero = Momentum shift
- Use with price action confirmation

---

## 30. Risk Management Guidelines

### Position Sizing
- Risk 1-2% of account per trade
- Calculate position size: Risk Amount / (Entry - Stop Loss)
- Reduce size in volatile markets

### Stop Loss Placement
- ATR-based: 1.5-3× ATR from entry
- Structure-based: Below support (longs) or above resistance (shorts)
- Never move stop loss against position

### Take Profit Strategies
- Fixed R:R ratio (1:2 or 1:3)
- Scale out at multiple targets
- Trail stop using ATR or moving average

### Trade Management
- Move stop to breakeven after 1R profit
- Trail stop as trade moves in favor
- Don't add to losing positions

### Market Conditions
- Reduce position size in choppy markets
- Increase position size in trending markets
- Avoid trading during major news events

### Psychology Rules
- Stick to trading plan
- Accept losses as part of trading
- Don't revenge trade
- Take breaks after losing streaks
- Journal all trades for review

---

## Implementation Notes for Kite System

### Existing Indicator Modules

The kite project has these indicator modules available:

- `kite/indicators/moving_averages.py` - EMA, SMA, VWMA
- `kite/indicators/oscillators.py` - RSI, MACD, Stochastic, CCI
- `kite/indicators/volatility.py` - ATR, Bollinger Bands
- `kite/indicators/volume.py` - OBV, MFI, volume indicators
- `kite/indicators/fibonacci.py` - Fibonacci levels
- `kite/indicators/support_resistance.py` - S/R detection
- `kite/indicators/trend.py` - ADX, trend indicators

### Adding New Strategies

1. Create strategy file in `kite/strategies/`
2. Import required indicators
3. Implement entry/exit logic
4. Add backtesting support
5. Test with historical data

### Strategy Template

```python
from kite.indicators.oscillators import calculate_rsi
from kite.indicators.moving_averages import calculate_ema

class MyStrategy:
    def __init__(self, params=None):
        self.params = params or {}
        
    def generate_signals(self, df):
        """Generate buy/sell signals"""
        # Calculate indicators
        df['rsi'] = calculate_rsi(df['close'], period=14)
        df['ema_200'] = calculate_ema(df['close'], period=200)
        
        # Generate signals
        df['signal'] = 0
        df.loc[(df['close'] > df['ema_200']) & 
               (df['rsi'] > 50) & 
               (df['rsi'].shift(1) <= 50), 'signal'] = 1  # Buy
        df.loc[(df['close'] < df['ema_200']) & 
               (df['rsi'] < 50) & 
               (df['rsi'].shift(1) >= 50), 'signal'] = -1  # Sell
               
        return df
```

---

## Quick Reference Table

| Strategy | Type | Best Timeframe | Difficulty |
|----------|------|----------------|------------|
| RSI Divergence | Reversal | 4H, Daily | Medium |
| MACD Zero-Line | Trend | 4H, Daily | Easy |
| BB Squeeze | Breakout | 1H, 4H | Medium |
| 3-EMA Scalping | Scalping | 1m, 5m | Medium |
| VWAP Bounce | Intraday | 5m, 15m | Easy |
| Ichimoku Cloud | Trend | 4H, Daily | Hard |
| Supply/Demand | Price Action | 1H, 4H | Medium |
| Wyckoff | Structure | Daily | Hard |
| Fibonacci 61.8% | Trend | 4H, Daily | Medium |
| TTM Squeeze | Breakout | 1H, 4H | Medium |

---

*This guide is for educational purposes. Always backtest strategies before live trading and use proper risk management.*
