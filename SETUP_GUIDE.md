# 🚀 Complete Setup Guide - Fully Automated Zerodha Data Collection

This guide will help you set up **100% automated** daily data collection that:
- ✅ Runs in the cloud (GitHub Actions - FREE)
- ✅ Auto-logs into Zerodha (no manual token refresh!)
- ✅ Sends you Telegram notifications
- ✅ Stores data permanently
- ✅ Works even when your PC is off

## Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    HOW IT WORKS                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   Every day at 4 PM IST:                                    │
│                                                              │
│   1. GitHub Actions wakes up (FREE cloud computer)          │
│   2. Auto-logs into your Zerodha account                    │
│   3. Downloads 1-minute data for 50 stocks                  │
│   4. Saves to database                                       │
│   5. Uploads database to GitHub Releases                    │
│   6. Sends you a Telegram message with summary              │
│                                                              │
│   You don't need to do ANYTHING! 🎉                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Step 1: Get Your TOTP Secret (5 minutes)

The TOTP secret is what generates your 6-digit 2FA codes. You need this for auto-login.

### How to Get Your TOTP Secret:

1. **Go to [kite.zerodha.com](https://kite.zerodha.com)** and login
2. **Click your User ID** in the top-right corner (e.g., `DR8342`)
3. **Click "My Profile"**
4. **Scroll down to "Password & Security"** section
5. **Look for "External TOTP"** or **"2FA Settings"**
6. Click **"Reset TOTP"** or **"Setup External TOTP"**
7. When shown the QR code, click **"Can't scan? Show secret key"** or **"Manual setup"**
8. **COPY THE SECRET KEY** (looks like: `JBSWY3DPEHPK3PXP`)
9. Add this secret to your authenticator app (Google Authenticator/Authy)
10. Enter the 6-digit code to confirm

### Can't Find It?

Try these alternative paths:
- **Kite Web** → Click User ID → **Settings** → **Security**
- **Kite Web** → **Profile** → **Password & Security**
- **Kite Mobile App** → **Menu** → **Settings** → **Security** → **TOTP**

### If You Already Have TOTP Set Up:

You'll need to **reset it** to see the secret key again. Don't worry - just:
1. Click "Reset TOTP" 
2. Copy the new secret
3. Re-add to your authenticator app

⚠️ **Save this secret somewhere safe!** You'll need it for the automation.

---

## Step 2: Create a Telegram Bot (5 minutes)

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name (e.g., "My Zerodha Bot")
4. Choose a username (e.g., "my_zerodha_data_bot")
5. **Copy the bot token** (looks like: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

### Get Your Chat ID:

1. Search for **@userinfobot** on Telegram
2. Send `/start`
3. **Copy your ID** (a number like `123456789`)

---

## Step 3: Set Up GitHub Repository (10 minutes)

### 3.1 Create a GitHub Account (if you don't have one)
Go to [github.com](https://github.com) and sign up (FREE)

### 3.2 Create a New Repository

1. Click **"New repository"**
2. Name it `zerodha-data` (or anything you like)
3. Make it **Private** (important for security!)
4. Click **Create repository**

### 3.3 Upload the Code

Option A - Using GitHub Web:
1. Click **"uploading an existing file"**
2. Drag and drop all files from `D:\study\kite\`
3. Click **Commit changes**

Option B - Using Git:
```bash
cd D:\study\kite
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/zerodha-data.git
git push -u origin main
```

### 3.4 Add Secrets (IMPORTANT!)

1. Go to your repository → **Settings** → **Secrets and variables** → **Actions**
2. Click **"New repository secret"** and add these:

| Secret Name | Value |
|-------------|-------|
| `ZERODHA_USER_ID` | Your Zerodha client ID (e.g., `DR8342`) |
| `ZERODHA_PASSWORD` | Your Zerodha password |
| `ZERODHA_TOTP_SECRET` | The TOTP secret from Step 1 |
| `TELEGRAM_BOT_TOKEN` | Bot token from Step 2 |
| `TELEGRAM_CHAT_ID` | Your chat ID from Step 2 |

⚠️ **These secrets are encrypted and secure. GitHub cannot see them.**

---

## Step 4: Enable GitHub Actions

1. Go to your repository → **Actions** tab
2. Click **"I understand my workflows, go ahead and enable them"**
3. You should see "Daily Data Collection" workflow

### Test It!

1. Click on **"Daily Data Collection"**
2. Click **"Run workflow"** → **"Run workflow"**
3. Watch it run! (takes ~3-5 minutes)
4. You should get a Telegram message when done!

---

## Step 5: Download Your Data

### Option A: From GitHub Releases
1. Go to your repository → **Releases**
2. Download `zerodha_data.db` from the latest release

### Option B: From Telegram
Send `/download RELIANCE` to your bot to get CSV files

### Option C: Automatic Sync (Advanced)
Set up a script to download the latest database:

```python
import requests

# Get latest release
repo = "YOUR_USERNAME/zerodha-data"
url = f"https://api.github.com/repos/{repo}/releases/latest"
response = requests.get(url, headers={"Authorization": "token YOUR_GITHUB_TOKEN"})
release = response.json()

# Find database file
for asset in release['assets']:
    if asset['name'] == 'zerodha_data.db':
        download_url = asset['browser_download_url']
        # Download it
        db = requests.get(download_url)
        with open('zerodha_data.db', 'wb') as f:
            f.write(db.content)
        print("Downloaded!")
```

---

## How the Schedule Works

The workflow runs automatically:
- **When:** Every weekday (Mon-Fri) at 4:00 PM IST
- **What:** Collects that day's 1-minute data
- **Where:** GitHub's cloud servers (FREE)

You can also trigger it manually anytime from the Actions tab.

---

## Telegram Bot Commands

Once set up, you can control everything from Telegram:

| Command | Description |
|---------|-------------|
| `/status` | Check system status |
| `/collect` | Manually trigger collection |
| `/stats` | View database statistics |
| `/download SYMBOL` | Get CSV file for a stock |
| `/help` | Show all commands |

---

## Troubleshooting

### "Login failed" error
- Check your ZERODHA_USER_ID and ZERODHA_PASSWORD secrets
- Make sure TOTP secret is correct (no spaces)
- Try resetting TOTP and getting a fresh secret

### "TOTP invalid" error
- Your TOTP secret might be wrong
- Make sure you copied the secret key, not the 6-digit code
- Reset TOTP on Zerodha Console and try again

### No Telegram notifications
- Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
- Make sure you started a chat with your bot
- Send `/start` to your bot first

### Workflow not running
- Check if Actions are enabled in your repository
- Look at the Actions tab for error messages
- Make sure all secrets are set correctly

---

## Cost

**Everything is FREE!**

| Service | Cost | Limit |
|---------|------|-------|
| GitHub Actions | Free | 2,000 minutes/month |
| GitHub Storage | Free | Unlimited releases |
| Telegram Bot | Free | Unlimited |

Our workflow uses ~5 minutes per run × 22 days = ~110 minutes/month (well under the limit)

---

## Security Notes

1. **Repository should be PRIVATE** - Your data is personal
2. **Secrets are encrypted** - GitHub cannot see them
3. **Don't share your TOTP secret** - It's like a password
4. **Use a strong Zerodha password** - Enable all security features

---

## What Data You'll Collect

Over time, your database will grow:

| Time | Records | Size |
|------|---------|------|
| 1 day | ~16,000 | ~1 MB |
| 1 month | ~350,000 | ~25 MB |
| 6 months | ~2,000,000 | ~150 MB |
| 1 year | ~4,000,000 | ~300 MB |

All 50 NIFTY stocks, 1-minute candles, every trading day!

---

## Need Help?

1. Check the Actions tab for error logs
2. Make sure all secrets are set correctly
3. Try running the workflow manually first
4. Check Telegram for error notifications

---

# 📊 GitHub Actions Trading Monitor Setup

This section explains how to set up the **automated paper trading monitor** that runs on GitHub Actions for FREE.

## What It Does

```
┌─────────────────────────────────────────────────────────────┐
│              TRADING MONITOR - HOW IT WORKS                 │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   Every 5 minutes during market hours (9:15 AM - 3:30 PM):  │
│                                                              │
│   1. GitHub Actions runs the scanner                        │
│   2. Fetches live data from Zerodha                         │
│   3. Scans NIFTY 50 stocks for Fib 3-Wave patterns          │
│   4. Opens paper trading positions on signals               │
│   5. Checks open positions for SL/TP hits                   │
│   6. Sends Telegram alerts for all actions                  │
│   7. Saves order book state for next run                    │
│                                                              │
│   All FREE! Your PC stays OFF! 🎉                           │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Quick Setup (5 minutes)

### Step 1: Add Secrets to GitHub

Go to your repository → **Settings** → **Secrets and variables** → **Actions**

Add these secrets:

| Secret Name | Value | Required |
|-------------|-------|----------|
| `ZERODHA_ENCTOKEN` | Your Zerodha enctoken (from browser) | Yes |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | Yes |
| `TELEGRAM_CHAT_ID` | Your chat ID from @userinfobot | Yes |

### Step 2: Get Your Zerodha Enctoken

1. Login to [kite.zerodha.com](https://kite.zerodha.com) in your browser
2. Open Developer Tools (F12) → Application → Cookies
3. Find `enctoken` cookie and copy its value
4. Add it to GitHub Secrets as `ZERODHA_ENCTOKEN`

**Note:** The enctoken expires daily. You need to update it each morning before market opens.

### Step 3: Create Telegram Bot

1. Open Telegram, search for **@BotFather**
2. Send `/newbot` and follow instructions
3. Copy the bot token → Add as `TELEGRAM_BOT_TOKEN`
4. Search for **@userinfobot**, send `/start`
5. Copy your ID → Add as `TELEGRAM_CHAT_ID`

### Step 4: Enable GitHub Actions

1. Go to your repository → **Actions** tab
2. Click "I understand my workflows, go ahead and enable them"
3. The "Trading Monitor" workflow will now run automatically!

### Step 5: Test It

1. Go to **Actions** → **Trading Monitor**
2. Click **Run workflow** → **Run workflow**
3. Watch it run and check your Telegram for alerts!

## What You'll Receive on Telegram

### 1. Trade Signals
```
[BUY] TRADE ALERT - BUY [BUY]

Stock: RELIANCE
Signal: BUY
Strategy: Fib 3-Wave

Entry Price: Rs 2,500.00
Stop Loss: Rs 2,450.00 (2.0% risk)
Target: Rs 2,600.00 (4.0% reward)

Risk:Reward: 1:2.0
Quantity: 40 shares
Position Size: Rs 1,00,000.00
```

### 2. Position Opened
```
[LONG] POSITION OPENED [LONG]

Stock: RELIANCE
Direction: BUY
Entry Price: Rs 2,500.00
Quantity: 40 shares
Stop Loss: Rs 2,450.00
Take Profit: Rs 2,600.00
```

### 3. Position Closed
```
TRADE CLOSED - [WIN] PROFIT

Stock: RELIANCE
Exit Reason: take_profit

Entry: Rs 2,500.00
Exit: Rs 2,600.00

P&L: Rs +4,000.00 (+4.00%)
Running Total: Rs +4,000.00
Win Rate: 100.0%
```

### 4. Daily Summary
```
DAILY TRADING SUMMARY

Date: 2026-01-19

Today's Performance:
- Trades Taken: 2
- Wins: 1 | Losses: 1
- Day P&L: Rs +1,500.00

Overall Performance:
- Total Trades: 10
- Win Rate: 60.0%
- Total P&L: Rs +5,000.00

Capital: Rs 1,05,000.00
```

## Order Book System

The trading monitor maintains a **persistent order book** that tracks:

- Open positions with entry price, SL, TP
- Closed trades with P&L
- Account balance and performance metrics
- Daily summaries

The order book is saved as a JSON file and persisted between GitHub Actions runs using artifacts.

### Order Book Structure
```json
{
  "account": {
    "initial_capital": 100000,
    "current_capital": 105000,
    "total_pnl": 5000,
    "total_trades": 10,
    "wins": 6,
    "losses": 4,
    "win_rate": 60.0
  },
  "open_positions": [...],
  "closed_trades": [...],
  "daily_summary": {...}
}
```

## Manual Actions

You can trigger specific actions manually:

1. Go to **Actions** → **Trading Monitor**
2. Click **Run workflow**
3. Select action:
   - `scan` - Run full market scan (default)
   - `status` - Send current status to Telegram
   - `summary` - Send daily summary to Telegram

## Cost & Limits

| Resource | Free Limit | Our Usage |
|----------|------------|-----------|
| GitHub Actions | 2,000 min/month | ~400 min/month |
| Artifacts | 500 MB | ~1 MB |
| Telegram | Unlimited | Unlimited |

**Calculation:**
- 5-min intervals × 6 hours × 22 days = 1,584 runs/month
- Each run ~15 seconds = ~400 minutes/month
- Well within free limits!

## Troubleshooting

### "No signals found"
- This is normal! Fib 3-Wave patterns don't appear every day
- The strategy is selective for high-quality setups

### "Enctoken expired"
- Login to Kite web and get a fresh enctoken
- Update the `ZERODHA_ENCTOKEN` secret

### "Telegram not sending"
- Check bot token and chat ID are correct
- Make sure you started a chat with your bot

### "Workflow not running"
- Check Actions are enabled in repository settings
- Verify all secrets are set correctly

## Files Overview

| File | Purpose |
|------|---------|
| `.github/workflows/trading-monitor.yml` | GitHub Actions workflow |
| `kite/live_monitor/github_scanner.py` | Main scanner script |
| `kite/live_monitor/order_book.py` | Order book management |
| `kite/live_monitor/telegram_bot.py` | Telegram notifications |
| `kite/live_monitor/signal_detector.py` | Pattern detection |
| `kite/live_monitor/data_fetcher.py` | Zerodha data fetching |

---

Happy automated trading! 🚀📈
