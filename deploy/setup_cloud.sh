#!/bin/bash
# Cloud Setup Script for Trading Monitor
# Run this on your cloud VM (Ubuntu)

echo "=========================================="
echo "Trading Monitor - Cloud Setup"
echo "=========================================="

# Update system
echo "Updating system..."
sudo apt update && sudo apt upgrade -y

# Install Python
echo "Installing Python..."
sudo apt install python3 python3-pip python3-venv git -y

# Create directory
mkdir -p ~/trading
cd ~/trading

# Clone or copy code
# If using git:
# git clone https://github.com/yourusername/kite.git .

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install pandas numpy requests schedule tqdm kiteconnect

# Create environment file
echo "Creating environment file..."
cat > .env << 'EOF'
# Zerodha credentials (update daily or use Kite Connect API)
ZERODHA_ENCTOKEN=your_enctoken_here

# Telegram Bot credentials
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
EOF

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Edit .env file with your credentials:"
echo "   nano .env"
echo ""
echo "2. Source the environment:"
echo "   source .env && export ZERODHA_ENCTOKEN TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID"
echo ""
echo "3. Run the bot:"
echo "   python start_monitor.py --live --telegram"
echo ""
echo "4. To run as a service, create systemd unit (see README)"
echo ""
