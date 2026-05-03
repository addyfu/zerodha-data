# DB-Backed Live Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-stock Zerodha API bulk fetch at startup with a local SQLite DB seeded from GitHub releases, and append live 5-min candles to that DB during trading so it grows continuously.

**Architecture:** A new `DBManager` class handles all DB I/O — seeding from GitHub release on first run, loading NIFTY 50 5-min data, and appending new candles during the day. `monitor.py`'s `load_historical_data()` and `update_with_latest_candle()` delegate to `DBManager` instead of calling Zerodha API 48 times at startup.

**Tech Stack:** Python 3.10+, SQLite (stdlib), pandas, requests (for GitHub API + DB download)

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `kite/live_monitor/db_manager.py` | **Create** | All DB operations: seed check, download, load, append |
| `kite/live_monitor/monitor.py` | **Modify** | Replace bulk fetch with `DBManager` calls |

---

### Task 1: Create `DBManager` — seed check and download

**Files:**
- Create: `kite/live_monitor/db_manager.py`

**Context:**
- GitHub API endpoint: `https://api.github.com/repos/addyfu/zerodha-data/releases/latest`
- DB download URL pattern: `https://github.com/addyfu/zerodha-data/releases/download/<tag>/zerodha_data.db`
- Local DB path: `data/zerodha_data.db` (relative to repo root)
- DB has 1.8 GB — stream download in chunks, show progress
- "Needs update" = local DB doesn't exist OR GitHub release is newer than local DB file mtime

- [ ] **Step 1: Create the file with imports and class skeleton**

```python
# kite/live_monitor/db_manager.py
"""
DBManager
=========
Manages the local SQLite DB of OHLCV data.
- Seeds from GitHub release on first run or when stale
- Loads historical 5-min data for NIFTY 50
- Appends live candles during trading hours
"""
import os
import sqlite3
import logging
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / 'data' / 'zerodha_data.db'
GITHUB_REPO = 'addyfu/zerodha-data'
GITHUB_API = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'


class DBManager:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2: Add `_get_latest_release_info()` — fetch GitHub release metadata**

Add this method to `DBManager`:

```python
    def _get_latest_release_info(self) -> Optional[dict]:
        """Return {'tag': str, 'published_at': datetime, 'download_url': str} or None."""
        try:
            resp = requests.get(
                GITHUB_API,
                headers={'Accept': 'application/vnd.github+json'},
                timeout=15
            )
            if resp.status_code != 200:
                logger.warning(f"GitHub API returned {resp.status_code}")
                return None
            data = resp.json()
            tag = data['tag_name']
            published_at = datetime.fromisoformat(
                data['published_at'].replace('Z', '+00:00')
            )
            # Find zerodha_data.db asset
            download_url = None
            for asset in data.get('assets', []):
                if asset['name'] == 'zerodha_data.db':
                    download_url = asset['browser_download_url']
                    break
            if not download_url:
                logger.warning("No zerodha_data.db asset in latest release")
                return None
            return {'tag': tag, 'published_at': published_at, 'download_url': download_url}
        except Exception as e:
            logger.error(f"Failed to fetch release info: {e}")
            return None
```

- [ ] **Step 3: Add `needs_update()` — compare release timestamp vs local file mtime**

```python
    def needs_update(self) -> bool:
        """Return True if local DB is missing or older than latest GitHub release."""
        if not self.db_path.exists():
            logger.info("Local DB not found — will download from GitHub")
            return True

        release = self._get_latest_release_info()
        if release is None:
            logger.warning("Could not check GitHub release — using existing local DB")
            return False

        local_mtime = datetime.fromtimestamp(
            self.db_path.stat().st_mtime, tz=timezone.utc
        )
        if release['published_at'] > local_mtime:
            logger.info(
                f"GitHub release {release['tag']} ({release['published_at']}) "
                f"is newer than local DB ({local_mtime}) — will update"
            )
            return True

        logger.info(f"Local DB is up to date (release: {release['tag']})")
        return False
