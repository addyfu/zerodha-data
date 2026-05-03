#!/bin/bash
# =============================================================
# Install cron job for the trading scanner
# Runs every 5 minutes (script handles market hours check)
# =============================================================

set -e

# Create logs directory
mkdir -p ~/kite/logs

# Make scripts executable
chmod +x ~/kite/deploy/run_scanner.sh

# Add cron job (every 5 minutes)
CRON_JOB="*/5 * * * * ~/kite/deploy/run_scanner.sh"

# Check if already installed
if crontab -l 2>/dev/null | grep -q "run_scanner.sh"; then
    echo "Cron job already installed. Updating..."
    crontab -l | grep -v "run_scanner.sh" | crontab -
fi

# Install
(crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -

echo "Cron job installed successfully!"
echo ""
echo "Verify with: crontab -l"
echo "View logs:   tail -f ~/kite/logs/scanner.log"
echo ""
echo "To remove:   crontab -l | grep -v run_scanner | crontab -"
