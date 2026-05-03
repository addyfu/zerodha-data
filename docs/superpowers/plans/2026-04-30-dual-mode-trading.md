# Dual-Mode Trading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add intraday + swing dual-mode trading to the live monitor, so intraday positions close at EOD while swing positions hold with trailing stops.

**Architecture:** Add `trade_mode` field to Position/TradeSignal dataclasses. Monitor runs two scan paths — 5-min candles for intraday (`fib_3wave`), daily candles for swing (`ema_21_55`, `vwap_pullback`, `elliott_wave3`). EOD close filters by mode. Stepped trailing stop ratchets up for swing positions.

**Tech Stack:** Python, SQLite3, Flask, existing strategy registry, existing data fetcher.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `kite/live_monitor/paper_trader.py` | Position/TradeSignal dataclasses, paper trading engine, DB persistence |
| `kite/live_monitor/signal_detector.py` | Signal detection, position sizing, trade_mode passthrough |
| `kite/live_monitor/monitor.py` | Main orchestration, scan scheduling, strategy routing |
| `kite/live_monitor/dashboard.py` | Flask web dashboard |

No new files. All changes in existing files.

---

### Task 1: Add `trade_mode` to TradeSignal Dataclass

**Files:**
- Modify: `kite/live_monitor/signal_detector.py:24-58`

- [ ] **Step 1: Add trade_mode field to TradeSignal**

In `kite/live_monitor/signal_detector.py`, add `trade_mode` field to the `TradeSignal` dataclass after the `notes` field (line 41):

```python
@dataclass
class TradeSignal:
    """Represents a detected trading signal."""
    symbol: str
    direction: str  # 'BUY' or 'SELL'
    strategy: str
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_pct: float
    reward_pct: float
    rr_ratio: float
    quantity: int
    position_value: float
    timestamp: datetime
    confidence: float = 0.0
    notes: str = ""
    trade_mode: str = "INTRADAY"  # "INTRADAY" or "SWING"
```

- [ ] **Step 2: Add trade_mode to TradeSignal.to_dict()**

Add `'trade_mode': self.trade_mode` to the `to_dict` method return dict.

- [ ] **Step 3: Commit**

```bash
git add kite/live_monitor/signal_detector.py
git commit -m "feat: add trade_mode field to TradeSignal dataclass"
```

---

### Task 2: Add `trade_mode` to Position Dataclass and DB

**Files:**
- Modify: `kite/live_monitor/paper_trader.py:34-84` (Position dataclass)
- Modify: `kite/live_monitor/paper_trader.py:124-182` (_init_database, DB migration)

- [ ] **Step 1: Add trade_mode field to Position dataclass**

In `kite/live_monitor/paper_trader.py`, add `trade_mode` field to `Position` after `status` (line 57):

```python
@dataclass
class Position:
    """Represents an open or closed position."""
    id: int
    symbol: str
    direction: str  # 'BUY' or 'SELL'
    entry_price: float
    entry_time: datetime
    quantity: int
    stop_loss: float
    take_profit: float
    strategy: str
    
    # Exit info (filled when closed)
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_reason: Optional[str] = None
    
    # P&L
    pnl: float = 0.0
    pnl_pct: float = 0.0
    
    # Status
    status: str = "open"
    
    # Trade mode
    trade_mode: str = "INTRADAY"  # "INTRADAY" or "SWING"
    
    # Trailing stop
    trailing_stop: Optional[float] = None
    highest_price: Optional[float] = None  # For long
    lowest_price: Optional[float] = None   # For short
```

- [ ] **Step 2: Add trade_mode to Position.to_dict()**

Add `'trade_mode': self.trade_mode` to the `to_dict` method return dict.

- [ ] **Step 3: Add DB migration for trade_mode column**

In `_init_database()`, after the existing `CREATE TABLE` statements (after line 181), add migration:

```python
        # Migration: add trade_mode column if missing
        try:
            cursor.execute("ALTER TABLE positions ADD COLUMN trade_mode TEXT DEFAULT 'INTRADAY'")
        except sqlite3.OperationalError:
            pass  # Column already exists
```

- [ ] **Step 4: Update _save_position to include trade_mode**

Update the `_save_position` method to include `trade_mode` in the INSERT statement. The column list and VALUES tuple both need the new field:

