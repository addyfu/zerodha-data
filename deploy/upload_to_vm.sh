#!/bin/bash
# =============================================================
# Upload project files to Oracle Cloud VM
# =============================================================
# Usage: ./deploy/upload_to_vm.sh <VM_IP>
# Example: ./deploy/upload_to_vm.sh 129.154.55.100
# =============================================================

if [ -z "$1" ]; then
    echo "Usage: $0 <VM_IP> [SSH_KEY_PATH]"
    echo "Example: $0 129.154.55.100"
    echo "Example: $0 129.154.55.100 ~/.ssh/oracle_key"
    exit 1
fi

VM_IP="$1"
SSH_KEY="${2:+"-i $2"}"
SSH_USER="ubuntu"

echo "Uploading to ${SSH_USER}@${VM_IP}..."

# Create remote directories
ssh $SSH_KEY ${SSH_USER}@${VM_IP} "mkdir -p ~/kite/kite/strategies ~/kite/kite/live_monitor ~/kite/kite/indicators ~/kite/kite/backtesting ~/kite/kite/utils ~/kite/deploy ~/kite/data/daily"

# Upload core files
echo "[1/5] Uploading root modules..."
scp $SSH_KEY \
    cloud_collector.py \
    zerodha_auto_login.py \
    ${SSH_USER}@${VM_IP}:~/kite/

# Upload kite package
echo "[2/5] Uploading kite package..."
scp $SSH_KEY kite/__init__.py kite/config.py ${SSH_USER}@${VM_IP}:~/kite/kite/ 2>/dev/null || true

# Upload strategies
echo "[3/5] Uploading strategies..."
scp $SSH_KEY kite/strategies/*.py ${SSH_USER}@${VM_IP}:~/kite/kite/strategies/

# Upload live monitor
echo "[4/5] Uploading live monitor..."
scp $SSH_KEY kite/live_monitor/*.py ${SSH_USER}@${VM_IP}:~/kite/kite/live_monitor/

# Upload supporting modules
echo "[5/5] Uploading indicators, utils, backtesting..."
scp $SSH_KEY kite/indicators/*.py ${SSH_USER}@${VM_IP}:~/kite/kite/indicators/
scp $SSH_KEY kite/utils/*.py ${SSH_USER}@${VM_IP}:~/kite/kite/utils/
scp $SSH_KEY kite/backtesting/*.py ${SSH_USER}@${VM_IP}:~/kite/kite/backtesting/

# Upload deploy scripts
scp $SSH_KEY deploy/*.sh ${SSH_USER}@${VM_IP}:~/kite/deploy/

# Ensure __init__.py files exist
ssh $SSH_KEY ${SSH_USER}@${VM_IP} "touch ~/kite/kite/__init__.py ~/kite/kite/live_monitor/__init__.py ~/kite/kite/indicators/__init__.py ~/kite/kite/utils/__init__.py ~/kite/kite/backtesting/__init__.py ~/kite/kite/strategies/__init__.py"

echo ""
echo "Upload complete!"
echo ""
echo "Now SSH in and run setup:"
echo "  ssh $SSH_KEY ${SSH_USER}@${VM_IP}"
echo "  cd ~/kite && chmod +x deploy/*.sh"
echo "  ./deploy/setup_oracle.sh"