```

- [ ] **Step 4: Add `download()` — stream download with progress logging**

```python
    def download(self) -> bool:
        """Download latest DB from GitHub release. Returns True on success."""
        release = self._get_latest_release_info()
        if release is None:
            return False

        url = release['download_url']
        logger.info(f"Downloading DB from {url} ...")
        tmp_path = self.db_path.with_suffix('.tmp')

        try:
            with requests.get(url, stream=True, timeout=300) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get('content-length', 0))
                downloaded = 0
                with open(tmp_path, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8 * 1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded / total * 100
                            logger.info(f"  Download: {pct:.0f}% ({downloaded/1e6:.0f}/{total/1e6:.0f} MB)")

            # Atomic replace
            tmp_path.replace(self.db_path)
            logger.info(f"DB downloaded to {self.db_path} ({self.db_path.stat().st_size/1e6:.0f} MB)")
            return True

        except Exception as e:
            logger.error(f"Download failed: {e}")
            if tmp_path.exists():
                tmp_path.unlink()
            return False
```

- [ ] **Step 5: Add `ensure_seeded()` — orchestrate the seed check + download**

```python
    def ensure_seeded(self) -> bool:
        """
        Check if local DB needs update and download if so.
        Returns True if DB is ready to use.
        """
        if self.needs_update():
            success = self.download()
            if not success and not self.db_path.exists():
                logger.error("DB download failed and no local DB exists — cannot proceed")
                return False
        return self.db_path.exists()
```

- [ ] **Step 6: Test it manually**

```bash
cd D:\study\kite
python -c "
from kite.live_monitor.db_manager import DBManager
dm = DBManager()
print('needs_update:', dm.needs_update())
print('db exists:', dm.db_path.exists())
"
```

Expected output (DB already exists and is recent):
```
Local DB is up to date (release: data-67)
needs_update: False
db exists: True
```

- [ ] **Step 7: Commit**

```bash
git add kite/live_monitor/db_manager.py
git commit -m "feat: add DBManager with GitHub release seed check and download"
```

---

### Task 2: Add `load_nifty50()` — load and resample from local DB

**Files:**
- Modify: `kite/live_monitor/db_manager.py`

**Context:**
- DB stores 1-min candles with `interval='minute'`
- Need to resample to 5-min for strategies
- Only load NIFTY 50 symbols (48 stocks)
- Strip timezone from index for compatibility with strategies
- Return `Dict[str, pd.DataFrame]` — same shape as `monitor.py`'s `data_cache`

- [ ] **Step 1: Add `load_nifty50()` method**

```python
    def load_nifty50(self, symbols: list, resample: str = '5min') -> Dict[str, pd.DataFrame]:
        """
        Load 1-min OHLCV from local DB for given symbols and resample to 5-min.
        Returns dict of symbol -> DataFrame with columns [open, high, low, close, volume].
        """
        if not self.db_path.exists():
            logger.error("DB not found — call ensure_seeded() first")
            return {}

        logger.info(f"Loading {resample} data for {len(symbols)} stocks from local DB...")

        placeholders = ','.join('?' * len(symbols))
        query = f"""
            SELECT symbol, datetime, open, high, low, close, volume
            FROM ohlcv
            WHERE symbol IN ({placeholders}) AND interval = 'minute'
            ORDER BY symbol, datetime
        """

        try:
            con = sqlite3.connect(self.db_path)
            df_all = pd.read_sql(query, con, params=symbols)
            con.close()
        except Exception as e:
            logger.error(f"DB load failed: {e}")
            return {}

        stock_data = {}
        for symbol, grp in df_all.groupby('symbol'):
            grp = grp.copy()
            grp['datetime'] = pd.to_datetime(grp['datetime']).dt.tz_localize(None)
            grp = grp.set_index('datetime')[['open', 'high', 'low', 'close', 'volume']]
            if resample != '1min':
                grp = grp.resample(resample).agg({
                    'open': 'first', 'high': 'max', 'low': 'min',
                    'close': 'last', 'volume': 'sum'
                }).dropna()
            if len(grp) >= 60:
                stock_data[symbol] = grp

        logger.info(f"Loaded {len(stock_data)}/{len(symbols)} stocks from DB")
        return stock_data
```

- [ ] **Step 2: Test loading**

```bash
cd D:\study\kite
python -c "
from kite.live_monitor.db_manager import DBManager
NIFTY_50 = ['RELIANCE','HDFCBANK','ICICIBANK','TCS','INFY','SBIN','AXISBANK','WIPRO','ITC','BAJFINANCE']
dm = DBManager()
data = dm.load_nifty50(NIFTY_50)
for sym, df in list(data.items())[:3]:
    print(sym, len(df), 'rows | last:', df.index[-1], '| close:', df['close'].iloc[-1])
"
```

Expected:
```
AXISBANK 2340 rows | last: 2026-03-25 15:25:00 | close: 1120.5
BAJFINANCE 2250 rows | last: 2026-03-25 15:25:00 | close: 890.2
HDFCBANK 2300 rows | last: 2026-03-25 15:25:00 | close: 1650.1
```

- [ ] **Step 3: Commit**

```bash
git add kite/live_monitor/db_manager.py
git commit -m "feat: add DBManager.load_nifty50() to load and resample from local DB"
```

---

### Task 3: Add `append_candles()` — write live candles to DB

**Files:**
- Modify: `kite/live_monitor/db_manager.py`

**Context:**
- Called every 5 min with the new candles fetched from Zerodha
- Input: `Dict[str, pd.DataFrame]` — symbol → DataFrame of new rows
- Must avoid duplicates (use INSERT OR IGNORE with unique constraint on symbol+datetime+interval)
- Store as `interval='minute'` to match existing DB schema (even if candles are 5-min, store each row with its actual timestamp)

- [ ] **Step 1: Add unique index to DB if not exists**

Add `_ensure_schema()` method:

```python
    def _ensure_schema(self):
        """Ensure unique index exists to prevent duplicate candles."""
        try:
            con = sqlite3.connect(self.db_path)
            con.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_ohlcv_unique ON ohlcv(symbol, datetime, interval)
            """)
            con.commit()
            con.close()
        except Exception as e:
            logger.warning(f"Schema check failed: {e}")
```

Call it in `__init__`:
```python
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            self._ensure_schema()
```

- [ ] **Step 2: Add `append_candles()` method**

```python
    def append_candles(self, new_data: Dict[str, pd.DataFrame], interval: str = 'minute') -> int:
        """
        Append new candles to DB. Silently skips duplicates.
        Returns number of rows inserted.
        """
        if not self.db_path.exists():
            return 0

        rows = []
        for symbol, df in new_data.items():
            for ts, row in df.iterrows():
                rows.append((
                    symbol,
                    str(ts),
                    interval,
                    float(row['open']),
                    float(row['high']),
                    float(row['low']),
                    float(row['close']),
                    int(row.get('volume', 0)),
                    int(row.get('oi', 0)),
                ))

        if not rows:
            return 0

        try:
            con = sqlite3.connect(self.db_path)
            con.executemany("""
                INSERT OR IGNORE INTO ohlcv
                (symbol, datetime, interval, open, high, low, close, volume, oi)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            inserted = con.total_changes
            con.commit()
            con.close()
            if inserted > 0:
                logger.info(f"Appended {inserted} new candles to DB")
            return inserted
        except Exception as e:
            logger.error(f"DB append failed: {e}")
            return 0
```

- [ ] **Step 3: Test append**

```bash
cd D:\study\kite
python -c "
import pandas as pd
from datetime import datetime
from kite.live_monitor.db_manager import DBManager

dm = DBManager()

# Fake a new candle
fake_df = pd.DataFrame([{
    'open': 1400.0, 'high': 1410.0, 'low': 1395.0, 'close': 1405.0, 'volume': 50000
}], index=[pd.Timestamp('2026-04-16 09:15:00')])

inserted = dm.append_candles({'RELIANCE': fake_df})
print('Inserted:', inserted)

# Try again — should be 0 (duplicate)
inserted2 = dm.append_candles({'RELIANCE': fake_df})
print('Duplicate insert (should be 0):', inserted2)
"
```

Expected:
```
Appended 1 new candles to DB
Inserted: 1
Duplicate insert (should be 0): 0
```

- [ ] **Step 4: Commit**

```bash
git add kite/live_monitor/db_manager.py
git commit -m "feat: add DBManager.append_candles() to persist live candles to DB"
```

---

### Task 4: Wire DBManager into `monitor.py`

**Files:**
- Modify: `kite/live_monitor/monitor.py` lines ~84-194

**Context:**
- `LiveMonitor.__init__()` — add `self.db = DBManager()`
- `load_historical_data()` — replace Zerodha bulk fetch with `db.ensure_seeded()` + `db.load_nifty50()`
- `update_with_latest_candle()` — keep Zerodha fetch for latest candle, but also call `db.append_candles()` with the new rows

- [ ] **Step 1: Add DBManager import and instantiation**

In `monitor.py`, add import near the top (after existing imports):
```python
from kite.live_monitor.db_manager import DBManager
```

In `LiveMonitor.__init__()`, after `self.data_cache: Dict[str, pd.DataFrame] = {}`:
```python
        self.db = DBManager()
```

- [ ] **Step 2: Replace `load_historical_data()`**

Replace the entire method:

```python
    def load_historical_data(self):
        """Load 5-min data from local DB (seeded from GitHub release if needed)."""
        logger.info("Loading historical data from local DB...")

        # Seed DB from GitHub release if missing or stale
        if not self.db.ensure_seeded():
            logger.error("DB unavailable — falling back to Zerodha API fetch")
            self._load_from_zerodha_fallback()
            return

        # Load NIFTY 50 5-min data from DB
        self.data_cache = self.db.load_nifty50(self.stocks, resample='5min')

        self.history_loaded = True
        logger.info(f"Loaded 5-min data for {len(self.data_cache)}/{len(self.stocks)} stocks from DB")

    def _load_from_zerodha_fallback(self):
        """Fallback: fetch from Zerodha API if DB unavailable (original logic)."""
        logger.info(f"Fallback: fetching 5-min data for {len(self.stocks)} stocks from Zerodha...")

        def fetch_one(symbol):
            try:
                df = self.fetcher.get_historical_data(symbol, '5minute', 60)
                if df is not None and len(df) >= 60:
                    if df.index.tz is not None:
                        df = df.copy()
                        df.index = df.index.tz_localize(None)
                    return symbol, df
            except Exception as e:
                logger.error(f"Failed to load {symbol}: {e}")
            return symbol, None

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(fetch_one, s): s for s in self.stocks}
            for future in as_completed(futures):
                symbol, df = future.result()
                if df is not None:
                    self.data_cache[symbol] = df
                time.sleep(0.3)

        self.history_loaded = True
        logger.info(f"Fallback loaded {len(self.data_cache)}/{len(self.stocks)} stocks")
