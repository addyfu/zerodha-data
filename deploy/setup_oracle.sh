#!/bin/bash
# =============================================================
# Oracle Cloud VM Setup Script for Kite Trading Scanner
# =============================================================
# Run this ONCE after SSHing into your new Oracle Cloud VM:
#   chmod +x setup_oracle.sh && ./setup_oracle.sh
# =============================================================

set -e

echo "=========================================="
echo "  Kite Trading Scanner - VM Setup"
echo "=========================================="

# 1. Update system
echo "[1/6] Updating system packages..."
sudo apt update && sudo apt upgrade -y

# 2. Install Python 3.10+ and pip
echo "[2/6] Installing Python..."
sudo apt install -y python3 python3-pip python3-venv git

# 3. Create project directory
echo "[3/6] Setting up project directory..."
mkdir -p ~/kite
cd ~/kite

# 4. Create virtual environment
echo "[4/6] Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# 5. Install Python dependencies
echo "[5/6] Installing Python packages..."
pip install --upgrade pip
pip install pandas numpy requests tqdm pyotp

# 6. Create .env template
echo "[6/6] Creating environment file..."
if [ ! -f ~/kite/.env ]; then
    cat > ~/kite/.env << 'ENVEOF'
# Zerodha Credentials (REQUIRED)
ZERODHA_USER_ID=your_user_id
ZERODHA_PASSWORD=your_password
ZERODHA_TOTP_SECRET=your_totp_secret

# Telegram Alerts (REQUIRED for notifications)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
ENVEOF
    echo ""
    echo "IMPORTANT: Edit ~/kite/.env with your actual credentials:"
    echo "  nano ~/kite/.env"
else
    echo ".env already exists, skipping..."
fi

echo ""
echo "=========================================="
echo "  Setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Upload your code:  (from your PC)"
echo "     scp -r kite/ cloud_collector.py zerodha_auto_login.py ubuntu@<VM_IP>:~/kite/"
echo ""
echo "  2. Edit credentials:"
echo "     nano ~/kite/.env"
echo ""
echo "  3. Test the scanner:"
echo "     cd ~/kite && source venv/bin/activate"
echo "     python kite/live_monitor/github_scanner.py --offline"
echo ""
echo "  4. Install the cron job:"
echo "     chmod +x deploy/install_cron.sh && ./deploy/install_cron.sh"
echo ""
