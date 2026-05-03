# Dual-Mode Trading: Intraday + Swing

**Date:** 2026-04-30
**Status:** Approved

## Problem

Live monitor uses 3 strategies (elliott_wave3, vwap_pullback, ichimoku_ha) that are profitable on daily timeframe but lose money on intraday (5-min candles with EOD square-off). Only `fib_3wave` shows positive intraday returns. The system has no concept of holding positions overnight.

## Solution

Add dual trading modes to the existing monitor — **INTRADAY** and **SWING** — in a single process, single DB, single dashboard.

### Strategies by Mode

| Mode | Strategies | Candle Timeframe | Holding Period |
|------|-----------|-----------------|----------------|
| INTRADAY | `fib_3wave` | 5-minute | EOD close at 15:20 |
| SWING | `ema_21_55`, `vwap_pullback`, `elliott_wave3` | Daily | Until SL/TP/trailing stop |

### Backtest Justification

| Strategy | Timeframe | Return | Win Rate | Sharpe |
|----------|-----------|--------|----------|--------|
| fib_3wave | Hourly | +5.1% | 78% | 0.68 |
| ema_21_55 | Daily | +45.7% | 66% | 0.50 |
| vwap_pullback | Daily | +27.6% | 38% | 0.17 |
| elliott_wave3 | Daily | +19.5% | 46% | 0.22 |

## Architecture: Approach A — Trade Mode Field on Position

Single process, single DB. Mode tagged per position. EOD close filters by mode.

### Data Model Changes

**Position dataclass** — add field:
```python
trade_mode: str  # "INTRADAY" or "SWING"
```

**TradeSignal dataclass** — add field:
```python
trade_mode: str  # "INTRADAY" or "SWING"
```

**DB `positions` table** — add column:
```sql
ALTER TABLE positions ADD COLUMN trade_mode TEXT DEFAULT 'INTRADAY'
```

Migration via try/except in `_init_database()` (SQLite lacks ALTER IF NOT EXISTS).

**EOD close** — `close_all_positions_eod()` filters to `WHERE trade_mode = 'INTRADAY'` only.

### Monitor Loop

**Intraday scan (existing, modified):**
- Runs every 5 min during market hours (9:20–15:10)
- `fib_3wave` strategy only
- 5-min candles fed to signal detector
- Positions tagged `trade_mode=INTRADAY`
- EOD close at 15:20 — INTRADAY positions only

**Swing scan (new):**
- Runs once daily at 9:25 (after market open, fresh daily candle)
- `ema_21_55`, `vwap_pullback`, `elliott_wave3` strategies
- Daily candles fed to signal detector
- Positions tagged `trade_mode=SWING`
- No EOD close

**Swing position check (piggybacks on existing 5-min cycle):**
- For each open SWING position: fetch current price, update trailing stop, check SL/TP
- Same `check_open_positions` call handles both modes

### Capital Allocation (Dynamic)

- Total capital pool shared, no hard split
- Slot-based sizing: ₹20K slots, 5 max positions
- If 3 swing positions open, 2 slots available for intraday (or more swing)
- Existing `required_capital > self.capital` check prevents over-allocation

### Trailing Stop for Swing Positions

Stepped ratchet — after entry, tighten stop as price moves in favor. Never move stop backwards.

**On entry:** `trailing_stop = stop_loss` (same as initial SL)

**Every 5-min check cycle, for each SWING position:**
1. Fetch current price
2. Calculate favorable move: for BUY `move_pct = (current - entry) / entry`, for SELL `move_pct = (entry - current) / entry`
3. Apply stepped thresholds (trail above entry for BUY, below entry for SELL):

```python
TRAILING_STEPS = [
    (0.01, 0.000),   # 1% move -> breakeven
    (0.03, 0.015),   # 3% move -> lock 1.5%
    (0.05, 0.030),   # 5% move -> lock 3%
    (0.08, 0.055),   # 8% move -> lock 5.5%
]
```

4. Never move stop lower than current `trailing_stop` value
5. Exit when price crosses trailing stop

### Dashboard Updates

- **Open Positions table** — add "Mode" column (INTRADAY blue `#60a5fa`, SWING purple `#a78bfa`)
- **Closed Trades table** — add "Mode" column
- **Cards section** — add "Swing Positions" count card
- **Equity curve** — no change (tracks total capital, mode-agnostic)

### Deployment

- Same tar/scp/extract flow to Oracle ARM
- Restart `kite-monitor` and `kite-dashboard` services
- Wipe DB (old data has broken capital from previous bugs)
- No new services, ports, or infra changes

### Strategy Config

```python
INTRADAY_STRATEGIES = ['fib_3wave']
SWING_STRATEGIES = ['ema_21_55', 'vwap_pullback', 'elliott_wave3']
```

Hardcoded in monitor.py. CLI `--strategy` flag still works for overrides.

### Schedule

| Time | Action |
|------|--------|
| 9:20 | Intraday scan starts (every 5 min) |
| 9:25 | Swing scan (once daily) |
| 9:20–15:10 | Swing position trailing stop check (every 5 min) |
| 15:20 | EOD close — INTRADAY only |

## Files Modified

| File | Changes |
|------|---------|
| `kite/live_monitor/paper_trader.py` | Add `trade_mode` to Position, TradeSignal. Filter EOD close. Add trailing stop update method. DB migration. |
| `kite/live_monitor/monitor.py` | Split strategy lists. Add swing scan schedule. Route signals with mode tag. |
| `kite/live_monitor/signal_detector.py` | Accept and pass through `trade_mode` on TradeSignal. |
| `kite/live_monitor/dashboard.py` | Add Mode column to tables, swing count card, mode badges. |
