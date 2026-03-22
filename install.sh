#!/bin/bash

# ============================================================
# BARKOMATIC - Fresh Raspberry Pi Installation Script
# ============================================================
# Complete setup from zero to running web dashboard
# Run with: bash install.sh

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════╗"
echo "║         🐕 BARKOMATIC - Fresh Install Setup            ║"
echo "║    AI Sound Detection for Raspberry Pi                 ║"
echo "╚════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ────────────────────────────────────────────────────────────
# Step 1: Update package lists
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[1/7] Updating package lists...${NC}"
sudo apt-get update -qq
echo -e "${GREEN}✓ Package lists updated${NC}"
echo ""

# ────────────────────────────────────────────────────────────
# Step 2: Install Python and pip
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[2/7] Installing Python 3 and pip...${NC}"
sudo apt-get install -y -qq python3 python3-pip python3-full
PYTHON_VERSION=$(python3 --version 2>&1)
echo -e "${GREEN}✓ $PYTHON_VERSION installed${NC}"
echo ""

# ────────────────────────────────────────────────────────────
# Step 3: Install and configure UFW firewall
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[3/7] Setting up firewall (UFW)...${NC}"
sudo apt-get install -y -qq ufw

# Enable UFW without prompting
echo "y" | sudo ufw enable > /dev/null 2>&1 || true

# Allow SSH (important!)
sudo ufw allow 22/tcp > /dev/null 2>&1 || true

# Allow Barkomatic web port
sudo ufw allow 8080/tcp > /dev/null 2>&1 || true

echo -e "${GREEN}✓ Firewall configured${NC}"
echo "  - SSH (port 22) allowed"
echo "  - Barkomatic (port 8080) allowed"
echo ""

# ────────────────────────────────────────────────────────────
# Step 4: Clone or update repository
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[4/7] Cloning Barkomatic repository...${NC}"

if [ -d "$HOME/bark0matic" ]; then
  echo "  Repository already exists, updating..."
  cd "$HOME/bark0matic"
  git pull origin main -q
else
  cd "$HOME"
  git clone https://github.com/alecjea/bark0matic.git -q
  cd bark0matic
fi

echo -e "${GREEN}✓ Repository ready at $HOME/bark0matic${NC}"
echo ""

# ────────────────────────────────────────────────────────────
# Step 5: Install Python dependencies
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[5/7] Installing Python dependencies...${NC}"
pip install --break-system-packages -q -r requirements.txt 2>/dev/null || pip install --break-system-packages -r requirements.txt
echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

# ────────────────────────────────────────────────────────────
# Step 6: Optional systemd service setup
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[6/7] Setting up systemd service (auto-start on boot)...${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

sudo tee /etc/systemd/system/barkomatic.service > /dev/null << EOF
[Unit]
Description=Barkomatic - AI Sound Detection System
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 $SCRIPT_DIR/main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable barkomatic
echo -e "${GREEN}✓ Systemd service created${NC}"
echo "  - Auto-start on boot enabled"
echo ""

# ────────────────────────────────────────────────────────────
# Step 7: Summary and next steps
# ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[7/7] Setup complete!${NC}"
echo ""

echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ BARKOMATIC IS READY!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo ""

echo "Next steps:"
echo ""
echo "1. Start the app:"
echo -e "   ${BLUE}cd ~/bark0matic${NC}"
echo -e "   ${BLUE}python3 main.py${NC}"
echo ""
echo "2. Open dashboard in browser:"
echo -e "   ${BLUE}http://localhost:8080${NC}"
echo ""
echo "3. Or use systemd (auto-start on boot):"
echo -e "   ${BLUE}sudo systemctl start barkomatic${NC}"
echo -e "   ${BLUE}sudo systemctl status barkomatic${NC}"
echo ""
echo "Configuration:"
echo -e "  - Web Dashboard: http://<rpi-ip>:8080"
echo -e "  - Config file: ~/bark0matic/config.json"
echo -e "  - Logs: ~/bark0matic/detections.csv"
echo ""
echo "Firewall status:"
sudo ufw status | grep -E "22/tcp|8080/tcp"
echo ""
echo -e "${GREEN}Happy barking! 🐕${NC}"