```python
    def _save_position(self, position: Position):
        """Save position to database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO positions 
            (id, symbol, direction, entry_price, entry_time, quantity, stop_loss, take_profit,
             strategy, exit_price, exit_time, exit_reason, pnl, pnl_pct, status,
             trailing_stop, highest_price, lowest_price, trade_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            position.id, position.symbol, position.direction, position.entry_price,
            position.entry_time.isoformat(), position.quantity, position.stop_loss,
            position.take_profit, position.strategy, position.exit_price,
            position.exit_time.isoformat() if position.exit_time else None,
            position.exit_reason, position.pnl, position.pnl_pct, position.status,
            position.trailing_stop, position.highest_price, position.lowest_price,
            position.trade_mode
        ))
        
        conn.commit()
        conn.close()
```

- [ ] **Step 5: Update _load_state to read trade_mode**

In `_load_state`, update the Position construction from DB row to include `trade_mode`. The new column is index 18 (after highest_price at 16, lowest_price at 17):

```python
            pos = Position(
                id=row[0],
                symbol=row[1],
                direction=row[2],
                entry_price=row[3],
                entry_time=datetime.fromisoformat(row[4]),
                quantity=row[5],
                stop_loss=row[6],
                take_profit=row[7],
                strategy=row[8],
                status='open',
                trailing_stop=row[15],
                highest_price=row[16],
                lowest_price=row[17],
                trade_mode=row[18] if len(row) > 18 and row[18] else "INTRADAY"
            )
```

- [ ] **Step 6: Commit**

```bash
git add kite/live_monitor/paper_trader.py
git commit -m "feat: add trade_mode to Position dataclass and DB schema"
```

---

### Task 3: Wire trade_mode Through open_position

**Files:**
- Modify: `kite/live_monitor/paper_trader.py:255-316` (open_position)

- [ ] **Step 1: Set trade_mode from signal in open_position**

In `open_position`, when creating the Position object (line 286), add `trade_mode` from the signal:

```python
        position = Position(
            id=self.trade_counter,
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.entry_price,
            entry_time=datetime.now(),
            quantity=signal.quantity,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            strategy=signal.strategy,
            trade_mode=getattr(signal, 'trade_mode', 'INTRADAY'),
            highest_price=signal.entry_price if signal.direction == 'BUY' else None,
            lowest_price=signal.entry_price if signal.direction == 'SELL' else None
        )
```

- [ ] **Step 2: Commit**

```bash
git add kite/live_monitor/paper_trader.py
git commit -m "feat: wire trade_mode from signal to position on open"
```

---

### Task 4: Filter EOD Close to INTRADAY Only

**Files:**
- Modify: `kite/live_monitor/paper_trader.py:425-434` (close_all_positions)

- [ ] **Step 1: Add trade_mode filter to close_all_positions**

Change `close_all_positions` to accept an optional `trade_mode` filter:

```python
    def close_all_positions(self, current_prices: Dict[str, float],
                           reason: ExitReason = ExitReason.END_OF_DAY,
                           trade_mode: Optional[str] = None) -> List[Position]:
        """Close positions, optionally filtered by trade_mode."""
        closed = []
        for symbol in list(self.positions.keys()):
            position = self.positions[symbol]
            if trade_mode and position.trade_mode != trade_mode:
                continue
            if symbol in current_prices:
                closed_pos = self.close_position(symbol, current_prices[symbol], reason)
                if closed_pos:
                    closed.append(closed_pos)
        return closed
```

- [ ] **Step 2: Update monitor.py EOD call to filter INTRADAY only**

In `kite/live_monitor/monitor.py`, line 399, change:

```python
        closed = self.trader.close_all_positions(current_prices, ExitReason.END_OF_DAY)
```

to:

```python
        closed = self.trader.close_all_positions(current_prices, ExitReason.END_OF_DAY, trade_mode="INTRADAY")
```

- [ ] **Step 3: Update EOD log message to clarify intraday-only**

In `monitor.py`, change the EOD header (line 381):

```python
        logger.info("END OF DAY - CLOSING INTRADAY POSITIONS")
```

And the summary (line 415):

```python
        logger.info(f"Closed {len(closed)} intraday positions at EOD")
```

- [ ] **Step 4: Commit**

```bash
git add kite/live_monitor/paper_trader.py kite/live_monitor/monitor.py
git commit -m "feat: EOD close filters to INTRADAY positions only"
```

---

### Task 5: Add Stepped Trailing Stop for Swing Positions