```

- [ ] **Step 3: Update `update_with_latest_candle()` to also write to DB**

Find the line inside `update_with_latest_candle()` that does:
```python
                    if not new_rows.empty:
                        self.data_cache[symbol] = pd.concat([cached, new_rows])
```

Replace it with:
```python
                    if not new_rows.empty:
                        self.data_cache[symbol] = pd.concat([cached, new_rows])
                        # Persist new candle to local DB
                        self.db.append_candles({symbol: new_rows}, interval='minute')
```

- [ ] **Step 4: Test the full flow**

```bash
cd D:\study\kite
python -c "
import sys
sys.path.insert(0, '.')
from kite.live_monitor.monitor import LiveMonitor
m = LiveMonitor(offline=True)  # offline=True skips Zerodha login
m.load_historical_data()
print('Loaded stocks:', len(m.data_cache))
for sym, df in list(m.data_cache.items())[:2]:
    print(f'  {sym}: {len(df)} rows, last: {df.index[-1]}')
"
```

Expected:
```
Loading historical data from local DB...
Local DB is up to date (release: data-67)
Loaded 5-min data for 48/48 stocks from DB
Loaded stocks: 48
  ADANIPORTS: 2180 rows, last: 2026-03-25 15:25:00
  APOLLOHOSP: 2160 rows, last: 2026-03-25 15:25:00
