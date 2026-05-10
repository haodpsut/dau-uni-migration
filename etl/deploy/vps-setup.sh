#!/bin/bash
# vps-setup.sh — One-time VPS setup
# Run lần đầu trên VPS Ubuntu (24.04 hoặc 22.04)
# Cài Docker + Python + git + rclone + Git LFS
#
# Usage:
#   curl -fsSL <raw-url-to-this-script> | bash
#   hoặc
#   bash vps-setup.sh

set -euo pipefail

G='\033[0;32m'
Y='\033[0;33m'
R='\033[0;31m'
N='\033[0m'

log()  { echo -e "${G}[$(date +%H:%M:%S)]${N} $*"; }
warn() { echo -e "${Y}[$(date +%H:%M:%S)]${N} $*"; }
fail() { echo -e "${R}[$(date +%H:%M:%S)]${N} $*"; exit 1; }

# Check OS
if [ ! -f /etc/lsb-release ] || ! grep -qi ubuntu /etc/lsb-release; then
    warn "Tested only on Ubuntu. Continuing anyway..."
fi

log "=== DAU University VPS Setup ==="

# 1. Update apt
log "[1/8] apt update..."
sudo apt-get update -qq

# 2. Install basics
log "[2/8] Installing git, python3-venv, curl, gzip..."
sudo apt-get install -y -qq git python3-venv python3-pip curl gzip ca-certificates gnupg

# 3. Install Docker
if ! command -v docker &>/dev/null; then
    log "[3/8] Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    warn "  → You may need to log out + log back in for group changes."
else
    log "[3/8] Docker already installed: $(docker --version)"
fi

# 4. Install Docker Compose plugin (if not bundled)
if ! docker compose version &>/dev/null; then
    log "[4/8] Installing docker-compose-plugin..."
    sudo apt-get install -y -qq docker-compose-plugin
else
    log "[4/8] Docker Compose: $(docker compose version | head -1)"
fi

# 5. Install rclone
if ! command -v rclone &>/dev/null; then
    log "[5/8] Installing rclone..."
    curl https://rclone.org/install.sh | sudo bash
else
    log "[5/8] rclone: $(rclone --version | head -1)"
fi

# 6. Install Git LFS
if ! command -v git-lfs &>/dev/null; then
    log "[6/8] Installing git-lfs..."
    sudo apt-get install -y -qq git-lfs
    git lfs install
else
    log "[6/8] git-lfs: $(git-lfs --version | head -1)"
fi

# 7. Setup swap if not present (mssql sometimes OOMs on 8GB)
SWAP_ACTIVE=$(swapon --show=NAME --noheadings | head -1)
if [ -z "$SWAP_ACTIVE" ]; then
    log "[7/8] Adding 4GB swap (mssql safety)..."
    sudo fallocate -l 4G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
else
    log "[7/8] Swap already active: $(free -h | grep Swap | awk '{print $2}')"
fi

# 8. Verify all tools
log "[8/8] Verification:"
echo "  Docker:  $(docker --version)"
echo "  Compose: $(docker compose version | head -1)"
echo "  Python:  $(python3 --version)"
echo "  rclone:  $(rclone --version | head -1)"
echo "  git-lfs: $(git-lfs --version | head -1)"
echo "  Disk:    $(df -h / | tail -1 | awk '{print $4 " free / " $2 " total"}')"
echo "  RAM:     $(free -h | awk '/^Mem:/ {print $7" available / "$2" total"}')"

cat <<EOF

${G}════════════════════════════════════════${N}
${G} ✓ VPS setup complete${N}
${G}════════════════════════════════════════${N}

Next steps:
  1. Configure rclone for Google Drive:
     ${Y}rclone config${N}
     (see DEPLOY.md Phase 2.3)

  2. Test: ${Y}rclone ls gdrive:dau-uni-backup${N}

  3. Clone repo:
     ${Y}sudo mkdir -p /opt/dau-uni && sudo chown \$USER /opt/dau-uni${N}
     ${Y}cd /opt/dau-uni && git clone https://github.com/<you>/<repo>.git .${N}

  4. Setup ETL:
     ${Y}cd etl && python3 -m venv .venv && source .venv/bin/activate${N}
     ${Y}pip install -r requirements.txt${N}
     ${Y}cp .env.example .env && nano .env${N}

  5. Run ETL:
     ${Y}docker compose up -d${N}
     ${Y}python run.py setup${N}
     ${Y}./deploy/vps-run-etl.sh${N}
EOF