**Files:**
- Modify: `kite/live_monitor/paper_trader.py` (add new method)

- [ ] **Step 1: Add TRAILING_STEPS constant and update_swing_trailing_stop method**

Add after the existing `_update_trailing_stop` method (after line 456):

```python
    TRAILING_STEPS = [
        (0.01, 0.000),   # 1% move -> breakeven
        (0.03, 0.015),   # 3% move -> lock 1.5%
        (0.05, 0.030),   # 5% move -> lock 3%
        (0.08, 0.055),   # 8% move -> lock 5.5%
    ]

    def update_swing_trailing_stop(self, position: Position, current_price: float) -> bool:
        """
        Update trailing stop for swing positions using stepped ratchet.
        Returns True if trailing stop was updated.
        """
        if position.trade_mode != "SWING":
            return False

        entry = position.entry_price

        if position.direction == 'BUY':
            move_pct = (current_price - entry) / entry
            for threshold, lock_pct in reversed(self.TRAILING_STEPS):
                if move_pct >= threshold:
                    new_stop = entry * (1 + lock_pct)
                    if position.trailing_stop is None or new_stop > position.trailing_stop:
                        position.trailing_stop = new_stop
                        self._save_position(position)
                        logger.info(f"SWING trailing stop updated: {position.symbol} -> {new_stop:.2f} (move {move_pct:.1%}, lock {lock_pct:.1%})")
                        return True
                    break
        else:  # SELL
            move_pct = (entry - current_price) / entry
            for threshold, lock_pct in reversed(self.TRAILING_STEPS):
                if move_pct >= threshold:
                    new_stop = entry * (1 - lock_pct)
                    if position.trailing_stop is None or new_stop < position.trailing_stop:
                        position.trailing_stop = new_stop
                        self._save_position(position)
                        logger.info(f"SWING trailing stop updated: {position.symbol} -> {new_stop:.2f} (move {move_pct:.1%}, lock {lock_pct:.1%})")
                        return True
                    break

        return False
```

- [ ] **Step 2: Call swing trailing stop in check_exits**

In `check_exits` method (line 386-388), replace the existing trailing stop update block:

```python
            # Update trailing stop
            if self.use_trailing_stop:
                self._update_trailing_stop(position, price)
```

with mode-aware logic:

```python
            # Update trailing stop (mode-specific)
            if position.trade_mode == "SWING":
                self.update_swing_trailing_stop(position, price)
            elif self.use_trailing_stop:
                self._update_trailing_stop(position, price)
```

- [ ] **Step 3: Commit**

```bash
git add kite/live_monitor/paper_trader.py
git commit -m "feat: add stepped trailing stop for swing positions"
```

---

### Task 6: Split Strategy Lists and Add Swing Scan to Monitor

**Files:**
- Modify: `kite/live_monitor/monitor.py:82-83` (strategy constants)
- Modify: `kite/live_monitor/monitor.py:118-132` (detector init)
- Modify: `kite/live_monitor/monitor.py:178-196` (data loading)
- Modify: `kite/live_monitor/monitor.py:259-279` (scan_for_signals)
- Modify: `kite/live_monitor/monitor.py:432-452` (scheduling)

- [ ] **Step 1: Replace STRATEGIES with INTRADAY_STRATEGIES and SWING_STRATEGIES**

In `kite/live_monitor/monitor.py`, replace line 82-83:

```python
    # Best 3 strategies for 5-minute intraday (backtested on real 5-min data)
    STRATEGIES = ['elliott_wave3', 'vwap_pullback', 'ichimoku_ha']
```

with:

```python
    INTRADAY_STRATEGIES = ['fib_3wave']
    SWING_STRATEGIES = ['ema_21_55', 'vwap_pullback', 'elliott_wave3']
```

- [ ] **Step 2: Create separate detector lists for each mode**

Replace the detector init block (lines 118-132) with:

```python
        # Signal detectors — separate lists per mode
        max_positions = 5
        slot_size = capital / max_positions

        if strategy:
            # CLI override: single strategy, default to intraday
            self.intraday_detectors = [
                SignalDetector(strategy_name=strategy, capital=capital,
                               risk_per_trade=0.02, min_rr_ratio=1.5,
                               max_position_pct=slot_size / capital)
            ]
            self.swing_detectors = []
        else:
            self.intraday_detectors = [
                SignalDetector(strategy_name=s, capital=capital,
                               risk_per_trade=0.02, min_rr_ratio=1.5,
                               max_position_pct=slot_size / capital)
                for s in self.INTRADAY_STRATEGIES
            ]
            self.swing_detectors = [
                SignalDetector(strategy_name=s, capital=capital,
                               risk_per_trade=0.02, min_rr_ratio=1.5,
                               max_position_pct=slot_size / capital)
                for s in self.SWING_STRATEGIES
            ]

        all_strategies = [d.strategy_name for d in self.intraday_detectors + self.swing_detectors]
        logger.info(f"Strategies: {', '.join(all_strategies)} | Slot size: Rs {slot_size:,.0f}")
```

- [ ] **Step 3: Add daily data cache for swing strategies**

Add a new attribute in `__init__` (after `self.data_cache` line 147):

```python
        self.daily_data_cache: Dict[str, pd.DataFrame] = {}
        self.swing_scanned_today = False
```

- [ ] **Step 4: Load daily data alongside 5-min data**

In `load_historical_data`, after the existing `self.data_cache = self.db.load_nifty50(self.stocks, resample='5min')` line (193), add:

```python
        # Load daily data for swing strategies
        if self.swing_detectors:
            self.daily_data_cache = self.db.load_nifty50(self.stocks, resample='1D')
            logger.info(f"Loaded daily data for {len(self.daily_data_cache)}/{len(self.stocks)} stocks (swing mode)")
```

- [ ] **Step 5: Add scan_for_swing_signals method**

Add after `scan_for_signals` method:

```python
    def scan_for_swing_signals(self) -> List[TradeSignal]:
        """Scan daily data for swing trading signals (run once per day)."""
        if not self.swing_detectors or not self.daily_data_cache:
            return []

        signals = []
        seen = set()

        for symbol, df in self.daily_data_cache.items():
            if df is None or len(df) < 50:
                continue
            for detector in self.swing_detectors:
                try:
                    signal = detector.detect_signal(symbol, df)
                    if signal:
                        key = (symbol, signal.direction)
                        if key not in seen:
                            signal.trade_mode = "SWING"
                            seen.add(key)
                            signals.append(signal)
                            logger.info(f"SWING SIGNAL [{signal.strategy}]: {symbol} {signal.direction} @ Rs {signal.entry_price:.2f}")
                except Exception as e:
                    logger.error(f"Error scanning {symbol} with {detector.strategy_name} (swing): {e}", exc_info=True)

        return signals
```

- [ ] **Step 6: Update scan_for_signals to tag intraday mode**

In the existing `scan_for_signals` method, after `signals.append(signal)` (line 274), add:

```python
                            signal.trade_mode = "INTRADAY"
```

- [ ] **Step 7: Add swing scan to run_scan_cycle**

In `run_scan_cycle`, after processing intraday signals (after line 362), add the swing scan:

```python
            # Swing scan — once per day at market open
            now = datetime.now()
            if not self.swing_scanned_today and now.time() >= dtime(9, 25):
                swing_signals = self.scan_for_swing_signals()
                logger.info(f"Swing scan: {len(swing_signals)} signal(s) found")
                if swing_signals:
                    self.process_signals(swing_signals)
                self.swing_scanned_today = True

            # Reset swing scan flag for next day
            if now.time() < dtime(9, 20):
                self.swing_scanned_today = False
```

- [ ] **Step 8: Update start() logging to show both modes**

In `start()`, replace the strategies log line (line 439):

```python
        logger.info(f"Strategies: {', '.join(d.strategy_name for d in self.detectors)}")
```

with:

```python
        intraday_names = [d.strategy_name for d in self.intraday_detectors]
        swing_names = [d.strategy_name for d in self.swing_detectors]
        logger.info(f"Intraday strategies: {', '.join(intraday_names)}")
        logger.info(f"Swing strategies: {', '.join(swing_names)}")
```

- [ ] **Step 9: Remove old self.detectors references**

Search for any remaining references to `self.detectors` in monitor.py and update them. The `scan_for_signals` method (line 267) uses `self.detectors` — change it to `self.intraday_detectors`:

```python
            for detector in self.intraday_detectors:
```

- [ ] **Step 10: Commit**

```bash
git add kite/live_monitor/monitor.py
git commit -m "feat: split strategies into intraday/swing modes with daily scan"
```

---

### Task 7: Update Dashboard with Mode Column

**Files:**
- Modify: `kite/live_monitor/dashboard.py`

