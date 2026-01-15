# Trading Strategy Backtesting System

A comprehensive Python-based backtesting framework for testing trading strategies on Indian stock market data (NIFTY 50).

## Features

- **9 Trading Strategies** implemented and ready to test:
  1. **EMA 21/55** - Contraction-Expansion strategy using dual EMAs
  2. **RSI Divergence** - Divergence trading at support/resistance
  3. **VWAP Pullback** - Pullback entries to VWAP
  4. **Bollinger Bands Squeeze** - Volatility breakout strategy
  5. **3-EMA Scalping** - Triple EMA trend-following
  6. **Supply & Demand** - Zone-based trading
  7. **Stochastic Confluence** - Multi-indicator confluence
  8. **Fibonacci 3-Wave** - ABC pattern with Fib extensions
  9. **Multi-Timeframe** - Higher TF trend + lower TF entry

- **Full Backtesting Engine** with:
  - Risk-based position sizing
  - Zerodha brokerage calculation
  - ATR-based stop losses
  - Performance metrics (Sharpe, Sortino, Calmar, etc.)

- **Comprehensive Analytics**:
  - Equity curves
  - Drawdown analysis
  - Monthly returns
  - Strategy comparison

## Installation

```bash
pip install -r requirements.txt
```

## Quick Start

### 1. Run Quick Test
```bash
python quick_test.py
```

### 2. Run Single Strategy Backtest
```bash
python run_backtest.py --strategy ema_21_55 --symbol RELIANCE --timeframe daily
```

### 3. Compare All Strategies on One Stock
```bash
python run_backtest.py --all-strategies --symbol RELIANCE --no-plots
```

### 4. Run Full Comparison Across Multiple Stocks
```bash
python compare_strategies.py --stocks RELIANCE TCS HDFCBANK INFY ICICIBANK
```

### 5. Run on All NIFTY 50 Stocks
```bash
python compare_strategies.py --all-stocks
```

## Available Strategies

| Strategy | Best For | Timeframe | Description |
|----------|----------|-----------|-------------|
| `ema_21_55` | Swing Trading | Daily/Hourly | Trades pullbacks to EMA zone |
| `rsi_divergence` | Reversals | Daily | Divergence at S/R levels |
| `vwap_pullback` | Day Trading | Minute/Hourly | VWAP as dynamic S/R |
| `bb_squeeze` | Breakouts | All | Low volatility breakouts |
| `ema_3_scalping` | Scalping | Minute | Triple EMA pullbacks |
| `supply_demand` | Swing | Daily/Hourly | Zone-based entries |
| `stochastic_confluence` | Swing | Daily | Multi-indicator confluence |
| `fib_3wave` | Swing | Daily | Fibonacci pattern trading |
| `multi_timeframe` | Swing | Multi | Higher TF trend alignment |

## Project Structure

```
kite/
├── config.py                 # Configuration and parameters
├── run_backtest.py          # Main backtest runner
├── compare_strategies.py     # Strategy comparison tool
├── quick_test.py            # Quick system test
├── requirements.txt         # Dependencies
│
├── strategies/              # Trading strategies
│   ├── base_strategy.py     # Abstract base class
│   ├── ema_21_55.py
│   ├── rsi_divergence.py
│   ├── vwap_pullback.py
│   ├── bb_squeeze.py
│   ├── ema_3_scalping.py
│   ├── supply_demand.py
│   ├── stochastic_confluence.py
│   ├── fib_3wave.py
│   └── multi_timeframe.py
│
├── indicators/              # Technical indicators
│   ├── moving_averages.py   # EMA, SMA, WMA, etc.
│   ├── oscillators.py       # RSI, Stochastic, etc.
│   ├── volatility.py        # ATR, Bollinger Bands
│   ├── volume.py            # VWAP, OBV, etc.
│   ├── fibonacci.py         # Fib retracements/extensions
│   └── support_resistance.py
│
├── backtesting/             # Backtesting engine
│   ├── engine.py            # Core backtest logic
│   └── performance.py       # Metrics and reports
│
├── utils/                   # Utilities
│   ├── data_loader.py       # Data loading
│   └── plotting.py          # Visualization
│
└── reports/                 # Generated reports
```

## Configuration

Edit `config.py` to customize:

```python
# Capital and risk settings
initial_capital = 100_000     # Starting capital (Rs)
risk_per_trade = 0.02         # 2% risk per trade
max_positions = 5             # Max concurrent positions

# Trading direction
allow_long = True
allow_short = True

# Zerodha charges are automatically calculated
```

## Performance Metrics

The system calculates:
- **Total Return %** - Overall profit/loss
- **Win Rate %** - Percentage of winning trades
- **Profit Factor** - Gross profit / Gross loss
- **Sharpe Ratio** - Risk-adjusted returns
- **Sortino Ratio** - Downside risk-adjusted returns
- **Max Drawdown** - Largest peak-to-trough decline
- **Calmar Ratio** - Annual return / Max drawdown

## Data Format

The system expects CSV files with columns:
```
datetime,open,high,low,close,volume,oi
```

Data should be placed in:
- `data/` - Minute data (e.g., `RELIANCE_minute_60d.csv`)
- `data/hourly/` - Hourly data
- `data/daily/` - Daily data (e.g., `RELIANCE_day_2000d.csv`)

## Creating Custom Strategies

1. Create a new file in `strategies/`
2. Inherit from `BaseStrategy`
3. Implement required methods:

```python
from kite.strategies.base_strategy import BaseStrategy, Signal

class MyStrategy(BaseStrategy):
    def generate_signals(self, df):
        # Your signal logic
        df['signal'] = 0  # 1=BUY, -1=SELL, 0=HOLD
        return df
    
    def calculate_stop_loss(self, df, idx, direction):
        # Return stop loss price
        pass
    
    def calculate_take_profit(self, df, idx, direction, entry, stop):
        # Return take profit price
        pass
```

## License

MIT License

## Disclaimer

This software is for educational purposes only. Trading involves substantial risk of loss. Past performance does not guarantee future results.
