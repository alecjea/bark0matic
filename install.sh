#!/bin/bash

# Barkomatic Automated Setup Script for Raspberry Pi
# Usage: bash install.sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🐕 Barkomatic - Raspberry Pi Auto-Setup${NC}"
echo ""

# ────────────────────────────────────────────────────────────────────
# Step 1: Check if running on Linux
# ────────────────────────────────────────────────────────────────────
if [[ "$OSTYPE" != "linux"* ]]; then
  echo -e "${RED}✗ This script only works on Linux (Raspberry Pi, etc.)${NC}"
  exit 1
fi

echo -e "${YELLOW}[1/5] Checking system requirements...${NC}"

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
  echo -e "${RED}✗ Python 3 not found. Install with: sudo apt-get install python3 python3-pip${NC}"
  exit 1
fi
echo -e "${GREEN}✓ Python 3 installed${NC}"

# Check if pip is installed
if ! command -v pip3 &> /dev/null; then
  echo -e "${RED}✗ pip3 not found. Install with: sudo apt-get install python3-pip${NC}"
  exit 1
fi
echo -e "${GREEN}✓ pip3 installed${NC}"

# Check disk space (need at least 500MB)
DISK_FREE=$(df /tmp | awk 'NR==2 {print $4}')
if [ "$DISK_FREE" -lt 500000 ]; then
  echo -e "${RED}✗ Not enough disk space (need 500MB free)${NC}"
  exit 1
fi
echo -e "${GREEN}✓ Sufficient disk space${NC}"
echo ""

# ────────────────────────────────────────────────────────────────────
# Step 2: Install Python dependencies
# ────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[2/5] Installing Python dependencies...${NC}"
pip3 install --quiet -r requirements.txt
echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

# ────────────────────────────────────────────────────────────────────
# Step 3: Create systemd service
# ────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[3/5] Creating systemd service...${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cat > /tmp/barkomatic.service << EOF
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

# Install service
sudo cp /tmp/barkomatic.service /etc/systemd/system/
sudo systemctl daemon-reload
echo -e "${GREEN}✓ Systemd service created${NC}"
echo ""

# ────────────────────────────────────────────────────────────────────
# Step 4: Start the service
# ────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[4/5] Enabling auto-start on boot...${NC}"
sudo systemctl enable barkomatic
echo -e "${GREEN}✓ Auto-start enabled${NC}"
echo ""

echo -e "${YELLOW}[5/5] Starting Barkomatic service...${NC}"
sudo systemctl start barkomatic
sleep 2

# Check if service is running
if sudo systemctl is-active --quiet barkomatic; then
  echo -e "${GREEN}✓ Service started successfully${NC}"
else
  echo -e "${RED}✗ Service failed to start. Check logs:${NC}"
  echo "  sudo journalctl -u barkomatic -n 50"
  exit 1
fi

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Barkomatic is ready!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo ""
echo "Access the dashboard:"
echo "  http://localhost:8080"
echo ""
echo "Check service status:"
echo "  sudo systemctl status barkomatic"
echo ""
echo "View live logs:"
echo "  sudo journalctl -u barkomatic -f"
echo ""
echo "Download detections:"
echo "  Use the web dashboard or:"
echo "  cat ~/barkomatic/detections.csv"
echo ""