```

- [ ] **Step 5: Commit**

```bash
git add kite/live_monitor/monitor.py kite/live_monitor/db_manager.py
git commit -m "feat: wire DBManager into monitor — load from DB, append live candles"
```

---

### Task 5: Push to GitHub and deploy to old laptop

**Files:**
- No code changes — deploy only

- [ ] **Step 1: Push to GitHub**

```bash
cd D:\study\kite
git push origin main
```

- [ ] **Step 2: Pull on old laptop via SSH**

```bash
python -c "
import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.1.8', username='sshuser', password='pass123')
stdin, stdout, stderr = ssh.exec_command('cd D:\\study\\kite && git pull origin main')
print(stdout.read().decode())
print(stderr.read().decode())
ssh.close()
"
```

- [ ] **Step 3: Verify DB seeds correctly on old laptop**

```bash
python -c "
import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.1.8', username='sshuser', password='pass123')
cmd = 'python -c \"from kite.live_monitor.db_manager import DBManager; dm = DBManager(); print(dm.ensure_seeded())\"'
stdin, stdout, stderr = ssh.exec_command(f'cd D:\\\\study\\\\kite && {cmd}', timeout=600)
print(stdout.read().decode())
print(stderr.read().decode())
ssh.close()
"
```

Expected (1.8 GB download on first run — takes a few minutes):
```
Downloading DB from https://github.com/...
  Download: 100% (1873/1873 MB)
DB downloaded to data/zerodha_data.db
True
```

- [ ] **Step 4: Final verification — run monitor in offline mode on old laptop**

```bash
python -c "
import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.1.8', username='sshuser', password='pass123')
cmd = 'python kite\\live_monitor\\monitor.py --offline'
stdin, stdout, stderr = ssh.exec_command(f'cd D:\\\\study\\\\kite && {cmd}', timeout=60)
import time; time.sleep(15)
stdin.channel.send('\x03')  # Ctrl+C
print(stdout.read().decode()[:2000])
ssh.close()
"
```

Expected:
```
Loading historical data from local DB...
Local DB is up to date
Loaded 5-min data for 48/48 stocks from DB
LIVE TRADING MONITOR STARTED
```

- [ ] **Step 5: Commit deploy confirmation**

```bash
git commit --allow-empty -m "chore: deployed DB-backed monitor to old laptop"
```

---

## Self-Review

**Spec coverage:**
- ✅ Download DB from GitHub release on first run
- ✅ Skip download if local DB is up to date
- ✅ Load 5-min data from local DB instead of 48 Zerodha API calls
- ✅ Append live candles to DB every 5 min
- ✅ Fallback to Zerodha API if DB unavailable
- ✅ Deploy to old laptop

**No placeholders:** All code is complete and runnable.

**Type consistency:** `Dict[str, pd.DataFrame]` used consistently across `load_nifty50()`, `append_candles()`, and `data_cache` in `monitor.py`.
