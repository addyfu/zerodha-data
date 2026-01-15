# Zerodha 1-Minute Data Scraper 📈

Free tool to download and automatically collect 1-minute OHLCV historical data from Zerodha using your existing account. **No paid API subscription required!**

## Features

- ✅ Download 1-minute data for all NIFTY 50 stocks
- ✅ **Automatic daily collection** via Windows Task Scheduler
- ✅ **SQLite database** for efficient storage & querying
- ✅ Data management utilities (export, query, resample)
- ✅ Desktop notifications on completion

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Get Your Enctoken

The enctoken is your session token from the Kite web interface.

1. Open Chrome/Edge and go to [kite.zerodha.com](https://kite.zerodha.com)
2. Login with your Zerodha credentials
3. Press `F12` to open Developer Tools
4. Go to **Application** tab → **Cookies** → **kite.zerodha.com**
5. Find the cookie named `enctoken`
6. Copy its VALUE (it's a long string)

### 3. Save Your Token

**Option A:** Double-click `update_token.bat` and paste your token

**Option B:** Save directly to `enctoken.txt`:
```bash
echo YOUR_TOKEN_HERE > enctoken.txt
```

### 4. Initial Data Collection (60 days history)

```bash
python daily_collector.py --historical
```

### 5. Set Up Automatic Daily Collection

```powershell
# Run as Administrator
.\setup_scheduler.ps1 -Time "16:00"
```

This will collect new data every day at 4 PM (after market close).

## Daily Collection System

### How It Works

1. **SQLite Database**: All data is stored in `data/zerodha_data.db`
2. **No Duplicates**: The system automatically handles duplicates
3. **Incremental**: Only new candles are added each day
4. **Queryable**: Use SQL or the data manager to query your data

### Commands

```bash
# Collect today's data
python daily_collector.py --days 1

# Collect last 7 days
python daily_collector.py --days 7

# Initial setup (60 days history)
python daily_collector.py --historical

# View database stats
python daily_collector.py --stats

# Query specific stock
python daily_collector.py --query RELIANCE
```

### Data Manager

```bash
# View all statistics
python data_manager.py --stats

# List all symbols
python data_manager.py --symbols

# Query a stock
python data_manager.py --query RELIANCE --tail 50

# Resample to 5-minute candles
python data_manager.py --query RELIANCE --resample 5min

# Export to CSV
python data_manager.py --export RELIANCE

# Export all symbols
python data_manager.py --export-all
```

### Use in Python Code

```python
from data_manager import DataManager

# Connect to database
dm = DataManager()

# Get data for a symbol
df = dm.get_data("RELIANCE", start_date="2024-01-01")
print(df.tail())

# Resample to 15-minute candles
df_15m = dm.resample("RELIANCE", "15min")

# Get multiple symbols
data = dm.get_multiple(["RELIANCE", "TCS", "INFY"])

dm.close()
```

## One-Time Download (CSV Files)

For quick downloads without the database:

```bash
# Single stock
python zerodha_scraper.py --symbol RELIANCE --days 60

# All NIFTY 50 stocks
python zerodha_scraper.py --all-nifty50 --days 60

# Different intervals
python zerodha_scraper.py --symbol TCS --days 400 --interval 60minute
```

## Available Intervals

| Interval | Description | Max Days Per Request |
|----------|-------------|---------------------|
| `minute` | 1-minute candles | ~60 days |
| `3minute` | 3-minute candles | ~100 days |
| `5minute` | 5-minute candles | ~100 days |
| `15minute` | 15-minute candles | ~200 days |
| `30minute` | 30-minute candles | ~200 days |
| `60minute` | 1-hour candles | ~400 days |
| `day` | Daily candles | ~2000 days |

## Output Format

Data is saved as CSV with columns:
- `datetime` - Timestamp (index)
- `open` - Opening price
- `high` - High price
- `low` - Low price
- `close` - Closing price
- `volume` - Trade volume
- `oi` - Open Interest (for F&O)

## Windows Task Scheduler Setup

### Automatic Setup

```powershell
# Run PowerShell as Administrator
.\setup_scheduler.ps1 -Time "16:00"
```

### Manual Setup

1. Open Task Scheduler (`taskschd.msc`)
2. Create Basic Task → Name: "ZerodhaDailyCollector"
3. Trigger: Daily at 4:00 PM
4. Action: Start a program
   - Program: `python`
   - Arguments: `"D:\study\kite\daily_collector.py" --days 1 --notify`
   - Start in: `D:\study\kite`

### Manage Scheduled Task

```powershell
# View task
Get-ScheduledTask -TaskName "ZerodhaDailyCollector"

# Run manually
Start-ScheduledTask -TaskName "ZerodhaDailyCollector"

# Remove task
.\setup_scheduler.ps1 -Remove
```

## Updating Your Token

Your enctoken expires after ~24 hours or when you logout. Update it:

**Option 1:** Double-click `update_token.bat`

**Option 2:** Edit `enctoken.txt` directly

**Option 3:** Get new token from browser and save

## File Structure

```
D:\study\kite\
├── data/
│   ├── zerodha_data.db      # SQLite database (main storage)
│   ├── *.csv                # One-time CSV downloads
│   ├── hourly/              # Hourly data CSVs
│   └── daily/               # Daily data CSVs
├── logs/                    # Collection logs
├── exports/                 # Exported CSVs
├── daily_collector.py       # Main collection script
├── data_manager.py          # Query & export utilities
├── zerodha_scraper.py       # One-time CSV downloader
├── setup_scheduler.ps1      # Task scheduler setup
├── update_token.bat         # Easy token update
├── enctoken.txt             # Your session token
└── README.md
```

## Limitations

1. **Session Expiry**: Enctoken expires after ~24 hours. Update it regularly.
2. **1-Minute Data**: Only available for last ~60 days (Zerodha limit)
3. **Market Hours**: Data only for 9:15 AM - 3:30 PM IST

## Troubleshooting

### "Session expired" Error
1. Login to kite.zerodha.com
2. Get new enctoken from cookies
3. Run `update_token.bat` or edit `enctoken.txt`

### Database Issues
```bash
# Check database stats
python daily_collector.py --stats

# Query specific symbol
python data_manager.py --query RELIANCE
```

## Legal Disclaimer

This tool is for personal use only. Respect Zerodha's terms of service.

## License

MIT - Use freely, but at your own risk.
