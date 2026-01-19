# Cloud Deployment Guide for Live Trading Monitor

## Option 1: Oracle Cloud (FREE Forever) - Recommended

### Step 1: Create Oracle Cloud Account
1. Go to https://cloud.oracle.com/
2. Sign up for free tier (requires credit card for verification, but won't charge)
3. Select your home region (Mumbai for lowest latency)

### Step 2: Create a Free VM
1. Go to Compute > Instances > Create Instance
2. Choose:
   - Shape: VM.Standard.E2.1.Micro (Always Free)
   - Image: Ubuntu 22.04
   - Add SSH key (or let Oracle generate one)
3. Click Create

### Step 3: Connect to VM
```bash
ssh -i your_key.pem ubuntu@<your_vm_ip>
```

### Step 4: Setup the Monitor
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python
sudo apt install python3 python3-pip python3-venv -y

# Clone your code (or upload via SCP)
git clone https://github.com/yourusername/kite.git
cd kite

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export ZERODHA_ENCTOKEN="your_token"
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"

# Run the monitor
python start_monitor.py --live --telegram
```

### Step 5: Keep it Running (using systemd)
```bash
# Create service file
sudo nano /etc/systemd/system/trading-monitor.service
```

Paste this content:
```ini
[Unit]
Description=Trading Monitor
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/kite
Environment="ZERODHA_ENCTOKEN=your_token"
Environment="TELEGRAM_BOT_TOKEN=your_bot_token"
Environment="TELEGRAM_CHAT_ID=your_chat_id"
ExecStart=/home/ubuntu/kite/venv/bin/python start_monitor.py --live --telegram
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable trading-monitor
sudo systemctl start trading-monitor
sudo systemctl status trading-monitor
```

---

## Option 2: PythonAnywhere (Easiest, Free)

### Limitations
- Free tier only allows scheduled tasks (not always-on)
- Can run every hour during market hours

### Setup
1. Go to https://www.pythonanywhere.com/
2. Sign up for free account
3. Upload your code via Files tab
4. Go to Tasks tab
5. Add scheduled task: `python /home/yourusername/kite/start_monitor.py --offline`

---

## Option 3: Railway.app (Easy Deploy)

### Setup
1. Go to https://railway.app/
2. Connect GitHub
3. Deploy from repo
4. Add environment variables in dashboard
5. It auto-deploys on git push

---

## Option 4: Run on Android Phone (Free!)

You can run Python on your old Android phone 24/7!

### Setup with Termux
1. Install Termux from F-Droid (not Play Store)
2. Run:
```bash
pkg update && pkg upgrade
pkg install python git
pip install pandas numpy requests schedule
git clone https://github.com/yourusername/kite.git
cd kite
python start_monitor.py --live --telegram
```

3. Use Termux:Boot to auto-start on phone reboot

---

## Handling Zerodha Token Refresh

The enctoken expires daily. Solutions:

### Option A: Manual Daily Refresh
- Login to Kite web daily
- Copy new enctoken
- Update via Telegram command

### Option B: Automated Login (Advanced)
- Use Selenium to auto-login
- Requires 2FA handling

### Option C: Use Kite Connect API
- Pay ₹2000/month for official API
- Tokens last longer, more reliable

---

## Quick Start Commands

```bash
# Clone repo
git clone https://github.com/yourusername/kite.git
cd kite

# Install
pip install -r requirements.txt

# Set credentials
export ZERODHA_ENCTOKEN="your_token"
export TELEGRAM_BOT_TOKEN="your_bot_token" 
export TELEGRAM_CHAT_ID="your_chat_id"

# Run
python start_monitor.py --live --telegram
```

## Monitoring Logs

```bash
# View live logs
journalctl -u trading-monitor -f

# View last 100 lines
journalctl -u trading-monitor -n 100
```

## Telegram Commands (Future Enhancement)

You can add these commands to control the bot:
- `/status` - Get current status
- `/positions` - View open positions
- `/performance` - Get performance summary
- `/token <new_token>` - Update enctoken
- `/stop` - Stop monitoring
- `/start` - Start monitoring