- [ ] **Step 1: Add mode badge helper function**

After the `_side_badge` function (line 130), add:

```python
def _mode_badge(mode):
    """Return a colored mode badge."""
    if not mode:
        return ""
    if mode == "SWING":
        return '<span style="background:rgba(167,139,250,0.15);color:#a78bfa;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:600;">SWING</span>'
    return '<span style="background:rgba(96,165,250,0.15);color:#60a5fa;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:600;">INTRADAY</span>'
```

- [ ] **Step 2: Add Mode column to open positions table**

In the open positions table header (line 379), add `<th>Mode</th>` after Strategy:

```html
<th>Symbol</th>
<th>Side</th>
<th>Entry Price</th>
<th>Qty</th>
<th>Stop Loss</th>
<th>Take Profit</th>
<th>Strategy</th>
<th>Mode</th>
```

In the open positions row template (lines 170-178), add mode badge after strategy:

```python
                <td>{_mode_badge(p.get('trade_mode',''))}</td>
```

Update the "No open positions" colspan from 7 to 8.

- [ ] **Step 3: Add Mode column to closed trades table**

In the closed trades table header (line 403), add `<th>Mode</th>` after Strategy:

```html
<th>Symbol</th>
<th>Side</th>
<th>Entry</th>
<th>Exit</th>
<th>Qty</th>
<th>P&amp;L</th>
<th>%</th>
<th>Exit Reason</th>
<th>Strategy</th>
<th>Mode</th>
```

In the closed trades row template (lines 188-198), add mode badge after strategy:

```python
                <td>{_mode_badge(t.get('trade_mode',''))}</td>
```

Update the "No closed trades" colspan from 9 to 10.

- [ ] **Step 4: Add Swing Positions count card**

In the cards section, after the "Open Positions" card (lines 354-357), add:

```html
        <div class="card">
            <div class="card-label">Swing Positions</div>
            <div class="card-value" style="color:#a78bfa;">{swing_count}</div>
        </div>
```

And compute `swing_count` at the top of the `index()` function after `open_pos` is fetched:

```python
    swing_count = sum(1 for p in open_pos if p.get('trade_mode') == 'SWING')
```

- [ ] **Step 5: Commit**

```bash
git add kite/live_monitor/dashboard.py
git commit -m "feat: add trade mode column and swing count to dashboard"
```

---

### Task 8: Wipe DB and Deploy to Oracle

**Files:**
- No local file changes — remote operations only

- [ ] **Step 1: Package project**

```bash
cd D:\study\kite
tar -czf /tmp/kite-monitor.tar.gz --exclude='.git' --exclude='__pycache__' --exclude='venv' --exclude='node_modules' --exclude='TradingAgents' --exclude='data/*.db' --exclude='.specstory' -C . .
```

- [ ] **Step 2: Upload to Oracle**

```bash
scp -i "C:/Users/pc/Downloads/ssh-key-2026-04-24.key" -o StrictHostKeyChecking=no /tmp/kite-monitor.tar.gz ubuntu@80.225.202.32:/tmp/
```

- [ ] **Step 3: Extract, wipe DB, restart services**

```bash
ssh -i "C:/Users/pc/Downloads/ssh-key-2026-04-24.key" -o StrictHostKeyChecking=no ubuntu@80.225.202.32 "cd ~/projects/kite-monitor && tar -xzf /tmp/kite-monitor.tar.gz && rm -f data/paper_trades.db && sudo systemctl restart kite-monitor && sudo systemctl restart kite-dashboard"
```

- [ ] **Step 4: Verify services running**

```bash
ssh -i "C:/Users/pc/Downloads/ssh-key-2026-04-24.key" -o StrictHostKeyChecking=no ubuntu@80.225.202.32 "sudo systemctl status kite-monitor --no-pager -l | head -20 && echo '---' && sudo systemctl status kite-dashboard --no-pager -l | head -20"
```

- [ ] **Step 5: Verify dashboard accessible**

```bash
curl -s -o /dev/null -w "HTTP %{http_code}" http://80.225.202.32:8050/
```

Expected: HTTP 200.

- [ ] **Step 6: Commit all local changes**

```bash
git add kite/live_monitor/paper_trader.py kite/live_monitor/signal_detector.py kite/live_monitor/monitor.py kite/live_monitor/dashboard.py
git commit -m "feat: dual-mode trading (intraday + swing) with stepped trailing stops"
```
