#!/bin/bash
# =============================================================
# Cron wrapper script - runs the trading scanner
# Called by cron every 5 minutes during market hours
# =============================================================

cd ~/kite

# Load environment variables
set -a
source ~/kite/.env
set +a

# Activate virtualenv
source ~/kite/venv/bin/activate

# Get current IST time (UTC+5:30)
IST_HOUR=$(TZ='Asia/Kolkata' date +%H)
IST_MIN=$(TZ='Asia/Kolkata' date +%M)
IST_DOW=$(TZ='Asia/Kolkata' date +%u)  # 1=Mon, 7=Sun

# Skip weekends (Sat=6, Sun=7)
if [ "$IST_DOW" -ge 6 ]; then
    exit 0
fi

# Skip outside market hours (9:15 AM - 3:30 PM IST)
IST_TOTAL=$((IST_HOUR * 60 + IST_MIN))
MARKET_OPEN=$((9 * 60 + 15))   # 9:15 AM = 555 min
MARKET_CLOSE=$((15 * 60 + 30)) # 3:30 PM = 930 min

if [ "$IST_TOTAL" -lt "$MARKET_OPEN" ] || [ "$IST_TOTAL" -gt "$MARKET_CLOSE" ]; then
    exit 0
fi

# Run the scanner
python kite/live_monitor/github_scanner.py \
    --strategy ema_21_55 \
    --state-file ~/kite/order_book.json \
    >> ~/kite/logs/scanner.log 2>&1

# Send daily summary at market close (3:25-3:35 PM IST)
if [ "$IST_TOTAL" -ge 925 ] && [ "$IST_TOTAL" -le 935 ]; then
    python kite/live_monitor/github_scanner.py \
        --summary \
        --state-file ~/kite/order_book.json \
        >> ~/kite/logs/scanner.log 2>&1
fi
